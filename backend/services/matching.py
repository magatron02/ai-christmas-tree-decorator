"""Find catalogue products that look like a decoration in a customer's photo.

Product.md 8.3c. Every description — catalogue and query — is embedded as text, and the
match is cosine similarity between them.

Two rules from NonGoals.md 7 shape everything here:

  * three candidates, never one. A single confident answer is a wrong order waiting to
    happen, and the shop wears it.
  * a real refusal. If nothing scores above the threshold the answer is "nothing close",
    not the least-bad row. A recommender that always recommends has not been tested for the
    case where it should not.

Each result carries the photo it came from. The pairing between a code and its photo is a
geometric guess (scripts/build_product_index.py), so the photo travelling with the code is
what lets whoever is looking catch a bad pairing at the moment it matters.
"""

import json
from functools import lru_cache

import numpy as np

from backend import config
from backend.validation import ValidationError

# Measured by scripts/calibrate_matching.py, 2026-08-05, over 1,053 described products:
#
#   things a Christmas photo really contains   0.564 to 0.793
#   things nobody sells here                   0.273 to 0.463   (mug, chair, shoes, laptop)
#
# The groups separate by 0.101, so a threshold between them can refuse honestly. 0.51 sits
# in the middle of that gap. An earlier guess of 0.55 was only 0.008 above the weakest real
# match and would have refused genuine products for no reason.
#
# Re-run the calibration if the catalogue or the description schema changes: a threshold
# that no longer separates the groups means the search cannot refuse, and NonGoals.md 7 says
# it must not then be shipped as a recommender.
MIN_SCORE = 0.51
TOP_N = 3

# Free-text shape/colour, bucketed by hand from what actually appears in catalog/descriptions.json
# (checked directly, e.g. "sphere"/"round", "cone"/"conical"/"tree"/"mini tree"/"fir tree" all
# name the same shape). Ranking-only — see find()'s SHAPE_BONUS/COLOUR_BONUS comment for why
# this never touches the refusal threshold. Hand-maintained on purpose: if this keeps growing,
# that is the signal to constrain vision.Decoration.shape to a fixed enum (like `kind` and
# `finish` already are) and re-run scripts/describe_catalog.py + embed_catalog.py properly —
# not before, since that costs ~1,053 real vision calls.
SHAPE_BUCKETS = {
    "sphere": {"sphere", "round", "ball", "globe"},
    "cone": {"cone", "conical", "tree", "conical tree", "mini tree", "christmas tree",
             "fir tree"},
    "star": {"star", "five-point star"},
    "spray": {"spray", "flower spray", "poinsettia flower spray"},
    "teardrop": {"teardrop", "elongated teardrop", "onion"},
    "bow": {"bow", "bow with long ribbon tails", "ribbon bow", "ribbon bow with long tails"},
    "flower": {"flower", "poinsettia flower"},
    "figure": {"figure", "bear figure"},
    "box": {"box", "cube"},
    "strand": {"long strand", "long strip"},
}
COLOUR_BUCKETS = {
    "multicolour": {"multicolour", "multi", "rainbow"},
    "silver": {"silver", "grey"},
}
SHAPE_BONUS = 0.03
COLOUR_BONUS = 0.03


def _normalize(value, buckets):
    """A free-text field's bucket name, or the lowercased value itself when no bucket claims
    it — so an unbucketed shape/colour still compares by exact match, same as before this
    existed."""
    value = (value or "").strip().lower()
    for bucket, synonyms in buckets.items():
        if value in synonyms:
            return bucket
    return value


@lru_cache(maxsize=1)
def _descriptions():
    path = config.CATALOG_PATH.parent / "descriptions.json"
    if not path.is_file():
        raise ValidationError(
            "ยังไม่ได้ทำคำอธิบาย catalogue — รัน scripts/describe_catalog.py ก่อน"
        )
    rows = json.loads(path.read_text(encoding="utf-8"))
    return [row for row in rows.values() if not row.get("error")]


