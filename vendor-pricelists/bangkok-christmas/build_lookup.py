"""Extracts a minimal, committable code -> {price, size_mm, name} mapping from cleaned/all-
products-2568.csv, for the app's own vendor lookup (backend/services/vendor_lookup.py) — the
exclusive source for price, size, and (2026-09-10) a display name, since the catalogue itself
has no name field at all (just code/size_raw/section/book) — the shop's own catalogue still
supplies the product, its photo and its code, but never any of these three.

`size_mm` is parsed through catalog.parse_size()/longest_side_mm() — the exact same logic the
catalogue's own sizes go through — so "the longest side, in mm" carries one meaning across
both sources, and a size that does not parse (no size-like token in size_raw at all) is simply
absent here, same "missing, not invented" stance as everywhere else (NonGoals.md 8).

`name` is the CSV's own `product_name` verbatim (already had its size/pack text folded out by
parse_pricelist.py) — the one column of the supplier's own sheet this file does carry, since
quote.html has nothing else to call a decoration by. Everything else in the full CSV (category,
pack size, page, flags, ...) still stays out: the CSV and the source PDF remain exactly as
gitignored as they always were (see ../README.md and the repo-root .gitignore). This one file
is still the sole exception, carved out on purpose.

`pack_qty`/`pack_unit` (2026-09-10): `price` is the price exactly as printed, which for a
product sold by the bag/box is the price of the whole pack, not one piece of it (checked
against the CSV: code 017-06 is 48 บาท ต่อถุง ของ 2 ชิ้น, not 48 บาท ต่อชิ้น) — dividing it out
to a "per-piece" figure was considered and rejected, since a shop cannot actually buy half a
bag; backend/main.py's quantity math instead rounds *up* to whole packs and reports the
leftover, using these two fields to know the pack size when the CSV states one plainly.
`qty_per_pack`/`pack_unit` are always both-or-neither in the CSV (checked), so testing for
`pack_unit` alone is enough.

`pack_ambiguous` marks a row whose `price_unit` mentions packaging (ถุง/กล่อง/ชุด/แผง/ช่อ/แพค)
with no size to put on it and no clean single-unit word (ชิ้น/ต้น/เส้น) offered as the
alternative either — genuinely unknown whether `price` prices one piece or an unstated pack of
them, not something this pipeline can resolve from the sheet alone (a per-row check against
the source PDF page would be the only way to know for sure). Treated as a single priceable
unit by the app, same as before, but flagged so the shop sees the uncertainty rather than a
confident-looking number that might be a pack price in disguise.

Checked 2026-09-10 (after this flag first shipped and turned out to fire on the vast majority
of rows, not the rare case it was meant to be): `price_unit` is often several alternatives
glued together with " | " — one PDF header covering a whole section's worth of rows below it,
not a resolved single answer for *this* row (../README.md's own note on category headers
working the same way). Of 1993 rows mentioning a packaging word, 1718 also listed ชิ้น as one
of the alternatives — meaning the row very likely does sell as a single piece and the
packaging words just describe *other* rows the same header covers. Only the 275 that mention
packaging with no ชิ้น/ต้น/เส้น option in sight, and no qty_per_pack, are treated as truly
ambiguous now — mostly "ราคา /โหล" (per dozen), which build_lookup.py resolves outright below
rather than flagging (โหล means exactly 12, no qty_per_pack column needed to know that).

Re-run this whenever cleaned/all-products-2568.csv is regenerated from an updated price list
(parse_pricelist.py's own instructions), then commit the new lookup.json:

    D:/tree_decorator/.venv/Scripts/python.exe build_lookup.py
"""

import csv
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "cleaned" / "all-products-2568.csv"
OUTPUT = HERE / "cleaned" / "lookup.json"

# So `from backend.services.catalog import ...` resolves without installing the project —
# this script lives outside backend/ on purpose (it is vendor-pricelists' own tool, not the
# app's), the same reasoning scripts/extract_catalog.py already documents for parse_size.
sys.path.insert(0, str(HERE.parents[1]))
from backend.services.catalog import longest_side_mm, parse_size  # noqa: E402

