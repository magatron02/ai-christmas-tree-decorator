"""Add one catalogue product by hand, from the settings page.

Product.md 8.1 built the 1,095-row catalogue from a PDF; this is the manual door for the
odd item that never came from one — a single new product, or an item from a book too small
to justify running the whole extract/build-index pipeline over.

Same rule as the PDF pipeline: never overwrite. A code that already exists is a collision,
not an update — NonGoals.md 7/8 forbid guessing which product a reused code now means, and
silently replacing a row is exactly that guess.
"""

import json

from backend import config
from backend.services import catalog
from backend.validation import ValidationError

PRODUCTS_PATH = config.CATALOG_PATH
IMAGES_DIR = config.CATALOG_PATH.parent / "images"
PRODUCT_IMAGES_PATH = config.CATALOG_PATH.parent / "product_images.json"


def _load(path, default):
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def add_product(code, size_raw, section, book, image_bytes):
    """Append one product. Raises ValidationError on a duplicate code or bad input."""
    code = (code or "").strip()
    if not code:
        raise ValidationError("Give a product code.")
    if not image_bytes:
        raise ValidationError("Give a photo of the product.")

    products = _load(PRODUCTS_PATH, [])
    if any(row["code"] == code for row in products):
        raise ValidationError(
            f"'{code}' is already in the catalogue. Pick a different code, or edit the "
            "catalogue files directly if this is really meant to replace it."
        )

    products.append({
        "code": code,
        "size_raw": size_raw.strip() or None,
        "size": None,
        "section": section.strip() or None,
        "page_headings": [],
        "pdf_page": None,
        "bbox": None,
        "duplicate": False,
        "book": book.strip() or None,
    })

    filename = f"{code.replace('/', '_')}.png"
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    (IMAGES_DIR / filename).write_bytes(image_bytes)

    images = _load(PRODUCT_IMAGES_PATH, [])
    images.append({
        "code": code, "pdf_page": None, "image": filename, "match": "manual",
    })

    PRODUCTS_PATH.write_text(json.dumps(products, indent=1, ensure_ascii=False), encoding="utf-8")
    PRODUCT_IMAGES_PATH.write_text(json.dumps(images, indent=1, ensure_ascii=False), encoding="utf-8")
    catalog.refresh()
    return {"code": code, "image": filename}