@lru_cache(maxsize=1)
def _vectors():
    """The embedded catalogue, built once and cached on disk — 1,053 embeddings is a cheap
    call but not a free one, and nothing about them changes between runs.

    Filtered to the same codes catalog.browse() will show a photo for. A description was
    written by describing this code's CROP, so a code whose crop turned out to be shared with
    another code, or to be page furniture rather than a product, has a description of the
    wrong thing — searching it can point a customer's photo at a code that only looks right
    because the text describes someone else's picture. catalog.crop_is_showable() is already
    the system's one answer to "can this code's photo be trusted", so matching defers to it
    rather than keeping a second opinion.
    """
    path = config.CATALOG_PATH.parent / "embeddings.npy"
    codes_path = config.CATALOG_PATH.parent / "embedding_codes.json"
    if not (path.is_file() and codes_path.is_file()):
        raise ValidationError(
            "ยังไม่ได้ทำดัชนีค้นหา catalogue — รัน scripts/embed_catalog.py ก่อน"
        )
    matrix = np.load(path)
    codes = json.loads(codes_path.read_text(encoding="utf-8"))

    from backend.services import catalog

    keep = [i for i, code in enumerate(codes) if catalog.crop_is_showable(code)]
    if len(keep) != len(codes):
        codes = [codes[i] for i in keep]
        matrix = matrix[keep]
    return codes, matrix


def refresh():
    """Drop the cached embeddings, so a sync that rewrites embeddings.npy — or a change to
    which crops count as showable — is visible on the next search without restarting."""
    _descriptions.cache_clear()
    _vectors.cache_clear()


def embed(texts):
    """Unit-length vectors, so cosine similarity is a dot product."""
    from openai import OpenAI

    client = OpenAI(timeout=config.API_TIMEOUT_S)
    response = client.embeddings.create(model=config.EMBEDDING_MODEL, input=list(texts))
    matrix = np.array([item.embedding for item in response.data], dtype=np.float32)
    return matrix / np.linalg.norm(matrix, axis=1, keepdims=True)


def upsert_embedding(code, text):
    """Add or replace one code's vector in the on-disk embeddings (issue #12) — a shop photo
    upload re-embeds only that code, not the whole catalogue the way scripts/embed_catalog.py
    does. Safe to call before either file exists (a fresh catalogue with nothing embedded
    yet); the pair is created rather than requiring embed_catalog.py to have run first.
    """
    path = config.CATALOG_PATH.parent / "embeddings.npy"
    codes_path = config.CATALOG_PATH.parent / "embedding_codes.json"
    vector = embed([text])[0]

    if path.is_file() and codes_path.is_file():
        matrix = np.load(path)
        codes = json.loads(codes_path.read_text(encoding="utf-8"))
    else:
        matrix = np.empty((0, vector.shape[0]), dtype=np.float32)
        codes = []

    if code in codes:
        matrix = matrix.copy()
        matrix[codes.index(code)] = vector
    else:
        matrix = np.vstack([matrix, vector])
        codes = [*codes, code]

    np.save(path, matrix)
    codes_path.write_text(json.dumps(codes), encoding="utf-8")
    refresh()


