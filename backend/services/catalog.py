"""The product catalogue: what a code is, and how big it really is.

Built by scripts/extract_catalog.py from the catalogue PDF. This module only reads it.

The point of having it is Product.md 8.2: the prompt used to ask for "a believable size",
which the model was free to interpret. With a tree code and an element code it can be told
that an 80 mm bauble on a 1524 mm tree is one nineteenth of the tree's height, which is a
fact rather than an adjective.

Nothing here estimates. A code that is not in the catalogue is a refusal outright — likely a
typo, and a wrong code is a wrong order. A code that exists but has no printed size is
different: scale_sentence() falls back to "believable, not exact" for that one item instead
of refusing the whole request, and reports it as missing so the caller can warn instead of
silently guessing — NonGoals.md 8 forbids inventing a dimension, not generating without one.
"""

import json
import re
from functools import lru_cache

from backend import config
from backend.services import shop_overlay
from backend.validation import ValidationError

__all__ = [
    "find", "search", "browse", "longest_side_mm", "describe", "require_size",
    "scale_sentence", "image_for", "image_path", "recent", "parse_size", "shops",
    "auto_pool", "row_matches_tone", "label_for", "orphans", "pricing_queue",
    "overridden_fields", "product_detail", "resolve_image_path", "split_codes",
    "set_colour_split", "clear_colour_split", "colour_name", "supporting_photos",
]


@lru_cache(maxsize=1)
def _rows():
    """Product records: the catalogue base merged with the shop overlay, field by field.

    The merge happens here, in the one accessor every other reader in this module already
    derives from, so no call site anywhere in the app has to know there are two layers
    (ADR-0001). The overlay only ever holds fields the shop actually set, so `{**base,
    **overlay}` is the whole rule — an unedited field still follows the re-imported book.
    """
    if not config.CATALOG_PATH.is_file():
        raise ValidationError(
            f"ไม่พบไฟล์ catalogue ({config.CATALOG_PATH.name}) — "
            "รัน scripts/extract_catalog.py กับ PDF catalogue ก่อน"
        )
    base = json.loads(config.CATALOG_PATH.read_text(encoding="utf-8"))
    return [{**row, **shop_overlay.fields_for(row["code"])} for row in base]


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
    """The picture to show for a code: the shop's own photo if it has taken one (issue #12),
    else the catalogue crop paired at import time, or None if neither exists.

    A shop photo is returned as a URL path rooted at "/" (`/shop-photos/<file>`); a book crop
    as a bare filename under catalog/images/, unchanged from before this existed. Every
    frontend caller already goes through api.js's catalogImageUrl() to tell the two apart, so
    this is the one place that distinction has to be made.
    """
    shop_photo = shop_overlay.fields_for(code).get("shop_photo")
    if shop_photo:
        return f"/shop-photos/{shop_photo}"
    return _images_by_code().get(code)


def resolve_image_path(image):
    """Absolute path for any image string this module hands out: a bare book-crop filename, a
    "variants/<name>" colour split, or a "/shop-photos/<file>" shop photo (issue #12). Every
    caller that turns a picked `image` value back into bytes goes through this rather than
    joining catalog/images itself, so a shop photo resolves correctly wherever it is picked.
    """
    if image is None:
        return None
    if image.startswith("/shop-photos/"):
        return config.SHOP_PHOTOS_DIR / image.removeprefix("/shop-photos/")
    return config.CATALOG_PATH.parent / "images" / image


