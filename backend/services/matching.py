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


def find(query_text, top_n=TOP_N, min_score=MIN_SCORE, query_kind=None, query_shape=None):
    """Closest catalogue products to one described decoration.

    This is a nearest-neighbour search, not an identification. Measured on a real photo it
    reliably finds the right category — a wreath finds wreaths, a Santa finds Santas — and
    within a category it can be wrong about the thing that matters: a nutcracker scored 0.820
    against a Santa, a star ornament 0.812 against a round bauble. The threshold separates
    "a Christmas decoration" from "a coffee mug"; it does not separate one Christmas
    decoration from another.

    So the score is not the whole answer. `kind_agrees` and `shape_agrees` are returned per
    candidate, because the disagreements are exactly the cases a person needs to catch, and
    a number in the nineties reads as certainty when it is not.

    Returns (matches, refused). When refused, `matches` is still filled in so the closest
    rows can be seen — but the caller must present them as "nothing close".
    """
    codes, matrix = _vectors()
    by_code = {row["code"]: row for row in _descriptions()}

    scores = matrix @ embed([query_text])[0]
    order = np.argsort(-scores)[:top_n]

    matches = []
    for position in order:
        code = codes[position]
        row = by_code.get(code, {})
        attributes = row.get("attributes", {})
        matches.append({
            "code": code,
            "score": round(float(scores[position]), 4),
            "text": row.get("text"),
            "summary": attributes.get("summary"),
            "kind": attributes.get("kind"),
            "shape": attributes.get("shape"),
            "kind_agrees": None if query_kind is None else attributes.get("kind") == query_kind,
            "shape_agrees": None if query_shape is None else (
                (attributes.get("shape") or "").lower() == query_shape.lower()
            ),
            "image": row.get("image"),
            "pdf_page": row.get("pdf_page"),
            # the code-to-photo pairing is a geometric guess, not a verified fact
            "photo_match": row.get("match"),
        })

    refused = not matches or matches[0]["score"] < min_score
    return matches, refused


def suggest_quantity(tree_code, element_code):
    """How many of a decoration a tree of that size takes.

    Derived from the two real sizes and the density the prompt already asks for — 12 to 20
    decorations on a full-height tree — scaled by how large this one is against a reference
    80 mm bauble. Sizes come from the catalogue only; NonGoals.md 8 forbids inventing one.
    """
    from backend.services import catalog

    tree_mm = catalog.require_size(catalog.find(tree_code))
    element_mm = catalog.require_size(catalog.find(element_code))

    # a 5 ft tree with 80 mm baubles is the case the density guidance was written for
    reference_tree, reference_element = 1524.0, 80.0
    by_height = tree_mm / reference_tree
    by_size = reference_element / element_mm
    low = round(12 * by_height * by_size)
    high = round(20 * by_height * by_size)
    return {"low": max(low, 1), "high": max(high, low, 1),
            "tree_mm": tree_mm, "element_mm": element_mm}
