"""Total retail price of the decorations in one generation.

Unrelated to the OpenAI billing removed by NonGoals #4 — this is the shop's own product
`price` field (pricing queue / settings page), summed across a request's accepted
decorations. Only a fraction of the catalogue carries a price at all, so a decoration with
none must show up as missing rather than being counted as free (the same stance
`scale_sentence` already takes on an unresolved size).
"""

import pytest

from backend import config
from backend.services import catalog, catalog_admin, settings

from helpers import png_bytes, upload


@pytest.fixture
def temp_catalog(tmp_path, monkeypatch):
    products = tmp_path / "products.json"
    products.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(catalog_admin, "PRODUCTS_PATH", products)
    monkeypatch.setattr(catalog_admin, "IMAGES_DIR", tmp_path / "images")
    monkeypatch.setattr(catalog_admin, "PRODUCT_IMAGES_PATH", tmp_path / "product_images.json")
    monkeypatch.setattr(config, "CATALOG_PATH", products)
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "data" / "app.db")
    catalog.refresh()
    yield tmp_path
    catalog.refresh()


@pytest.fixture
def local(monkeypatch):
    monkeypatch.setattr(settings, "is_local", lambda request: True)


# ---------------------------------------------------------------- catalog.decoration_price_total


def test_every_decoration_priced_sums_with_nothing_missing(temp_catalog):
    catalog_admin.add_product("E001", "80 mm.", "ornament", "2026", png_bytes(), price="150")
    catalog_admin.add_product("E002", "40 mm.", "ornament", "2026", png_bytes(), price="99")

    total, missing = catalog.decoration_price_total(["E001", "E002"])

    assert total == 249.0
    assert missing == []


def test_an_unpriced_code_is_excluded_and_reported(temp_catalog):
    catalog_admin.add_product("E001", "80 mm.", "ornament", "2026", png_bytes(), price="150")
    catalog_admin.add_product("E002", "40 mm.", "ornament", "2026", png_bytes())

    total, missing = catalog.decoration_price_total(["E001", "E002"])

    assert total == 150.0
    assert len(missing) == 1
    assert "E002" in missing[0]


def test_a_code_no_longer_in_the_catalogue_is_missing_not_a_crash(temp_catalog):
    total, missing = catalog.decoration_price_total(["GONE-1"])

    assert total == 0.0
    assert missing == ["GONE-1"]


def test_a_codeless_element_is_missing_with_a_plain_label(temp_catalog):
    total, missing = catalog.decoration_price_total([None, ""])

    assert total == 0.0
    assert len(missing) == 2
    assert all("catalogue" in m for m in missing)


# ---------------------------------------------------------------- end-to-end


def cut_out(client, n=1):
    tokens = []
    for _ in range(n):
        response = client.post("/api/remove-bg", files=[upload(png_bytes(), "element.png")])
        assert response.status_code == 200, response.text
        tokens.append(response.json()["element"])
    return tokens


def prepare(client, tokens, **extra):
    return client.post(
        "/api/prepare",
        files=[upload(png_bytes(), "tree.png")],
        data={"element": tokens, "size": "4:5", **extra},
    )


def test_generate_response_carries_the_decoration_price_total(
    client, conn, fake_gen, fake_rembg, temp_catalog
):
    catalog_admin.add_product("TREE1", "150 cm.", "tree", "2026", png_bytes())
    catalog_admin.add_product("E001", "80 mm.", "ornament", "2026", png_bytes(), price="150")
    catalog_admin.add_product("E002", "40 mm.", "ornament", "2026", png_bytes())

    tokens = cut_out(client, 2)
    ready = prepare(client, tokens, tree_code="TREE1", element_code=["E001", "E002"])
    assert ready.status_code == 200, ready.text

    response = client.post(f"/api/generate/{ready.json()['request_id']}")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["price_total"] == 150.0
    assert len(body["price_missing"]) == 1
    assert "E002" in body["price_missing"][0]


def test_history_carries_the_same_price_fields_as_generate(
    client, conn, fake_gen, fake_rembg, temp_catalog
):
    """_row_json is shared between /api/generate and /api/history — this proves it, rather
    than each endpoint computing its own total that could quietly drift apart."""
    catalog_admin.add_product("TREE1", "150 cm.", "tree", "2026", png_bytes())
    catalog_admin.add_product("E001", "80 mm.", "ornament", "2026", png_bytes(), price="150")
    catalog_admin.add_product("E002", "40 mm.", "ornament", "2026", png_bytes())

    tokens = cut_out(client, 2)
    ready = prepare(client, tokens, tree_code="TREE1", element_code=["E001", "E002"])
    request_id = ready.json()["request_id"]
    client.post(f"/api/generate/{request_id}")

    history = client.get("/api/history")

    assert history.status_code == 200, history.text
    row = next(r for r in history.json()["requests"] if r["request_id"] == request_id)
    assert row["price_total"] == 150.0
    assert len(row["price_missing"]) == 1
    assert "E002" in row["price_missing"][0]


def test_row_json_carries_enough_to_resume_a_request_later(
    client, conn, fake_gen, fake_rembg, temp_catalog
):
    """The "จัดการต่อ" flow rebuilds panel 4 from a past request — proving the per-element and
    per-tree price/size/label fields _row_json adds are actually there, not just the totals."""
    catalog_admin.add_product("TREE1", "150 cm.", "tree", "2026", png_bytes(), price="500")
    catalog_admin.add_product("E001", "80 mm.", "ornament", "2026", png_bytes(), price="150")

    tokens = cut_out(client, 1)
    ready = prepare(client, tokens, tree_code="TREE1", element_code=["E001"])
    request_id = ready.json()["request_id"]

    response = client.post(f"/api/generate/{request_id}")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["tree_price"] == 500.0
    assert body["tree_size_mm"] == 1500.0
    assert body["tree_label"] == "TREE1 (150 cm.)"
    element = body["elements"][0]
    assert element["price"] == 150.0
    assert element["size_mm"] == 80.0
    assert element["label"] == "E001 (80 mm.)"


def test_api_request_returns_one_row_by_id(client, conn, fake_gen, fake_rembg, temp_catalog):
    catalog_admin.add_product("TREE1", "150 cm.", "tree", "2026", png_bytes())
    catalog_admin.add_product("E001", "80 mm.", "ornament", "2026", png_bytes(), price="150")

    tokens = cut_out(client, 1)
    ready = prepare(client, tokens, tree_code="TREE1", element_code=["E001"])
    request_id = ready.json()["request_id"]
    client.post(f"/api/generate/{request_id}")

    response = client.get(f"/api/request/{request_id}")

    assert response.status_code == 200, response.text
    assert response.json()["request_id"] == request_id
    assert response.json()["price_total"] == 150.0


def test_api_request_404s_on_an_unknown_id(client, conn, temp_catalog):
    response = client.get("/api/request/does-not-exist")

    assert response.status_code == 404, response.text
