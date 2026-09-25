"""The catalogue as an Excel file plus its photos, zipped — export, and import back (ADR-0005).

This is the shop's own copy of its product data: one row per code with its name, photos,
categories, pack size, size and price. It can be exported from any machine, corrected in Excel,
and imported into this machine or another one. It replaces the PDF catalogue as the way product
data gets in; the PDF extractor kept producing wrong codes, photos that did not match their
code, poor crops and one photo shared by several codes.

Package layout (`catalog-<date>.zip`):
    products.xlsx   sheet "สินค้า" (the data) and "วิธีกรอก" (how to fill it in)
    images/         every photo the sheet names, by file name

Import replaces the whole catalogue except MS Natural Design, whose rows came from the shop's
own stock export and stay exactly as they are. It is two steps: preview() unpacks the zip into
a staging folder, checks every row and reports what would change, and writes nothing else;
apply() backs up the current catalogue files and then writes. A preview with any row errors
cannot be applied — a rejected row of a product that exists today would otherwise silently
delete it.

No subprocess and nothing billed, so this works the same from an installed copy (unlike the
catalogue sync, issue #36). The photo-search index (descriptions/embeddings) is not rebuilt;
categories come from the sheet, so the picker does not depend on it.
"""

import hashlib
import io
import json
import re
import shutil
import time
import uuid
import zipfile
from datetime import datetime
from pathlib import Path, PurePosixPath

from backend import config, validation
from backend.services import catalog, shop_overlay, vendor_lookup, vendor_overlay
from backend.validation import ValidationError

KEPT_BOOK = "MS Natural Design"
SHEET = "สินค้า"
HELP_SHEET = "วิธีกรอก"
XLSX_NAME = "products.xlsx"

# (header, key) in sheet order. `longest_mm` and `thumb` are export-only — read-only checks for a
# person, ignored on import.
COLUMNS = [
    ("รหัสสินค้า", "code"),
    ("ชื่อ", "name"),
    ("รูป", "images"),
    ("ชื่อสี", "colour_names"),
    ("หมวดหมู่หลัก", "category"),
    ("หมวดหมู่รอง", "section"),
    ("จำนวน", "pack_size"),
    ("ขนาด", "size_raw"),
    ("ขนาดด้านยาวสุด (มม.)", "longest_mm"),
    ("ราคา", "price"),
    ("ร้าน", "book"),
    ("รูปย่อ", "thumb"),
]
HEADER_TO_KEY = {header: key for header, key in COLUMNS}
REQUIRED_HEADERS = ("รหัสสินค้า", "รูป")

# Where imported photos go, under catalog/images/ and catalog/images/variants/. File names carry
# a hash of the bytes, so a re-import never overwrites a file an older cut-out was made from.
IMPORTED_DIR = "xlsx"

# Overlay opinions the sheet now owns for every code it imports: the sheet is the truth for
# those, so an older opinion must not keep overriding it.
SHEET_OWNED_OVERLAY_FIELDS = tuple(
    sorted(catalog.EDITABLE_DISPLAY_FIELDS | {"size", "shop_photo", "colours", "colour_names",
                                              "supporting_photos"})
)

MAX_ZIP_BYTES = 2 * 1024 ** 3  # uncompressed total; the whole current catalogue is ~150 MB
THUMB_PX = 48


def _paths():
    """Read from config at call time — the tests repoint CATALOG_PATH and DATA_DIR."""
    folder = config.CATALOG_PATH.parent
    return {
        "products": config.CATALOG_PATH,
        "images_index": folder / "product_images.json",
        "images": folder / "images",
        "conflicts": folder / "book_conflicts.json",
        "staging": config.DATA_DIR / "import-staging",
        "exports": config.DATA_DIR / "exports",
        "backups": config.DATA_DIR / "backups",
    }


