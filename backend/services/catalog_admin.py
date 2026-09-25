"""Add one catalogue product by hand, from the settings page.

Product.md 8.1 built the 1,095-row catalogue from a PDF; this is the manual door for the
odd item that never came from one — a single new product, or an item from a book too small
to justify running the whole extract/build-index pipeline over.

Same rule as the PDF pipeline: never overwrite. A code that already exists is a collision,
not an update — NonGoals.md 7/8 forbid guessing which product a reused code now means, and
silently replacing a row is exactly that guess.
"""

import json
import shutil
import uuid

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
EDITABLE_FIELDS_NO_PRICE = tuple(f for f in EDITABLE_FIELDS if f != "price")


def set_pack_size(code, pack_size):
    """How many pieces come in one pack of this product (issue #25), or None for one sold by
    the piece.

    A shop fact, never a book one — the books print a pack count in the size line when they
    print it at all — so it lives in the overlay and survives a re-import like a price does.
    Two is the smallest meaningful pack: a "pack of one" is a piece, and recording it would put
    "1 pack (of 1)" on every line for nothing.
    """
    code = (code or "").strip().upper()
    catalog.find(code)  # raises ValidationError on an unknown code
    if pack_size is not None:
        try:
            pack_size = int(pack_size)
        except (TypeError, ValueError):
            raise ValidationError(f"จำนวนต่อแพ็ค '{pack_size}' ไม่ใช่จำนวนเต็ม")
        if pack_size < 2:
            raise ValidationError("จำนวนต่อแพ็คต้องเป็น 2 ชิ้นขึ้นไป — แพ็คละ 1 คือขายเป็นชิ้น")
    shop_overlay.set_fields(
        code, {"pack_size": pack_size} if pack_size else {}, speaks_for=("pack_size",)
    )
    catalog.refresh()
    return {"code": code, "pack_size": pack_size}


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
    }
    # `price=None` means "this edit says nothing about price" — the settings form no longer
    # sends one, because prices are managed on the supplier-price page (vendor_admin). A price
    # already in the overlay stays exactly as it was: still the fallback when the supplier has
    # none, just not editable from the catalogue screen. Any string (even "") is an opinion.
    speaks_for = EDITABLE_FIELDS_NO_PRICE
    if price is not None:
        typed["price"] = _parse_price(price)
        speaks_for = EDITABLE_FIELDS
    opinions = {
        name: value for name, value in typed.items() if value != base.get(name)
    }
    shop_overlay.set_fields(code, opinions, speaks_for=speaks_for)
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


def _shop_photo_filename(fmt):
    ext = config.FORMAT_EXT.get(fmt, "png")
    return f"/shop-photos/{uuid.uuid4().hex}.{ext}"


def _delete_shop_photo(image):
    if image.startswith("/shop-photos/"):
        (config.SHOP_PHOTOS_DIR / image.removeprefix("/shop-photos/")).unlink(missing_ok=True)


def add_supporting_photo(code, main_image, image_bytes, fmt="PNG"):
    """Add another photo for a colour that already has a main one (issue #17) — the back, a
    detail shot, one that shows scale. Never becomes what the generator sees: catalog.
    variants_of() (what /api/element/from-catalog validates a pick against) is built from
    `colours` alone, and this only ever touches `supporting_photos`.

    Stored under data/shop_photos/ like a shop photo (issue #12), for the same reason — a
    re-import or reinstall must never be able to lose it.
    """
    code = (code or "").strip().upper()
    catalog.find(code)  # raises ValidationError on an unknown code
    main_key = main_image.removeprefix("variants/")
    colours = shop_overlay.fields_for(code).get("colours") or []
    if main_key not in colours:
        raise ValidationError(f"'{main_image}' ไม่ใช่รูปหลักของสีไหนใน {code}")

    filename = _shop_photo_filename(fmt)
    config.SHOP_PHOTOS_DIR.mkdir(parents=True, exist_ok=True)
    (config.SHOP_PHOTOS_DIR / filename.removeprefix("/shop-photos/")).write_bytes(image_bytes)

    supporting = {
        key: list(files)
        for key, files in (shop_overlay.fields_for(code).get("supporting_photos") or {}).items()
    }
    supporting.setdefault(main_key, []).append(filename)
    shop_overlay.set_fields(code, {"supporting_photos": supporting}, speaks_for=("supporting_photos",))
    catalog.refresh()
    return {"code": code, "image": filename}


def _promote(colours, names, old_main, new_main):
    """Swaps new_main into old_main's slot in `colours`, carrying the Thai name across — a
    name belongs to whichever photo is currently main, not to a specific file. The shared
    core of remove_photo's forced promotion and set_main_photo's deliberate one; both mutate
    and return the same two structures they were given."""
    colours[colours.index(old_main)] = new_main
    if old_main in names:
        names[new_main] = names.pop(old_main)
    return colours, names


