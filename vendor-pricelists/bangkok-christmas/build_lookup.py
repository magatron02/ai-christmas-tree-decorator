"""Extracts a minimal, committable code -> {price, size_mm} mapping from cleaned/all-products-
2568.csv, for the app's own vendor lookup (backend/services/vendor_lookup.py) — the exclusive
source for both price and size (2026-09-10 decision), not just a fallback: the shop's own
catalogue still supplies the product, its photo and its code, but no longer its price or size.

`size_mm` is parsed through catalog.parse_size()/longest_side_mm() — the exact same logic the
catalogue's own sizes go through — so "the longest side, in mm" carries one meaning across
both sources, and a size that does not parse (no size-like token in size_raw at all) is simply
absent here, same "missing, not invented" stance as everywhere else (NonGoals.md 8).

Deliberately NOT the full cleaned CSV: that carries product names, categories, pack sizes and
every other column parse_pricelist.py extracted, none of which the app needs, and the less of
the supplier's own sheet ends up in a committed file the better — the CSV and the source PDF
stay exactly as gitignored as they always were (see ../README.md and the repo-root .gitignore).
This one file is the sole exception, carved out on purpose.

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
    print(f"wrote {len(data)} codes to {OUTPUT} ({with_price} priced, {with_size} sized)")


if __name__ == "__main__":
    main()