# parse_size()'s regexes only recognise English unit abbreviations — built against the
# catalogue's own English-labelled book. The vendor's price list states the same handful of
# units in Thai instead (../README.md's own note on size_raw: "มม./นิ้ว/ซม./cm/ฟุต/เมตร mixed,
# as printed"). Checked against the raw CSV (2026-09-10): of 2276 rows with *some* size_raw
# text, only 275 parsed before this translation step existed — the other 2001 were exactly
# this, a Thai unit word parse_size() had never been taught, not sizes that genuinely don't
# parse. None of these Thai words collides with another as a substring, so plain in-order
# substitution is safe.
_THAI_UNITS = [
    (re.compile("มม\\.?"), "mm"),
    (re.compile("ซม\\.?"), "cm"),
    (re.compile("นิ้ว"), "inch"),
    (re.compile("ฟุต"), "ft"),
    (re.compile("เมตร"), "m."),
]


def _to_english_units(text):
    for pattern, replacement in _THAI_UNITS:
        text = pattern.sub(replacement, text)
    return text


# see the module docstring's 2026-09-10 note for why ชิ้น/ต้น/เส้น being offered as one of the
# alternatives outweighs a packaging word also being listed, and why โหล is resolved as a known
# dozen-pack rather than joining the ambiguous pile.
_PACKAGING_WORDS = ("ถุง", "กล่อง", "ชุด", "แผง", "ช่อ", "แพค")
_SINGLE_UNIT_WORDS = ("ชิ้น", "ต้น", "เส้น")


def _pack_hint(price_unit):
    """None (plainly single-unit or unremarkable), {"qty": 12, "unit": "โหล"} (a definite
    dozen), or "ambiguous" (packaging mentioned, no size and no single-unit alternative)."""
    if "โหล" in price_unit:
        return {"qty": 12, "unit": "โหล"}
    if any(word in price_unit for word in _SINGLE_UNIT_WORDS):
        return None
    if any(word in price_unit for word in _PACKAGING_WORDS):
        return "ambiguous"
    return None


def main():
    data = {}
    with open(SOURCE, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            code = row.get("code")
            if not code:
                continue
            entry = {}

            price_raw = row.get("price_baht")
            if price_raw:
                entry["price"] = float(price_raw)

            name = row.get("product_name")
            if name:
                entry["name"] = name

            qty_per_pack = row.get("qty_per_pack")
            pack_unit = row.get("pack_unit")
            if qty_per_pack and pack_unit:
                entry["pack_qty"] = int(float(qty_per_pack))
                entry["pack_unit"] = pack_unit
            else:
                hint = _pack_hint(row.get("price_unit", ""))
                if hint == "ambiguous":
                    entry["pack_ambiguous"] = True
                elif hint:
                    entry["pack_qty"] = hint["qty"]
                    entry["pack_unit"] = hint["unit"]

            size_raw = row.get("size_raw")
            if size_raw:
                parsed = parse_size(_to_english_units(size_raw))
                if parsed:
                    mm = longest_side_mm({"size": parsed})
                    if mm:
                        entry["size_mm"] = mm

            if entry:
                data[code] = entry

    OUTPUT.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    with_price = sum(1 for v in data.values() if "price" in v)
    with_size = sum(1 for v in data.values() if "size_mm" in v)
    with_name = sum(1 for v in data.values() if "name" in v)
    with_pack = sum(1 for v in data.values() if "pack_qty" in v)
    ambiguous = sum(1 for v in data.values() if v.get("pack_ambiguous"))
    print(
        f"wrote {len(data)} codes to {OUTPUT} "
        f"({with_price} priced, {with_size} sized, {with_name} named, "
        f"{with_pack} packs, {ambiguous} ambiguous-pack)"
    )


if __name__ == "__main__":
    main()
