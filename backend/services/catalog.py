"""The product catalogue: what a code is, and how big it really is.

Built by scripts/extract_catalog.py from the catalogue PDF. This module only reads it.

The point of having it is Product.md 8.2: the prompt used to ask for "a believable size",
which the model was free to interpret. With a tree code and an element code it can be told
that an 80 mm bauble on a 1524 mm tree is one nineteenth of the tree's height, which is a
fact rather than an adjective.

Nothing here estimates. A code that is not in the catalogue, or one the catalogue prints no
size for, produces a refusal — NonGoals.md 8 forbids guessing a dimension, because a guessed
size becomes a quoted size the moment it reaches a customer.
"""

import json
from functools import lru_cache

from backend import config
from backend.validation import ValidationError

__all__ = [
    "find", "search", "browse", "longest_side_mm", "describe", "require_size",
    "scale_sentence", "image_for", "image_path", "recent",
]


@lru_cache(maxsize=1)
def _rows():
    if not config.CATALOG_PATH.is_file():
        raise ValidationError(
            f"The product catalogue is missing ({config.CATALOG_PATH.name}). "
            "Run scripts/extract_catalog.py against the catalogue PDF."
        )
    return json.loads(config.CATALOG_PATH.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _by_code():
    index = {}
    for row in _rows():
        index.setdefault(row["code"], row)  # a repeated code is the same product listed twice
    return index


@lru_cache(maxsize=1)
def _images_by_code():
    path = config.CATALOG_PATH.parent / "product_images.json"
    if not path.is_file():
        return {}
    index = {}
    for row in json.loads(path.read_text(encoding="utf-8")):
        index.setdefault(row["code"], row["image"])
    return index


def image_for(code):
    """The catalogue crop filename for a code, or None if none was paired (Product.md 8.1
    phase B is a confidence-scored guess, not every code gets one)."""
    return _images_by_code().get(code)


def image_path(code):
    """Absolute path to the crop on disk, or None."""
    image = image_for(code)
    return (config.CATALOG_PATH.parent / "images" / image) if image else None


def recent(n=20):
    """The last n rows in file order — the admin form appends, so this is "most recently
    added" without needing a timestamp field the PDF-derived rows never had."""
    return _rows()[-n:][::-1]


@lru_cache(maxsize=1)
def _with_photos():
    return [row for row in _rows() if image_for(row["code"])]


def browse(limit=60, offset=0):
    """One page of the catalogue in printed order, plus how many pages' worth there are.

    Only the codes that have a photo: this backs a thumbnail grid, and a card with nothing
    to show is worse than no card. search() answers the empty query with nothing on purpose
    (it also backs a datalist, which must not swallow 1,300 rows), so browsing is asked here
    instead of by widening that.
    """
    rows = _with_photos()
    return rows[offset : offset + limit], len(rows)


def refresh():
    """Drop every cached read, so a write to products.json/product_images.json (the admin
    add-catalogue form) is visible on the next lookup without restarting the server."""
    _rows.cache_clear()
    _by_code.cache_clear()
    _images_by_code.cache_clear()
    _with_photos.cache_clear()


def find(code):
    """Look up one product. Raises rather than returning None: every caller is about to put
    this in front of a customer."""
    code = (code or "").strip().upper()
    row = _by_code().get(code)
    if row is None:
        raise ValidationError(f"Product code '{code}' is not in the catalogue.")
    return row


def search(query, limit=20):
    """Substring match over the code and the headings printed on its page, for the pickers.

    Searching the page headings rather than a per-code name is deliberate: "norwood" finds
    the trees on the Norwood Fir page without the data claiming any particular code is the
    Norwood Fir. See scripts/extract_catalog.py for why that claim is not made.
    """
    query = (query or "").strip().lower()
    if not query:
        return []
    hits = [
        row for row in _rows()
        if query in row["code"].lower()
        or any(query in heading.lower() for heading in row.get("page_headings", []))
    ]
    hits.sort(key=lambda row: (not row["code"].lower().startswith(query), row["code"]))
    return hits[:limit]


def longest_side_mm(row):
    """The dimension a person would call the size of this thing, or None if the catalogue
    never printed one."""
    size = row.get("size")
    if not size:
        return None
    for key in ("height_mm", "diameter_mm", "size_mm"):
        if size.get(key):
            return float(size[key])
    if size.get("dimensions_mm"):
        return float(max(size["dimensions_mm"]))
    return None


def describe(row):
    """'05021-1 (5 Ft.)' — what to call this in a prompt or an error. Code and printed size
    only: those are the two things the catalogue states outright about a code."""
    if row.get("size_raw"):
        return f"{row['code']} ({row['size_raw']})"
    return row["code"]


def require_size(row):
    millimetres = longest_side_mm(row)
    if millimetres is None:
        raise ValidationError(
            f"The catalogue prints no size for {describe(row)}, so the real scale cannot be "
            "worked out. Pick a product that has a size, or generate without codes."
        )
    return millimetres


def scale_sentence(tree_code, element_codes):
    """The paragraph that replaces 'keep it in proportion' with actual numbers.

    `element_codes` is a list, one per decoration. Returns a generic instruction when no
    codes were given — the caller always gets usable prompt text, and never gets an invented
    measurement.
    """
    if isinstance(element_codes, str) or element_codes is None:
        element_codes = [element_codes] if element_codes else []
    element_codes = [code for code in element_codes if code]

    if not tree_code and not element_codes:
        return (
            "Keep every copy in proportion to the tree, as if it were the real object "
            "hanging there."
        )
    if not tree_code or not element_codes:
        raise ValidationError(
            "Give a product code for the tree and for every decoration, or for none of "
            "them — a partial set is not enough to work out the real scale."
        )

    tree = find(tree_code)
    tree_mm = require_size(tree)
    elements = [(find(code), require_size(find(code))) for code in element_codes]

    if len(elements) > 1:
        lines = [
            f"These are real products and their real sizes are known. The tree is "
            f"{describe(tree)}, {tree_mm:.0f} mm tall. Each decoration has its own size and "
            f"they are not interchangeable:"
        ]
        for row, millimetres in elements:
            lines.append(
                f"- {describe(row)}: {millimetres:.0f} mm across, one "
                f"{tree_mm / millimetres:.0f}th of the tree's height."
            )
        lines.append(
            "Draw each kind at its own size. A smaller product must look smaller than a "
            "larger one in the picture, by that much. Judge every copy against the whole "
            "tree, not against the branch it sits on."
        )
        return "\n".join(lines)

    element, element_mm = elements[0]
    ratio = tree_mm / element_mm

    # Measured over four generations of the same tree and bauble:
    #   nothing stated        0.59x the true ratio, sizes within one picture spread 1.86x
    #   true size stated      0.70x, spread 1.38x
    #   same, longer wording  0.67x, spread 1.12x
    #   ratio pre-corrected   0.55x, spread 1.19x
    #
    # So stating the size makes the copies match each other, which was one of the AC-5
    # defects. It does not make them the true size, and asking for a larger fraction to
    # compensate made them smaller — the rendered size does not track the instructed
    # fraction. The honest number is the one that stays.
    return (
        f"These are real products and their real sizes are known. The tree is "
        f"{describe(tree)}, {tree_mm:.0f} mm tall. The decoration is {describe(element)}, "
        f"{element_mm:.0f} mm across. So each decoration must be drawn at one "
        f"{ratio:.0f}th of the tree's height — no larger, no smaller. Judge every copy "
        f"against the whole tree, not against the branch it sits on."
    )
