"""Browse, check, fix and import suppliers' own price lists (vendor-pricelists/<slug>/), from
the settings page.

Parallel to catalog_admin.py, deliberately not merged into it: the vendor price list
(vendor_lookup.py) and the shop's own catalogue (catalog.py) are two different bases with two
different overlays (ADR-0001's pattern, applied twice — see vendor_overlay.py) and CLAUDE.md is
explicit that the two must never be mixed at the file level. This module only ever writes
`data/vendor_overlay.json` or files under vendor-pricelists/<slug>/ — never catalog/products.json
or data/shop_overlay.json.

More than one supplier can be configured (`config.VENDOR_SUPPLIERS`) — every function here that
used to assume one hardcoded supplier now looks it up per code (`_row()`'s "supplier") or loops
over every configured one (`_catalogued_codes_by_book()`, `issues()`), so adding a second
supplier is a config entry plus its own vendor-pricelists/<slug>/ folder, not a code change.
"""

import importlib.util
import json
import subprocess
import sys

from backend import config
from backend.services import catalog, vendor_lookup, vendor_overlay
from backend.validation import ValidationError

# Same Private-Use-Area range parse_pricelist.py's own PUA_RANGE flags a name with as
# unmapped_character_in_name_check_pdf — a handful of rare glyphs the PDF's font remaps that
# this pipeline never learned (see that script's module docstring). Checked live against the
# name text rather than carried as a stored flag: it's a property of the string itself, so
# there's nothing to keep in sync if a name is later corrected through the overlay.
_UNMAPPED_CHAR_RANGE = range(0xE000, 0xF900)


def _has_unmapped_char(name):
    return any(ord(ch) in _UNMAPPED_CHAR_RANGE for ch in (name or ""))


def _paths_for(supplier):
    """One configured supplier's own folder + pipeline scripts. Raises on an unconfigured
    supplier — same "never guess" stance as everywhere else (NonGoals.md 7/8): a slug typo'd
    in a form field must not silently read a folder nothing decided should be wired in."""
    if supplier not in config.VENDOR_SUPPLIERS:
        raise ValidationError(f"ไม่รู้จักซัพพลายเออร์ '{supplier}'")
    vendor_dir = config.VENDOR_PRICELISTS_DIR / supplier
    return vendor_dir, vendor_dir / "source", vendor_dir / "parse_pricelist.py", vendor_dir / "build_lookup.py"


def suppliers():
    """Every configured supplier, for the settings page's dropdowns — same {key, label} shape
    as catalog.shops()."""
    return [{"key": slug, "label": info["label"]} for slug, info in config.VENDOR_SUPPLIERS.items()]


def _catalogued_codes_by_book():
    """book -> the catalogued codes for that book, for every book any configured supplier maps
    to — issues()/`_row()`'s "in_catalog" both scope against the book the code's *own* supplier
    lines up with, never one hardcoded book."""
    books = {info["book"] for info in config.VENDOR_SUPPLIERS.values()}
    return {book: {row["code"] for row in catalog.browse(10_000, 0, None, book)[0]} for book in books}


def _in_catalog(code, supplier, catalogued_by_book):
    book = config.VENDOR_SUPPLIERS.get(supplier, {}).get("book")
    return code in catalogued_by_book.get(book, ())


def _parse_number(raw, field, kind=float):
    raw = (raw or "").strip()
    if not raw:
        raise ValidationError(f"{field}: ใส่ค่าด้วย — เว้นว่างไว้ให้กด 'ล้างค่า' แทน")
    try:
        value = kind(raw)
    except ValueError:
        raise ValidationError(f"{field}: '{raw}' ไม่ใช่ตัวเลข")
    if value < 0:
        raise ValidationError(f"{field}: ต้องไม่ติดลบ")
    return value


def _matching_codes(query, supplier, in_catalog=None, missing_size=False, unmapped_char=False):
    """The full match list (before `search()`'s own `limit` slices it) — shared with `count()`
    so the browse table can show "(2,875)" without silently meaning "only 50", the number
    `search()`'s own sliced list would otherwise imply. `in_catalog` (True/False/None-for-any),
    `missing_size` and `unmapped_char` are the browse table's status filters, applied after the
    text/supplier match so they narrow whatever query is already active rather than replacing
    it."""
    query = (query or "").strip().lower()
    all_entries = vendor_lookup.entries()
    catalogued_by_book = _catalogued_codes_by_book()  # computed once, not per row
    codes = sorted(all_entries)
    if supplier:
        codes = [code for code in codes if all_entries[code].get("supplier") == supplier]
    if query:
        codes = [
            code for code in codes
            if query in code.lower() or query in (all_entries[code].get("name") or "").lower()
        ]
        codes.sort(key=lambda code: (not code.lower().startswith(query), code))
    if in_catalog is not None:
        codes = [
            code for code in codes
            if _in_catalog(code, all_entries[code].get("supplier"), catalogued_by_book) == in_catalog
        ]
    if missing_size:
        codes = [code for code in codes if all_entries[code].get("size_mm") is None]
    if unmapped_char:
        codes = [code for code in codes if _has_unmapped_char(all_entries[code].get("name"))]
    return all_entries, catalogued_by_book, codes