def set_main_photo(code, image):
    """Choose which of a colour's photos is main, without removing anything (issue #17, AC
    "chosen by the shop") — the old main becomes a supporting photo of the same colour rather
    than disappearing. A no-op if `image` is already the main."""
    code = (code or "").strip().upper()
    catalog.find(code)
    key = image.removeprefix("variants/")
    colours = list(shop_overlay.fields_for(code).get("colours") or [])
    if key in colours:
        return {"code": code}

    supporting = {
        k: list(v)
        for k, v in (shop_overlay.fields_for(code).get("supporting_photos") or {}).items()
    }
    owner = next((main for main, files in supporting.items() if key in files), None)
    if owner is None:
        raise ValidationError(f"'{image}' ไม่ใช่รูปของ {code}")

    remaining = [f for f in supporting.pop(owner) if f != key]
    remaining.append(owner)  # the demoted main stays with its colour, as a supporting photo
    names = dict(shop_overlay.fields_for(code).get("colour_names", {}))
    colours, names = _promote(colours, names, owner, key)
    supporting[key] = remaining

    shop_overlay.set_fields(
        code, {"colours": colours, "supporting_photos": supporting, "colour_names": names},
        speaks_for=("colours", "supporting_photos", "colour_names"),
    )
    catalog.refresh()
    return {"code": code}


def remove_photo(code, image):
    """Remove one photo of a colour, main or supporting (issue #17).

    Removing the main promotes that colour's first supporting photo to take its place (see
    _promote). Refuses to remove a colour's only photo rather than leaving it with none; add
    another first if that colour genuinely needs replacing.
    """
    code = (code or "").strip().upper()
    catalog.find(code)
    key = image.removeprefix("variants/")
    colours = list(shop_overlay.fields_for(code).get("colours") or [])
    supporting = {
        k: list(v)
        for k, v in (shop_overlay.fields_for(code).get("supporting_photos") or {}).items()
    }
    names = dict(shop_overlay.fields_for(code).get("colour_names", {}))

    if key in colours:
        siblings = supporting.pop(key, [])
        if not siblings:
            raise ValidationError(
                f"'{image}' เป็นรูปเดียวที่เหลือของสีนี้ใน {code} — เพิ่มรูปอื่นก่อนถึงจะลบรูปนี้ได้"
            )
        new_main, *rest = siblings
        colours, names = _promote(colours, names, key, new_main)
        if rest:
            supporting[new_main] = rest
        shop_overlay.set_fields(
            code, {"colours": colours, "supporting_photos": supporting, "colour_names": names},
            speaks_for=("colours", "supporting_photos", "colour_names"),
        )
    else:
        owner = next((main for main, files in supporting.items() if key in files), None)
        if owner is None:
            raise ValidationError(f"'{image}' ไม่ใช่รูปของ {code}")
        supporting[owner] = [f for f in supporting[owner] if f != key]
        if not supporting[owner]:
            del supporting[owner]
        shop_overlay.set_fields(code, {"supporting_photos": supporting}, speaks_for=("supporting_photos",))

    _delete_shop_photo(key)
    catalog.refresh()
    return {"code": code}


def _shop_photo_names(colours):
    return [c.removeprefix("/shop-photos/") for c in colours if c.startswith("/shop-photos/")]


def add_variant(code, image_bytes, name_th, fmt="PNG", first_name_th=None):
    """Add one more colour or pattern (ลาย) to a code (ADR-0002: still one code, a named photo).

    The first split of an unsplit code keeps today's photo as variant 1 — copied into
    data/shop_photos/ so a re-import can never orphan it — and `first_name_th` names it. The
    code's first shop-owned photo is also recorded as its `shop_photo`, which is what tells
    catalog.crop_is_showable that a person chose these pictures.
    """
    code = (code or "").strip().upper()
    catalog.find(code)
    name_th = (name_th or "").strip()
    if not name_th:
        raise ValidationError("ใส่ชื่อสี/ลายด้วย")
    fields = shop_overlay.fields_for(code)
    colours = list(fields.get("colours") or [])
    names = dict(fields.get("colour_names") or {})
    config.SHOP_PHOTOS_DIR.mkdir(parents=True, exist_ok=True)

    if not colours:
        current = catalog.image_for(code)
        if current:
            if current.startswith("/shop-photos/"):
                seed = current
            else:
                source = catalog.resolve_image_path(current)
                seed = f"/shop-photos/{uuid.uuid4().hex}{source.suffix}"
                shutil.copyfile(source, config.SHOP_PHOTOS_DIR / seed.removeprefix("/shop-photos/"))
            colours.append(seed)
            if (first_name_th or "").strip():
                names[seed] = first_name_th.strip()

    new = _shop_photo_filename(fmt)
    (config.SHOP_PHOTOS_DIR / new.removeprefix("/shop-photos/")).write_bytes(image_bytes)
    colours.append(new)
    names[new] = name_th

    main_before = _main_photo_bytes(code)
    changes = {"colours": colours, "colour_names": names}
    speaks_for = ["colours", "colour_names"]
    if not fields.get("shop_photo"):
        # marked, so clearing the split later knows this photo is ours to take back
        changes["shop_photo"] = _shop_photo_names(colours)[0]
        changes["shop_photo_from_split"] = True
        speaks_for += ["shop_photo", "shop_photo_from_split"]
    if fields.get("supporting_photos"):
        changes["supporting_photos"] = fields["supporting_photos"]
        speaks_for.append("supporting_photos")
    shop_overlay.set_fields(code, changes, speaks_for=tuple(speaks_for))
    catalog.refresh()
    _reindex_if_main_changed(code, main_before)
    return {"code": code, "image": new}