def image_path(code):
    """Absolute path to the picture on disk, or None."""
    return resolve_image_path(image_for(code))


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
    ("wreath",   "พวงหรีด & สวอก",           ("wreath", "swa", "พวงมาลัย")),
    ("garland",  "สายรุ้ง & การ์แลนด์",       ("garland", "bead", "pullout", "arch")),
    # "snake light" rather than a bare "light"/"ไฟ": a Christmas tree's own section or name
    # routinely says "(มีไฟประดับ)" or "(ไม่มีไฟประดับ)" ("with/without lighting") — a needle
    # that short would catch the tree line first and misfile every lit tree as a light fixture.
    ("light",    "ไฟประดับ & โคมไฟ",          ("lanter", "lighting", "lights", "llum", "snake light")),
    ("ribbon",   "ริบบิ้น & โบว์",            ("ribbon", "bow")),
    ("bell",     "ระฆัง",                     ("bell",)),
    ("giftbox",  "กล่องของขวัญ",              ("gift", "box")),
    ("flower",   "ดอกไม้ & ช่อประดับ",        ("flower", "spray", "branch", "pick", "stem", "butterfly", "ดอกไม้")),
    # "wflake" rather than "snowflake": it matches both the clean spelling and the catalogue's
    # own "Sno wflakes", which is how that heading actually comes out of the PDF
    ("ornament", "ลูกบอล & ออร์นาเมนต์แขวน",  ("ornament", "bauble", "ball", "glitter", "honeycomb", "tinsel", "wflake",
                                              "ลูกบอล", "นกตกแต่ง", "นกตกเเต่ง")),
    ("topper",   "ดาว & ยอดต้น",              ("topper", "star")),
    ("tree",     "ต้นคริสต์มาส",              ("tree", "fir", "spruce", "pine", "rosemary", "ต้นคริสต์มาส")),
    ("banner",   "ป้ายอวยพร & แบนเนอร์",      ("banner", "blessing")),
    # "u u t t c c" is the Nutcracker heading as the PDF actually renders it, every letter
    # doubled: "N N u u t t c c r r a a c c". There is no un-mangled spelling to match on.
    ("figure",   "ตุ๊กตา & ของตั้งโชว์",      ("figure", "santa", "sleigh", "fantasy", "sculpture",
                                              "foam", "display", "u u t t c c", "ตุ๊กตา")),
]


@lru_cache(maxsize=1)
def _descriptions():
    """The vision pass's own file, by code — same one matching.py reads. Shared loader so
    category/kind lookups and auto_pool()'s colour lookup read the file once, not per caller."""
    path = config.CATALOG_PATH.parent / "descriptions.json"
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _kinds():
    """What the vision pass called each photo, by code. Second haystack for categorising: a
    section heading is printed once per page and carried forward, so it is often vaguer than
    the photo itself."""
    return {
        code: (entry.get("attributes") or {}).get("kind", "")
        for code, entry in _descriptions().items()
    }


def label_for(category):
    """The Thai label a category is shown under, or the key itself if it isn't one of ours.
    Lives here rather than at the call site because CATEGORIES is catalogue data."""
    return next((label for key, label, _needles in CATEGORIES if key == category), category)


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
    """The one question the picker asks: can this photo stand for this code on a card?

    A shop's own photo (issue #12) is trusted outright, bypassing every book-crop failure
    mode below — the shop took it of the real product, so a shared crop, page furniture, or a
    contested code no longer describes what is being shown. This is the mechanism by which
    photographing a product un-hides it.
    """
    if shop_overlay.fields_for(code).get("shop_photo"):
        return True
    return (
        bool(image_for(code))
        and not crop_is_ambiguous(code)
        and not crop_is_not_a_product(code)
        and not code_is_contested(code)
    )


def variants_of(code):
    """The images to offer for this code: one per colour where the photo was split, otherwise
    the single crop. Always at least one entry, so callers need no special case.

    This catalogue shoots a product across all its colours in one frame: 4400-1 is a single
    4-inch tinsel garland and its photo shows six of them in six colours. One code, but not
    one picture — picking it whole hands the generator all six at once.

    The split lives in the shop overlay, not a base file (issue #13): scripts/
    split_colourways.py's own output used to be catalog/variants.json, and the 2026-08-19
    re-import wiped that from 264 codes to nothing, orphaning 919 colour photographs that were
    still on disk. A base file computed at build time is still exactly the kind of thing a
    re-import can regenerate out from under the picker, so the mapping now goes through
    shop_overlay.set_fields like everything else ADR-0001 protects, and split_colourways.py
    writes there directly instead.
    """
    colours = shop_overlay.fields_for(code).get("colours")
    if colours:
        return [_qualify_colour_photo(name) for name in colours]
    image = image_for(code)
    return [image] if image else []


def _qualify_colour_photo(entry):
    """A `colours[]` entry is either a bare book-crop filename (the split's own output,
    lives under catalog/images/variants/) or, once a main photo has been promoted from a
    shop upload (issue #17), an already-absolute "/shop-photos/..." URL the same way
    catalog.image_for() returns a shop photo. Only the bare case needs the prefix added."""
    return entry if entry.startswith(("/", "variants/")) else f"variants/{entry}"


@lru_cache(maxsize=1)
def _with_photos():
    return [row for row in _rows() if crop_is_showable(row["code"])]


