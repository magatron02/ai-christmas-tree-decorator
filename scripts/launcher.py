"""Desktop entry point: start the server, open the browser, stay running.

This is what the installed shortcut points at. The web app is unchanged — this only does the
three things a double-click has to do that `uvicorn backend.main:app` on a terminal does not:
pick a port that is actually free, wait until the server answers before opening a browser at
it, and leave a window on screen that explains how to quit.

Not a service and not silent on purpose: this is one shop's own machine, and a console window
the user closes is a quit button they can find without being taught one.
"""

import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

# Running from source this file sits in scripts/, so the repo root — where `backend` lives —
# is not on the path yet. Frozen, PyInstaller has already bundled the package and there is no
# repo to point at.
if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

def _make_console_utf8_safe():
    """Stop Thai text from killing the app before it starts.

    A frozen console app on Windows gets cp1252 stdout, and the first print of a Thai line
    raises UnicodeEncodeError — the whole program dies on launch, which is exactly what
    happened the first time this exe was run. Reconfiguring with errors="replace" means the
    worst case is a mangled character rather than no program; switching the console to UTF-8
    lets it render properly wherever the console font has Thai glyphs.
    """
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.kernel32.SetConsoleOutputCP(65001)
        except Exception:
            pass
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass


HOST = "127.0.0.1"
FIRST_PORT = 8000
PORT_ATTEMPTS = 20
STARTUP_TIMEOUT_S = 180  # rembg's onnx session is slow to warm on a cold machine


def _already_serving(port):
    """True when something on this port is this app rather than an unrelated server — so a
    second double-click reopens the running instance instead of failing to bind."""
    try:
        with urllib.request.urlopen(f"http://{HOST}:{port}/api/config", timeout=2) as response:
            return response.status == 200
    except (urllib.error.URLError, OSError):
        return False


def _free_port():
    """The first port nothing is listening on, or None when this app already holds one."""
    for port in range(FIRST_PORT, FIRST_PORT + PORT_ATTEMPTS):
        with socket.socket() as probe:
            if probe.connect_ex((HOST, port)) != 0:
                return port, False
        if _already_serving(port):
            return port, True
    raise SystemExit(
        f"ไม่มีพอร์ตว่างระหว่าง {FIRST_PORT}-{FIRST_PORT + PORT_ATTEMPTS - 1} — "
        "ปิดโปรแกรมที่ใช้พอร์ตพวกนี้แล้วลองใหม่"
    )


def _open_when_ready(url, port):
    """Open the browser only once the server answers. Opening immediately races the boot and
    lands the user on a connection-refused page, which reads as 'the program is broken'."""
    deadline = time.monotonic() + STARTUP_TIMEOUT_S
    while time.monotonic() < deadline:
        if _already_serving(port):
            webbrowser.open(url)
            return
        time.sleep(0.3)
    print(f"เซิร์ฟเวอร์ยังไม่ตอบใน {STARTUP_TIMEOUT_S} วินาที — เปิดเองที่ {url}")


def _use_bundled_rembg_model():
    """Point rembg at the model the installer shipped.

    Left alone rembg downloads ~168 MB into ~/.u2net on the first cut-out, so the first thing
    the user tries needs internet and a long silent wait. The installed copy carries the model
    beside the exe instead; running from source there is no models/ dir and rembg keeps its
    own default.
    """
    bundled = Path(sys.executable).resolve().parent / "models" if getattr(sys, "frozen", False) else None
    if bundled and (bundled / "u2net.onnx").is_file():
        os.environ.setdefault("U2NET_HOME", str(bundled))


def main():
    _make_console_utf8_safe()
    _use_bundled_rembg_model()
    port, running = _free_port()
    url = f"http://{HOST}:{port}"

    if running:
        print(f"Already running at {url} — opening the browser")
        print(f"เปิดอยู่แล้วที่ {url} — กำลังเปิดหน้าเว็บให้")
        webbrowser.open(url)
        return

    print("=" * 58)
    print("  Tree Decorator")
    print(f"  {url}")
    print("  Close this window to quit  /  ปิดหน้าต่างนี้เพื่อออกจากโปรแกรม")
    print("=" * 58)

    threading.Thread(target=_open_when_ready, args=(url, port), daemon=True).start()

    import uvicorn

    from backend.main import app
    from backend.services import background_removal

    # Load the cut-out model now rather than on the first click. It is the single slowest
    # thing this app does on a cold start, and paying for it here — while the user is still
    # looking at the browser opening — is time they were spending anyway. The server is
    # already usable meanwhile; a pick that lands mid-warm just waits for the same load it
    # would have triggered itself.
    threading.Thread(target=background_removal.warm, daemon=True).start()

    try:
        uvicorn.run(app, host=HOST, port=port, log_level="warning")
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:  # a frozen app has no terminal to leave a traceback on
        import traceback

        traceback.print_exc()
        print(f"\nเปิดโปรแกรมไม่สำเร็จ: {exc}")
        input("\nกด Enter เพื่อปิด...")
        sys.exit(1)
