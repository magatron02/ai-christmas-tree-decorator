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
    code = (code or "").strip().upper()
    if not code:
        raise ValidationError("ใส่รหัสสินค้าด้วย")
    if not image_bytes:
        raise ValidationError("ใส่รูปสินค้าด้วย")

    products = _load(PRODUCTS_PATH, [])
    if any(row["code"] == code for row in products):
        raise ValidationError(
            f"'{code}' มีใน catalogue อยู่แล้ว — ใช้รหัสอื่น "
            "หรือถ้าตั้งใจจะแทนที่ตัวเดิมจริง ๆ ให้แก้ไฟล์ catalogue ตรง ๆ"
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


def update_product(code, size_raw, section, book, image_bytes=None):
    """Edit an existing product's fields, and optionally its photo.

    Never renames or deletes a code — the row is found by its existing code, which does not
    change; that keeps this out of the image/variant-file migration a rename would need.
    NonGoals.md 7/8 still govern the photo: a code split into colour variants
    (catalog.variants_of returns more than one entry) is never something a single new photo
    can safely replace, since the picker always shows the variant list over a lone crop —
    refused before anything is written, same as every other check here.
    """
    code = (code or "").strip().upper()
    products = _load(PRODUCTS_PATH, [])
    row = next((r for r in products if r["code"] == code), None)
    if row is None:
        raise ValidationError(f"ไม่พบรหัส '{code}' ใน catalogue")
    if image_bytes and len(catalog.variants_of(code)) > 1:
        raise ValidationError(
            f"'{code}' ถูกแยกเป็นหลายสีไว้แล้ว (catalog/variants.json) — "
            "เปลี่ยนรูปเดี่ยวแบบนี้จะไม่ถูกใช้ แก้ไฟล์ variants ตรง ๆ แทน"
        )

    row["size_raw"] = size_raw.strip() or None
    row["section"] = section.strip() or None
    row["book"] = book.strip() or None
    PRODUCTS_PATH.write_text(json.dumps(products, indent=1, ensure_ascii=False), encoding="utf-8")

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
            images.append({"code": code, "pdf_page": None, "image": filename, "match": "manual"})
        PRODUCT_IMAGES_PATH.write_text(json.dumps(images, indent=1, ensure_ascii=False), encoding="utf-8")

    catalog.refresh()
    return {"code": code}