def _load(path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else default


def _safe(code):
    return re.sub(r"[^A-Za-z0-9._-]", "_", code)


def _price_used(row):
    """The price a quote uses: the supplier's when it has one, else the catalogue's — the same
    precedence as main._priced_extra()."""
    vendor = vendor_lookup.price_for(row["code"])
    return vendor if vendor is not None else row.get("price")


def _photos_of(code):
    """The photo strings for a code, in sheet order: its colours when it has them (the full
    colour-range frame is not a pickable photo, so it is not exported), else its one photo."""
    colours = shop_overlay.fields_for(code).get("colours")
    if colours:
        return catalog.variants_of(code)
    image = catalog.image_for(code)
    return [image] if image else []


# ---------------------------------------------------------------------------- export


def _thumbnail(path):
    from PIL import Image as PILImage

    with PILImage.open(path) as img:
        img = img.convert("RGBA")
        img.thumbnail((THUMB_PX, THUMB_PX))
        canvas = PILImage.new("RGB", img.size, (255, 255, 255))
        canvas.paste(img, mask=img.split()[-1])
        out = io.BytesIO()
        canvas.save(out, format="PNG")
        out.seek(0)
        return out


def _write_help(wb):
    ws = wb.create_sheet(HELP_SHEET)
    ws.append(["คอลัมน์", "วิธีกรอก"])
    for row in (
        ("รหัสสินค้า", "ห้ามว่าง ห้ามซ้ำ — รหัสของร้าน"),
        ("ชื่อ", "ชื่อสินค้า (ไม่บังคับ)"),
        ("รูป", "ชื่อไฟล์ในโฟลเดอร์ images/ ของไฟล์ zip นี้ · หลายสีคั่นด้วย ; (ไฟล์แรกคือรูปหลัก)"),
        ("ชื่อสี", "ชื่อของแต่ละสี เรียงตามรูป คั่นด้วย ; (ไม่บังคับ)"),
        ("หมวดหมู่หลัก", "เลือกจากรายการด้านล่าง · เว้นว่างได้ ระบบจะเดาจากหมวดหมู่รอง"),
        ("หมวดหมู่รอง", "ข้อความอิสระ เช่น ชื่อกลุ่มสินค้า"),
        ("จำนวน", "ชิ้นต่อแพ็ก · เว้นว่างหรือ 1 = ขายเป็นชิ้น"),
        ("ขนาด", "เช่น 80 mm · 12 cm · 8 นิ้ว · 5 ฟุต · 1.5 m · 40x60 cm · H 215 x D 142 cm"),
        ("ขนาดด้านยาวสุด (มม.)", "ระบบคำนวณให้ดู ไม่ต้องกรอก (ไม่ถูกนำเข้า)"),
        ("ราคา", "ราคาที่ใช้เสนอลูกค้า (บาท) · เว้นว่าง = ใช้ราคาซัพพลายเออร์ถ้ามี"),
        ("ร้าน", "เช่น Bangkok Christmas · แถวของ MS Natural Design จะไม่ถูกนำเข้า"),
        ("รูปย่อ", "ให้ดูเฉยๆ ไม่ถูกนำเข้า"),
    ):
        ws.append(list(row))
    ws.append([])
    ws.append(["หมวดหมู่หลักที่ใช้ได้", "(พิมพ์ชื่อไทยหรือคีย์ภาษาอังกฤษก็ได้)"])
    for key, label, _needles in catalog.CATEGORIES:
        ws.append([label, key])
    ws.column_dimensions["A"].width = 26
    ws.column_dimensions["B"].width = 80


def export_zip():
    """Build the package for the whole catalogue (every book) and return its path. Written to
    data/exports/ rather than memory: with its photos it is well over a hundred megabytes."""
    from openpyxl import Workbook
    from openpyxl.drawing.image import Image as XLImage
    from openpyxl.styles import Alignment, Font

    paths = _paths()
    paths["exports"].mkdir(parents=True, exist_ok=True)
    for old in paths["exports"].glob("catalog-*.zip"):  # one export at a time is plenty
        old.unlink(missing_ok=True)
    out_path = paths["exports"] / f"catalog-{datetime.now():%Y%m%d-%H%M%S}.zip"

    wb = Workbook()
    ws = wb.active
    ws.title = SHEET
    ws.append([header for header, _key in COLUMNS])
    for cell in ws[1]:
        cell.font = Font(bold=True)
    thumb_col = len(COLUMNS)

    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for index, row in enumerate(catalog.all_products(), start=2):
            code = row["code"]
            names, colour_names, first_path = [], [], None
            for n, image in enumerate(_photos_of(code), start=1):
                path = catalog.resolve_image_path(image)
                if not path or not path.is_file():
                    continue
                name = f"{_safe(code)}{'' if n == 1 else f'__c{n}'}{path.suffix.lower()}"
                zf.write(path, f"images/{name}", compress_type=zipfile.ZIP_STORED)  # PNG/JPEG are already compressed
                names.append(name)
                colour_names.append(catalog.colour_name(code, image) or "")
                first_path = first_path or path
            category = catalog.category_of(row)
            longest = catalog.longest_side_mm(row)
            values = {
                "code": code,
                "name": row.get("name") or vendor_lookup.name_for(code) or "",
                "images": "; ".join(names),
                "colour_names": "; ".join(colour_names) if len(names) > 1 and any(colour_names) else "",
                "category": catalog.label_for(category) if category else "",
                "section": row.get("section") or "",
                "pack_size": row.get("pack_size") or None,
                "size_raw": row.get("size_raw") or "",
                "longest_mm": round(longest) if longest else None,
                "price": _price_used(row),
                "book": row.get("book") or "",
            }
            ws.append([values.get(key) for _header, key in COLUMNS[:-1]])
            ws.cell(row=index, column=1).number_format = "@"  # a code is text, never a number
            if first_path:
                try:
                    image = XLImage(_thumbnail(first_path))
                    ws.add_image(image, ws.cell(row=index, column=thumb_col).coordinate)
                    ws.row_dimensions[index].height = THUMB_PX * 0.8
                except Exception:  # a thumbnail is a convenience; the file name is the data
                    pass

        for column, width in zip("ABCDEFGHIJKL", (14, 30, 28, 18, 24, 34, 8, 18, 10, 10, 18, 9)):
            ws.column_dimensions[column].width = width
        for cells in ws.iter_rows(min_row=2):
            for cell in cells:
                cell.alignment = Alignment(vertical="center")
        ws.freeze_panes = "B2"
        _write_help(wb)

        buffer = io.BytesIO()
        wb.save(buffer)
        zf.writestr(XLSX_NAME, buffer.getvalue())
    return out_path


# ---------------------------------------------------------------------------- import: read


def _text(value):
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value).strip()


