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


def update_product(code, size_raw, section, book, price=None):
    """Edit an existing product's fields.

    The fields go to the shop overlay, never into the base — the base is book data, and a
    correction written into it is destroyed by the next re-import (ADR-0001). Only the fields
    that actually differ from what the book says are recorded: submitting the form unchanged
    must not quietly claim an opinion on all five, or a re-import would stop correcting this
    product at all. `size` travels with `size_raw` because it is derived from it — leaving the
    book's parsed size beside a shop-typed size string is the one pairing a per-field merge
    cannot work out for itself.

    Never renames or deletes a code — the row is found by its existing code, which does not
    change; that keeps this out of the image/variant-file migration a rename would need.

    The photo is a separate concern now (set_shop_photo, issue #12): a photo replaces the
    book's crop through the shop overlay, not by overwriting the file this function edits.
    """
    code = (code or "").strip().upper()
    base = next((r for r in _load(PRODUCTS_PATH, []) if r["code"] == code), None)
    if base is None:
        raise ValidationError(f"ไม่พบรหัส '{code}' ใน catalogue")

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
    catalog.refresh()
    return {"code": code, **_saved_state(code)}


def set_shop_photo(code, image_bytes, fmt="PNG"):
    """Upload a shop photo for one product (issue #12): it becomes the picture shown
    everywhere that product appears (catalog.image_for prefers it over the book crop), and it
    un-hides a product that was hidden for a bad book crop (catalog.crop_is_showable trusts a
    shop photo outright — the shop took it of the real thing). It also re-runs the product's
    search description and embedding, so "find product from a photo" keeps working against
    the new picture instead of the discarded one, without the shop pressing sync.

    `fmt` is validation.check_image()'s sniffed format ("PNG" or "JPEG"), not whatever the
    upload's filename claimed — a phone photo is JPEG far more often than not, and saving it
    under the wrong extension is a smaller problem than describing it to the vision model as
    the wrong MIME type, which is a request the model is free to simply fail on.

    The book photo is never touched or deleted — remove_shop_photo falls back to it. Refuses
    a colour-split code for the same reason update_product's old photo path did:
    catalog.variants_of() always shows the split list over a single photo, so a lone shop
    photo here would never be seen.
    """
    code = (code or "").strip().upper()
    catalog.find(code)  # raises ValidationError on an unknown code
    if len(catalog.variants_of(code)) > 1:
        raise ValidationError(
            f"'{code}' ถูกแยกเป็นหลายสีไว้แล้ว (catalog/variants.json) — "
            "อัปโหลดรูปเดี่ยวแบบนี้จะไม่ถูกใช้ แก้ไฟล์ variants ตรง ๆ แทน"
        )

    ext = config.FORMAT_EXT.get(fmt, "png")
    filename = f"{code.replace('/', '_')}.{ext}"
    config.SHOP_PHOTOS_DIR.mkdir(parents=True, exist_ok=True)
    (config.SHOP_PHOTOS_DIR / filename).write_bytes(image_bytes)
    shop_overlay.set_fields(code, {"shop_photo": filename}, speaks_for=("shop_photo",))
    catalog.refresh()
    _reindex_one(code, image_bytes, fmt)
    return {"code": code, **_saved_state(code)}


def remove_shop_photo(code):
    """Fall back to the book photo (issue #12). The book crop was never touched by uploading
    a shop photo, so there is nothing to restore on disk — only the overlay's pointer to the
    shop's file, and the file itself, go away."""
    code = (code or "").strip().upper()
    catalog.find(code)
    filename = shop_overlay.fields_for(code).get("shop_photo")
    shop_overlay.set_fields(code, {}, speaks_for=("shop_photo",))
    if filename:
        (config.SHOP_PHOTOS_DIR / filename).unlink(missing_ok=True)
    catalog.refresh()
    return {"code": code}


def _reindex_one(code, image_bytes, fmt="PNG"):
    """Re-describe and re-embed one code from its new shop photo (issue #12) — at the
    per-code vision seam tests fake instead of paying for, rather than the whole-catalogue
    scripts/describe_catalog.py + embed_catalog.py pass the settings-page "sync" button runs.

    A failure is recorded the same way describe_catalog.py records one, rather than raised:
    the photo is already saved and shown by the time this runs, and a flaky vision call must
    not undo that. NonGoals.md 8's "never invent" applies here too — nothing here retries an
    unclear photo with a guess.
    """
    from backend.services import matching, vision

    mime = config.FORMAT_MIME.get(fmt, "image/png")
    path = config.CATALOG_PATH.parent / "descriptions.json"
    descriptions = _load(path, {})
    try:
        parsed, usage = vision.describe_catalogue_photo(image_bytes, mime=mime)
        decoration = parsed.decorations[0] if parsed.decorations else None
        if decoration is None:
            raise ValueError("the model described nothing in the photo")
        text = vision.as_text(decoration)
        descriptions[code] = {
            "code": code, "pdf_page": None, "image": None, "match": "shop_photo",
            "attributes": decoration.model_dump(), "text": text, "tokens": usage["total_tokens"],
        }
        matching.upsert_embedding(code, text)
    except Exception as exc:
        descriptions[code] = {"code": code, "image": None, "error": f"{type(exc).__name__}: {exc}"}
    path.write_text(json.dumps(descriptions, indent=1, ensure_ascii=False), encoding="utf-8")