def search(
    query="", limit=50, supplier=None, offset=0,
    in_catalog=None, missing_size=False, unmapped_char=False,
):
    """Substring match over the code and the vendor's own name, for the browse table, one page
    (`offset`/`limit`) at a time — with no query, the first page is file order, so the panel
    opens onto something rather than an empty box, same as catalog.api_catalog_search's
    no-query path. `supplier` narrows to one configured supplier's own codes; `in_catalog`/
    `missing_size`/`unmapped_char` are the browse table's status filters."""
    all_entries, catalogued_by_book, codes = _matching_codes(
        query, supplier, in_catalog, missing_size, unmapped_char
    )
    page = codes[offset : offset + limit]
    return [_row(code, all_entries[code], catalogued_by_book) for code in page]


def count(query="", supplier=None, in_catalog=None, missing_size=False, unmapped_char=False):
    """How many codes `search()` matched before its own `limit` sliced the list — the browse
    table's heading count."""
    _all_entries, _catalogued_by_book, codes = _matching_codes(
        query, supplier, in_catalog, missing_size, unmapped_char
    )
    return len(codes)


def _note_for(price, size_mm, pack):
    """The "หมายเหตุ" text a row's own data earns it — folded into the browse table/edit panel
    (settings page) rather than a separate check-for-errors list, so a problem shows up right
    where the code that has it already is instead of a second place to go look for it."""
    notes = []
    if price is None:
        notes.append("ไม่มีราคา")
    if size_mm is None:
        notes.append("ไม่มีขนาด")
    if pack and pack.get("ambiguous"):
        notes.append("ราคาต่อชิ้นหรือต่อแพ็คยังไม่ชัดเจน")
    return " · ".join(notes)


def _row(code, entry, catalogued_by_book):
    price, size_mm = entry.get("price"), entry.get("size_mm")
    pack = vendor_lookup.pack_for(code)
    supplier = entry.get("supplier")  # None for a code only ever set via an overlay opinion
    return {
        "code": code,
        "price": price,
        "size_mm": size_mm,
        "name": entry.get("name"),
        "pack": pack,
        "overridden": sorted(vendor_overlay.fields_for(code)),
        "supplier": supplier,
        "in_catalog": _in_catalog(code, supplier, catalogued_by_book),
        "note": _note_for(price, size_mm, pack),
    }


def find(code):
    code = (code or "").strip()
    all_entries = vendor_lookup.entries()
    if code not in all_entries:
        raise ValidationError(f"รหัส '{code}' ไม่มีในข้อมูลราคาซัพพลายเออร์")
    return _row(code, all_entries[code], _catalogued_codes_by_book())


def issues():
    """What's worth a shop's attention, scoped to codes actually in the catalogue (issue: a
    vendor-admin browse of all 2875 supplier rows would bury the ~638 that matter under over
    2000 decorations this shop never added as a product at all). Each category lists just
    enough to render a row and jump into editing it.

    `vendor_rows_without_catalog_match` is a count only, not a per-row list — at ~2200 of the
    2875 rows (README's own 96.7%-match figure implies the rest), a full browsable list would
    be exactly the noise this function exists to avoid; the raw lookup.json is still there for
    anyone who needs the detail.
    """
    all_entries = vendor_lookup.entries()
    catalogued = sorted(set().union(*_catalogued_codes_by_book().values()))

    no_vendor_entry, missing_price, missing_size, pack_ambiguous = [], [], [], []
    for code in catalogued:
        entry = all_entries.get(code)
        if entry is None:
            no_vendor_entry.append({"code": code})
            continue
        item = {"code": code, "name": entry.get("name")}
        if entry.get("price") is None:
            missing_price.append(item)
        if entry.get("size_mm") is None:
            missing_size.append(item)
        if entry.get("pack_ambiguous"):
            pack_ambiguous.append({**item, "price": entry.get("price")})

    return {
        "no_vendor_entry": no_vendor_entry,
        "missing_price": missing_price,
        "missing_size": missing_size,
        "pack_ambiguous": pack_ambiguous,
        "vendor_rows_without_catalog_match": sum(
            1 for code in all_entries if code not in catalogued
        ),
    }


