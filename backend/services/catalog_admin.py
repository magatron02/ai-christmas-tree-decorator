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
from backend.services import catalog, shop_overlay
from backend.validation import ValidationError

PRODUCTS_PATH = config.CATALOG_PATH
IMAGES_DIR = config.CATALOG_PATH.parent / "images"
PRODUCT_IMAGES_PATH = config.CATALOG_PATH.parent / "product_images.json"


def _load(path, default):
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _parse_price(raw):
    """Blank stays unpriced rather than free — this is manual entry, so a typo (an empty
    field submitted by mistake) must not silently read as "0 บาท"."""
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        price = float(raw)
    except ValueError:
        raise ValidationError(f"ราคา '{raw}' ไม่ใช่ตัวเลข")
    if price < 0:
        raise ValidationError("ราคาต้องไม่ติดลบ")
    return price


def _saved_state(code):
    """What the two generation-critical fields actually resolved to once saved.

    Both are derived, not typed: `size_raw` only reaches the prompt if parse_size() can read
    it, and `section` only reaches the picker if it matches a category's needles. Typing
    something neither can use fails silently otherwise — the row saves, and the miss only
    shows up as a product that never appears under a filter, or one that quietly can't do
    exact scale. The form reports these back instead.
    """
    row = catalog.find(code)
    millimetres = catalog.longest_side_mm(row)
    return {
        "size_mm": millimetres,
        "category": catalog.category_of(row),
    }


def add_product(code, size_raw, section, book, image_bytes, price=None):
    """Append one product. Raises ValidationError on a duplicate code or bad input."""
    code = (code or "").strip().upper()
    if not code:
        raise ValidationError("ใส่รหัสสินค้าด้วย")
    if not image_bytes:
        raise ValidationError("ใส่รูปสินค้าด้วย")
    price = _parse_price(price)

    products = _load(PRODUCTS_PATH, [])
    if any(row["code"] == code for row in products):
        raise ValidationError(
            f"'{code}' มีใน catalogue อยู่แล้ว — ใช้รหัสอื่น "
            "หรือถ้าตั้งใจจะแทนที่ตัวเดิมจริง ๆ ให้แก้ไฟล์ catalogue ตรง ๆ"
        )

    size_raw = size_raw.strip() or None
    products.append({
        "code": code,
        "size_raw": size_raw,
        "size": catalog.parse_size(size_raw) if size_raw else None,
        "section": section.strip() or None,
        "page_headings": [],
        "pdf_page": None,
        "bbox": None,
        "duplicate": False,
        "book": book.strip() or None,
        "price": price,
    })

    filename = f"{code.replace('/', '_')}.png"
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    (IMAGES_DIR / filename).write_bytes(image_bytes)

    images = _load(PRODUCT_IMAGES_PATH, [])
    images.append({
        "code": code, "pdf_page": None, "image": filename, "match": "manual", "shared_with": 0,
    })

    PRODUCTS_PATH.write_text(json.dumps(products, indent=1, ensure_ascii=False), encoding="utf-8")
    PRODUCT_IMAGES_PATH.write_text(json.dumps(images, indent=1, ensure_ascii=False), encoding="utf-8")
    catalog.refresh()
    return {"code": code, "image": filename, **_saved_state(code)}


EDITABLE_FIELDS = ("size_raw", "size", "section", "book", "price")


def update_product(code, size_raw, section, book, image_bytes=None, price=None):
    """Edit an existing product's fields, and optionally its photo.

    The fields go to the shop overlay, never into the base — the base is book data, and a
    correction written into it is destroyed by the next re-import (ADR-0001). Only the fields
    that actually differ from what the book says are recorded: submitting the form unchanged
    must not quietly claim an opinion on all five, or a re-import would stop correcting this
    product at all. `size` travels with `size_raw` because it is derived from it — leaving the
    book's parsed size beside a shop-typed size string is the one pairing a per-field merge
    cannot work out for itself.

    Never renames or deletes a code — the row is found by its existing code, which does not
    change; that keeps this out of the image/variant-file migration a rename would need.
    NonGoals.md 7/8 still govern the photo: a code split into colour variants
    (catalog.variants_of returns more than one entry) is never something a single new photo
    can safely replace, since the picker always shows the variant list over a lone crop —
    refused before anything is written, same as every other check here.
    """
    code = (code or "").strip().upper()
    base = next((r for r in _load(PRODUCTS_PATH, []) if r["code"] == code), None)
    if base is None:
        raise ValidationError(f"ไม่พบรหัส '{code}' ใน catalogue")
    if image_bytes and len(catalog.variants_of(code)) > 1:
        raise ValidationError(
            f"'{code}' ถูกแยกเป็นหลายสีไว้แล้ว (catalog/variants.json) — "
            "เปลี่ยนรูปเดี่ยวแบบนี้จะไม่ถูกใช้ แก้ไฟล์ variants ตรง ๆ แทน"
        )

    size_raw = size_raw.strip() or None
    typed = {
        "size_raw": size_raw,
        "size": catalog.parse_size(size_raw) if size_raw else None,
        "section": section.strip() or None,
        "book": book.strip() or None,
        "price": _parse_price(price),
    }
    opinions = {
        name: value for name, value in typed.items() if value != base.get(name)
    }
    shop_overlay.set_fields(code, opinions, speaks_for=EDITABLE_FIELDS)

    if image_bytes:
        filename = f"{code.replace('/', '_')}.png"
        IMAGES_DIR.mkdir(parents=True, exist_ok=True)
        (IMAGES_DIR / filename).write_bytes(image_bytes)

        images = _load(PRODUCT_IMAGES_PATH, [])
        existing = next((im for im in images if im["code"] == code), None)
        if existing:
            existing["image"] = filename
            existing["match"] = "manual"
        else:
            images.append({
                "code": code, "pdf_page": None, "image": filename, "match": "manual", "shared_with": 0,
            })
        PRODUCT_IMAGES_PATH.write_text(json.dumps(images, indent=1, ensure_ascii=False), encoding="utf-8")

    catalog.refresh()
    return {"code": code, **_saved_state(code)}