def browse(limit=60, offset=0, category=None, book=None):
    """One page of the catalogue in printed order, plus how many pages' worth there are.

    Only the codes that have a photo worth showing: this backs a thumbnail grid, and a card
    showing the wrong thing is worse than no card. search() answers the empty query with
    nothing on purpose (it also backs a datalist, which must not swallow 1,300 rows), so
    browsing is asked here instead of by widening that.
    """
    rows = _with_photos()
    if category:
        rows = [row for row in rows if category_of(row) == category]
    if book:
        rows = [row for row in rows if row.get("book") == book]
    return rows[offset : offset + limit], len(rows)


def row_matches_tone(row, tone_colours):
    """Whether a product's own colour falls inside a tone preset's colour list. `None` when
    `tone_colours` is empty (the question doesn't apply), so a caller can tell "doesn't match"
    apart from "wasn't asked"."""
    from backend.services.matching import COLOUR_BUCKETS, _normalize

    if not tone_colours:
        return None
    wanted = {_normalize(c, COLOUR_BUCKETS) for c in tone_colours}
    attrs = (_descriptions().get(row["code"]) or {}).get("attributes") or {}
    return _normalize(attrs.get("primary_colour"), COLOUR_BUCKETS) in wanted


def auto_pool(category, tone_colours):
    """Every showable product in one category whose colour fits a tone — what auto pick draws
    a recipe slot from.

    Price is not consulted. It used to be: a budget ceiling excluded unpriced products
    outright, and since only 191 of 829 products carry a price that quietly reduced auto pick
    to a quarter of the catalogue while appearing to search all of it. Nothing is being costed
    at pick time, so the ceiling bought nothing and cost most of the stock (ADR-0003).

    `tone_colours` is optional — `None` (or empty) means no colour filter.
    """
    pool = []
    for row in _with_photos():
        if category_of(row) != category:
            continue
        if tone_colours and not row_matches_tone(row, tone_colours):
            continue
        pool.append(row)
    return pool


EDITABLE_DISPLAY_FIELDS = frozenset({"price", "size_raw", "section", "book"})


def overridden_fields(code):
    """Which of the shop-editable fields this code's overlay actually holds an opinion on —
    what the find-and-correct screen (issue #11) shows as "overridden by the shop" versus
    "from the book". `size` is deliberately excluded: it travels with `size_raw` as a derived
    pair, and the screen only ever shows/edits the raw text a person typed."""
    return sorted(set(shop_overlay.fields_for(code)) & EDITABLE_DISPLAY_FIELDS)


def product_detail(row):
    """The merged record plus which of its fields are the shop's own opinion rather than the
    book's (issue #11) — shared by the recent list, the find-by-code lookup and the clear-
    override endpoint so all three show the same "overridden" badges from one source of
    truth. The book-derived position fields (bbox, pdf_page) are never part of this shape, so
    they never reach any caller of it either (ADR-0001).

    `has_shop_photo` (issue #12) is separate from `overridden`: a photo is not one of the
    text fields find-and-correct clears through CLEARABLE_FIELDS, so the screen needs its own
    flag to know whether "remove shop photo" applies to this code.
    """
    return {
        "code": row["code"], "image": image_for(row["code"]),
        "size_raw": row.get("size_raw"), "book": row.get("book"),
        "section": row.get("section"), "price": row.get("price"),
        "category": category_of(row),
        "overridden": overridden_fields(row["code"]),
        "has_shop_photo": bool(shop_overlay.fields_for(row["code"]).get("shop_photo")),
    }


def split_codes():
    """Every code with a colour-split mapping in the overlay (issue #13): code -> its list of
    colour image filenames. For build-time tooling that needs to enumerate every split at once
    rather than ask one code at a time through variants_of() —
    scripts/split_colourways.py's own stale-opinion cleanup, and
    scripts/restore_colour_variants.py's "is this code already restored" check.
    """
    return {
        code: fields["colours"]
        for code, fields in shop_overlay.all_fields().items()
        if fields.get("colours")
    }


def set_colour_split(code, names):
    """Record one code's colour-split mapping (issue #13) — the write side of variants_of().
    The one place scripts/split_colourways.py and scripts/restore_colour_variants.py reach
    into shop_overlay for this, so both stay in step with what "colours" actually means."""
    shop_overlay.set_fields(code, {"colours": names}, speaks_for=("colours",))


