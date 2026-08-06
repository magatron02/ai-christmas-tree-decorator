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

# Calibrated in scripts/calibrate_matching.py against products that are in the catalogue and
# a query that deliberately is not. Below this, "nothing close" is the honest answer.
MIN_SCORE = 0.55
TOP_N = 3


@lru_cache(maxsize=1)
def _descriptions():
    path = config.CATALOG_PATH.parent / "descriptions.json"
    if not path.is_file():
        raise ValidationError(
            "The catalogue has not been described yet. Run scripts/describe_catalog.py."
        )
    rows = json.loads(path.read_text(encoding="utf-8"))
    return [row for row in rows.values() if not row.get("error")]


@lru_cache(maxsize=1)
def _vectors():
    """The embedded catalogue, built once and cached on disk — 1,053 embeddings is a cheap
    call but not a free one, and nothing about them changes between runs."""
    path = config.CATALOG_PATH.parent / "embeddings.npy"
    codes_path = config.CATALOG_PATH.parent / "embedding_codes.json"
    if not (path.is_file() and codes_path.is_file()):
        raise ValidationError(
            "The catalogue has not been embedded yet. Run scripts/embed_catalog.py."
        )
    matrix = np.load(path)
    codes = json.loads(codes_path.read_text(encoding="utf-8"))
    return codes, matrix


def embed(texts):
    """Unit-length vectors, so cosine similarity is a dot product."""
    from openai import OpenAI

    client = OpenAI(timeout=config.API_TIMEOUT_S)
    response = client.embeddings.create(model=config.EMBEDDING_MODEL, input=list(texts))
    matrix = np.array([item.embedding for item in response.data], dtype=np.float32)
    return matrix / np.linalg.norm(matrix, axis=1, keepdims=True)


def find(query_text, top_n=TOP_N, min_score=MIN_SCORE):
    """Best catalogue matches for one described decoration.

    Returns (matches, refused). `refused` is True when nothing cleared the threshold, and in
    that case `matches` is still populated so a person can see what was closest and judge —
    but the caller must present it as "nothing close", not as a recommendation.
    """
    codes, matrix = _vectors()
    by_code = {row["code"]: row for row in _descriptions()}

    scores = matrix @ embed([query_text])[0]
    order = np.argsort(-scores)[:top_n]

    matches = []
    for position in order:
        code = codes[position]
        row = by_code.get(code, {})
        matches.append({
            "code": code,
            "score": round(float(scores[position]), 4),
            "text": row.get("text"),
            "summary": row.get("attributes", {}).get("summary"),
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
