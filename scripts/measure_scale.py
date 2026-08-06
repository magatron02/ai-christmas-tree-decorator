"""Measure how big the decorations actually came out, against how big they were told to be.

    python scripts/measure_scale.py ac5-results/scale-on --tree-code 05021-1 --element-code 017-06

This is the check behind config.RENDER_SCALE_BIAS. gpt-image-2 renders decorations smaller
than instructed by a consistent factor, so the prompt corrects for it — and a correction
factor nobody can re-measure is a number that silently goes stale. Run this after any model
change, or whenever output starts looking off.

Two images differing by 15% in bauble size look identical side by side. The difference only
exists as a number, which is the reason this exists rather than an eyeball check.
"""

import argparse
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

MIN_BLOB_PX = 12
ROUNDNESS = (0.65, 1.55)


def element_colour(path):
    """The decoration's own colour, taken from the element image that was fed in.

    An earlier version of this script looked for "anything strongly non-green", which also
    found the black tree stand and the gold hanging caps and reported nine-fold size spreads
    that were not there. The element image is right next to the output, so use it instead of
    guessing what a decoration looks like.
    """
    rgb = np.asarray(Image.open(path).convert("RGB")).astype(np.int16)
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    subject = ~((r > 225) & (g > 225) & (b > 225))          # drop the white card
    subject &= np.abs(r - g) + np.abs(g - b) + np.abs(r - b) > 40   # and the grey line art
    if subject.sum() < 50:
        return None
    return np.array([channel[subject].mean() for channel in (r, g, b)])


def measure(path, colour, tolerance=90):
    """Median decoration diameter as a fraction of the tree's height in the same picture.

    Self-referential on purpose: comparing pixels between images would only measure how the
    tree happened to be framed.
    """
    rgb = np.asarray(Image.open(path).convert("RGB")).astype(np.int16)
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]

    subject = ~((r > 235) & (g > 235) & (b > 235))
    subject = ndimage.binary_closing(subject, np.ones((9, 9)))
    rows = np.where(subject.any(axis=1))[0]
    if not len(rows):
        return None
    tree_height = rows[-1] - rows[0] + 1

    distance = np.sqrt(((rgb - colour) ** 2).sum(axis=2))
    coloured = distance < tolerance
    coloured = ndimage.binary_fill_holes(ndimage.binary_closing(coloured, np.ones((5, 5))))
    labels, _ = ndimage.label(coloured)

    diameters = []
    for ys, xs in ndimage.find_objects(labels):
        h, w = ys.stop - ys.start, xs.stop - xs.start
        if min(h, w) < MIN_BLOB_PX or not (ROUNDNESS[0] <= w / h <= ROUNDNESS[1]):
            continue
        diameters.append((h + w) / 2)

    if not diameters:
        return None
    return {
        "tree_height_px": int(tree_height),
        "count": len(diameters),
        "median_px": float(np.median(diameters)),
        "ratio": float(np.median(diameters)) / tree_height,
        "spread": (round(min(diameters)), round(max(diameters))),
        "spread_factor": max(diameters) / min(diameters),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folders", nargs="+", help="run folders under ac5-results/")
    parser.add_argument("--tree-code")
    parser.add_argument("--element-code")
    args = parser.parse_args()

    target = None
    if args.tree_code and args.element_code:
        from backend.services import catalog

        target = catalog.require_size(catalog.find(args.element_code)) / catalog.require_size(
            catalog.find(args.tree_code)
        )
        print(f"target ratio {target:.4f} — {args.element_code} on {args.tree_code}\n")

    print(f"{'run':16} {'tree_px':>8} {'n':>4} {'median':>8} {'ratio':>8} "
          f"{'vs target':>10} {'spread':>12} {'spread x':>9}")
    for name in args.folders:
        folder = ROOT / name if not Path(name).is_absolute() else Path(name)
        images = sorted(folder.glob("*_output.png"))
        if not images:
            print(f"{name:16} no output images")
            continue
        for image in images:
            element = image.with_name(image.name.replace("_output", "_element"))
            colour = element_colour(element) if element.exists() else None
            if colour is None:
                print(f"{folder.name:16} {image.name}: no element image to take a colour from")
                continue
            m = measure(image, colour)
            if m is None:
                print(f"{folder.name:16} {image.name}: nothing measurable")
                continue
            versus = f"{m['ratio'] / target:.2f}x" if target else "-"
            print(f"{folder.name:16} {m['tree_height_px']:>8} {m['count']:>4} "
                  f"{m['median_px']:>8.1f} {m['ratio']:>8.4f} {versus:>10} "
                  f"{str(m['spread']):>12} {m['spread_factor']:>8.2f}x")
    return 0


if __name__ == "__main__":
    sys.exit(main())