def set_override(code, field, value):
    """No existence check against vendor_lookup.entries() — a code the supplier's current
    sheet has dropped (or never had at all) can still be corrected ahead of a future import,
    same "orphans are kept, never silently dropped" stance ADR-0001 takes for the catalogue."""
    code = (code or "").strip()
    if field not in vendor_overlay.OVERLAYABLE_FIELDS:
        raise ValidationError(f"แก้ทับฟิลด์ '{field}' ไม่ได้")

    if field in ("price", "size_mm"):
        parsed = _parse_number(value, field)
    elif field == "pack_qty":
        parsed = int(_parse_number(value, field, kind=int))
    elif field == "pack_ambiguous":
        parsed = (value or "").strip().lower() in ("1", "true", "yes", "on")
    else:  # name, pack_unit — plain text
        parsed = (value or "").strip()
        if not parsed:
            raise ValidationError(f"{field}: ใส่ค่าด้วย — เว้นว่างไว้ให้กด 'ล้างค่า' แทน")

    if parsed == vendor_lookup.base_field(code, field):
        # Retyped back to exactly what the supplier's own sheet already says — clear the
        # overlay opinion instead of storing a redundant copy of the base value, so the code
        # goes back to "no opinion, follow the vendor" and a future build_lookup.py re-run
        # (which could itself change this value) is picked up cleanly again.
        return clear_override(code, field)

    vendor_overlay.set_fields(code, {field: parsed}, speaks_for=(field,))
    vendor_lookup.refresh()
    return find(code)


def clear_override(code, field):
    code = (code or "").strip()
    if field not in vendor_overlay.OVERLAYABLE_FIELDS:
        raise ValidationError(f"ล้างค่าฟิลด์ '{field}' ไม่ได้")
    vendor_overlay.set_fields(code, {}, speaks_for=(field,))
    vendor_lookup.refresh()
    return find(code)


def _build_lookup_paths(build_script):
    """One supplier's own build_lookup.py's SOURCE/OUTPUT constants, read by loading the script
    rather than hardcoding its year-specific CSV filename a second time here — if that script is
    ever pointed at a new year's file, this stays in sync without a matching edit."""
    spec = importlib.util.spec_from_file_location("_vendor_build_lookup", build_script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.SOURCE, module.OUTPUT


def _diff_entries(before, after):
    added = sorted(after.keys() - before.keys())
    removed = sorted(before.keys() - after.keys())
    changed = sorted(
        code for code in (before.keys() & after.keys()) if before[code] != after[code]
    )
    return {"added": len(added), "removed": len(removed), "changed": len(changed)}


def import_pricelist(supplier, pdf_bytes, filename):
    """Upload a refreshed price-list PDF for one configured supplier and rebuild that
    supplier's own lookup.json from it (parse_pricelist.py then build_lookup.py, same
    subprocess pattern as /api/catalog/sync). Never touches the raw PDF/CSV that are already
    there — a re-upload under a name already on disk is a collision, same "never silently
    overwrite" stance as catalog_admin.add_product on a duplicate code; delete or rename the
    old one by hand first if this really is meant to replace it.
    """
    vendor_dir, source_dir, parse_script, build_script = _paths_for(supplier)

    filename = (filename or "").strip()
    if not filename.lower().endswith(".pdf"):
        raise ValidationError("อัปโหลดไฟล์ .pdf เท่านั้น")
    if not pdf_bytes or pdf_bytes[:4] != b"%PDF":
        raise ValidationError("ไฟล์นี้ไม่ใช่ PDF จริง")

    source_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = source_dir / filename
    if pdf_path.exists():
        raise ValidationError(
            f"'{filename}' มีอยู่แล้วใน {source_dir} — ลบหรือเปลี่ยนชื่อไฟล์เดิมก่อน ถ้าตั้งใจจะแทนที่จริง ๆ"
        )

    csv_path, lookup_path = _build_lookup_paths(build_script)
    # The diff below is against the base file alone, not vendor_lookup.entries() (base+overlay
    # merged) — an overridden code must not read as "changed" just because build_lookup.py
    # reproduced the same figure the shop already corrected to.
    before_base = json.loads(lookup_path.read_text(encoding="utf-8")) if lookup_path.is_file() else {}

    pdf_path.write_bytes(pdf_bytes)

    result = subprocess.run(
        [sys.executable, str(parse_script), str(pdf_path), str(csv_path)],
        capture_output=True, text=True, cwd=vendor_dir,
    )
    if result.returncode != 0:
        raise ValidationError(f"แปลง PDF ไม่สำเร็จ:\n{result.stderr[-2000:]}")

    result = subprocess.run(
        [sys.executable, str(build_script)], capture_output=True, text=True, cwd=vendor_dir,
    )
    if result.returncode != 0:
        raise ValidationError(f"สร้าง lookup.json ไม่สำเร็จ:\n{result.stderr[-2000:]}")

    after_base = json.loads(lookup_path.read_text(encoding="utf-8"))
    vendor_lookup.refresh()

    return {
        "pdf": filename,
        "build_output": result.stdout.strip(),
        **_diff_entries(before_base, after_base),
        "total_codes": len(after_base),
    }
