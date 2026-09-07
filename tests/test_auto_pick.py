"""/api/auto/config and /api/auto/pick — auto pick asks for a tone and nothing else (ADR-0003).

The wizard that used to gate this on size, budget and category is gone: the budget question
could only ever see the quarter of the catalogue that carries a price. What is left fills a
fixed recipe of categories and counts, using the tone only to decide which products fill it.
Touches no storage: no request_log row, no billed call.
"""

import pytest

from backend import config
from backend.services import catalog

# deliberately mixed: some priced, some not. Unpriced products must be eligible now — that is
# the behaviour change the wizard's removal exists for.
FAKE_ROWS = [
    {"code": "O-RED-1", "section": "ornament", "size": {"diameter_mm": 80}, "price": 150.0},
    {"code": "O-RED-2", "section": "ornament", "size": {"diameter_mm": 80}},
    {"code": "O-RED-3", "section": "ornament", "size": {"diameter_mm": 80}, "price": 5000.0},
    {"code": "O-GREEN", "section": "ornament", "size": {"diameter_mm": 80}, "price": 100.0},
    {"code": "R-RED", "section": "ribbon", "size": {"diameter_mm": 80}},
    {"code": "T-GOLD", "section": "topper", "size": {"diameter_mm": 80}, "price": 300.0},
    {"code": "F-RED", "section": "flower", "size": {"diameter_mm": 80}},
    {"code": "G-GOLD", "section": "giftbox", "size": {"diameter_mm": 80}, "price": 90.0},
    # no bell in any colour: its recipe slot has nothing to fill it with, in any tone
]
FAKE_DESCRIPTIONS = {
    "O-RED-1": {"attributes": {"primary_colour": "red"}},
    "O-RED-2": {"attributes": {"primary_colour": "red"}},
    "O-RED-3": {"attributes": {"primary_colour": "red"}},
    "O-GREEN": {"attributes": {"primary_colour": "green"}},
    "R-RED": {"attributes": {"primary_colour": "red"}},
    "T-GOLD": {"attributes": {"primary_colour": "gold"}},
    "F-RED": {"attributes": {"primary_colour": "red"}},
    "G-GOLD": {"attributes": {"primary_colour": "gold"}},
}


@pytest.fixture(autouse=True)
def fake_catalog(monkeypatch):
    monkeypatch.setattr(catalog, "_with_photos", lambda: FAKE_ROWS)
    monkeypatch.setattr(catalog, "_descriptions", lambda: FAKE_DESCRIPTIONS)
    monkeypatch.setattr(catalog, "_kinds", lambda: {})


def pick(client, **data):
    return client.post("/api/auto/pick", data={"tone": "redgold", **data})


# ---------------------------------------------------------------- config


def test_config_offers_tones_and_the_recipe(client):
    body = client.get("/api/auto/config").json()
    assert {t["key"] for t in body["tones"]} == set(config.TONE_PRESETS)
    assert [(r["category"], r["count"]) for r in body["recipe"]] == list(config.AUTO_RECIPE)


def test_config_no_longer_asks_about_size_budget_or_category(client):
    body = client.get("/api/auto/config").json()
    for gone in ("tree_heights", "categories", "history_counts"):
        assert gone not in body


def test_the_recipe_fits_inside_the_element_ceiling():
    assert config.AUTO_RECIPE_TOTAL <= config.MAX_ELEMENTS
    assert config.AUTO_RECIPE_TOTAL == sum(count for _category, count in config.AUTO_RECIPE)


# ---------------------------------------------------------------- pick


def test_a_tone_alone_produces_a_proposal(client):
    response = pick(client)
    assert response.status_code == 200, response.text
    assert response.json()["decorations"]


def test_the_proposal_follows_the_recipe(client):
    body = pick(client).json()
    placed = {}
    for decoration in body["decorations"]:
        placed[decoration["category"]] = placed.get(decoration["category"], 0) + 1
    # every category the fake catalogue can fill, filled to exactly its recipe count
    assert placed == {"ornament": 3, "ribbon": 1, "topper": 1, "flower": 1, "giftbox": 1}


def test_unpriced_products_are_eligible(client):
    """The wizard excluded them outright; 638 of 829 products have no price, so that quietly
    hid three quarters of the catalogue from auto pick (ADR-0003)."""
    codes = {d["code"] for d in pick(client).json()["decorations"]}
    assert "R-RED" in codes  # ribbon, no price at all
    assert "F-RED" in codes  # flower, no price at all


def test_every_item_matches_the_requested_tone(client):
    codes = {d["code"] for d in pick(client).json()["decorations"]}
    assert "O-GREEN" not in codes  # green is in neither redgold colour


def test_a_category_with_nothing_in_this_tone_is_skipped_not_substituted(client):
    body = pick(client).json()
    assert "bell" in body["missing"]
    assert all(d["category"] != "bell" for d in body["decorations"])


def test_fewer_items_rather_than_an_off_tone_substitution(client):
    body = pick(client).json()
    # 8 asked for, bell unfillable, so 7 placed — never 8 with something off-tone in it
    assert body["requested"] == 8
    assert len(body["decorations"]) == 7


def test_a_category_short_of_stock_places_what_it_has(client, monkeypatch):
    rows = [row for row in FAKE_ROWS if row["code"] not in {"O-RED-2", "O-RED-3"}]
    monkeypatch.setattr(catalog, "_with_photos", lambda: rows)
    body = pick(client).json()
    ornaments = [d for d in body["decorations"] if d["category"] == "ornament"]
    assert len(ornaments) == 1  # only O-RED-1 is a red ornament now
    assert body["short"] == {"ornament": 1}


def test_auto_pick_proposes_no_tree(client):
    """The tree is the shop's own — uploaded or picked from the catalogue, the same as in
    กำหนดเอง. Auto pick stopped guessing one when the size question went away."""
    assert "tree" not in pick(client).json()


def test_an_unknown_tone_is_refused(client):
    assert pick(client, tone="not-a-tone").status_code == 422


def test_a_missing_tone_is_refused(client):
    assert client.post("/api/auto/pick", data={}).status_code == 422


def test_exclude_prefers_products_not_shown_yet(client):
    body = pick(client, exclude=["O-RED-1", "O-RED-2"]).json()
    ornaments = {d["code"] for d in body["decorations"] if d["category"] == "ornament"}
    assert "O-RED-3" in ornaments  # the one red ornament not shown yet is taken first


def test_a_re_roll_still_fills_the_recipe(client):
    """`exclude` is a preference, not a filter. Truncating instead would shrink the proposal
    on every สุ่มใหม่ — the shop asked for a different set, not a smaller one."""
    body = pick(client, exclude=["O-RED-1", "O-RED-2"]).json()
    ornaments = [d for d in body["decorations"] if d["category"] == "ornament"]
    assert len(ornaments) == 3
    assert body["short"] == {}


def test_exclude_falls_back_rather_than_returning_nothing(client):
    """Excluding everything in a category still yields that category — a re-roll that empties
    the tree is worse than a repeat."""
    body = pick(client, exclude=["R-RED"]).json()
    assert any(d["category"] == "ribbon" for d in body["decorations"])


# ---------------------------------------------------------------- the wizard is gone


@pytest.mark.parametrize("path", ["/api/wizard/config", "/api/wizard/pick"])
def test_the_wizard_endpoints_no_longer_exist(client, path):
    assert client.get(path).status_code == 404
    assert client.post(path, data={}).status_code == 404
