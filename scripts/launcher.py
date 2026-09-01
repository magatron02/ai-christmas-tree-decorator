"""Desktop entry point: start the server, sit in the system tray, stay running.

This is what the installed shortcut points at. The web app is unchanged — this only does the
things a double-click has to do that `uvicorn backend.main:app` on a terminal does not: pick
a port that is actually free, wait until the server answers before opening a browser at it,
and give the user a way to quit that does not require a visible window.

No console window (TreeDecorator.spec sets console=False) — a command-prompt window sitting
in the taskbar for the life of the program read as "this program is broken" to a shop that
never opens a terminal. The system tray icon is the quit button instead: "เปิดหน้าเว็บ" opens
the app again, "ปิดโปรแกรม" shuts the server down and exits. Running from source
(`python scripts/launcher.py`) goes through the same tray path — one code path, not a
`--console` dev-only branch to keep in sync with the real one.

Because there is no console, nothing here may assume `print`/`input` work: sys.stdout can be
None. `_log()` is the one place that touches it, and every informational message — including
a crash before the tray exists to say anything — goes through it, appended to launcher.log
beside the exe (or the repo root, running from source) plus a native message box for
failures, since a log file nobody is looking at might as well not exist.
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

# Computed independently of backend.config: this has to work even if importing the backend
# package itself is what failed, since the crash handler at the bottom still needs it.
ROOT = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) \
    else Path(__file__).resolve().parent.parent
LOG_PATH = ROOT / "launcher.log"


def _log(message):
    """Print when there is a console to read it (dev/source runs), always append to
    launcher.log (there usually is not one). Never raises — a logging failure must not turn
    into the reason the app doesn't start."""
    try:
        if sys.stdout is not None:
            print(message)
    except Exception:
        pass
    try:
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(message + "\n")
    except OSError:
        pass


def _message_box(text):
    """The one UI surface available before the tray icon exists (or if building it failed) —
    stdlib ctypes only, no GUI dependency beyond what Windows already ships."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(0, text, "Tree Decorator", 0x10)  # MB_ICONERROR
    except Exception:
        pass


def _make_console_utf8_safe():
    """Stop Thai text from killing the app before it starts, on the rare path that does have
    a console (running from source). A frozen console app used to get cp1252 stdout, and the
    first print of a Thai line raised UnicodeEncodeError before this existed. Harmless no-op
    now that the shipped build has no console at all — sys.stdout is None, reconfigure()
    raises AttributeError on None, which is exactly what is caught below.
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
    _log(f"Server did not answer within {STARTUP_TIMEOUT_S}s — open {url} yourself")


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


def _build_tray_icon(url, server):
    """The quit button, now that there is no console window to be one.

    pystray's Icon.run() has to own the main thread on Windows, which is why uvicorn runs in
    a background thread via uvicorn.Server (not the blocking uvicorn.run()) — "ปิดโปรแกรม" sets
    should_exit on that server object and stops the icon, and both threads unwind cleanly from
    there without killing a request that happens to be in flight.
    """
    import pystray
    from PIL import Image

    icon_path = ROOT / "frontend" / "icon.ico"
    image = Image.open(icon_path) if icon_path.is_file() else Image.new("RGB", (32, 32), "#7A2E2E")

    def on_open(icon, item):
        webbrowser.open(url)

    def on_quit(icon, item):
        server.should_exit = True
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem("เปิดหน้าเว็บ", on_open, default=True),
        pystray.MenuItem("ปิดโปรแกรม", on_quit),
    )
    return pystray.Icon("TreeDecorator", image, "Tree Decorator", menu)


def main():
    _make_console_utf8_safe()
    _use_bundled_rembg_model()
    port, running = _free_port()
    url = f"http://{HOST}:{port}"

    if running:
        _log(f"Already running at {url} — opening the browser")
        webbrowser.open(url)
        return

    _log(f"Starting Tree Decorator at {url}")

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

    # log_config=None: uvicorn's default logging setup builds a formatter that calls
    # sys.stdout.isatty() to decide whether to colourize, and sys.stdout is None with no
    # console attached — that crashed uvicorn.Config() itself before the server ever started.
    # There is nothing to colourize for either — no console reads it either way.
    server = uvicorn.Server(
        uvicorn.Config(app, host=HOST, port=port, log_level="warning", log_config=None)
    )
    threading.Thread(target=server.run, daemon=True).start()

    icon = _build_tray_icon(url, server)
    icon.run()  # blocks the main thread until "ปิดโปรแกรม" calls icon.stop()


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:
        import traceback

        _log(traceback.format_exc())
        _message_box(
            f"เปิดโปรแกรมไม่สำเร็จ:\n{exc}\n\nรายละเอียดอยู่ที่ {LOG_PATH}"
        )
        sys.exit(1)
