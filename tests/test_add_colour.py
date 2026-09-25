"""Adding a colour or pattern to a code from the settings page (ADR-0002: still one code)."""

import numpy as np
import pytest

from backend import config
from backend.services import catalog, catalog_admin, matching, settings
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


@pytest.fixture
def local(monkeypatch):
    monkeypatch.setattr(settings, "is_local", lambda request: True)


@pytest.fixture
def fake_embed(monkeypatch):
    monkeypatch.setattr(matching, "embed", lambda texts: np.array([[1.0, 0.0]] * len(texts), dtype=np.float32))


def test_first_split_keeps_the_existing_photo_as_colour_one(client, temp_catalog, local):
    catalog_admin.add_product("4400-1", "80 mm.", "garland", "2026", png_bytes())

    response = client.post(
        "/api/catalog/products/4400-1/colours",
        data={"name_th": "ลายจุด", "first_name_th": "สีแดง"},
        files={"image": ("dot.png", png_bytes(color=(200, 0, 0, 255)), "image/png")},
    )

    assert response.status_code == 200
    colours = client.get("/api/catalog/products/4400-1/colours").json()["colours"]
    assert [c["name"] for c in colours] == ["สีแดง", "ลายจุด"]
    results = client.get("/api/catalog/search?q=4400-1").json()["results"]
    assert [r["colour_name"] for r in results] == ["สีแดง", "ลายจุด"]


def test_a_second_colour_appends_without_reseeding(client, temp_catalog, local):
    catalog_admin.add_product("4400-1", "80 mm.", "garland", "2026", png_bytes())
    catalog_admin.add_colour("4400-1", png_bytes(), "แดง")
    catalog_admin.add_colour("4400-1", png_bytes(), "เขียว")

    names = [c["name"] for c in client.get("/api/catalog/products/4400-1/colours").json()["colours"]]

    assert names == [None, "แดง", "เขียว"]


def test_a_colour_needs_a_name(temp_catalog):
    catalog_admin.add_product("4400-1", "80 mm.", "garland", "2026", png_bytes())

    with pytest.raises(ValidationError):
        catalog_admin.add_colour("4400-1", png_bytes(), "  ")


def test_removing_a_colour_drops_its_name_and_file(client, temp_catalog, local):
    catalog_admin.add_product("4400-1", "80 mm.", "garland", "2026", png_bytes())
    catalog_admin.add_colour("4400-1", png_bytes(), "แดง")
    catalog_admin.add_colour("4400-1", png_bytes(), "เขียว")
    red = client.get("/api/catalog/products/4400-1/colours").json()["colours"][1]["image"]

    response = client.delete("/api/catalog/products/4400-1/colours", params={"image": red})

    assert response.status_code == 200
    names = [c["name"] for c in client.get("/api/catalog/products/4400-1/colours").json()["colours"]]
    assert names == [None, "เขียว"]
    assert not (config.SHOP_PHOTOS_DIR / red.removeprefix("/shop-photos/")).exists()


def test_the_last_colour_cannot_be_removed(temp_catalog):
    catalog_admin.add_product("4400-1", "80 mm.", "garland", "2026", png_bytes())
    catalog_admin.add_colour("4400-1", png_bytes(), "แดง")
    catalog_admin.remove_colour("4400-1", catalog.variants_of("4400-1")[1])

    with pytest.raises(ValidationError):
        catalog_admin.remove_colour("4400-1", catalog.variants_of("4400-1")[0])


def test_clearing_returns_the_code_to_its_original_picture(client, temp_catalog, local):
    catalog_admin.add_product("4400-1", "80 mm.", "garland", "2026", png_bytes())
    original = catalog.image_for("4400-1")
    catalog_admin.add_colour("4400-1", png_bytes(color=(200, 0, 0, 255)), "แดง", first_name_th="เดิม")
    catalog_admin.add_colour("4400-1", png_bytes(color=(0, 200, 0, 255)), "เขียว")
    assert len(list(config.SHOP_PHOTOS_DIR.iterdir())) == 3

    response = client.post("/api/catalog/products/4400-1/clear-colours")

    assert response.status_code == 200
    results = client.get("/api/catalog/search?q=4400-1").json()["results"]
    assert [(r["colours"], r["colour_name"]) for r in results] == [(1, None)]
    assert catalog.image_for("4400-1") == original
    assert list(config.SHOP_PHOTOS_DIR.iterdir()) == []


def test_clearing_keeps_a_shop_photo_the_shop_took_itself(temp_catalog, fake_vision, fake_embed):
    catalog_admin.add_product("4400-1", "80 mm.", "garland", "2026", png_bytes())
    catalog_admin.set_shop_photo("4400-1", png_bytes(color=(9, 9, 9, 255)))
    own = catalog.image_for("4400-1")
    catalog_admin.add_colour("4400-1", png_bytes(color=(200, 0, 0, 255)), "แดง")

    catalog_admin.clear_colours("4400-1")

    assert catalog.image_for("4400-1") == own
    assert catalog.resolve_image_path(own).is_file()


def test_a_split_that_changes_the_main_picture_rebuilds_photo_search(temp_catalog, fake_vision, fake_embed):
    catalog_admin.add_product("4400-1", "80 mm.", "garland", "2026", png_bytes())
    catalog_admin.add_colour("4400-1", png_bytes(color=(200, 0, 0, 255)), "แดง")
    assert fake_vision.count == 0  # the seeded first colour is the same picture

    catalog_admin.remove_colour("4400-1", catalog.variants_of("4400-1")[0])

    assert fake_vision.count == 1


def test_clearing_a_plain_code_is_harmless(client, temp_catalog, local):
    catalog_admin.add_product("4400-1", "80 mm.", "garland", "2026", png_bytes())

    assert client.post("/api/catalog/products/4400-1/clear-colours").status_code == 200


def test_colour_writes_are_local_only(client, temp_catalog, monkeypatch):
    monkeypatch.setattr(settings, "is_local", lambda request: False)
    catalog_admin.add_product("4400-1", "80 mm.", "garland", "2026", png_bytes())

    response = client.post(
        "/api/catalog/products/4400-1/colours",
        data={"name_th": "แดง"},
        files={"image": ("a.png", png_bytes(), "image/png")},
    )

    assert response.status_code == 403