def _extract(zip_file, target):
    """Unpack into `target`, refusing anything that would land outside it or blow up."""
    with zipfile.ZipFile(zip_file) as zf:
        members = zf.infolist()
        if sum(m.file_size for m in members) > MAX_ZIP_BYTES:
            raise ValidationError("ไฟล์ zip ใหญ่เกินไป")
        root = target.resolve()
        for member in members:
            name = member.filename.replace("\\", "/")
            if name.endswith("/"):
                continue
            parts = PurePosixPath(name).parts
            if name.startswith("/") or ".." in parts or (parts and ":" in parts[0]):
                raise ValidationError(f"ไฟล์ zip มี path ที่ไม่ปลอดภัย: {member.filename}")
            dest = (target / Path(*parts)).resolve()
            if root not in dest.parents:
                raise ValidationError(f"ไฟล์ zip มี path ที่ไม่ปลอดภัย: {member.filename}")
            dest.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member) as src, open(dest, "wb") as out:
                shutil.copyfileobj(src, out)


def _find_xlsx(folder):
    preferred = folder / XLSX_NAME
    if preferred.is_file():
        return preferred
    found = [p for p in folder.glob("*.xlsx") if not p.name.startswith("~$")]
    if len(found) != 1:
        raise ValidationError(f"ใน zip ต้องมีไฟล์ Excel ({XLSX_NAME}) หนึ่งไฟล์ที่ชั้นนอกสุด")
    return found[0]


def _image_index(folder):
    """Every file under images/ by its name, case-insensitively — the sheet names a photo by
    its file name only."""
    images = folder / "images"
    if not images.is_dir():
        return {}
    return {p.name.lower(): p for p in images.rglob("*") if p.is_file()}


