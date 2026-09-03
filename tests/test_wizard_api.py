"""/api/wizard/config and /api/wizard/pick — the budget wizard's own endpoints (wayfinder
map #1). Touches no storage: neither is a `request_log` row or a billed call.
"""

import pytest

from backend import config
from backend.services import catalog

FAKE_ROWS = [
    {"code": "T-150", "section": "tree", "size": {"height_mm": 1500}, "price": 4000.0},
    {"code": "O-RED-CHEAP", "section": "ornament", "size": {"diameter_mm": 80}, "price": 150.0},
    {"code": "O-RED-PRICEY", "section": "ornament", "size": {"diameter_mm": 80}, "price": 5000.0},
    {"code": "O-GREEN-CHEAP", "section": "ornament", "size": {"diameter_mm": 80}, "price": 100.0},
    {"code": "F-CHEAP", "section": "flower", "size": {"diameter_mm": 80}, "price": 50.0},
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


def test_wizard_config_shape(client):
    response = client.get("/api/wizard/config")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["tree_heights"] == [
        {"ft": ft, "mm": round(catalog.feet_to_mm(ft))} for ft in config.WIZARD_TREE_HEIGHTS_FT
    ]
    assert {c["key"] for c in body["categories"]} == set(config.WIZARD_CATEGORIES)
    assert {t["key"] for t in body["tones"]} == set(config.TONE_PRESETS)
    assert isinstance(body["history_counts"], dict)


def test_wizard_config_counts_reflect_the_fake_pool(client):
    body = client.get("/api/wizard/config").json()
    ornament = next(c for c in body["categories"] if c["key"] == "ornament")
    # every priced ornament row counts once regardless of tone (auto_pool with no tone filter)
    assert ornament["count"] == 3
    flower = next(c for c in body["categories"] if c["key"] == "flower")
    assert flower["count"] == 1


def test_pick_full_filter_when_the_pool_is_not_empty(client):
    response = client.post("/api/wizard/pick", data={
        "size_ft": 5, "budget": 200, "category": "ornament", "tone": "redgold",
    })
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["relaxed"] == []
    assert body["tree"]["code"] == "T-150"
    codes = {d["code"] for d in body["decorations"]}
    assert codes == {"O-RED-CHEAP"}
    assert all(d["price"] <= 200 for d in body["decorations"])
    assert all(d["matches_category"] for d in body["decorations"])
    assert all(d["matches_tone"] for d in body["decorations"])


def test_pick_relaxes_tone_first_when_that_pool_is_empty(client):
    # under budget 100, no red ornament exists (the only red one is 5000) — only the tone
    # constraint should be dropped, category and budget both still apply
    response = client.post("/api/wizard/pick", data={
        "size_ft": 5, "budget": 100, "category": "ornament", "tone": "redgold",
    })
    body = response.json()
    codes = {d["code"] for d in body["decorations"]}
    assert "O-GREEN-CHEAP" in codes
    assert body["relaxed"] == ["tone"]
    green = next(d for d in body["decorations"] if d["code"] == "O-GREEN-CHEAP")
    assert green["matches_tone"] is False
    assert green["matches_category"] is True


def test_pick_relaxes_category_too_when_still_empty(client):
    # cheapest ornament is 100; budget 60 clears no ornament at all, but does clear the
    # flower item at 50 — the cascade must fall through to other WIZARD_CATEGORIES
    response = client.post("/api/wizard/pick", data={
        "size_ft": 5, "budget": 60, "category": "ornament", "tone": "redgold",
    })
    body = response.json()
    assert body["relaxed"] == ["tone", "category"]
    codes = {d["code"] for d in body["decorations"]}
    assert codes == {"F-CHEAP"}
    flower = body["decorations"][0]
    assert flower["matches_category"] is False


def test_budget_never_relaxes(client):
    """No candidate at any relax stage may cost more than the budget — that constraint is
    never dropped, per wayfinder ticket #4."""
    response = client.post("/api/wizard/pick", data={
        "size_ft": 5, "budget": 60, "category": "ornament", "tone": "redgold",
    })
    body = response.json()
    for decoration in body["decorations"]:
        assert decoration["price"] <= 60


def test_low_pool_flag_at_the_boundary(client):
    below = client.post("/api/wizard/pick", data={
        "size_ft": 5, "budget": 200, "category": "ornament", "tone": "redgold",
    }).json()
    assert below["pool_size"] == 1
    assert below["low_pool"] is True


def test_pool_size_three_or_more_is_not_low(client, monkeypatch):
    rows = FAKE_ROWS + [
        {"code": f"O-EXTRA-{i}", "section": "ornament", "size": {"diameter_mm": 80}, "price": 100.0}
        for i in range(2)
    ]
    descriptions = dict(FAKE_DESCRIPTIONS)
    for i in range(2):
        descriptions[f"O-EXTRA-{i}"] = {"attributes": {"primary_colour": "red"}}
    monkeypatch.setattr(catalog, "_with_photos", lambda: rows)
    monkeypatch.setattr(catalog, "_descriptions", lambda: descriptions)

    body = client.post("/api/wizard/pick", data={
        "size_ft": 5, "budget": 200, "category": "ornament", "tone": "redgold",
    }).json()
    assert body["pool_size"] == 3
    assert body["low_pool"] is False


def test_unknown_category_is_refused(client):
    response = client.post("/api/wizard/pick", data={
        "size_ft": 5, "budget": 200, "category": "not-a-category", "tone": "redgold",
    })
    assert response.status_code == 422


def test_unknown_tone_is_refused(client):
    response = client.post("/api/wizard/pick", data={
        "size_ft": 5, "budget": 200, "category": "ornament", "tone": "not-a-tone",
    })
    assert response.status_code == 422


def test_exclude_avoids_repeats_where_the_pool_allows_it(client, monkeypatch):
    rows = FAKE_ROWS + [
        {"code": f"O-EXTRA-{i}", "section": "ornament", "size": {"diameter_mm": 80}, "price": 100.0}
        for i in range(3)
    ]
    descriptions = dict(FAKE_DESCRIPTIONS)
    for i in range(3):
        descriptions[f"O-EXTRA-{i}"] = {"attributes": {"primary_colour": "red"}}
    monkeypatch.setattr(catalog, "_with_photos", lambda: rows)
    monkeypatch.setattr(catalog, "_descriptions", lambda: descriptions)

    body = client.post("/api/wizard/pick", data={
        "size_ft": 5, "budget": 200, "category": "ornament", "tone": "redgold",
        "exclude": ["O-RED-CHEAP", "O-EXTRA-0", "O-EXTRA-1"],
    }).json()
    codes = {d["code"] for d in body["decorations"]}
    assert codes == {"O-EXTRA-2"}


# ---------------------------------------------------------------- omitted tone (live count)
# the wizard's single-panel step (ไซส์/งบ/แนว) previews how many decorations match before a
# tone has even been chosen — tone comes later, in its own screen


def test_omitted_tone_pools_by_category_and_budget_only(client):
    body = client.post("/api/wizard/pick", data={
        "size_ft": 5, "budget": 200, "category": "ornament", "tone": "",
    }).json()
    codes = {d["code"] for d in body["decorations"]}
    # both cheap ornaments qualify regardless of colour — no tone was given to filter by
    assert codes == {"O-RED-CHEAP", "O-GREEN-CHEAP"}
    assert body["relaxed"] == []


def test_omitted_tone_leaves_matches_tone_null_not_false(client):
    body = client.post("/api/wizard/pick", data={
        "size_ft": 5, "budget": 200, "category": "ornament", "tone": "",
    }).json()
    assert all(d["matches_tone"] is None for d in body["decorations"])
