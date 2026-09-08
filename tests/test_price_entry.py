"""Price entry after picking from the catalogue (issue #27).

Picking a product with no printed size already opens an inline field to type the real one.
Price got no equivalent: noticing an unpriced product mid-pick meant leaving the flow for the
pricing queue. The picker now says whether a picked product has a price, so the same inline
treatment can offer to fill it in — and unlike the size gate, it never blocks Generate, because
a price has never been required to make a picture (CONTEXT.md).
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
    catalog.refresh()
    yield tmp_path
    catalog.refresh()


@pytest.fixture
def local(monkeypatch):
    monkeypatch.setattr(settings, "is_local", lambda request: True)


def add(code, section="baubles", price=""):
    catalog_admin.add_product(code, "80 mm.", section, "2026", png_bytes(), price)


# ---- the picker says whether a picked product has a price ----


def test_picking_an_element_reports_it_has_no_price(client, temp_catalog, fake_rembg):
    add("NOPRICE")
    catalog.refresh()

    body = client.post("/api/element/from-catalog", data={"code": "NOPRICE"}).json()

    assert body["price"] is None


def test_picking_an_element_reports_the_price_it_has(client, temp_catalog, fake_rembg):
    add("PRICED", price="250")
    catalog.refresh()

    body = client.post("/api/element/from-catalog", data={"code": "PRICED"}).json()

    assert body["price"] == 250.0


def test_picking_a_tree_reports_its_price_too(client, temp_catalog, fake_rembg):
    """The tree slot takes a catalogue product the same way, and is just as likely to be the
    unpriced one."""
    add("TREE-1", section="tree", price="1800")
    catalog.refresh()

    body = client.post("/api/tree/from-catalog", data={"code": "TREE-1"}).json()

    assert body["price"] == 1800.0


# ---- typing one in uses the machinery that already exists ----


def test_a_price_typed_after_picking_is_saved(client, temp_catalog, local, fake_rembg):
    add("NOPRICE")
    catalog.refresh()
    assert client.post("/api/element/from-catalog", data={"code": "NOPRICE"}).json()["price"] is None

    saved = client.post("/api/catalog/pricing-queue/NOPRICE/price", data={"price": "120"})

    assert saved.status_code == 200, saved.text
    body = client.post("/api/element/from-catalog", data={"code": "NOPRICE"}).json()
    assert body["price"] == 120.0


def test_a_price_typed_after_picking_survives_a_re_import(client, temp_catalog, local, fake_rembg):
    """It goes through the same overlay write as the pricing queue, so it is durable for the
    same reason (ADR-0001) — this ticket adds a surface, not a second storage path."""
    add("NOPRICE")
    catalog.refresh()
    client.post("/api/catalog/pricing-queue/NOPRICE/price", data={"price": "120"})

    from backend.services import shop_overlay

    assert shop_overlay.fields_for("NOPRICE")["price"] == 120.0