def _read_sheet(xlsx_path):
    from openpyxl import load_workbook

    wb = load_workbook(xlsx_path, read_only=True, data_only=True)
    ws = wb[SHEET] if SHEET in wb.sheetnames else wb.worksheets[0]
    rows = ws.iter_rows(values_only=True)
    header = [(_text(h)) for h in next(rows, [])]
    missing = [h for h in REQUIRED_HEADERS if h not in header]
    if missing:
        raise ValidationError(f"ไม่พบคอลัมน์ {', '.join(missing)} ในแถวแรกของ Excel")
    keys = [HEADER_TO_KEY.get(h) for h in header]
    out = []
    for number, values in enumerate(rows, start=2):
        record = {key: value for key, value in zip(keys, values) if key}
        if any(_text(v) for k, v in record.items() if k not in ("thumb", "longest_mm")):
            out.append((number, record))
    wb.close()
    return out


def _parse_row(record, images, errors, warnings, number):
    code = _text(record.get("code")).upper()
    where = f"แถว {number}" + (f" ({code})" if code else "")
    if not code:
        errors.append(f"{where}: ไม่มีรหัสสินค้า")
        return None

    files = [f.strip() for f in _text(record.get("images")).split(";") if f.strip()]
    photos = []
    for name in files:
        path = images.get(PurePosixPath(name.replace("\\", "/")).name.lower())
        if path is None:
            errors.append(f"{where}: ไม่พบไฟล์รูป '{name}' ในโฟลเดอร์ images/")
            continue
        try:
            validation.check_image(path.read_bytes(), path.name, None, "รูป")
        except ValidationError as exc:
            errors.append(f"{where}: {exc}")
            continue
        photos.append(str(path))
    if not files:
        warnings.append(f"{where}: ไม่มีรูป — จะไม่แสดงใน catalogue picker")

    colour_names = [n.strip() for n in _text(record.get("colour_names")).split(";")]
    colour_names = colour_names[: len(photos)] if len(photos) > 1 else []

    try:
        category = catalog.category_key(_text(record.get("category")))
    except ValidationError as exc:
        errors.append(f"{where}: {exc}")
        category = None

    pack_text = _text(record.get("pack_size"))
    pack_size = None
    if pack_text:
        try:
            pack_size = int(float(pack_text))
            if pack_size != float(pack_text) or pack_size < 1:
                raise ValueError
            pack_size = pack_size if pack_size >= 2 else None
        except ValueError:
            errors.append(f"{where}: จำนวน '{pack_text}' ต้องเป็นจำนวนเต็มตั้งแต่ 1 ขึ้นไป")
            pack_size = None

    price_text = _text(record.get("price")).replace(",", "").replace("฿", "").strip()
    price = None
    if price_text:
        try:
            price = float(price_text)
            if price < 0:
                raise ValueError
        except ValueError:
            errors.append(f"{where}: ราคา '{price_text}' ต้องเป็นตัวเลขตั้งแต่ 0 ขึ้นไป")
            price = None

    size_raw = _text(record.get("size_raw"))
    size = catalog.parse_size(size_raw) if size_raw else None
    if size_raw and size is None:
        warnings.append(f"{where}: อ่านขนาด '{size_raw}' ไม่ออก — จะไม่มีขนาดใช้คำนวณ")
    elif not size_raw:
        warnings.append(f"{where}: ไม่มีขนาด")

    return {
        "code": code,
        "name": _text(record.get("name")) or None,
        "photos": photos,
        "colour_names": colour_names,
        "category": category,
        "section": _text(record.get("section")) or None,
        "pack_size": pack_size,
        "size_raw": size_raw or None,
        "size": size,
        "price": price,
        "book": _text(record.get("book")) or None,
    }


def _digest(path):
    return hashlib.sha1(Path(path).read_bytes()).hexdigest()


def _current_digests(code):
    out = []
    for image in _photos_of(code):
        path = catalog.resolve_image_path(image)
        if path and path.is_file():
            out.append(_digest(path))
    return out