def _main_photo_bytes(code):
    photos = catalog.variants_of(code)
    path = catalog.resolve_image_path(photos[0]) if photos else None
    return path.read_bytes() if path and path.is_file() else None


def _reindex_if_main_changed(code, before):
    """Photo search describes a code by its main picture; rebuild it only when that picture's
    content really changed — a split's seeded copy is the same picture, not a billed call."""
    after = _main_photo_bytes(code)
    if after and after != before:
        _reindex_one(code, after, "JPEG" if after[:3] == b"\xff\xd8\xff" else "PNG")


def clear_variants(code):
    """Back to one plain code: drop every colour/pattern, name and supporting photo, and the
    shop photos they used. A `shop_photo` the shop set itself stays; one add_variant set
    (`shop_photo_from_split`) goes too, so the code shows exactly what it showed before."""
    code = (code or "").strip().upper()
    catalog.find(code)
    fields = shop_overlay.fields_for(code)
    if not fields.get("colours"):
        return {"code": code}
    main_before = _main_photo_bytes(code)
    keep = None if fields.get("shop_photo_from_split") else fields.get("shop_photo")
    files = [c for c in fields["colours"] if c.startswith("/shop-photos/")]
    for group in (fields.get("supporting_photos") or {}).values():
        files += group
    if fields.get("shop_photo"):
        files.append(f"/shop-photos/{fields['shop_photo']}")
    for file in set(files):
        if file.removeprefix("/shop-photos/") != keep:
            _delete_shop_photo(file)
    shop_overlay.set_fields(
        code, {"shop_photo": keep} if keep else {},
        speaks_for=("colours", "colour_names", "supporting_photos", "shop_photo", "shop_photo_from_split"),
    )
    catalog.refresh()
    _reindex_if_main_changed(code, main_before)
    return {"code": code}


def remove_variant(code, image):
    """Remove a whole colour/pattern: its main photo, supporting photos and name. At least one
    must remain. Book photos are never deleted from disk, only shop-owned ones."""
    code = (code or "").strip().upper()
    catalog.find(code)
    key = image.removeprefix("variants/")
    fields = shop_overlay.fields_for(code)
    colours = list(fields.get("colours") or [])
    if key not in colours:
        raise ValidationError(f"'{image}' ไม่ใช่สี/ลายของ {code}")
    if len(colours) == 1:
        raise ValidationError(f"'{image}' เป็นสี/ลายเดียวที่เหลือของ {code} — ลบไม่ได้")

    main_before = _main_photo_bytes(code)
    colours.remove(key)
    names = {k: v for k, v in (fields.get("colour_names") or {}).items() if k != key}
    supporting = dict(fields.get("supporting_photos") or {})
    for file in supporting.pop(key, []):
        _delete_shop_photo(file)
    _delete_shop_photo(key)

    changes = {"colours": colours, "colour_names": names}
    speaks_for = ["colours", "colour_names", "supporting_photos"]
    if supporting:
        changes["supporting_photos"] = supporting
    shop_photo = fields.get("shop_photo")
    if shop_photo:
        speaks_for += ["shop_photo", "shop_photo_from_split"]
        if f"/shop-photos/{shop_photo}" != key:
            changes["shop_photo"] = shop_photo
        elif _shop_photo_names(colours):
            changes["shop_photo"] = _shop_photo_names(colours)[0]
        if "shop_photo" in changes and fields.get("shop_photo_from_split"):
            changes["shop_photo_from_split"] = True
    shop_overlay.set_fields(code, changes, speaks_for=tuple(speaks_for))
    catalog.refresh()
    _reindex_if_main_changed(code, main_before)
    return {"code": code}
