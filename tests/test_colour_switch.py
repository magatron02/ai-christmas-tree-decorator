"""Switch the colour of an already-picked decoration (issue #15).

A customer's second choice is a colour, not a different product (ADR-0002) — the card for an
accepted decoration offers the product's other colours by name, and choosing one swaps the
picture in place. This covers the one new backend piece: listing a product's colours (image +
name) for the switcher to offer. The swap itself reuses /api/element/from-catalog unchanged —
already precut (issue #13), so no live background removal either way.
"""

import pytest

from backend import config
from backend.services import catalog, catalog_admin
from backend.validation import ValidationError

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
    monkeypatch.setattr(config, "SHOP_PHOTOS_DIR", tmp_path / "data" / "shop_photos")
    catalog.refresh()
    yield tmp_path
    catalog.refresh()


def test_a_split_products_colours_are_listed_with_their_names(client, temp_catalog):
    catalog_admin.add_product("4400-1", "80 mm.", "garland", "2026", png_bytes())
    names = ["4400-1--1.png", "4400-1--2.png", "4400-1--3.png"]
    catalog.set_colour_split("4400-1", names)
    catalog_admin.set_colour_name("4400-1", names[0], "แดง")
    catalog_admin.set_colour_name("4400-1", names[1], "ทอง")
    catalog.refresh()

    response = client.get("/api/catalog/products/4400-1/colours")

    assert response.status_code == 200
    assert response.json() == {
        "colours": [
            {"image": "variants/4400-1--1.png", "name": "แดง"},
            {"image": "variants/4400-1--2.png", "name": "ทอง"},
            {"image": "variants/4400-1--3.png", "name": None},
        ]
    }


def test_a_single_colour_product_returns_exactly_one_entry(client, temp_catalog):
    catalog_admin.add_product("017-06", "80 mm.", "baubles", "2026", png_bytes())

    response = client.get("/api/catalog/products/017-06/colours")

    body = response.json()
    assert len(body["colours"]) == 1
    assert body["colours"][0]["image"] == catalog.image_for("017-06")
    assert body["colours"][0]["name"] is None


def test_an_unknown_code_is_refused(client, temp_catalog):
    response = client.get("/api/catalog/products/99999-9/colours")
    assert response.status_code == 422


def test_an_orphaned_codes_colours_are_refused_here(client, temp_catalog):
    """Unlike set_colour_name (which has to work for an orphan so seeding/correcting never
    stops), this endpoint backs a switcher on a decoration the shop is actively using right
    now — a code the current book has dropped is never something to switch *to* or *within*,
    so catalog.find()'s live-membership gate is correct here, not a bug to route around."""
    import json

    catalog_admin.add_product("4400-1", "80 mm.", "garland", "2026", png_bytes())
    catalog.set_colour_split("4400-1", ["4400-1--1.png", "4400-1--2.png"])
    (temp_catalog / "products.json").write_text(json.dumps([]), encoding="utf-8")
    catalog.refresh()

    response = client.get("/api/catalog/products/4400-1/colours")
    assert response.status_code == 422
