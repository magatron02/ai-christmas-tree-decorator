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


def refresh():
    """Drop the cached read, so a regenerated lookup.json is visible on the next lookup
    without restarting the server — same reasoning as catalog.refresh()."""
    _entries.cache_clear()
