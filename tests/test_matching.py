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


# ---- shape/colour bonus (ranking only, never the refusal threshold) ---------------------


@pytest.mark.parametrize(
    "value, bucket, expected",
    [
        ("cone", matching.SHAPE_BUCKETS, "cone"),
        ("conical", matching.SHAPE_BUCKETS, "cone"),
        ("tree", matching.SHAPE_BUCKETS, "cone"),
        ("mini tree", matching.SHAPE_BUCKETS, "cone"),
        ("sphere", matching.SHAPE_BUCKETS, "sphere"),
        ("round", matching.SHAPE_BUCKETS, "sphere"),
        ("something never seen before", matching.SHAPE_BUCKETS, "something never seen before"),
        (None, matching.SHAPE_BUCKETS, ""),
        ("gold", matching.COLOUR_BUCKETS, "gold"),  # no bucket for it; passes through as-is
        ("rainbow", matching.COLOUR_BUCKETS, "multicolour"),
        ("grey", matching.COLOUR_BUCKETS, "silver"),
    ],
)
def test_normalize_buckets_known_synonyms_together(value, bucket, expected):
    assert matching._normalize(value, bucket) == expected


def test_a_shape_matching_lower_cosine_candidate_outranks_a_higher_cosine_mismatch(monkeypatch):
    """The exact failure the module's own docstring documents: a star scored 0.812 against a
    round bauble, same category, wrong shape. This pins the fix — same gap, shape now decides
    which one shows up first."""
    codes = ["star-code", "bauble-code"]
    # bauble has the higher raw cosine; star matches the query's shape
    matrix = np.array([[0.90], [0.92]], dtype=np.float32)
    monkeypatch.setattr(matching, "_vectors", lambda: (codes, matrix))
    monkeypatch.setattr(matching, "_descriptions", lambda: [
        {"code": "star-code", "attributes": {"shape": "star", "primary_colour": "gold"}},
        {"code": "bauble-code", "attributes": {"shape": "sphere", "primary_colour": "gold"}},
    ])
    monkeypatch.setattr(matching, "embed", lambda texts: np.array([[1.0]], dtype=np.float32))

    matches, refused = matching.find("query", top_n=2, query_shape="star")

    assert refused is False
    assert matches[0]["code"] == "star-code", "shape agreement should have moved it to first"
    assert matches[0]["score"] == pytest.approx(0.90), (
        "the displayed score must stay the raw cosine, not the bonus-adjusted one"
    )
    assert matches[1]["code"] == "bauble-code"


def test_the_shape_bonus_never_lets_a_raw_refusal_through(monkeypatch):
    """Calibration-safety regression: a candidate whose RAW score sits just under MIN_SCORE
    must still be refused even when a shape bonus would push the adjusted score over the
    line — the bonus may reorder what is shown, it must never decide whether anything is."""
    just_under = matching.MIN_SCORE - 0.01
    assert just_under + matching.SHAPE_BONUS > matching.MIN_SCORE, (
        "test setup: the bonus must be large enough to actually cross the threshold, "
        "or this test proves nothing"
    )
    codes = ["almost-code"]
    matrix = np.array([[just_under]], dtype=np.float32)
    monkeypatch.setattr(matching, "_vectors", lambda: (codes, matrix))
    monkeypatch.setattr(matching, "_descriptions", lambda: [
        {"code": "almost-code", "attributes": {"shape": "star", "primary_colour": "gold"}},
    ])
    monkeypatch.setattr(matching, "embed", lambda texts: np.array([[1.0]], dtype=np.float32))

    matches, refused = matching.find("query", top_n=1, query_shape="star")

    assert refused is True, "a shape-agreeing bonus pushed a genuinely weak match past MIN_SCORE"
    assert matches[0]["score"] == pytest.approx(just_under)


def test_colour_agrees_flag_reflects_bucketed_comparison(fake_embed):
    codes, _ = matching._vectors()
    matches, _ = matching.find(codes[0], query_colour="green")

    for match in matches:
        if match["primary_colour"] is None:
            assert match["colour_agrees"] is False or match["colour_agrees"] is None
        else:
            expected = matching._normalize(match["primary_colour"], matching.COLOUR_BUCKETS) == "green"
            assert match["colour_agrees"] == expected


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


# ---- search never surfaces a code the picker itself would not show ------------------------


def test_the_search_space_excludes_every_unshowable_code():
    """A description was written by describing this code's CROP. If that crop turned out to
    be shared with another code, or to be page furniture, the description is of the wrong
    thing — matching against it can point a customer's photo at a code that only looks right
    because the text describes someone else's picture. This is the same standard
    catalog.browse() already holds the picker to."""
    from backend.services import catalog

    codes, _matrix = matching._vectors()
    assert codes, "expected at least one showable, embedded code to test against"
    for code in codes:
        assert catalog.crop_is_showable(code), f"{code} is searchable but not showable"


def test_refresh_forgets_a_code_that_stops_being_showable():
    """Mirrors catalog.refresh() — a sync must not require a server restart to take effect."""
    from backend.services import catalog

    codes_before, _ = matching._vectors()
    code = codes_before[0]
    assert catalog.crop_is_showable(code)

    original = catalog.crop_is_showable
    catalog.crop_is_showable = lambda c: False if c == code else original(c)
    try:
        matching.refresh()
        codes_after, _ = matching._vectors()
        assert code not in codes_after
    finally:
        catalog.crop_is_showable = original
        matching.refresh()
