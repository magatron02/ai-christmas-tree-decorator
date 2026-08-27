"""Lay out dist/TreeDecorator/ the way the installer will, so the frozen app can be tested.

PyInstaller freezes only the Python side; the installer is what drops frontend/, catalog/ and
the rembg model beside the exe (see installer/TreeDecorator.iss). Running dist/TreeDecorator/
TreeDecorator.exe straight after a build therefore tests a layout no user will ever have —
it has no web assets and no catalogue. This copies the missing half in.

Kept out of the .spec on purpose: if these folders were bundled by PyInstaller they would land
inside _internal/ (wrong place — backend.config points ROOT at the exe's own folder) and the
installer's "don't overwrite a catalogue the shop has edited" rule could not apply to them.

    python scripts/stage_desktop_build.py
"""

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist" / "TreeDecorator"


def main():
    if not (DIST / "TreeDecorator.exe").is_file():
        raise SystemExit(f"no frozen build at {DIST} — run PyInstaller first")

    shutil.copytree(ROOT / "frontend", DIST / "frontend", dirs_exist_ok=True)
    print("staged frontend/")

    catalog_out = DIST / "catalog"
    catalog_out.mkdir(parents=True, exist_ok=True)
    for item in (ROOT / "catalog").glob("*.json"):
        shutil.copy2(item, catalog_out / item.name)
    embeddings = ROOT / "catalog" / "embeddings.npy"
    if embeddings.is_file():
        shutil.copy2(embeddings, catalog_out / embeddings.name)
    images = ROOT / "catalog" / "images"
    if images.is_dir():
        shutil.copytree(images, catalog_out / "images", dirs_exist_ok=True)
    # optional: without them the app cuts on the fly, same as before they existed
    cutouts = ROOT / "catalog" / "cutouts"
    if cutouts.is_dir():
        shutil.copytree(cutouts, catalog_out / "cutouts", dirs_exist_ok=True)
    print("staged catalog/")

    model = ROOT / "build_assets" / "models" / "u2net.onnx"
    if not model.is_file():
        model = Path.home() / ".u2net" / "u2net.onnx"
    if model.is_file():
        (DIST / "models").mkdir(exist_ok=True)
        shutil.copy2(model, DIST / "models" / "u2net.onnx")
        print("staged models/u2net.onnx")
    else:
        print("no u2net.onnx found — background removal will download it on first use")

    print(f"\nready: {DIST / 'TreeDecorator.exe'}")


if __name__ == "__main__":
    sys.exit(main())
