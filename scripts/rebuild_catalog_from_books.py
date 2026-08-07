"""Rebuild catalog/ from scratch, using ONLY book1.pdf and book2.pdf as the source.

    python scripts/rebuild_catalog_from_books.py

Replaces scripts/ingest_new_book.py's merge-into-the-old-catalogue approach: the shop
decided the old catalogue (built from a different, larger PDF) should be discarded, and the
two books here are now the sole source of truth. This writes catalog/products.json and
catalog/product_images.json from nothing rather than appending to what was there.

A code appearing in both books (or twice within one book) is a genuine collision now, since
there is no larger catalogue to defer to — NonGoals.md 7/8 still forbid guessing which one a
reused code means, so the first occurrence wins and every later one is recorded in
catalog/book_conflicts.json rather than silently overwritten.

Does not call describe_catalog.py / embed_catalog.py — those cost real OpenAI API calls per
code, so they're a separate, explicit step (see README note printed at the end).
"""

import json
import sys
from pathlib import Path

import fitz
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import build_product_index as bpi  # noqa: E402
import extract_catalog  # noqa: E402

SOURCES = [
    (ROOT / "ac5-source" / "book1.pdf", ROOT / "ac5-source" / "Book1", (1, 96), "book1"),
    (ROOT / "ac5-source" / "book2.pdf", ROOT / "ac5-source" / "Book2", (1, 32), "book2"),
]

CATALOG_DIR = ROOT / "catalog"
PRODUCTS_PATH = CATALOG_DIR / "products.json"
IMAGES_PATH = CATALOG_DIR / "product_images.json"
IMAGES_DIR = CATALOG_DIR / "images"
CONFLICTS_PATH = CATALOG_DIR / "book_conflicts.json"


def main():
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)

    products, images, conflicts = [], [], []
    seen_codes = set()

    for pdf_path, pages_dir, page_range, book in SOURCES:
        if not pdf_path.is_file():
            print(f"skip {pdf_path.name}: not found")
            continue

        rows, unparsed = extract_catalog.extract(str(pdf_path), pages=page_range, book=book)
        codes_this_book = set()
        for row in rows:
            code = row["code"]
            if code in seen_codes:
                conflicts.append(row)
                continue
            seen_codes.add(code)
            codes_this_book.add(code)
            products.append(row)

        doc = fitz.open(str(pdf_path))
        start, end = page_range
        for number in range(start - 1, min(end, doc.page_count)):
            page_png_path = pages_dir / f"{number + 1}.png"
            if not page_png_path.is_file():
                continue
            page = doc[number]
            page_png = Image.open(page_png_path)
            scale = page_png.width / page.rect.width

            page_products = bpi.products_on(page)
            for code, bbox in bpi.labels_on(page):
                if code not in codes_this_book:
                    continue
                info, rule, gap = bpi.pair(bbox, page_products)
                tier = "no_photo_found" if info is None else bpi.match_quality(rule, gap)
                image_name = None
                if info is not None:
                    image_name = f"{code.replace('/', '_')}.png"
                    bpi.crop(page_png, info["bbox"], scale).save(IMAGES_DIR / image_name)
                # a row is written even with no photo — the index must cover exactly the
                # same codes as products.json, per test_the_index_covers_the_same_codes_
                # as_the_size_table, so "no photo found" is a recorded fact, not a gap
                images.append({
                    "code": code, "pdf_page": number + 1, "image": image_name,
                    "rule": rule, "gap_pt": gap, "match": tier, "book": book,
                })

        print(f"{pdf_path.name}: {len(codes_this_book)} codes, {len(unparsed)} unreadable sizes")

    # several codes legitimately share one photo (a ribbon listing two sizes points at one
    # pack) — counted the same way build_product_index.py does, over every row including the
    # imageless ones, so the count isn't silently dropped for the new source
    from collections import Counter

    shared = Counter(row["image"] for row in images if row["image"])
    for row in images:
        if row["image"]:
            row["shared_with"] = shared[row["image"]] - 1

    PRODUCTS_PATH.write_text(json.dumps(products, indent=1, ensure_ascii=False), encoding="utf-8")
    IMAGES_PATH.write_text(json.dumps(images, indent=1, ensure_ascii=False), encoding="utf-8")
    if conflicts:
        CONFLICTS_PATH.write_text(json.dumps(conflicts, indent=1, ensure_ascii=False), encoding="utf-8")
    elif CONFLICTS_PATH.is_file():
        CONFLICTS_PATH.unlink()

    codes_with_photo = {img["code"] for img in images if img["image"]}
    print(f"\n{len(products)} codes total -> {PRODUCTS_PATH}")
    print(f"{len(images)} index rows, {len(codes_with_photo)} with a cropped photo -> {IMAGES_DIR}")
    print(f"{len(conflicts)} collisions -> {CONFLICTS_PATH if conflicts else '(none)'}")
    print(
        "\nSearch (vision descriptions + embeddings) is NOT built yet — run:\n"
        "  python scripts/describe_catalog.py\n"
        "  python scripts/embed_catalog.py\n"
        "(real OpenAI API cost, roughly one small vision call per code)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
