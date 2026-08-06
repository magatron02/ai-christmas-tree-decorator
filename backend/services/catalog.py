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


def scale_sentence(tree_code, element_code):
    """The paragraph that replaces 'keep it in proportion' with actual numbers.

    Returns a generic instruction when no codes were given — the caller always gets usable
    prompt text, and never gets an invented measurement.
    """
    if not tree_code and not element_code:
        return (
            "Keep every copy in proportion to the tree, as if it were the real object "
            "hanging there."
        )
    if not (tree_code and element_code):
        raise ValidationError(
            "Give a product code for both the tree and the decoration, or for neither — "
            "one alone is not enough to work out the real scale."
        )

    tree, element = find(tree_code), find(element_code)
    tree_mm, element_mm = require_size(tree), require_size(element)
    ratio = tree_mm / element_mm

    # What this buys, measured on real generations of the same tree and bauble:
    #   no sizes given   baubles ranged 22-53 px, median 0.52x the true ratio
    #   sizes given      baubles ranged 48-61 px, median 0.60x
    # So stating the size makes every copy in a picture the same size, which was one of the
    # AC-5 defects. It does not make them the right size — the model draws roughly 60% of
    # whatever it is told, and a longer version of this text spelling the ratio out as a
    # visible fraction with a bias warning measured 0.58x, i.e. no different. The extra
    # words were removed rather than kept for the look of them.
    return (
        f"These are real products and their real sizes are known. The tree is "
        f"{describe(tree)}, {tree_mm:.0f} mm tall. The decoration is {describe(element)}, "
        f"{element_mm:.0f} mm across. So each decoration must be drawn at one "
        f"{ratio:.0f}th of the tree's height — no larger, no smaller. Judge every copy "
        f"against the whole tree, not against the branch it sits on."
    )
