"""Matching a reference photo against the catalogue — Product.md 8.3c.

The two things that must hold whatever the search quality turns out to be:

  * three candidates with scores, never one confident answer (NonGoals.md 7)
  * a refusal that actually fires when nothing is close

A recommender that always recommends has not been tested for the case where it should not,
and that case is the one that puts the wrong box in a customer's order.
"""

import json

import numpy as np
import pytest

from backend import config
from backend.services import matching
from backend.validation import ValidationError

CATALOG = config.CATALOG_PATH.parent

pytestmark = pytest.mark.skipif(
    not (CATALOG / "embeddings.npy").is_file(),
    reason="run scripts/describe_catalog.py then scripts/embed_catalog.py first",
)


@pytest.fixture
def fake_embed(monkeypatch):
    """Query embedding is the only API call in this module; the catalogue side is on disk."""
    codes, matrix = matching._vectors()

    def stub(texts):
        # answer with the stored vector of whatever code the test named, so similarity is
        # exercised for real without spending anything
        out = []
        for text in texts:
            if text in codes:
                out.append(matrix[codes.index(text)])
            else:
                rng = np.random.default_rng(abs(hash(text)) % (2**32))
                vector = rng.normal(size=matrix.shape[1]).astype(np.float32)
                out.append(vector / np.linalg.norm(vector))
        return np.array(out, dtype=np.float32)

    monkeypatch.setattr(matching, "embed", stub)
    return stub


def test_a_product_finds_itself(fake_embed):
    codes, _ = matching._vectors()
    matches, refused = matching.find(codes[0])

    assert refused is False
    assert matches[0]["code"] == codes[0]
    assert matches[0]["score"] > 0.99


def test_three_candidates_come_back_not_one(fake_embed):
    codes, _ = matching._vectors()
    matches, _ = matching.find(codes[0])

    assert len(matches) == 3
    assert all("score" in match for match in matches)


def test_nothing_close_is_refused(fake_embed):
    """A random direction in embedding space is nothing like any product. The answer has to
    be "nothing close", not the least-bad row presented as a recommendation."""
    matches, refused = matching.find("a query unrelated to anything in the catalogue")

    assert refused is True
    assert matches, "the closest rows are still returned so a person can judge"
    assert matches[0]["score"] < matching.MIN_SCORE


def test_every_candidate_carries_its_photo_and_how_it_was_paired(fake_embed):
    """The code-to-photo pairing is a geometric guess. It travels with the answer so a wrong
    pairing is visible at the moment someone acts on it."""
    codes, _ = matching._vectors()
    matches, _ = matching.find(codes[0])

    for match in matches:
        assert match["image"], "a candidate without a photo cannot be checked"
        assert match["photo_match"] in {
            "directly_above", "above_far", "beside", "no_rule_fitted"
        }


def test_scores_are_ordered(fake_embed):
    codes, _ = matching._vectors()
    matches, _ = matching.find(codes[0])
    assert [m["score"] for m in matches] == sorted((m["score"] for m in matches), reverse=True)


# ---- quantity ---------------------------------------------------------------------------


def test_quantity_scales_with_the_tree():
    """A 7 ft tree takes more of the same bauble than a 5 ft one."""
    small = matching.suggest_quantity("05021-1", "017-06")
    large = matching.suggest_quantity("07021-1", "017-06")

    assert large["low"] > small["low"]
    assert large["high"] > small["high"]


def test_quantity_scales_inversely_with_the_decoration():
    """The same tree takes more small baubles than large ones."""
    large_bauble = matching.suggest_quantity("05021-1", "017-06")   # 80 mm
    small_bauble = matching.suggest_quantity("05021-1", "018-02")   # 40 mm

    assert small_bauble["low"] > large_bauble["low"]


def test_quantity_reports_the_sizes_it_used():
    quantity = matching.suggest_quantity("05021-1", "017-06")
    assert quantity["tree_mm"] == 1524
    assert quantity["element_mm"] == 80


def test_quantity_refuses_when_a_size_is_unknown():
    """NonGoals.md 8: a guessed size becomes a quoted quantity."""
    from backend.services import catalog

    sizeless = next(row for row in catalog._rows() if row["size"] is None)

    with pytest.raises(ValidationError):
        matching.suggest_quantity("05021-1", sizeless["code"])


def test_the_threshold_sits_inside_the_measured_gap():
    """Calibrated 2026-08-05: real products scored 0.564 and up, things nobody sells scored
    0.463 and down. A threshold outside that gap either refuses genuine products or accepts
    a coffee mug, and both are silent failures."""
    assert 0.463 < matching.MIN_SCORE < 0.564


def test_the_embedded_catalogue_matches_the_descriptions():
    """A stale embedding file would answer from a catalogue that no longer exists, silently."""
    codes, matrix = matching._vectors()
    described = {row["code"] for row in matching._descriptions()}

    assert len(codes) == matrix.shape[0]
    assert set(codes) <= described
