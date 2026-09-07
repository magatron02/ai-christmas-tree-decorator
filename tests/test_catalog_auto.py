"""auto_pool() and row_matches_tone() — the catalogue queries behind auto pick (ADR-0003).

The real catalogue's priced items (191/829) and described items (colour/shape, 638/829) barely
overlap, and price is no longer consulted here at all. Fixture rows follow the same pattern
test_matching.py already uses: monkeypatch catalog's private caches with fabricated rows rather
than the raw catalogue files.
"""

import pytest

from backend.services import catalog

FAKE_ROWS = [
    {"code": "T-150", "section": "tree", "size": {"height_mm": 1500}, "price": 4000.0},
    {"code": "O-RED-CHEAP", "section": "ornament", "size": {"diameter_mm": 80}, "price": 100.0},
    {"code": "O-RED-PRICEY", "section": "ornament", "size": {"diameter_mm": 80}, "price": 5000.0},
    {"code": "O-GREEN-CHEAP", "section": "ornament", "size": {"diameter_mm": 80}, "price": 100.0},
    {"code": "O-NOPRICE", "section": "ornament", "size": {"diameter_mm": 80}, "price": None},
    {"code": "R-RED", "section": "ribbon", "size": {"diameter_mm": 80}, "price": None},
]
FAKE_DESCRIPTIONS = {
    "O-RED-CHEAP": {"attributes": {"primary_colour": "red"}},
    "O-RED-PRICEY": {"attributes": {"primary_colour": "red"}},
    "O-GREEN-CHEAP": {"attributes": {"primary_colour": "green"}},
    "O-NOPRICE": {"attributes": {"primary_colour": "red"}},
    "R-RED": {"attributes": {"primary_colour": "red"}},
}


@pytest.fixture(autouse=True)
def fake_catalog(monkeypatch):
    monkeypatch.setattr(catalog, "_with_photos", lambda: FAKE_ROWS)
    monkeypatch.setattr(catalog, "_descriptions", lambda: FAKE_DESCRIPTIONS)
    monkeypatch.setattr(catalog, "_kinds", lambda: {})


def test_auto_pool_filters_by_category():
    pool = {row["code"] for row in catalog.auto_pool("ribbon", None)}
    assert pool == {"R-RED"}


def test_auto_pool_filters_by_tone_colour():
    pool = {row["code"] for row in catalog.auto_pool("ornament", ["red"])}
    assert pool == {"O-RED-CHEAP", "O-RED-PRICEY", "O-NOPRICE"}


def test_auto_pool_keeps_unpriced_rows():
    """Price is not a filter any more. Excluding unpriced rows hid three quarters of the real
    catalogue from auto pick, and nothing is being costed at pick time (ADR-0003)."""
    pool = {row["code"] for row in catalog.auto_pool("ornament", None)}
    assert "O-NOPRICE" in pool


def test_auto_pool_ignores_price_entirely():
    """The pricey red ornament is in the pool alongside the cheap one — there is no ceiling
    left for it to fall outside of."""
    pool = {row["code"] for row in catalog.auto_pool("ornament", ["red"])}
    assert "O-RED-PRICEY" in pool


def test_auto_pool_empty_for_a_category_with_nothing_in_that_tone():
    assert catalog.auto_pool("ribbon", ["green"]) == []


def test_row_matches_tone_none_when_no_tone_given():
    row = next(r for r in FAKE_ROWS if r["code"] == "O-RED-CHEAP")
    assert catalog.row_matches_tone(row, None) is None
    assert catalog.row_matches_tone(row, []) is None


def test_row_matches_tone_true_and_false():
    red = next(r for r in FAKE_ROWS if r["code"] == "O-RED-CHEAP")
    green = next(r for r in FAKE_ROWS if r["code"] == "O-GREEN-CHEAP")
    assert catalog.row_matches_tone(red, ["red", "gold"]) is True
    assert catalog.row_matches_tone(green, ["red", "gold"]) is False