def _changes(new, current):
    """Which sheet fields differ between an imported row and today's product record."""
    before = {
        "name": current.get("name") or vendor_lookup.name_for(current["code"]),
        "category": catalog.category_of(current),
        "section": current.get("section"),
        "pack_size": current.get("pack_size") or None,
        "size_raw": current.get("size_raw"),
        "price": _price_used(current),
        "book": current.get("book"),
    }
    changed = []
    for field, old in before.items():
        value = new[field]
        if field == "category" and value is None:
            continue  # blank means "derive it", which is what `old` already is
        if field == "price" and value is None:
            continue  # blank keeps the supplier's price, whatever that is
        if (value or None) != (old or None) and not (
            isinstance(value, float) and isinstance(old, (int, float)) and value == old
        ):
            changed.append(field)
    if [_digest(p) for p in new["photos"]] != _current_digests(current["code"]):
        changed.append("photos")
    return changed


def _clean_staging(staging):
    if not staging.is_dir():
        return
    for folder in staging.iterdir():
        if folder.is_dir() and time.time() - folder.stat().st_mtime > 24 * 3600:
            shutil.rmtree(folder, ignore_errors=True)


def preview(zip_file):
    """Unpack and check an uploaded package; write nothing outside the staging folder.

    Returns the token apply() needs, what would be added/removed/changed, and every row error
    and warning. `can_apply` is False while any row has an error."""
    paths = _paths()
    _clean_staging(paths["staging"])
    token = uuid.uuid4().hex
    folder = paths["staging"] / token
    folder.mkdir(parents=True)
    try:
        try:
            _extract(zip_file, folder)
        except zipfile.BadZipFile:
            raise ValidationError("ไฟล์นี้ไม่ใช่ zip")
        records = _read_sheet(_find_xlsx(folder))
        images = _image_index(folder)

        current = {row["code"]: row for row in catalog.all_products()}
        kept_codes = {code for code, row in current.items() if row.get("book") == KEPT_BOOK}

        errors, warnings, parsed, skipped = [], [], [], 0
        seen = {}
        for number, record in records:
            if _text(record.get("book")) == KEPT_BOOK:
                skipped += 1
                continue
            row = _parse_row(record, images, errors, warnings, number)
            if row is None:
                continue
            if row["code"] in seen:
                errors.append(f"แถว {number} ({row['code']}): รหัสซ้ำกับแถว {seen[row['code']]}")
                continue
            if row["code"] in kept_codes:
                errors.append(f"แถว {number} ({row['code']}): รหัสนี้เป็นของ {KEPT_BOOK} ซึ่งไม่ถูกแทนที่")
                continue
            seen[row["code"]] = number
            parsed.append(row)

        if not parsed and not errors:
            errors.append("ไม่มีแถวสินค้าให้นำเข้า")

        replaced = {code for code in current if code not in kept_codes}
        imported = {row["code"] for row in parsed}
        changed = []
        for row in parsed:
            if row["code"] in current and row["code"] in replaced:
                fields = _changes(row, current[row["code"]])
                if fields:
                    changed.append({"code": row["code"], "fields": fields})

        plan = {"rows": parsed, "created": time.time()}
        (folder / "plan.json").write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
    except Exception:
        shutil.rmtree(folder, ignore_errors=True)
        raise

    return {
        "token": token,
        "rows": len(parsed),
        "added": sorted(imported - replaced),
        "removed": sorted(replaced - imported),
        "changed": changed,
        "unchanged": len(imported & replaced) - len(changed),
        "skipped_kept_book": skipped,
        "kept_book": KEPT_BOOK,
        "kept": len(kept_codes),
        "errors": errors,
        "warnings": warnings,
        "can_apply": not errors,
    }


# ---------------------------------------------------------------------------- import: write


def _backup(paths):
    paths["backups"].mkdir(parents=True, exist_ok=True)
    target = paths["backups"] / f"catalog-{datetime.now():%Y%m%d-%H%M%S}.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
        for label, path in (
            ("catalog/products.json", paths["products"]),
            ("catalog/product_images.json", paths["images_index"]),
            ("catalog/book_conflicts.json", paths["conflicts"]),
            ("data/shop_overlay.json", shop_overlay.overlay_path()),
            ("data/vendor_overlay.json", vendor_overlay.overlay_path()),
        ):
            if path.is_file():
                zf.write(path, label)
    return target


