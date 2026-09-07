"""The pricing queue: fast entry through the 638-of-829 unpriced products (issue #10).

A dedicated fast-entry mode, separate from the full edit screen — photo, code, one price
field, next. A product marked skipped for pricing leaves the queue for good but stays fully
usable everywhere else, including auto pick (ADR-0003 already excludes price from that pool).
"""

import pytest

from backend import config
from backend.services import catalog, catalog_admin, settings

from helpers import png_bytes


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


def test_an_unpriced_showable_product_appears_in_the_queue(temp_catalog):
    catalog_admin.add_product("017-06", "80 mm.", "baubles", "2026", png_bytes())

    queue = catalog.pricing_queue()

    assert [row["code"] for row in queue] == ["017-06"]


def test_a_priced_product_does_not_appear_in_the_queue(temp_catalog):
    catalog_admin.add_product("017-06", "80 mm.", "baubles", "2026", png_bytes(), price="99")

    assert catalog.pricing_queue() == []


def test_entering_a_price_through_the_http_seam_stores_it_and_leaves_the_queue(
    client, temp_catalog, local
):
    catalog_admin.add_product("017-06", "80 mm.", "baubles", "2026", png_bytes())

    response = client.post("/api/catalog/pricing-queue/017-06/price", data={"price": "250"})

    assert response.status_code == 200
    assert response.json() == {"code": "017-06", "price": 250.0}
    assert catalog.find("017-06")["price"] == 250.0
    assert catalog.pricing_queue() == []


def test_a_non_numeric_price_through_the_queue_is_refused(client, temp_catalog, local):
    catalog_admin.add_product("017-06", "80 mm.", "baubles", "2026", png_bytes())

    response = client.post("/api/catalog/pricing-queue/017-06/price", data={"price": "แพง"})

    assert response.status_code != 200
    assert catalog.pricing_queue() != []


def test_skipping_a_product_removes_it_from_the_queue_permanently(client, temp_catalog, local):
    catalog_admin.add_product("017-06", "80 mm.", "baubles", "2026", png_bytes())

    response = client.post("/api/catalog/pricing-queue/017-06/skip")

    assert response.status_code == 200
    assert catalog.pricing_queue() == []


def test_a_skipped_product_still_has_no_price_but_stays_fully_usable(
    client, temp_catalog, local
):
    catalog_admin.add_product("017-06", "80 mm.", "baubles", "2026", png_bytes())
    client.post("/api/catalog/pricing-queue/017-06/skip")

    row = catalog.find("017-06")
    assert row["price"] is None
    assert any(r["code"] == "017-06" for r in catalog.auto_pool(catalog.category_of(row), None))
    rows, _total = catalog.browse(limit=1000)
    assert any(r["code"] == "017-06" for r in rows)


def test_the_queue_endpoint_reports_how_many_remain_and_reaches_zero(
    client, temp_catalog, local
):
    catalog_admin.add_product("017-06", "80 mm.", "baubles", "2026", png_bytes())
    catalog_admin.add_product("099-01", "40 mm.", "baubles", "2026", png_bytes())

    first = client.get("/api/catalog/pricing-queue").json()
    assert first["remaining"] == 2
    assert first["next"]["code"] in ("017-06", "099-01")

    client.post(f"/api/catalog/pricing-queue/{first['next']['code']}/price", data={"price": "10"})
    second = client.get("/api/catalog/pricing-queue").json()
    assert second["remaining"] == 1

    client.post(f"/api/catalog/pricing-queue/{second['next']['code']}/skip")
    empty = client.get("/api/catalog/pricing-queue").json()
    assert empty["remaining"] == 0
    assert empty["next"] is None


def test_an_unpriced_product_is_still_selectable_by_auto_pick(temp_catalog):
    """ADR-0003: auto_pool never consults price. A regression here would quietly shrink the
    pool auto pick draws from, the way the old budget ceiling once did."""
    catalog_admin.add_product("017-06", "80 mm.", "baubles", "2026", png_bytes())
    row = catalog.find("017-06")

    pool = catalog.auto_pool(catalog.category_of(row), None)

    assert any(r["code"] == "017-06" for r in pool)


def test_a_blank_price_through_the_queue_is_accepted_and_clears_no_opinion(
    client, temp_catalog, local
):
    """Regression: Form(...) treats an empty submitted value as missing entirely (a 422, not
    a validation error), the same trap update_product's own price field already avoids by
    defaulting to Form(""). A blank here is a legitimate no-op — the product just stays in
    the queue — not a malformed request."""
    catalog_admin.add_product("017-06", "80 mm.", "baubles", "2026", png_bytes())

    response = client.post("/api/catalog/pricing-queue/017-06/price", data={"price": ""})

    assert response.status_code == 200
    assert catalog.find("017-06")["price"] is None
    assert catalog.pricing_queue() != []


def test_a_product_with_an_unknown_code_is_refused(client, temp_catalog, local):
    response = client.post("/api/catalog/pricing-queue/99999-9/price", data={"price": "10"})
    assert response.status_code != 200


def test_the_queue_endpoints_are_localhost_only(client, temp_catalog, monkeypatch):
    monkeypatch.setattr(settings, "is_local", lambda request: False)
    catalog_admin.add_product("017-06", "80 mm.", "baubles", "2026", png_bytes())

    assert client.post(
        "/api/catalog/pricing-queue/017-06/price", data={"price": "10"}
    ).status_code == 403
    assert client.post("/api/catalog/pricing-queue/017-06/skip").status_code == 403
