"""Cut the background out of every catalogue photo the picker can reach, once, up front.

Picking a decoration used to run rembg on the spot. Warming the model at startup already took
that from 68s to half a second, but half a second is still a wait for something that never
changes: the same product photo produces the same cut-out every time. This does all of them
in advance and leaves the results in catalog/cutouts/, so a pick becomes a file read.

Only images the picker can actually offer are cut. Of the 1,748 PNGs on disk, 657 are
reachable — the rest belong to codes that are contested, share a crop with too many other
codes, or were judged page furniture, and catalog.crop_is_showable already keeps them out of
the grid. Cutting them would be five minutes and 100 MB spent on pictures nobody can pick.

Trees are not excluded even though the tree picker never cuts them: the same photo can be
chosen as a decoration from panel 2, and that path does cut.

    python scripts/precut_catalog.py            # cut what is missing
    python scripts/precut_catalog.py --recut    # redo everything, e.g. after a rembg upgrade

Safe to re-run and safe to interrupt: finished files are skipped, so a second run picks up
where the first stopped.
"""

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend import config  # noqa: E402
from backend.services import background_removal, catalog  # noqa: E402

IMAGES_DIR = config.CATALOG_PATH.parent / "images"
CUTOUTS_DIR = config.CATALOG_PATH.parent / "cutouts"


def reachable_images():
    """Every image file the picker can put in front of a user, deduplicated.

    Built from the same browse() the picker calls rather than from the directory listing, so
    "reachable" means exactly what the grid means by it.
    """
    rows, _total = catalog.browse(10_000, 0)
    names = set()
    for row in rows:
        code = row["code"]
        names.update(catalog.variants_of(code) or [])
        primary = catalog.image_for(code)
        if primary:
            names.add(primary)
    return sorted(name for name in names if (IMAGES_DIR / name).is_file())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recut", action="store_true",
                        help="redo images that already have a cut-out")
    args = parser.parse_args()

    names = reachable_images()
    todo = [n for n in names if args.recut or not (CUTOUTS_DIR / n).is_file()]
    done_already = len(names) - len(todo)

    print(f"{len(names)} images reachable from the picker")
    if done_already:
        print(f"{done_already} already cut — skipping (use --recut to redo them)")
    if not todo:
        print("nothing to do")
        return 0

    print(f"cutting {len(todo)}; loading the model first…")
    background_removal.warm()

    failures = []
    start = time.time()
    for i, name in enumerate(todo, 1):
        source = IMAGES_DIR / name
        target = CUTOUTS_DIR / name
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            target.write_bytes(background_removal.remove_background(source.read_bytes()))
        except background_removal.BackgroundRemovalError as exc:
            # Usually "nothing was cut" — the product and its backdrop are too close in
            # colour. Leaving no file is deliberate: the runtime falls back to cutting live
            # and the user sees the real reason, rather than being handed an uncut picture.
            failures.append((name, str(exc)))
            target.unlink(missing_ok=True)

        if i % 25 == 0 or i == len(todo):
            rate = (time.time() - start) / i
            left = rate * (len(todo) - i)
            print(f"  {i}/{len(todo)}  {rate:.2f}s each  ~{left / 60:.1f} min left")

    elapsed = time.time() - start
    written = len(todo) - len(failures)
    size = sum(p.stat().st_size for p in CUTOUTS_DIR.rglob("*.png")) if CUTOUTS_DIR.is_dir() else 0
    print(f"\ncut {written} in {elapsed / 60:.1f} min — {CUTOUTS_DIR} is now {size / 1e6:.0f} MB")

    if failures:
        print(f"\n{len(failures)} could not be cut; these still cut live when picked:")
        for name, why in failures[:20]:
            print(f"  {name}: {why}")
        if len(failures) > 20:
            print(f"  … and {len(failures) - 20} more")
    return 0


if __name__ == "__main__":
    sys.exit(main())
