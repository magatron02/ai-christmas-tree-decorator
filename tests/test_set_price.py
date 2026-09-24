"""One product's price, set inline after a catalogue pick (issue #27).

The old fast-entry pricing queue (issue #10) is gone — vendor prices already cover most
unpriced codes, so a separate walk-through screen was asking staff for numbers the app then
ignored. What stays is the single write path the picker's inline price row uses.
"""

import pytest

from backend import config
from backend.services import catalog, catalog_admin, settings, vendor_lookup

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
    vendor_lookup.refresh()
    yield tmp_path
    catalog.refresh()
    vendor_lookup.refresh()


@pytest.fixture
def local(monkeypatch):
    monkeypatch.setattr(settings, "is_local", lambda request: True)


def test_setting_a_price_stores_it(client, temp_catalog, local):
    catalog_admin.add_product("ZZ-TEST-1", "80 mm.", "baubles", "2026", png_bytes())

    response = client.post("/api/catalog/products/ZZ-TEST-1/price", data={"price": "250"})

    assert response.status_code == 200
    assert response.json() == {"code": "ZZ-TEST-1", "price": 250.0}
    # written to the supplier-price overlay, which is what a quote reads first — not the catalogue's
    assert vendor_lookup.price_for("ZZ-TEST-1") == 250.0
    assert catalog.find("ZZ-TEST-1")["price"] is None


def test_a_non_numeric_price_is_refused(client, temp_catalog, local):
    catalog_admin.add_product("ZZ-TEST-1", "80 mm.", "baubles", "2026", png_bytes())

    response = client.post("/api/catalog/products/ZZ-TEST-1/price", data={"price": "แพง"})

    assert response.status_code != 200
    assert vendor_lookup.price_for("ZZ-TEST-1") is None


def test_a_blank_price_is_accepted_and_sets_nothing(client, temp_catalog, local):
    """Regression: Form(...) treats an empty submitted value as missing entirely (a 422, not
    a validation error), the same trap update_product's own price field already avoids by
    defaulting to Form(""). A blank is a legitimate no-op, not a malformed request."""
    catalog_admin.add_product("ZZ-TEST-1", "80 mm.", "baubles", "2026", png_bytes())

    response = client.post("/api/catalog/products/ZZ-TEST-1/price", data={"price": ""})

    assert response.status_code == 200
    assert vendor_lookup.price_for("ZZ-TEST-1") is None


def test_an_unknown_code_is_refused(client, temp_catalog, local):
    response = client.post("/api/catalog/products/99999-9/price", data={"price": "10"})
    assert response.status_code != 200


def test_the_endpoint_is_localhost_only(client, temp_catalog, monkeypatch):
    monkeypatch.setattr(settings, "is_local", lambda request: False)
    catalog_admin.add_product("ZZ-TEST-1", "80 mm.", "baubles", "2026", png_bytes())

    assert client.post(
        "/api/catalog/products/ZZ-TEST-1/price", data={"price": "10"}
    ).status_code == 403


def test_an_unpriced_product_is_still_selectable_by_auto_pick(temp_catalog):
    """ADR-0003: auto_pool never consults price. A regression here would quietly shrink the
    pool auto pick draws from, the way the old budget ceiling once did."""
    catalog_admin.add_product("ZZ-TEST-1", "80 mm.", "baubles", "2026", png_bytes())
    row = catalog.find("ZZ-TEST-1")

    pool = catalog.auto_pool(catalog.category_of(row), None)

    assert any(r["code"] == "ZZ-TEST-1" for r in pool)
