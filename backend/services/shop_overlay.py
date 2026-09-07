"""The shop's own corrections to the catalogue, held field by field (ADR-0001).

The catalogue base under catalog/ is book data: extracted from a shop's printed book,
regenerated wholesale on every re-import, never edited by hand. This is the other layer — only
the fields the shop has actually set, keyed by code. An absent field means "no opinion", not
"empty", which is what lets a corrected book keep correcting everything the shop never touched.

It lives in data/ rather than beside the catalogue on purpose: the installer ships catalog/ and
excludes data/, so an overlay written next to products.json is work a reinstall can throw away.
That is not hypothetical — the 2026-08-19 re-import already destroyed a round of it once.

catalog._rows() does the merge, so nothing outside these two modules knows there are two layers.
"""

import json
from functools import lru_cache

from backend import config
from backend.validation import ValidationError

__all__ = ["overlay_path", "fields_for", "set_fields", "refresh", "NEVER_OVERLAYABLE"]

# `code` is the key the overlay, the generation history and the staff worksheet all join on —
# a wrong code is fixed by deleting the product and creating it again, never by overlaying a
# different one. `bbox` and `pdf_page` describe where a crop sat on a PDF page, which is not a
# fact about a product and not something a shop has an opinion about (ADR-0001).
NEVER_OVERLAYABLE = frozenset({"code", "bbox", "pdf_page"})


def overlay_path():
    """Read from config at call time, not import time — the tests repoint DATA_DIR."""
    return config.DATA_DIR / "shop_overlay.json"


@lru_cache(maxsize=1)
def _overlay():
    path = overlay_path()
    if not path.is_file():
        return {}  # no shop has corrected anything yet, which is a valid state
    return json.loads(path.read_text(encoding="utf-8"))


def fields_for(code):
    """The fields this shop has set on one code. Empty means the book has the last word."""
    return _overlay().get(code, {})


def set_fields(code, fields, speaks_for=None):
    """Record the shop's opinion on some fields of one product.

    `speaks_for` names the fields this write speaks for. Any of them missing from `fields` has
    its opinion dropped rather than left standing — so a value edited back to what the book
    says returns to following the book instead of freezing the old number in place forever.
    Fields outside `speaks_for` (another writer's — a photo, a colour name) are left exactly as
    they were.
    """
    rejected = sorted(NEVER_OVERLAYABLE.intersection(fields))
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