def clear_colour_split(code):
    """Drop a code's colour-split opinion, returning it to its single image."""
    shop_overlay.set_fields(code, {}, speaks_for=("colours",))


def colour_name(code, image):
    """The Thai name of one colour photo (issue #14, ADR-0002), or None if it has not been
    named yet — the picker falls back to a position label ("สี 2 จาก 6") in that case, never
    inventing a name. `image` is keyed the same way variants_of() returns it ("variants/
    <file>"), so a caller can pass either straight through without stripping the prefix."""
    names = shop_overlay.fields_for(code).get("colour_names", {})
    return names.get(image.removeprefix("variants/"))


def supporting_photos(code, main_image):
    """Every extra photo kept for one colour (issue #17) — the back, a detail shot, one that
    shows scale — for staff to browse and edit, never for the generator: catalog.variants_of()
    is the only list /api/element/from-catalog will accept a pick from, and this is not it.
    `main_image` is keyed the same way colour_name() is; empty when this colour has only its
    one main photo."""
    photos = shop_overlay.fields_for(code).get("supporting_photos", {})
    stored = photos.get(main_image.removeprefix("variants/"), [])
    return [_qualify_colour_photo(name) for name in stored]


def orphans():
    """Shop overlays whose code no longer appears in the current base (ADR-0001, issue #9).

    A code a re-import drops has no book position or photo left to show it with, so it does
    not resurface in find/search/browse — but the shop paid for the work in its overlay with
    its own time, so it is never deleted: it stays on disk and is surfaced here, in its own
    listing, for the shop to see and decide what to do about.
    """
    known = set(_by_code())
    return [
        {"code": code, **fields}
        for code, fields in shop_overlay.all_fields().items()
        if code not in known
    ]


def pricing_queue():
    """Every showable product with no price and not skipped — what the fast pricing entry
    mode walks (issue #10). Printed order, same as browse(), so the queue is stable between
    calls rather than reshuffling as prices come in.
    """
    return [
        row for row in _with_photos()
        if row.get("price") is None and not row.get("price_skipped")
    ]


def shops():
    """Every brand/shop the catalogue actually holds a showable product for, with counts —
    same shape as CATEGORIES' counts, so the picker can offer "pick the shop first" as a real
    filter instead of a hardcoded pair that goes stale the day a third shop's products land."""
    counts = {}
    for row in _with_photos():
        book = row.get("book")
        if book:
            counts[book] = counts.get(book, 0) + 1
    return sorted(counts.items())


def refresh():
    """Drop every cached read, so a write to products.json/product_images.json (the admin
    add-catalogue form) or to the shop overlay is visible on the next lookup without
    restarting the server."""
    shop_overlay.refresh()
    _rows.cache_clear()
    _by_code.cache_clear()
    _images_by_code.cache_clear()
    _with_photos.cache_clear()
    _crop_users.cache_clear()
    _crop_verdicts.cache_clear()
    _kinds.cache_clear()
    _contested_codes.cache_clear()
    _descriptions.cache_clear()


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
# "H 215 x D 142 cm", "D80xL80xH10cm" — each number carries its own axis letter, so the plain
# digit-x-digit _SERIES regex can't match (a letter sits between the "x" and the next number).
# Tried before _SERIES: a labelled dimension is also a valid _SERIES-shaped string once you
# ignore the letters, and _SERIES would silently mis-split it (no letters ever changed the
# answer here, longest_side_mm only ever wants the largest of the numbers).
_LABELLED_SERIES = re.compile(r"(?:[HDLW]\s*[\d.]+\s*[x×]\s*)+[HDLW]\s*[\d.]+\s*(cm|mm)", re.I)
_NUMBER = re.compile(r"[\d.]+")
_CM = re.compile(r"([\d.]+)\s*cm", re.I)
_MM = re.compile(r"([\d.]+)\s*mm", re.I)
_METRES = re.compile(r"([\d.]+)\s*m\.", re.I)

_MM_PER_FOOT = 304.8
_MM_PER_INCH = 25.4


def parse_size(raw):
    """'5 Ft.' -> height 1524 mm · '80 mm.' -> diameter 80 · '12 inc.' -> 305 mm ·
    '29 x 150 cm.' -> 290 x 1500 mm · 'H 215 x D 142 cm' -> 2150 x 1420 mm. Anything
    unrecognised returns None rather than a guess — NonGoals.md 8 forbids inventing a
    dimension, so an unparsed size stays absent, not a plausible-looking wrong number."""
    text = " ".join(raw.split())

    if match := _LABELLED_SERIES.search(text):
        unit = match.group(1).lower()
        factor = 10 if unit == "cm" else 1
        numbers = [float(n) for n in _NUMBER.findall(match.group(0))]
        return {"dimensions_mm": [round(n * factor) for n in numbers], "unit_printed": unit}

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


