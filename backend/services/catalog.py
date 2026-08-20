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
import re
from functools import lru_cache

from backend import config
from backend.validation import ValidationError

__all__ = [
    "find", "search", "browse", "longest_side_mm", "describe", "require_size",
    "scale_sentence", "image_for", "image_path", "recent", "parse_size",
]


@lru_cache(maxsize=1)
def _rows():
    if not config.CATALOG_PATH.is_file():
        raise ValidationError(
            f"ไม่พบไฟล์ catalogue ({config.CATALOG_PATH.name}) — "
            "รัน scripts/extract_catalog.py กับ PDF catalogue ก่อน"
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


# Browsing categories. The catalogue's own `section` string comes from PDF text spans and is
# mangled often enough that it cannot be shown to anyone as-is — the real data contains
# "N N u u t t c c r r a a c c" (Nutcracker), "Lanter ns", "Christmas Swa gs", "ChristmasTrees".
# So each category carries substrings that survive the mangling, tested against the section AND
# against what the vision pass saw in the photo, and the first match wins. Order is therefore
# load-bearing: "star topper" must reach `topper` before `tree` claims it for "tree topper".
CATEGORIES = [
    ("wreath",   "พวงหรีด & สวอก",           ("wreath", "swa")),
    ("garland",  "สายรุ้ง & การ์แลนด์",       ("garland", "bead", "pullout", "arch")),
    ("light",    "ไฟประดับ & โคมไฟ",          ("lanter", "lighting", "lights", "llum")),
    ("ribbon",   "ริบบิ้น & โบว์",            ("ribbon", "bow")),
    ("bell",     "ระฆัง",                     ("bell",)),
    ("giftbox",  "กล่องของขวัญ",              ("gift", "box")),
    ("flower",   "ดอกไม้ & ช่อประดับ",        ("flower", "spray", "branch", "pick", "stem", "butterfly")),
    # "wflake" rather than "snowflake": it matches both the clean spelling and the catalogue's
    # own "Sno wflakes", which is how that heading actually comes out of the PDF
    ("ornament", "ลูกบอล & ออร์นาเมนต์แขวน",  ("ornament", "bauble", "ball", "glitter", "honeycomb", "tinsel", "wflake")),
    ("topper",   "ดาว & ยอดต้น",              ("topper", "star")),
    ("tree",     "ต้นคริสต์มาส",              ("tree", "fir", "spruce", "pine", "rosemary")),
    ("banner",   "ป้ายอวยพร & แบนเนอร์",      ("banner", "blessing")),
    # "u u t t c c" is the Nutcracker heading as the PDF actually renders it, every letter
    # doubled: "N N u u t t c c r r a a c c". There is no un-mangled spelling to match on.
    ("figure",   "ตุ๊กตา & ของตั้งโชว์",      ("figure", "santa", "sleigh", "fantasy", "sculpture",
                                              "foam", "display", "u u t t c c")),
]


@lru_cache(maxsize=1)
def _kinds():
    """What the vision pass called each photo, by code. Second haystack for categorising: a
    section heading is printed once per page and carried forward, so it is often vaguer than
    the photo itself."""
    path = config.CATALOG_PATH.parent / "descriptions.json"
    if not path.is_file():
        return {}
    described = json.loads(path.read_text(encoding="utf-8"))
    return {
        code: (entry.get("attributes") or {}).get("kind", "")
        for code, entry in described.items()
    }


def category_of(row):
    """The first category whose substrings appear in this product's section or photo kind,
    or None when nothing matches."""
    haystack = f"{row.get('section') or ''} {_kinds().get(row['code'], '')}".lower()
    for key, _label, needles in CATEGORIES:
        if any(needle in haystack for needle in needles):
            return key
    return None


# How many codes may share one crop file before the crop stops identifying any of them.
#
# Set to 2, meaning any duplicate at all disqualifies every code that shares it. The first
# version allowed up to 4, on the assumption that a small group sharing a photo was the
# legitimate case of one product printed with several sizes under it. Surveying the crops
# against the caption ribbons printed inside them showed that assumption was wrong: on book1
# pages 17-32, 128 crops resolve to only 91 distinct images, and where a ribbon was legible it
# named exactly one owner — 35072-1.png is byte-identical to 34072-1, 36072-1, 37072-1 and
# 38072-1, and the ribbon inside it reads "34072-1 (4 Ft.)". A shared crop can be right for at
# most one of its claimants, so every other claim is a picture of the wrong product, which is
# the thing NonGoals.md 7 exists to prevent.
MAX_SHARED_CROP = 2


@lru_cache(maxsize=1)
def _crop_users():
    """code -> how many OTHER codes show the identical crop.

    Read from product_images.json's `shared_with`, which the build script computes by hashing
    the file contents. Counting filenames here instead would always report zero: every code
    writes its own <code>.png, so duplicates are byte-identical files under different names.
    """
    path = config.CATALOG_PATH.parent / "product_images.json"
    if not path.is_file():
        return {}
    return {
        row["code"]: row.get("shared_with", 0)
        for row in json.loads(path.read_text(encoding="utf-8"))
        if row.get("image")
    }


def crop_is_ambiguous(code):
    """True when this code's photo is shared by so many codes that it cannot be showing any
    one of them. Such a photo is worse than no photo in a picker: it looks like an answer."""
    return _crop_users().get(code, 0) + 1 >= MAX_SHARED_CROP


# Which of the vision audit's rejection reasons are actually acted on.
#
# The audit (scripts/audit_crops.py) rejected 137 crops. Sampling each reason against the real
# pixels found only two of them reliable. The rest reject real merchandise:
#
#   heading      7 of 7 correct   — section lettering, no product in frame
#   page_number  3 of 3 correct   — the printed page-number badge
#   logo         8 of 9 correct
#   caption     10 of 12 correct
#   multiple     1 of 12 correct  ← this catalogue prints one product in ALL ITS COLOURWAYS in
#                                   a single photo. Six tinsel garlands in six colours is one
#                                   SKU's colour range, which is exactly what the picker should
#                                   show; the audit counted objects and called it a montage.
#   unclear      1 of 14 correct  ← "if in doubt reject", rationalised after the fact
#   blank        0 of 3 correct
#
# So `multiple`, `unclear` and `blank` are ignored entirely: acting on them would have hidden
# roughly a hundred real products to remove a handful of page fragments.
REJECTABLE_CROP_KINDS = {"page_number", "heading", "logo", "caption"}

# Rejections inside the trusted reasons that were checked by eye and found wrong anyway.
KEEP_DESPITE_AUDIT = {"70912-4/D1", "4501-09", "90773-1"}


@lru_cache(maxsize=1)
def _crop_verdicts():
    """code -> the reason a vision pass gave for calling this crop something other than a
    product. Only reasons in REJECTABLE_CROP_KINDS end up here.

    Written by scripts/audit_crops.py. Absent entries mean "never judged", which is treated as
    showable: the file is optional, and an un-run audit must not empty the picker.
    """
    path = config.CATALOG_PATH.parent / "crop_audit.json"
    if not path.is_file():
        return {}
    judged = json.loads(path.read_text(encoding="utf-8"))
    return {
        code: entry["crop_kind"]
        for code, entry in judged.items()
        if entry.get("is_product") is False
        and entry.get("crop_kind") in REJECTABLE_CROP_KINDS
        and code not in KEEP_DESPITE_AUDIT
    }


def crop_is_not_a_product(code):
    """True when the crop was judged page furniture for a reason that held up to checking —
    the page-number badge, the brand logo, heading artwork, or a bare code/size ribbon."""
    return code in _crop_verdicts()


@lru_cache(maxsize=1)
def _contested_codes():
    """Codes the rebuild found printed on two different pages with two different meanings.

    catalog/book_conflicts.json records every code that lost that race: extraction keeps
    whichever occurrence it saw first and logs the rest here rather than overwriting silently
    (same NonGoals.md 7/8 reasoning as everywhere else in this file). Some of these losses are
    probably harmless — a multi-page spread repeating its own code, the same label read twice
    off one page — and some are not: 90634-8 is a glittered ball ornament on one page and a
    star topper on another, from two different catalogue editions.

    Telling those apart would mean guessing which occurrence is "real", which is the one thing
    this whole module refuses to do. So every code here is treated as contested, not just the
    ones that look risky by eye — a human who knows the product line resolves it, surfaced
    in Settings, not a heuristic here deciding some conflicts don't count.
    """
    path = config.CATALOG_PATH.parent / "book_conflicts.json"
    if not path.is_file():
        return set()
    return {row["code"] for row in json.loads(path.read_text(encoding="utf-8"))}


def code_is_contested(code):
    return code in _contested_codes()


def conflicts():
    """One row per contested code, kept and lost side by side, for the Settings page to show
    someone who can actually tell the two products apart."""
    lost_by_code = {}
    for row in json.loads(
        (config.CATALOG_PATH.parent / "book_conflicts.json").read_text(encoding="utf-8")
    ) if (config.CATALOG_PATH.parent / "book_conflicts.json").is_file() else []:
        lost_by_code.setdefault(row["code"], []).append(row)

    out = []
    for code, losers in lost_by_code.items():
        kept = _by_code().get(code, {})
        out.append({
            "code": code,
            "kept": {"book": kept.get("book"), "page": kept.get("pdf_page"),
                     "section": kept.get("section"), "size_raw": kept.get("size_raw")},
            "lost": [{"book": row.get("book"), "page": row.get("pdf_page"),
                      "section": row.get("section"), "size_raw": row.get("size_raw")}
                     for row in losers],
        })
    return out


def crop_is_showable(code):
    """The one question the picker asks: can this photo stand for this code on a card?"""
    return (
        bool(image_for(code))
        and not crop_is_ambiguous(code)
        and not crop_is_not_a_product(code)
        and not code_is_contested(code)
    )


@lru_cache(maxsize=1)
def _variants():
    """code -> one image per colour, for the products photographed as a colour range.

    This catalogue shoots a product across all its colours in one frame: 4400-1 is a single
    4-inch tinsel garland and its photo shows six of them in six colours. One code, but not
    one picture — picking it whole hands the generator all six at once. Built by
    scripts/split_colourways.py; absent file means nothing was split, which is a valid state.
    """
    path = config.CATALOG_PATH.parent / "variants.json"
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def variants_of(code):
    """The images to offer for this code: one per colour where the photo was split, otherwise
    the single crop. Always at least one entry, so callers need no special case."""
    split = _variants().get(code)
    if split:
        return [f"variants/{name}" for name in split]
    image = image_for(code)
    return [image] if image else []


@lru_cache(maxsize=1)
def _with_photos():
    return [row for row in _rows() if crop_is_showable(row["code"])]


def browse(limit=60, offset=0, category=None):
    """One page of the catalogue in printed order, plus how many pages' worth there are.

    Only the codes that have a photo worth showing: this backs a thumbnail grid, and a card
    showing the wrong thing is worse than no card. search() answers the empty query with
    nothing on purpose (it also backs a datalist, which must not swallow 1,300 rows), so
    browsing is asked here instead of by widening that.
    """
    rows = _with_photos()
    if category:
        rows = [row for row in rows if category_of(row) == category]
    return rows[offset : offset + limit], len(rows)


def refresh():
    """Drop every cached read, so a write to products.json/product_images.json (the admin
    add-catalogue form) is visible on the next lookup without restarting the server."""
    _rows.cache_clear()
    _by_code.cache_clear()
    _images_by_code.cache_clear()
    _with_photos.cache_clear()
    _crop_users.cache_clear()
    _crop_verdicts.cache_clear()
    _kinds.cache_clear()
    _contested_codes.cache_clear()
    _variants.cache_clear()


def find(code):
    """Look up one product. Raises rather than returning None: every caller is about to put
    this in front of a customer."""
    code = (code or "").strip().upper()
    row = _by_code().get(code)
    if row is None:
        raise ValidationError(f"รหัส '{code}' ไม่มีใน catalogue")
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


# shared with scripts/extract_catalog.py (which imports parse_size from here) — one
# implementation for "what does this size text mean", whether it came off a printed page or
# was typed into the settings-page add/edit form
_FEET = re.compile(r"([\d.]+)\s*Ft", re.I)
_INCHES = re.compile(r"([\d.]+)\s*in(?:c|ch|ches)?\b", re.I)
_SERIES = re.compile(r"([\d.]+(?:\s*[x×]\s*[\d.]+)+)\s*(cm|mm|in(?:c|ch)?)", re.I)
_CM = re.compile(r"([\d.]+)\s*cm", re.I)
_MM = re.compile(r"([\d.]+)\s*mm", re.I)
_METRES = re.compile(r"([\d.]+)\s*m\.", re.I)

_MM_PER_FOOT = 304.8
_MM_PER_INCH = 25.4


def parse_size(raw):
    """'5 Ft.' -> height 1524 mm · '80 mm.' -> diameter 80 · '12 inc.' -> 305 mm ·
    '29 x 150 cm.' -> 290 x 1500 mm. Anything unrecognised returns None rather than a guess —
    NonGoals.md 8 forbids inventing a dimension, so an unparsed size stays absent, not a
    plausible-looking wrong number."""
    text = " ".join(raw.split())

    if match := _SERIES.search(text):
        parts = [float(p) for p in re.split(r"[x×]", match.group(1))]
        unit = match.group(2).lower()
        unit = "inch" if unit.startswith("in") else unit
        factor = 10 if unit == "cm" else _MM_PER_INCH if unit == "inch" else 1
        return {"dimensions_mm": [round(p * factor) for p in parts], "unit_printed": unit}

    if match := _FEET.search(text):
        feet = float(match.group(1))
        return {"feet": feet, "height_mm": round(feet * _MM_PER_FOOT), "unit_printed": "ft"}

    if match := _INCHES.search(text):
        inches = float(match.group(1))
        return {"inches": inches, "size_mm": round(inches * _MM_PER_INCH), "unit_printed": "inch"}

    if match := _MM.search(text):
        return {"diameter_mm": float(match.group(1)), "unit_printed": "mm"}

    if match := _CM.search(text):
        return {"diameter_mm": round(float(match.group(1)) * 10), "unit_printed": "cm"}

    if match := _METRES.search(text):
        return {"size_mm": round(float(match.group(1)) * 1000), "unit_printed": "m"}

    return None


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
            f"catalogue ไม่มีขนาดของ {describe(row)} เลยคำนวณสัดส่วนจริงไม่ได้ — "
            "เลือกสินค้าที่มีขนาดระบุ หรือสร้างภาพโดยไม่ใส่รหัส"
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
            "ใส่รหัสสินค้าให้ทั้งต้นไม้และของตกแต่งทุกชิ้น หรือไม่ใส่เลยก็ได้ — "
            "ใส่บางส่วนคำนวณสัดส่วนจริงไม่ได้"
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