def queue_set_price(code, price):
    """The pricing queue's one field (issue #10) — sets just the price, nothing else.

    Unlike update_product this never diffs against the book: everything reaching the queue
    already has no book price (pricing_queue() only lists those), so any typed number is by
    definition the shop's own opinion. A blank clears that opinion and puts the product back
    in the queue, same "absent means no opinion" rule as everywhere else in the overlay.
    """
    code = (code or "").strip().upper()
    catalog.find(code)  # raises ValidationError on an unknown code
    parsed = _parse_price(price)
    shop_overlay.set_fields(code, {"price": parsed} if parsed is not None else {}, speaks_for=("price",))
    catalog.refresh()
    return {"code": code, "price": parsed}


# A field the find-and-correct screen (issue #11) can clear -> the overlay keys that opinion
# actually occupies. Derived from catalog.EDITABLE_DISPLAY_FIELDS rather than its own separate
# list of names, so the two never drift apart. size_raw is the one exception: it is cleared
# together with size, since they are one shop-typed opinion (a raw string and what parse_size
# made of it), never two independent ones.
CLEARABLE_FIELDS = {
    field: (field, "size") if field == "size_raw" else (field,)
    for field in catalog.EDITABLE_DISPLAY_FIELDS
}


def clear_override(code, field):
    """Drop the shop's opinion on one field, returning it to whatever the book says (issue
    #11, AC "clearing an override returns that field to the book's value"). Refuses a field
    that was never a shop opinion to begin with — the code, or anything not in
    CLEARABLE_FIELDS — the same way NEVER_OVERLAYABLE refuses writing to them.
    """
    code = (code or "").strip().upper()
    catalog.find(code)  # raises ValidationError on an unknown code
    keys = CLEARABLE_FIELDS.get(field)
    if keys is None:
        raise ValidationError(f"ล้างค่าฟิลด์ '{field}' ไม่ได้")
    shop_overlay.set_fields(code, {}, speaks_for=keys)
    catalog.refresh()
    return {"code": code, **_saved_state(code)}


def set_colour_name(code, image, name_th):
    """Seed or correct one colour photo's Thai name (issue #14, ADR-0002) — a colour is a
    named photo, not a code of its own, so the name lives per photo, not per product.

    Read-modify-write, not a plain overwrite: shop_overlay.set_fields replaces a field's whole
    value, and a code's `colour_names` holds every one of its photos' names in one dict, so
    correcting a single photo must not erase the others.

    Never gates on catalog.find(code) the way a pricing write does — a colour split, and now
    its names, are kept for an orphaned code exactly like every other overlay opinion (issue
    #9), so a code the current book has dropped can still be named ahead of a future re-import
    that brings it back. The membership check that matters is narrower and free: a photo must
    actually be one of this code's own `colours`, which also catches a code that was never
    split (or never existed) at all — a typo in the filename must not silently create a
    dangling name nothing ever shows.
    """
    code = (code or "").strip().upper()
    name_th = (name_th or "").strip()
    if not name_th:
        raise ValidationError("ใส่ชื่อสีด้วย")

    filename = image.removeprefix("variants/")
    colours = shop_overlay.fields_for(code).get("colours") or []
    if filename not in colours:
        raise ValidationError(f"'{image}' ไม่ใช่รูปสีของ {code}")

    names = dict(shop_overlay.fields_for(code).get("colour_names", {}))
    names[filename] = name_th
    shop_overlay.set_fields(code, {"colour_names": names}, speaks_for=("colour_names",))
    catalog.refresh()
    return {"code": code, "image": f"variants/{filename}", "name_th": name_th}


def skip_pricing(code):
    """Mark a product as one the shop will never price (issue #10) — it leaves the queue for
    good, but stays exactly as usable everywhere else: auto_pool never looks at price
    (ADR-0003), and nothing downstream requires one."""
    code = (code or "").strip().upper()
    catalog.find(code)
    shop_overlay.set_fields(code, {"price_skipped": True}, speaks_for=("price_skipped",))
    catalog.refresh()
    return {"code": code}
