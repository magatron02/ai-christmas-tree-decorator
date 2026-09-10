"""Price AND size, read exclusively from the supplier's own price list (2026-09-10 decision).

Originally just a price fallback for codes the shop's own catalogue had none for. Widened the
same day to also supply size, and to be the *only* source for both — not a fallback anymore —
because a partner-facing deployment wants one consistent size/price authority per code rather
than a patchwork of "some codes use the catalogue's own numbers, some use the vendor's". The
catalogue (catalog.py) is still where a product is found, photographed and coded; it is simply
no longer consulted for `price` or `size` once a code exists here — see backend/main.py's
_priced_extra() and the size_lookup= parameter threaded through catalog.scale_sentence() /
catalog.require_size() / matching.suggest_quantity() for where that switch actually happens.

Deliberately its own file, never merged into catalog/products.json or catalog.py's own
lookups — catalog.find() and catalog.longest_side_mm() stay exactly what they were (the
catalogue's own printed numbers), so anything that still wants the catalogue's own reading of
a code (there is no such caller left, by design, but nothing stops one existing later) is not
quietly rewired just because this file exists.
"""

import json
from functools import lru_cache

from backend import config


@lru_cache(maxsize=1)
def _entries():
    if not config.VENDOR_LOOKUP_PATH.is_file():
        return {}
    return json.loads(config.VENDOR_LOOKUP_PATH.read_text(encoding="utf-8"))


def price_for(code):
    """The vendor's own wholesale price for this exact code, or None.

    Exact match only, on the code exactly as printed — never a base-code or fuzzy match, so a
    hit always means this code was seen character-for-character in the supplier's own price
    list (see build_lookup.py). Codes this app never had a vendor price list for at all (MS
    Natural Design, mostly) simply never match.
    """
    if not code:
        return None
    return _entries().get(code, {}).get("price")


def size_mm_for(code):
    """The vendor's own printed size for this exact code, in millimetres, or None.

    Parsed by build_lookup.py through the same catalog.parse_size()/longest_side_mm() logic
    the catalogue's own sizes go through, so "the longest side, in mm" means the same thing
    whichever of the two ever ends up meaning anything here — the answer is a number, not the
    original unit the supplier printed.
    """
    if not code:
        return None
    return _entries().get(code, {}).get("size_mm")


def name_for(code):
    """A Thai display name for this exact code, or None — the catalogue itself has no name
    field at all (code/size_raw/section/book only), so this is the only source there is
    (2026-09-10). Verbatim from the supplier's own product_name column, size/pack text
    already folded out by parse_pricelist.py."""
    if not code:
        return None
    return _entries().get(code, {}).get("name")


def pack_for(code):
    """How `price` for this code is actually sold, or None for an ordinary single-piece price.

    `price` is always the figure exactly as printed — for a product sold by the bag or box
    that is the price of the whole pack, not one piece of it (2026-09-10: code 017-06 is
    48 baht per bag of 2, not 48 baht each — a shop cannot buy half a bag, so nothing here
    ever divides that out into a per-piece figure; backend/main.py rounds the quantity needed
    up to whole packs instead and reports the leftover).

    Returns `{"qty": int, "unit": str}` when build_lookup.py found a definite pack size
    (the CSV's own qty_per_pack + pack_unit columns), `{"ambiguous": True}` when the price's
    own unit column mentions packaging (ถุง/กล่อง/ชุด/แผง/ช่อ/โหล/แพค) with no size given for
    it — genuinely unknown whether `price` is per piece or per an unstated pack — or None when
    the price is plainly per piece (or per tree) with nothing to reconsider.
    """
    if not code:
        return None
    entry = _entries().get(code, {})
    if "pack_qty" in entry:
        return {"qty": entry["pack_qty"], "unit": entry["pack_unit"]}
    if entry.get("pack_ambiguous"):
        return {"ambiguous": True}
    return None


def refresh():
    """Drop the cached read, so a regenerated lookup.json is visible on the next lookup
    without restarting the server — same reasoning as catalog.refresh()."""
    _entries.cache_clear()
