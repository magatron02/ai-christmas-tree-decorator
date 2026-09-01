# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build for the desktop build of Tree Decorator.

Freezes the Python side only — code plus its dependencies. The app's *data* (frontend/,
catalog/, the rembg model) is deliberately not bundled here: backend.config points ROOT at
the exe's own folder when frozen, and the installer drops those directories there, so the
shipped catalogue stays an ordinary folder the settings page can keep writing to. Bundling
them under _internal/ would make them read-only-by-convention and invisible to the user.
"""

from PyInstaller.utils.hooks import collect_all, collect_submodules, copy_metadata

datas = [("backend/prompts", "backend/prompts")]
binaries = []
hiddenimports = []

# onnxruntime ships native .dll/.pyd next to Python shims, and rembg (with pymatting, which
# it imports for alpha matting) reaches its sessions by name at runtime — none of that
# survives static analysis alone.
for package in ("onnxruntime", "rembg", "pymatting"):
    pkg_datas, pkg_binaries, pkg_hidden = collect_all(package)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hidden

# These four read their own version out of the installed dist-info at import time, which a
# frozen app has none of unless it is copied in. pymatting is the one that actually bit:
# without its metadata the first background removal died with PackageNotFoundError, 60
# seconds into a click, having already looked like it was working.
for package in ("pymatting", "rembg", "onnxruntime", "numpy"):
    datas += copy_metadata(package)

# uvicorn resolves its loop/protocol implementations from strings at startup
hiddenimports += collect_submodules("uvicorn")
hiddenimports += ["backend.main"]

a = Analysis(
    ["scripts/launcher.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["pytest", "httpx", "tkinter", "matplotlib"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="TreeDecorator",
    debug=False,
    strip=False,
    upx=False,
    console=False,  # the system tray icon is the quit button now — see scripts/launcher.py
    icon="frontend/icon.ico",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="TreeDecorator",
)
