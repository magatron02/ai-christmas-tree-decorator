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

`lookup.json` is itself a base, same shape as the catalogue's: regenerated wholesale by
build_lookup.py, never hand-edited. `vendor_overlay.py` is its overlay, and `_entries()` below
merges the two field by field (ADR-0001's pattern, applied a second time to a second pair of
files) — a shop's corrected price or size survives the next `build_lookup.py` run exactly the
way an overlaid catalogue field survives a book re-import.

More than one supplier can be configured (`config.VENDOR_SUPPLIERS`) — each with its own
`lookup.json` under `vendor-pricelists/<slug>/cleaned/`. `_bases()` merges all of them into one
base layer, tagging each entry with the supplier it came from. A code claimed by two suppliers
keeps whichever was seen first (`VENDOR_SUPPLIERS`' own order) and is never silently
overwritten by the second — see `conflicting_codes()`. There is deliberately no UI for
resolving such a collision yet; it cannot happen with only one supplier configured, and building
one ahead of a real second supplier would be designing against a case nothing can test.
"""

import json
from functools import lru_cache

from backend import config
from backend.services import vendor_overlay


def _lookup_path(supplier):
    return config.VENDOR_PRICELISTS_DIR / supplier / "cleaned" / "lookup.json"


@lru_cache(maxsize=1)
def _bases():
    """{code: {**fields, "supplier": slug}} merged across every configured supplier, plus the
    set of codes more than one supplier claimed (kept as whichever supplier came first)."""
    merged, conflicts = {}, set()
    for slug in config.VENDOR_SUPPLIERS:
        path = _lookup_path(slug)
        if not path.is_file():
            continue
        for code, fields in json.loads(path.read_text(encoding="utf-8")).items():
            if code in merged:
                conflicts.add(code)
                continue
            merged[code] = {**fields, "supplier": slug}
    return merged, conflicts


def _base():
    return _bases()[0]


def conflicting_codes():
    """Codes more than one configured supplier's own lookup.json claims — the first supplier
    (VENDOR_SUPPLIERS' own order) is what every other function here reports; this is only
    visibility that a second, discarded claim exists, not a resolution UI (see module
    docstring)."""
    return sorted(_bases()[1])


def _entries():
    base = _base()
    overlay = vendor_overlay.all_fields()
    return {
        code: {**base.get(code, {}), **overlay.get(code, {})}
        for code in base.keys() | overlay.keys()
    }


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
        # .get(), not entry["pack_unit"]: build_lookup.py always sets the pair together, but a
        # shop overlay can now correct pack_qty and pack_unit independently (vendor_admin.py) —
        # a code caught mid-correction with only one of the two set must not crash a lookup.
        return {"qty": entry["pack_qty"], "unit": entry.get("pack_unit")}
    if entry.get("pack_ambiguous"):
        return {"ambiguous": True}
    return None


def entries():
    """Every vendor code, merged base+overlay — for the vendor admin screen's browse and
    check-for-errors views (backend/services/vendor_admin.py). Nothing else needs the whole
    table at once; every other reader here asks for one code at a time."""
    return _entries()


def base_field(code, field):
    """One field's value straight from the supplier's own sheet, overlay ignored entirely —
    for vendor_admin.set_override() to detect "typed back to exactly what the vendor already
    says" (in which case the right move is to clear the overlay opinion, not store a redundant
    copy of it). Comparing against `entries()` instead would compare against the overlay's own
    last write, which is never what's being asked here."""
    if not code:
        return None
    return _base().get(code, {}).get(field)


def refresh():
    """Drop the cached read, so a regenerated lookup.json is visible on the next lookup
    without restarting the server — same reasoning as catalog.refresh(). Clears the overlay's
    own cache too, since a vendor-admin write has to be visible the same way."""
    _bases.cache_clear()
    vendor_overlay.refresh()
