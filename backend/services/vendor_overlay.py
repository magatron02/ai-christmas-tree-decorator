"""The shop's own corrections to the vendor price list, held field by field — same split as
the catalogue's own base+overlay (ADR-0001), applied to a second, independent pair of files.

`vendor-pricelists/bangkok-christmas/cleaned/lookup.json` is vendor data: extracted from the
supplier's own PDF and regenerated wholesale whenever `build_lookup.py` re-runs (a corrected
price list, a fixed parsing bug). A shop correction written into that file would be destroyed
the next time it regenerates, exactly the failure ADR-0001 already fixed once for the
catalogue. So a shop's opinion on one vendor code's price/size/name/pack lives here instead,
in its own file, keyed by code, merged over the vendor base by vendor_lookup._entries().

Deliberately its own file, never `data/shop_overlay.json` — that overlay speaks for the
catalogue base (`catalog/products.json`), a different book from a different source, and
CLAUDE.md is explicit that vendor data and catalogue data must never be mixed at the file
level. Two bases, two overlays, one merge pattern.
"""

import json
from functools import lru_cache

from backend import config
from backend.validation import ValidationError

__all__ = ["overlay_path", "OVERLAYABLE_FIELDS", "fields_for", "all_fields", "set_fields", "refresh"]

# The only fields a shop can hold an opinion on — everything vendor_lookup.py actually reads
# (see its own docstring). Unlike shop_overlay's block-list (NEVER_OVERLAYABLE), this is an
# allow-list: the vendor base has a small, fixed shape (price/size_mm/name/pack_qty/pack_unit/
# pack_ambiguous), not the catalogue's long and still-growing one, so naming exactly what's
# allowed is no more restrictive in practice and catches a typo'd field name outright.
# `pack_ambiguous: false` is itself a real opinion ("checked the PDF page, it's per piece"),
# not merely the absence of one, so it belongs in this set like any other field.
OVERLAYABLE_FIELDS = frozenset({
    "price", "size_mm", "name", "pack_qty", "pack_unit", "pack_ambiguous",
})


def overlay_path():
    """Read from config at call time, not import time — the tests repoint DATA_DIR."""
    return config.DATA_DIR / "vendor_overlay.json"


@lru_cache(maxsize=1)
def _overlay():
    path = overlay_path()
    if not path.is_file():
        return {}  # no shop has corrected any vendor code yet, which is a valid state
    return json.loads(path.read_text(encoding="utf-8"))


def fields_for(code):
    """The fields this shop has set on one vendor code. Empty means the vendor's own printed
    figures have the last word."""
    return _overlay().get(code, {})


def all_fields():
    """Every code the overlay holds an opinion on, and what it holds."""
    return dict(_overlay())


def set_fields(code, fields, speaks_for=None):
    """Record the shop's opinion on some fields of one vendor code.

    `speaks_for` names the fields this write speaks for. Any of them missing from `fields` has
    its opinion dropped rather than left standing — a value edited back to what the vendor's
    own sheet says returns to following it instead of freezing the old number in place forever
    (same rule as shop_overlay.set_fields).
    """
    rejected = sorted(set(fields) - OVERLAYABLE_FIELDS)
    if rejected:
        raise ValidationError(f"แก้ทับฟิลด์ {', '.join(rejected)} ไม่ได้")

    existing = _overlay()
    kept = {
        name: value for name, value in existing.get(code, {}).items()
        if name not in (speaks_for or ())
    }
    data = {**existing, code: {**kept, **fields}}

    path = overlay_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    refresh()


def refresh():
    _overlay.cache_clear()