def _place_photo(source, subdir, code):
    """Copy one imported photo in under a content-hashed name; return its catalogue string."""
    source = Path(source)
    data = source.read_bytes()
    name = f"{_safe(code)}-{hashlib.sha1(data).hexdigest()[:10]}{source.suffix.lower()}"
    dest = subdir / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.is_file():
        dest.write_bytes(data)
    return f"{IMPORTED_DIR}/{name}"


def apply(token):
    """Replace every product except MS Natural Design with the previewed package.

    Backs up the catalogue and both overlays to data/backups/ first. Photos are added under new
    names and nothing on disk is deleted, so restoring the backup brings the old catalogue
    back complete. Codes that disappear keep their overlay and show as orphan products
    (ADR-0001)."""
    if not re.fullmatch(r"[0-9a-f]{32}", token or ""):
        raise ValidationError("ไม่รู้จักการนำเข้านี้")
    paths = _paths()
    folder = paths["staging"] / token
    plan_path = folder / "plan.json"
    if not plan_path.is_file():
        raise ValidationError("ไม่พบข้อมูลที่ตรวจไว้ — อัปโหลดไฟล์ใหม่อีกครั้ง")
    rows = json.loads(plan_path.read_text(encoding="utf-8"))["rows"]

    backup = _backup(paths)

    base = _load(paths["products"], [])
    kept_rows = [row for row in base if row.get("book") == KEPT_BOOK]
    kept_codes = {row["code"] for row in kept_rows}

    main_dir = paths["images"] / IMPORTED_DIR
    colour_dir = paths["images"] / "variants" / IMPORTED_DIR
    new_rows, image_rows, overlay_changes, vendor_changes = [], [], {}, {}
    vendor_existing = vendor_overlay.all_fields()
    shop_existing = shop_overlay.all_fields()
    for row in rows:
        code = row["code"]
        record = {"code": code}
        for field in ("name", "size_raw", "size", "section", "category", "pack_size", "book"):
            record[field] = row.get(field)
        record.update({"page_headings": [], "pdf_page": None, "bbox": None, "duplicate": False})
        new_rows.append(record)

        photos = row["photos"]
        main = _place_photo(photos[0], main_dir, code) if photos else None
        image_rows.append({
            "code": code, "pdf_page": None, "image": main, "rule": None, "gap_pt": None,
            "match": catalog.IMPORTED_MATCH, "book": row.get("book"), "shared_with": 0,
        })

        fields = {}
        if len(photos) > 1:
            colours = [_place_photo(p, colour_dir, code) for p in photos]
            fields["colours"] = colours
            names = {c: n for c, n in zip(colours, row["colour_names"]) if n}
            if names:
                fields["colour_names"] = names
        if fields or code in shop_existing:
            overlay_changes[code] = fields

        price = row.get("price")
        if price is not None and price == vendor_lookup.base_field(code, "price"):
            price = None  # the supplier already says exactly this
        if price is not None:
            vendor_changes[code] = {"price": price}
        elif "price" in vendor_existing.get(code, {}):
            vendor_changes[code] = {}

    paths["products"].write_text(
        json.dumps(new_rows + kept_rows, indent=1, ensure_ascii=False), encoding="utf-8"
    )
    kept_images = [r for r in _load(paths["images_index"], []) if r.get("code") in kept_codes]
    paths["images_index"].write_text(
        json.dumps(image_rows + kept_images, indent=1, ensure_ascii=False), encoding="utf-8"
    )
    if overlay_changes:
        shop_overlay.set_many(overlay_changes, speaks_for=SHEET_OWNED_OVERLAY_FIELDS)
    if vendor_changes:
        vendor_overlay.set_many(vendor_changes, speaks_for=("price",))

    catalog.refresh()
    vendor_lookup.refresh()
    from backend.services import matching

    matching.refresh()  # which photos are showable changed
    shutil.rmtree(folder, ignore_errors=True)

    removed = {row["code"] for row in base if row.get("book") != KEPT_BOOK} - {r["code"] for r in rows}
    return {
        "imported": len(rows),
        "removed": len(removed),
        "kept": len(kept_rows),
        "backup": backup.name,
    }
