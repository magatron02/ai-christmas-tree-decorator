"""Pair each product code with the photo the catalogue prints next to it.

    python scripts/build_product_index.py "ac5-source/CHRISTMAS BKK BOOK2024 .pdf (12).pdf" \
        --pages ac5-source

Phase B of Product.md 8.1, and what 8.3c needs before it can say "this looks like 017-06".

There is no single rule. Looking at the layouts: on the bauble pages the label sits a
consistent 15-19 pt below its product; on the tree pages it sits beside it; on others the
gap runs to 70 pt. So each pairing is made by whichever rule fits and is recorded with the
rule that fired and the distance, and those become a confidence tier.

Nothing here is verified by this script, and it does not pretend to be. NonGoals.md 7 forbids
presenting a product code as certain when it is not, so the design is that 8.3c always shows
the cropped photo next to the code it is proposing. A wrong pairing is then obvious to the
person deciding, at the moment they decide, rather than sitting unnoticed in a data file.
`--contact` writes a sheet for spot-checking a page at a time.
"""

import argparse
import json
import re
import sys
from pathlib import Path

import fitz
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent

CODE = re.compile(r"\b(\d{3,5}-\d{1,3}(?:/[A-Za-z0-9]+)*(?:[A-Z]{1,3}\b)?)")
LABEL_MAX_PT = 28

# a product photo is smaller than half the page (that is the background) and bigger than an
# icon; the red price ribbons are wide and flat, so they are excluded by shape
MAX_AREA_FRACTION = 0.5
MIN_SIDE_PT = 18
MAX_ASPECT = 3.5

BELOW_GAP_PT = 90      # a label this far under a photo is plausibly its label
SIDE_GAP_PT = 220      # tree pages put the label beside the photo


