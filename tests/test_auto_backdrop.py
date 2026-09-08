"""Auto pick works against any backdrop, not just a tree (issue #24).

One engine, not one per backdrop (ADR-0004): the same tone question and the same recipe
machinery fill a wall or door, from mounted categories instead of hung ones. A tone with
nothing for the chosen backdrop is not offered at all — asking for a tone the shop cannot
stock is a worse answer than not offering it.
"""

import pytest

from backend import config
from backend.services import catalog

FAKE_ROWS = [
    {"code": "O-RED", "section": "ornament", "size": {"diameter_mm": 80}},
    {"code": "R-RED", "section": "ribbon", "size": {"diameter_mm": 80}},
    {"code": "W-RED", "section": "wreath", "size": {"diameter_mm": 300}},
    {"code": "W-GREEN", "section": "wreath", "size": {"diameter_mm": 300}},
    {"code": "B-GOLD", "section": "blessing banner", "size": {"diameter_mm": 300}},
    # nothing white or silver anywhere, on either backdrop
]
FAKE_DESCRIPTIONS = {
    "O-RED": {"attributes": {"primary_colour": "red"}},
    "R-RED": {"attributes": {"primary_colour": "red"}},
    "W-RED": {"attributes": {"primary_colour": "red"}},
    "W-GREEN": {"attributes": {"primary_colour": "green"}},
    "B-GOLD": {"attributes": {"primary_colour": "gold"}},
}


@pytest.fixture(autouse=True)
def fake_catalog(monkeypatch):
    monkeypatch.setattr(catalog, "_with_photos", lambda: FAKE_ROWS)
    monkeypatch.setattr(catalog, "_descriptions", lambda: FAKE_DESCRIPTIONS)
    monkeypatch.setattr(catalog, "_kinds", lambda: {})


def pick(client, **data):
    return client.post("/api/auto/pick", data={"tone": "redgold", **data})


# ---- the recipe that applies ----


def test_the_wall_recipe_is_mounted_categories_only():
    assert [c for c, _n in config.AUTO_RECIPES["wall"]] == ["wreath", "banner"]
    for category, _count in config.AUTO_RECIPES["wall"]:
        assert catalog.placement_of(category) == "mounted"


def test_the_tree_recipe_is_unchanged():
    assert config.AUTO_RECIPES["tree"] == config.AUTO_RECIPE + config.AUTO_GROUNDED


def test_config_returns_the_recipe_for_the_backdrop_asked_for(client):
    tree = client.get("/api/auto/config?backdrop=tree").json()
    wall = client.get("/api/auto/config?backdrop=wall").json()

    assert [(r["category"], r["count"]) for r in tree["recipe"]] == list(config.AUTO_RECIPES["tree"])
    assert [(r["category"], r["count"]) for r in wall["recipe"]] == list(config.AUTO_RECIPES["wall"])


def test_no_backdrop_asked_for_is_the_tree_as_before(client):
    body = client.get("/api/auto/config").json()

    assert [(r["category"], r["count"]) for r in body["recipe"]] == list(config.AUTO_RECIPES["tree"])


# ---- tones with nothing behind them are not offered ----


def test_a_tone_with_nothing_for_this_backdrop_is_not_offered(client):
    wall = client.get("/api/auto/config?backdrop=wall").json()

    offered = {t["key"] for t in wall["tones"]}
    assert "redgold" in offered  # W-RED fills the wreath slot
    assert "whitesilver" not in offered  # nothing white or silver is stocked at all


def test_a_tone_is_offered_when_any_one_slot_can_be_filled(client):
    """natural has a green wreath and no banner — one slot of two is enough to be worth
    offering, the same way a tree tone with an unfillable bell is still offered."""
    offered = {t["key"] for t in client.get("/api/auto/config?backdrop=wall").json()["tones"]}

    assert "natural" in offered


def test_the_tree_offers_every_tone_exactly_as_before(client):
    """The tree's recipe is six categories wide — a tone that fills none of them is a
    catalogue problem, not a routine outcome, so nothing is hidden there."""
    offered = {t["key"] for t in client.get("/api/auto/config?backdrop=tree").json()["tones"]}

    assert offered == set(config.TONE_PRESETS)


# ---- picking ----


def test_a_wall_pick_proposes_mounted_products(client):
    body = pick(client, backdrop="wall").json()

    assert [d["code"] for d in body["decorations"]] == ["W-RED", "B-GOLD"]
    assert [d["category"] for d in body["decorations"]] == ["wreath", "banner"]


def test_a_wall_pick_never_proposes_something_for_a_tree(client):
    codes = {d["code"] for d in pick(client, backdrop="wall").json()["decorations"]}

    assert "O-RED" not in codes
    assert "R-RED" not in codes


def test_an_unfillable_wall_slot_is_skipped_not_substituted(client):
    """The only banner stocked is gold — asking for the natural tone places the green wreath
    and nothing else, rather than reaching for an off-tone banner, exactly as a tree recipe's
    empty slot does."""
    body = pick(client, tone="natural", backdrop="wall").json()

    assert "banner" in body["missing"]
    assert body["requested"] == 2
    assert [d["code"] for d in body["decorations"]] == ["W-GREEN"]


def test_a_tree_pick_is_unchanged_by_any_of_this(client):
    body = pick(client, backdrop="tree").json()

    codes = {d["code"] for d in body["decorations"]}
    assert codes == {"O-RED", "R-RED"}
    assert body["requested"] == sum(count for _category, count in config.AUTO_RECIPES["tree"])


def test_no_backdrop_given_picks_for_a_tree(client):
    assert pick(client).json()["requested"] == pick(client, backdrop="tree").json()["requested"]


def test_an_unknown_backdrop_is_refused(client):
    assert client.get("/api/auto/config?backdrop=ceiling").status_code == 422
    assert pick(client, backdrop="ceiling").status_code == 422
