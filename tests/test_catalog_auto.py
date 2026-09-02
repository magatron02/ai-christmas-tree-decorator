"""nearest_tree() and auto_pool() — the wizard's Auto-mode catalogue queries (wayfinder map #1).

The real catalogue's priced items (191/829) and described items (colour/shape, 638/829) barely
overlap — there is no real code that is both priced and colour-tagged, so tone filtering can't
be exercised against real data yet. Fixture rows here follow the same pattern test_matching.py
already uses for the same reason: monkeypatch catalog's private caches with fabricated rows
rather than the raw catalogue files.
"""

import pytest

from backend.services import catalog

FAKE_ROWS = [
    {"code": "T-150", "section": "tree", "size": {"height_mm": 1500}, "price": 4000.0},
    {"code": "T-200", "section": "tree", "size": {"height_mm": 2000}, "price": 6000.0},
    {"code": "T-NOSIZE", "section": "tree", "size": None, "price": 3000.0},
    {"code": "O-RED-CHEAP", "section": "ornament", "size": {"diameter_mm": 80}, "price": 100.0},
    {"code": "O-RED-PRICEY", "section": "ornament", "size": {"diameter_mm": 80}, "price": 5000.0},
    {"code": "O-GREEN-CHEAP", "section": "ornament", "size": {"diameter_mm": 80}, "price": 100.0},
    {"code": "O-NOPRICE", "section": "ornament", "size": {"diameter_mm": 80}, "price": None},
]
FAKE_DESCRIPTIONS = {
    "O-RED-CHEAP": {"attributes": {"primary_colour": "red"}},
    "O-RED-PRICEY": {"attributes": {"primary_colour": "red"}},
    "O-GREEN-CHEAP": {"attributes": {"primary_colour": "green"}},
}


@pytest.fixture(autouse=True)
def fake_catalog(monkeypatch):
    monkeypatch.setattr(catalog, "_with_photos", lambda: FAKE_ROWS)
    monkeypatch.setattr(catalog, "_descriptions", lambda: FAKE_DESCRIPTIONS)


def test_nearest_tree_picks_the_closest_sized_match():
    assert catalog.nearest_tree(1600)["code"] == "T-150"
    assert catalog.nearest_tree(1900)["code"] == "T-200"


def test_nearest_tree_ignores_a_tree_with_no_known_size():
    # T-NOSIZE is closer to nothing in particular since it has no mm to compare — it must
    # never win just because it exists
    for target in (1500, 2000, 1750):
        assert catalog.nearest_tree(target)["code"] != "T-NOSIZE"


def test_nearest_tree_returns_none_with_no_sized_tree_at_all(monkeypatch):
    monkeypatch.setattr(catalog, "_with_photos", lambda: [
        row for row in FAKE_ROWS if row["code"] != "T-150" and row["code"] != "T-200"
    ])
    assert catalog.nearest_tree(1600) is None


def test_auto_pool_filters_by_category_and_budget():
    pool = {row["code"] for row in catalog.auto_pool("ornament", None, 200)}
    assert pool == {"O-RED-CHEAP", "O-GREEN-CHEAP"}


def test_auto_pool_excludes_unpriced_rows_outright():
    """NonGoals.md 8: an unpriced row is never treated as free just because it is under any
    budget ceiling — it is excluded no matter how high the budget goes."""
    pool = {row["code"] for row in catalog.auto_pool("ornament", None, 1_000_000)}
    assert "O-NOPRICE" not in pool


def test_auto_pool_filters_by_tone_colour():
    pool = {row["code"] for row in catalog.auto_pool("ornament", ["red"], 200)}
    assert pool == {"O-RED-CHEAP"}


def test_auto_pool_tone_and_budget_both_apply():
    # the only red item under budget is O-RED-CHEAP; the pricier red one must not sneak in
    pool = {row["code"] for row in catalog.auto_pool("ornament", ["red"], 4999)}
    assert pool == {"O-RED-CHEAP"}


def test_row_matches_tone_none_when_no_tone_given():
    row = next(r for r in FAKE_ROWS if r["code"] == "O-RED-CHEAP")
    assert catalog.row_matches_tone(row, None) is None
    assert catalog.row_matches_tone(row, []) is None


def test_row_matches_tone_true_and_false():
    red = next(r for r in FAKE_ROWS if r["code"] == "O-RED-CHEAP")
    green = next(r for r in FAKE_ROWS if r["code"] == "O-GREEN-CHEAP")
    assert catalog.row_matches_tone(red, ["red", "gold"]) is True
    assert catalog.row_matches_tone(green, ["red", "gold"]) is False


def test_feet_to_mm():
    assert catalog.feet_to_mm(5) == pytest.approx(1524, abs=1)
