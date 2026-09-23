"""Generate candidate crops for every catalogue code that has no photo file locally yet, plus a
full-page "context" image with the candidate's box drawn on it — so a person can tell at a
glance whether the pairing grabbed the right product, not just trust the tier label.

    python scripts/stage_missing_photos.py "C:\\path\\to\\Ebook_catalougue.pdf" --out <staging dir>

Exists because re-deriving crops from a catalogue PDF is not reliable enough to write straight
into catalog/images/: measured against 415 codes this repo already has a correct photo for,
the pairing disagreed with the known-good photo on ~34% of them even restricted to the
"directly_above" (highest) confidence tier (2026-09-23). NonGoals.md's "never guess" spirit
extends to photos, not just codes/sizes — a wrong product photo shown to a customer is worse
than no photo at all, so nothing here touches catalog/images/ directly. Pair with
review_missing_photos.py, which is the human-in-the-loop step that actually writes the file,
one accepted code at a time.

Writes <out>/manifest.json — the review server's only input — plus <out>/crops/<code>.png (what
would go live) and <out>/context/<code>.jpg (the whole page, candidate box in red) for each code.
Safe to re-run: skips a code whose crop+context already exist.
"""

import argparse
import json
import sys
from pathlib import Path

import fitz
from PIL import Image, ImageDraw

from _bootstrap import ROOT  # noqa: E402

sys.path.insert(0, str(ROOT / "scripts"))
import build_product_index as bpi  # noqa: E402

from backend.services import catalog  # noqa: E402

IMAGES_DIR = ROOT / "catalog" / "images"
INDEX_PATH = ROOT / "catalog" / "product_images.json"

CONTEXT_MAX_PX = 1400  # full page, downscaled for a browser to load quickly


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf")
    parser.add_argument("--out", required=True)
    parser.add_argument("--limit", type=int, help="stop after this many new codes (for a quick look)")
    args = parser.parse_args()

    out = Path(args.out)
    crops_dir = out / "crops"
    context_dir = out / "context"
    crops_dir.mkdir(parents=True, exist_ok=True)
    context_dir.mkdir(parents=True, exist_ok=True)

    index = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    missing = [
        row for row in index
        if row.get("image") and not (IMAGES_DIR / row["image"]).is_file()
    ]
    print(f"{len(missing)} codes have no local photo yet")

    todo = [row for row in missing if not (crops_dir / f"{row['code'].replace('/', '_')}.png").is_file()]
    if args.limit:
        todo = todo[: args.limit]
    print(f"{len(todo)} to stage this run (already staged: {len(missing) - len(todo)})")

    by_page = {}
    for row in todo:
        by_page.setdefault(row["pdf_page"], []).append(row)

    doc = fitz.open(args.pdf)
    manifest = []
    not_found = []

    for page_no, rows in sorted(by_page.items()):
        page = doc[page_no - 1]
        need = {r["code"]: r for r in rows}
        pix = page.get_pixmap(dpi=200)
        page_png = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        scale = pix.width / page.rect.width
        products = bpi.products_on(page)

        found_this_page = set()
        for code, bbox in bpi.labels_on(page):
            if code not in need or code in found_this_page:
                continue
            info, rule, gap = bpi.pair(bbox, products)
            if info is None:
                continue
            found_this_page.add(code)
            row = need[code]

            safe = code.replace("/", "_")
            crop = bpi.crop(page_png, info["bbox"], scale)
            crop.save(crops_dir / f"{safe}.png")

            context = page_png.copy()
            context.thumbnail((CONTEXT_MAX_PX, CONTEXT_MAX_PX))
            ctx_scale = context.width / page_png.width
            draw = ImageDraw.Draw(context)
            # info["bbox"] is in PDF point space, like crop()'s own bbox argument — has to go
            # through the same points-to-pixels `scale` first, then the thumbnail's own shrink
            # factor, or the box lands near the origin, off the actual product entirely.
            x0, y0, x1, y1 = (v * scale * ctx_scale for v in info["bbox"])
            draw.rectangle([x0, y0, x1, y1], outline=(220, 30, 30), width=4)
            # the printed code text itself, same conversion — lets a reviewer see label and
            # candidate photo at once instead of hunting the page for where "06072-3" is set
            lx0, ly0, lx1, ly1 = (v * scale * ctx_scale for v in bbox)
            draw.rectangle([lx0, ly0, lx1, ly1], outline=(30, 90, 220), width=4)
            context.convert("RGB").save(context_dir / f"{safe}.jpg", quality=85)

            try:
                product_row = catalog.find(code)
                label = catalog.describe(product_row)
                section = product_row.get("section")
            except Exception:
                label, section = code, None

            manifest.append({
                "code": code, "image": row["image"], "pdf_page": page_no,
                "rule": rule, "gap_pt": gap,
                "match": bpi.match_quality(rule, gap),
                "label": label, "section": section,
                "crop": f"crops/{safe}.png", "context": f"context/{safe}.jpg",
            })

        for code in need:
            if code not in found_this_page:
                not_found.append(code)

    # merge with whatever a previous run already staged, so re-running only adds new entries
    manifest_path = out / "manifest.json"
    existing = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else []
    existing_codes = {m["code"] for m in existing}
    merged = existing + [m for m in manifest if m["code"] not in existing_codes]
    manifest_path.write_text(json.dumps(merged, indent=1, ensure_ascii=False), encoding="utf-8")

    print(f"staged {len(manifest)} candidates this run -> {manifest_path} ({len(merged)} total)")
    if not_found:
        print(f"{len(not_found)} codes never matched a label on their recorded page: {not_found[:20]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
