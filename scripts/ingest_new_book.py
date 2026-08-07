"""One-time ingestion of the new catalogue book into catalog/.

    python scripts/ingest_new_book.py

Checked before writing anything (both PDFs, in page-range chunks, against the existing
catalog/products.json codes): book1.pdf is 96 pages and 100% identical to the catalogue
already in the system (1,092 of its 1,092 codes already exist) — it is a re-export of the
same 2024 book, not new material, so it contributes nothing and is skipped entirely. book2.pdf
is a genuinely different, smaller catalogue: 32 pages, 201 codes, only ~1% overlap. That is
the one this ingests. (The pre-rendered ac5-source/Book1 folder turned out to be a duplicate
render of the existing book and is likewise unused here; ac5-source/Book2 — one PNG per page,
1:1 with book2.pdf — is what the crop step reads.)

Merges into catalog/products.json and catalog/product_images.json rather than replacing them
— running build_product_index.py's own main() against this PDF would overwrite
product_images.json wholesale and lose the existing 1,095-row catalogue, so this reuses its
pairing/cropping functions directly instead of running it as a script.

Never overwrites a code that already exists. NonGoals.md 7/8 forbid guessing which product a
reused code now means, so a collision is recorded in catalog/book_conflicts.json for someone
to resolve by hand rather than silently repointed.
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

BOOK = "2026"
SOURCES = [
    (ROOT / "ac5-source" / "book2.pdf", ROOT / "ac5-source" / "Book2", (1, 32)),
]

PRODUCTS_PATH = ROOT / "catalog" / "products.json"
IMAGES_PATH = ROOT / "catalog" / "product_images.json"
IMAGES_DIR = ROOT / "catalog" / "images"
CONFLICTS_PATH = ROOT / "catalog" / "book_conflicts.json"


def main():
    existing_products = json.loads(PRODUCTS_PATH.read_text(encoding="utf-8"))
    existing_codes = {row["code"] for row in existing_products}
    existing_images = json.loads(IMAGES_PATH.read_text(encoding="utf-8"))

    new_products, new_images, conflicts = [], [], []
    seen_new_codes = set()

    for pdf_path, pages_dir, page_range in SOURCES:
        if not pdf_path.is_file():
            print(f"skip {pdf_path.name}: not found")
            continue

        rows, _unparsed = extract_catalog.extract(str(pdf_path), pages=page_range, book=BOOK)
        for row in rows:
            code = row["code"]
            if code in existing_codes or code in seen_new_codes:
                conflicts.append(row)
                continue
            seen_new_codes.add(code)
            new_products.append(row)

        doc = fitz.open(str(pdf_path))
        start, end = page_range
        for number in range(start - 1, min(end, doc.page_count)):
            page_png_path = pages_dir / f"{number + 1}.png"
            if not page_png_path.is_file():
                continue
            page = doc[number]
            page_png = Image.open(page_png_path)
            scale = page_png.width / page.rect.width

            products = bpi.products_on(page)
            for code, bbox in bpi.labels_on(page):
                if code not in seen_new_codes:
                    continue  # collided against the existing catalogue, or a repeat on-page
                info, rule, gap = bpi.pair(bbox, products)
                if info is None:
                    continue
                filename = f"{code.replace('/', '_')}.png"
                bpi.crop(page_png, info["bbox"], scale).save(IMAGES_DIR / filename)
                new_images.append({
                    "code": code, "pdf_page": number + 1, "image": filename,
                    "rule": rule, "gap_pt": gap, "match": bpi.match_quality(rule, gap),
                    "shared_with": 0,
                })

    PRODUCTS_PATH.write_text(
        json.dumps(existing_products + new_products, indent=1, ensure_ascii=False),
        encoding="utf-8",
    )
    IMAGES_PATH.write_text(
        json.dumps(existing_images + new_images, indent=1, ensure_ascii=False),
        encoding="utf-8",
    )
    if conflicts:
        CONFLICTS_PATH.write_text(
            json.dumps(conflicts, indent=1, ensure_ascii=False), encoding="utf-8"
        )

    print(f"{len(new_products)} new codes merged, {len(new_images)} photos cropped")
    print(f"{len(conflicts)} code collisions -> {CONFLICTS_PATH if conflicts else '(none)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