_GENERIC_SCALE = (
    "Keep every copy in proportion to the tree, as if it were the real object hanging there."
)


def scale_sentence(tree_code, element_codes, tree_mm_override=None, element_mm_overrides=None):
    """The paragraph that replaces 'keep it in proportion' with actual numbers, for whichever
    codes the catalogue actually prints a size for.

    `element_codes` is a list, one per decoration. Returns `(sentence, missing)` — `missing`
    lists describe()-strings for the tree and/or any decoration whose catalogue row has no
    size, empty when every code resolved. A missing size never blocks the request and never
    gets a guessed number either: NonGoals.md 8 forbids inventing a dimension, not generating
    without one, so that one item falls back to "believable, not exact" instead — same as
    when no code was given at all. The caller surfaces `missing` as a warning before the paid
    call, since a mixed-exact result still needs the user to know which item is the guess.

    `tree_mm_override`/`element_mm_overrides` (a list aligned with `element_codes`, `None`
    entries meaning "no override") let a caller supply a real millimetre figure for a code
    whose catalogue row has none — the frontend's blocking manual-size gate — without this
    function ever inventing one itself. An overridden item is not "missing": the number came
    from a person, not a guess.
    """
    if isinstance(element_codes, str) or element_codes is None:
        element_codes = [element_codes] if element_codes else []
    if element_mm_overrides is None:
        element_mm_overrides = [None] * len(element_codes)
    paired = [
        (code, override) for code, override in zip(element_codes, element_mm_overrides) if code
    ]
    element_codes = [code for code, _override in paired]
    overrides = [override for _code, override in paired]

    if not tree_code and not element_codes:
        return (_GENERIC_SCALE, [])
    if not tree_code or not element_codes:
        raise ValidationError(
            "ใส่รหัสสินค้าให้ทั้งต้นไม้และของตกแต่งทุกชิ้น หรือไม่ใส่เลยก็ได้ — "
            "ใส่บางส่วนคำนวณสัดส่วนจริงไม่ได้"
        )

    tree = find(tree_code)
    tree_mm = tree_mm_override if tree_mm_override is not None else longest_side_mm(tree)
    elements = [
        (find(code), overrides[i] if overrides[i] is not None else longest_side_mm(find(code)))
        for i, code in enumerate(element_codes)
    ]
    element_missing = [describe(row) for row, mm in elements if mm is None]
    missing = ([describe(tree)] if tree_mm is None else []) + element_missing

    if tree_mm is None:
        # every ratio below needs the tree's own height as the denominator — without it
        # nothing here can be exact, not even for a decoration whose own size is known
        return (_GENERIC_SCALE, missing)

    if not element_missing:
        if len(elements) > 1:
            lines = [
                f"These are real products and their real sizes are known. The tree is "
                f"{describe(tree)}, {tree_mm:.0f} mm tall. Each decoration has its own size "
                f"and they are not interchangeable:"
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
            return ("\n".join(lines), missing)

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
            f"against the whole tree, not against the branch it sits on.",
            missing,
        )

    # at least one decoration has no catalogue size, but the tree does — mix exact lines
    # with an explicit "unknown, do not guess" line rather than refusing the whole request
    lines = [
        f"The tree is {describe(tree)}, {tree_mm:.0f} mm tall, and is a real product with a "
        f"known size. Some decorations below have a known real size too; others do not, and "
        f"are marked as such — treat those two groups differently:"
    ]
    for row, millimetres in elements:
        if millimetres is None:
            lines.append(
                f"- {describe(row)}: no catalogue size for this one — draw it at a believable "
                f"size next to the tree and the other decorations, not a guessed measurement."
            )
        else:
            lines.append(
                f"- {describe(row)}: {millimetres:.0f} mm across, one "
                f"{tree_mm / millimetres:.0f}th of the tree's height."
            )
    lines.append(
        "Draw each kind at its own size wherever that size is known. A smaller product must "
        "look smaller than a larger one in the picture, by that much. Judge every copy "
        "against the whole tree, not against the branch it sits on."
    )
    return ("\n".join(lines), missing)