def find(query_text, top_n=TOP_N, min_score=MIN_SCORE, query_kind=None, query_shape=None,
         query_colour=None):
    """Closest catalogue products to one described decoration.

    This is a nearest-neighbour search, not an identification. Measured on a real photo it
    reliably finds the right category — a wreath finds wreaths, a Santa finds Santas — and
    within a category it can be wrong about the thing that matters: a nutcracker scored 0.820
    against a Santa, a star ornament 0.812 against a round bauble. The threshold separates
    "a Christmas decoration" from "a coffee mug"; it does not separate one Christmas
    decoration from another.

    Shape and colour agreement nudges *which* candidates rank in the top N (a small bonus
    added to an `adjusted` score, SHAPE_BONUS/COLOUR_BONUS) — that is the whole fix for the
    star/bauble case above: same cosine, but the star now outranks the bauble once shape
    agreement is counted. `scores`/the returned `"score"` and the refusal check stay on raw
    cosine, never the adjusted value: MIN_SCORE was calibrated against pure cosine similarity
    (see the module comment above, and test_the_threshold_sits_inside_the_measured_gap), and
    a boosted score crossing that line would silently invalidate the calibration — a bonus
    may change the order of the results shown, it must never change whether they get shown.

    `kind_agrees`, `shape_agrees` and `colour_agrees` are still returned per candidate on top
    of that, because a disagreement is exactly the case a person needs to catch, and a number
    in the nineties reads as certainty when it is not.

    Returns (matches, refused). When refused, `matches` is still filled in so the closest
    rows can be seen — but the caller must present them as "nothing close".
    """
    from backend.services import catalog

    codes, matrix = _vectors()
    by_code = {row["code"]: row for row in _descriptions()}

    scores = matrix @ embed([query_text])[0]
    adjusted = scores.copy()

    query_shape_bucket = _normalize(query_shape, SHAPE_BUCKETS) if query_shape else None
    query_colour_bucket = _normalize(query_colour, COLOUR_BUCKETS) if query_colour else None
    if query_shape_bucket or query_colour_bucket:
        for i, code in enumerate(codes):
            attributes = by_code.get(code, {}).get("attributes", {})
            if query_shape_bucket and _normalize(attributes.get("shape"), SHAPE_BUCKETS) == query_shape_bucket:
                adjusted[i] += SHAPE_BONUS
            if query_colour_bucket and _normalize(attributes.get("primary_colour"), COLOUR_BUCKETS) == query_colour_bucket:
                adjusted[i] += COLOUR_BONUS

    order = np.argsort(-adjusted)[:top_n]

    matches = []
    for position in order:
        code = codes[position]
        row = by_code.get(code, {})
        attributes = row.get("attributes", {})
        candidate_shape = attributes.get("shape")
        candidate_colour = attributes.get("primary_colour")
        matches.append({
            "code": code,
            "score": round(float(scores[position]), 4),
            "text": row.get("text"),
            "summary": attributes.get("summary"),
            "kind": attributes.get("kind"),
            "shape": candidate_shape,
            "primary_colour": candidate_colour,
            "kind_agrees": None if query_kind is None else attributes.get("kind") == query_kind,
            "shape_agrees": None if query_shape is None else (
                _normalize(candidate_shape, SHAPE_BUCKETS) == _normalize(query_shape, SHAPE_BUCKETS)
            ),
            "colour_agrees": None if query_colour is None else (
                _normalize(candidate_colour, COLOUR_BUCKETS) == _normalize(query_colour, COLOUR_BUCKETS)
            ),
            # catalog.image_for(), not row.get("image") — a description row's own "image"
            # is a snapshot of the crop it was described from, which goes stale the moment a
            # shop photo supersedes it (issue #12); the live picture is always the true one.
            "image": catalog.image_for(code),
            "pdf_page": row.get("pdf_page"),
            # the code-to-photo pairing is a geometric guess, not a verified fact
            "photo_match": row.get("match"),
        })

    # refusal is decided on raw cosine over the WHOLE catalogue, not just the (possibly
    # re-ordered) top N — the bonus must not let a genuinely unrelated photo sneak past the
    # threshold just because it happened to share a shape/colour bucket with something
    refused = bool(len(scores) == 0 or float(scores.max()) < min_score)
    return matches, refused


def suggest_quantity(tree_code, element_code, size_lookup=None):
    """How many of a decoration a tree of that size takes.

    Derived from the two real sizes and the density the prompt already asks for — 12 to 20
    decorations on a full-height tree — scaled by how large this one is against a reference
    80 mm bauble. Sizes come from the catalogue by default; NonGoals.md 8 forbids inventing
    one either way. `size_lookup`, passed through to catalog.require_size(), lets a caller
    widen where a size may come from (main.py passes one that falls back to vendor_lookup for
    a code the catalogue itself has none for — 2026-09-10) without this function caring which.
    """
    from backend.services import catalog

    size_lookup = size_lookup or catalog.longest_side_mm
    tree_mm = catalog.require_size(catalog.find(tree_code), size_lookup)
    element_mm = catalog.require_size(catalog.find(element_code), size_lookup)

    # a 5 ft tree with 80 mm baubles is the case the density guidance was written for
    reference_tree, reference_element = 1524.0, 80.0
    by_height = tree_mm / reference_tree
    by_size = reference_element / element_mm
    low = round(12 * by_height * by_size)
    high = round(20 * by_height * by_size)
    return {"low": max(low, 1), "high": max(high, low, 1),
            "tree_mm": tree_mm, "element_mm": element_mm}