def centre(bbox):
    return ((bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2)


def labels_on(page):
    found = []
    for block in page.get_text("dict")["blocks"]:
        if block["type"] != 0:
            continue
        for line in block["lines"]:
            for span in line["spans"]:
                text = span["text"].strip()
                if span["size"] >= LABEL_MAX_PT:
                    continue
                for match in CODE.finditer(text):
                    found.append((match.group(1), span["bbox"]))
    return found


def products_on(page):
    page_area = page.rect.width * page.rect.height
    out = []
    for info in page.get_image_info(xrefs=True):
        x0, y0, x1, y1 = info["bbox"]
        width, height = x1 - x0, y1 - y0
        if width * height > page_area * MAX_AREA_FRACTION:
            continue                                   # the page background
        if min(width, height) < MIN_SIDE_PT:
            continue                                   # icons, hairlines
        if max(width, height) / max(min(width, height), 1) > MAX_ASPECT:
            continue                                   # price ribbons and banners
        out.append(info)
    return out


def pair(label_bbox, products):
    """Best photo for one label, with the rule that chose it and how far away it was."""
    lx, ly = centre(label_bbox)

    above = []
    for info in products:
        x0, y0, x1, y1 = info["bbox"]
        if y1 > ly:
            continue
        overlaps = x0 - 25 <= lx <= x1 + 25
        if overlaps and ly - y1 <= BELOW_GAP_PT:
            above.append((ly - y1, info))
    if above:
        gap, info = min(above, key=lambda t: t[0])
        return info, "above", round(gap, 1)

    beside = []
    for info in products:
        x0, y0, x1, y1 = info["bbox"]
        if not (y0 - 40 <= ly <= y1 + 40):
            continue
        gap = x0 - lx if x0 > lx else lx - x1
        if 0 <= gap <= SIDE_GAP_PT:
            beside.append((gap, info))
    if beside:
        gap, info = min(beside, key=lambda t: t[0])
        return info, "beside", round(gap, 1)

    if not products:
        return None, "none", None
    gap, info = min(
        ((((lx - centre(i["bbox"])[0]) ** 2 + (ly - centre(i["bbox"])[1]) ** 2) ** 0.5, i)
         for i in products), key=lambda t: t[0]
    )
    return info, "nearest", round(gap, 1)


def match_quality(rule, gap):
    """Which rule fired, not how likely it is to be right.

    An earlier version called these high/medium/low. Spot-checking page 63 showed "high"
    containing pairings that are ambiguous rather than certain: several labels have both a
    retail pack and a loose ball printed above them, and picking one is a coin toss the tier
    name was quietly hiding. These names say what actually happened instead.
    """
    if rule == "above" and gap is not None and gap <= 40:
        return "directly_above"
    if rule == "above":
        return "above_far"
    if rule == "beside":
        return "beside"
    return "no_rule_fitted"


MAX_CROP_PX = 384   # plenty for looking at and for an embedding; full page res was 850 MB


def crop(page_png, bbox, scale, pad=0.04):
    x0, y0, x1, y1 = (v * scale for v in bbox)
    px, py = (x1 - x0) * pad, (y1 - y0) * pad
    box = (max(x0 - px, 0), max(y0 - py, 0),
           min(x1 + px, page_png.width), min(y1 + py, page_png.height))
    piece = page_png.crop(tuple(round(v) for v in box))
    piece.thumbnail((MAX_CROP_PX, MAX_CROP_PX))
    return piece


def main():
    parser = argparse.ArgumentParser(description="Pair product codes with catalogue photos.")
    parser.add_argument("pdf")
    parser.add_argument("--pages", default="ac5-source", help="folder of <page>.png renders")
    parser.add_argument("--out", default="catalog")
    parser.add_argument("--contact", type=int, help="write a contact sheet for this page")
    args = parser.parse_args()

    doc = fitz.open(args.pdf)
    pages_dir = ROOT / args.pages
    images_dir = ROOT / args.out / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    index, tally = [], {}
    contact = []

    for number in range(doc.page_count):
        page = doc[number]
        page_png_path = pages_dir / f"{number + 1}.png"
        page_png = Image.open(page_png_path) if page_png_path.is_file() else None
        scale = page_png.width / page.rect.width if page_png else None

        products = products_on(page)
        for code, bbox in labels_on(page):
            info, rule, gap = pair(bbox, products)
            tier = "no_photo_found" if info is None else match_quality(rule, gap)
            tally[tier] = tally.get(tier, 0) + 1

            image_name = None
            if info is not None and page_png is not None:
                piece = crop(page_png, info["bbox"], scale)
                image_name = f"{code.replace('/', '_')}.png"
                piece.save(images_dir / image_name)
                if args.contact and number + 1 == args.contact:
                    contact.append((code, tier, piece))

            index.append({
                "code": code,
                "pdf_page": number + 1,
                "image": image_name,
                "rule": rule,
                "gap_pt": gap,
                "match": tier,
            })

    # Several codes legitimately share one photo: a ribbon listing two sizes points at one
    # pack. Counted so the number is known rather than discovered later as a surprise.
    from collections import Counter

    shared = Counter(row["image"] for row in index if row["image"])
    for row in index:
        if row["image"]:
            row["shared_with"] = shared[row["image"]] - 1

    out = ROOT / args.out / "product_images.json"
    out.write_text(json.dumps(index, indent=1, ensure_ascii=False), encoding="utf-8")

    print(f"{len(index)} labels -> {out}")
    for tier, count in sorted(tally.items(), key=lambda kv: -kv[1]):
        print(f"  {tier:16} {count:5}  {count / max(len(index), 1) * 100:5.1f}%")
    sharing = sum(1 for row in index if row.get("shared_with"))
    print(f"  {'sharing a photo':16} {sharing:5}  {sharing / max(len(index), 1) * 100:5.1f}%")
    print(f"crops in {images_dir}")
    print("\nNone of this is verified. 8.3c must show the photo beside the code it proposes.")

    if contact:
        cell = 240
        columns = min(8, len(contact))
        rows = (len(contact) + columns - 1) // columns
        sheet = Image.new("RGB", (columns * cell, rows * cell), (225, 225, 225))
        draw = ImageDraw.Draw(sheet)
        for i, (code, tier, piece) in enumerate(contact):
            thumb = piece.copy()
            thumb.thumbnail((cell - 16, cell - 40))
            x, y = (i % columns) * cell, (i // columns) * cell
            sheet.paste(thumb, (x + (cell - thumb.width) // 2, y + 32))
            draw.text((x + 6, y + 6), f"{code}  {tier}", fill=(20, 20, 20))
        path = ROOT / args.out / f"contact_page{args.contact}.png"
        sheet.save(path)
        print(f"contact sheet: {path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
