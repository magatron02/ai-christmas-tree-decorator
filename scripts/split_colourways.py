"""Split a product photo that shows one code in several colours into one image per colour.

    python scripts/split_colourways.py --dry-run     # report what would split, change nothing
    python scripts/split_colourways.py

This catalogue photographs a product across its whole colour range in a single frame: code
4400-1 is one 4-inch tinsel garland, and its photo shows six of them side by side in blue,
pink, silver, gold, red and green. That is one SKU, not six products — but it is also not a
usable picker thumbnail, because picking it hands the generator all six colours at once and
the tree comes back with a six-colour montage pasted on it.

So the code stays one code, and the picture becomes several: the picker shows the same code
once per colour, each card carrying just that colour.

Splitting is geometric — find the runs of foreground separated by page background — and it is
deliberately conservative. A wrong split produces exactly the kind of misleading thumbnail
this whole exercise is removing, so a crop is only split when the panels come out evenly
sized, which is what a colour range looks like and what a mixed montage does not. Anything
that does not split cleanly is left exactly as it was.

Writes catalog/variants.json: code -> [image filename per colour], read by catalog.variants_of.
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.services import catalog  # noqa: E402

IMAGES = ROOT / "catalog" / "images"
VARIANTS_DIR = IMAGES / "variants"
OUT = ROOT / "catalog" / "variants.json"

INK_THRESHOLD = 60        # channel-sum distance from the page background that counts as ink
COVERAGE = 0.20           # fraction of a line that must be ink for it to be inside a panel
MIN_PANEL_PX = 24         # narrower than this is a stray mark, not a product
MIN_PANELS, MAX_PANELS = 2, 12
MAX_WIDTH_RATIO = 1.7     # widest panel / narrowest; a colour range is evenly spaced
MIN_PANEL_SHARE = 0.05    # each panel must be at least this much of the crop's long side
PAD = 3


def background(pixels):
    """The page colour, taken from the crop's border rather than assumed white — these pages
    are printed on cream and some panels sit on a tinted block."""
    edge = np.concatenate([pixels[0], pixels[-1], pixels[:, 0], pixels[:, -1]])
    values, counts = np.unique(edge.reshape(-1, 3), axis=0, return_counts=True)
    return values[counts.argmax()]


def runs_along(ink, axis):
    """Contiguous stretches of the given axis whose lines are mostly ink."""
    profile = ink.mean(axis=axis)
    found, start = [], None
    for index, inside in enumerate(profile > COVERAGE):
        if inside and start is None:
            start = index
        elif not inside and start is not None:
            if index - start >= MIN_PANEL_PX:
                found.append((start, index))
            start = None
    if start is not None and len(profile) - start >= MIN_PANEL_PX:
        found.append((start, len(profile)))
    return found


def confident(panels, span):
    if not MIN_PANELS <= len(panels) <= MAX_PANELS:
        return False
    widths = [end - start for start, end in panels]
    if min(widths) < MIN_PANEL_SHARE * span:
        return False
    return max(widths) / min(widths) <= MAX_WIDTH_RATIO


def split(path):
    """Returns (axis, panels) for a confident split, or (None, []) to leave the crop alone."""
    pixels = np.asarray(Image.open(path).convert("RGB")).astype(int)
    ink = np.abs(pixels - background(pixels)).sum(axis=2) > INK_THRESHOLD

    columns = runs_along(ink, axis=0)
    if confident(columns, pixels.shape[1]):
        return "x", columns
    rows = runs_along(ink, axis=1)
    if confident(rows, pixels.shape[0]):
        return "y", rows
    return None, []


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()

    codes = [row["code"] for row in catalog._rows() if catalog.crop_is_showable(row["code"])]
    if args.limit:
        codes = codes[: args.limit]

    if not args.dry_run:
        VARIANTS_DIR.mkdir(parents=True, exist_ok=True)

    variants, counts = {}, {}
    for code in codes:
        path = IMAGES / catalog.image_for(code)
        if not path.is_file():
            continue
        try:
            axis, panels = split(path)
        except Exception as exc:
            print(f"  {code}: {type(exc).__name__}: {exc}")
            continue
        if not panels:
            continue

        counts[len(panels)] = counts.get(len(panels), 0) + 1
        if args.dry_run:
            variants[code] = len(panels)
            continue

        image = Image.open(path).convert("RGB")
        names = []
        for index, (start, end) in enumerate(panels, 1):
            if axis == "x":
                box = (max(start - PAD, 0), 0, min(end + PAD, image.width), image.height)
            else:
                box = (0, max(start - PAD, 0), image.width, min(end + PAD, image.height))
            name = f"{code.replace('/', '_')}--{index}.png"
            image.crop(box).save(VARIANTS_DIR / name)
            names.append(name)
        variants[code] = names

    if not args.dry_run:
        OUT.write_text(json.dumps(variants, indent=1, ensure_ascii=False), encoding="utf-8")
        # a crop that stopped being showable since the last run leaves its colour images
        # behind; they would still be served, and the manifest is the only thing that knows
        # they are stale
        keep = {name for names in variants.values() for name in names}
        removed = 0
        for stale in VARIANTS_DIR.glob("*.png"):
            if stale.name not in keep:
                stale.unlink()
                removed += 1
        if removed:
            print(f"removed {removed} colour images whose product is no longer showable")

    total = sum(len(v) if isinstance(v, list) else v for v in variants.values())
    print(f"{len(codes)} showable crops examined")
    print(f"{len(variants)} split into {total} colour images")
    print(f"{len(codes) - len(variants)} left as a single image")
    for panels, n in sorted(counts.items()):
        print(f"    {panels:2} colours: {n}")
    if not args.dry_run:
        print(f"\n-> {OUT}\n-> {VARIANTS_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
