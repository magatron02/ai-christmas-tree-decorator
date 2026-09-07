"""A shop photo supersedes the book photo (issue #12).

Uploading one makes it the picture shown everywhere, un-hides a product that was hidden for a
bad book crop, and re-runs the product's search description/embedding automatically — through
the vision test seam this ticket introduces, so none of this spends real money. The book photo
is never touched; removing the shop photo falls back to it.
"""

import io
import json

import numpy as np
import pytest

from backend import config
from backend.services import catalog, catalog_admin, matching, settings, shop_overlay
from backend.validation import ValidationError

from helpers import jpeg_bytes, png_bytes


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
    """This module's own catalogue is tiny and disposable — no real vectors to answer with,
    unlike test_matching.py's fixture of the same name, so a fixed deterministic vector is
    enough."""
    def stub(texts):
        return np.array([[1.0, 0.0]] * len(texts), dtype=np.float32)

    monkeypatch.setattr(matching, "embed", stub)
    return stub


def upload_photo(client, code, data=None):
    files = {"image": ("shop.png", io.BytesIO(data or png_bytes()), "image/png")}
    return client.post(f"/api/catalog/products/{code}/photo", files=files)


def make_ambiguous(temp_catalog, code):
    """Simulates a crop shared by too many codes to identify any of them — the "bad crop"
    state a shop photo is supposed to lift a code out of."""
    images = json.loads((temp_catalog / "product_images.json").read_text(encoding="utf-8"))
    for row in images:
        if row["code"] == code:
            row["shared_with"] = 5
    (temp_catalog / "product_images.json").write_text(
        json.dumps(images, ensure_ascii=False), encoding="utf-8"
    )
    catalog.refresh()


def test_uploading_a_shop_photo_becomes_the_picture_shown_everywhere(
    client, temp_catalog, local, fake_vision, fake_embed
):
    catalog_admin.add_product("017-06", "80 mm.", "baubles", "2026", png_bytes())

    response = upload_photo(client, "017-06")

    assert response.status_code == 200
    assert catalog.image_for("017-06").startswith("/shop-photos/")
    assert catalog.image_path("017-06").is_file()
    assert catalog.product_detail(catalog.find("017-06"))["image"] == catalog.image_for("017-06")


def test_a_bad_crop_code_appears_in_the_picker_once_photographed(
    client, temp_catalog, local, fake_vision, fake_embed
):
    catalog_admin.add_product("017-06", "80 mm.", "baubles", "2026", png_bytes())
    make_ambiguous(temp_catalog, "017-06")
    assert catalog.crop_is_showable("017-06") is False

    upload_photo(client, "017-06")

    assert catalog.crop_is_showable("017-06") is True
    rows, _total = catalog.browse(limit=1000)
    assert any(r["code"] == "017-06" for r in rows)


def test_uploading_refreshes_description_and_embedding_without_a_sync_click(
    client, temp_catalog, local, fake_vision, fake_embed
):
    catalog_admin.add_product("017-06", "80 mm.", "baubles", "2026", png_bytes())

    upload_photo(client, "017-06")

    assert fake_vision.count == 1
    descriptions = json.loads((temp_catalog / "descriptions.json").read_text(encoding="utf-8"))
    assert descriptions["017-06"]["match"] == "shop_photo"
    assert descriptions["017-06"]["text"]
    assert not descriptions["017-06"].get("error")

    codes = json.loads((temp_catalog / "embedding_codes.json").read_text(encoding="utf-8"))
    assert "017-06" in codes


def test_a_failed_description_does_not_block_the_photo_upload(
    client, temp_catalog, local, fake_embed, monkeypatch
):
    from backend.services import vision

    def raises(*args, **kwargs):
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(vision, "describe_catalogue_photo", raises)
    catalog_admin.add_product("017-06", "80 mm.", "baubles", "2026", png_bytes())

    response = upload_photo(client, "017-06")

    assert response.status_code == 200
    assert catalog.image_for("017-06").startswith("/shop-photos/")
    descriptions = json.loads((temp_catalog / "descriptions.json").read_text(encoding="utf-8"))
    assert "error" in descriptions["017-06"]


def test_removing_the_shop_photo_falls_back_to_the_book_photo(
    client, temp_catalog, local, fake_vision, fake_embed
):
    catalog_admin.add_product("017-06", "80 mm.", "baubles", "2026", png_bytes())
    book_image = catalog.image_for("017-06")
    upload_photo(client, "017-06")
    assert catalog.image_for("017-06") != book_image

    response = client.delete("/api/catalog/products/017-06/photo")

    assert response.status_code == 200
    assert catalog.image_for("017-06") == book_image
    assert catalog.image_path("017-06").is_file()


def test_removing_the_shop_photo_deletes_the_uploaded_file(
    client, temp_catalog, local, fake_vision, fake_embed
):
    catalog_admin.add_product("017-06", "80 mm.", "baubles", "2026", png_bytes())
    upload_photo(client, "017-06")
    shop_path = catalog.image_path("017-06")
    assert shop_path.is_file()

    client.delete("/api/catalog/products/017-06/photo")

    assert not shop_path.is_file()


def test_removing_a_photo_that_was_never_uploaded_is_a_harmless_no_op(
    client, temp_catalog, local
):
    catalog_admin.add_product("017-06", "80 mm.", "baubles", "2026", png_bytes())

    response = client.delete("/api/catalog/products/017-06/photo")

    assert response.status_code == 200


def test_the_shop_photo_lives_under_data_not_catalog(
    client, temp_catalog, local, fake_vision, fake_embed
):
    catalog_admin.add_product("017-06", "80 mm.", "baubles", "2026", png_bytes())

    upload_photo(client, "017-06")

    shop_path = catalog.image_path("017-06")
    assert shop_path.parent == config.SHOP_PHOTOS_DIR
    assert shop_path.parent == config.DATA_DIR / "shop_photos"
    assert shop_path.parent != config.CATALOG_PATH.parent / "images"


def test_a_jpeg_shop_photo_is_saved_and_described_as_the_jpeg_it_actually_is(
    client, temp_catalog, local, fake_vision, fake_embed
):
    """Regression: the upload was always saved as <code>.png regardless of its real format,
    and described to the vision model as image/png regardless too — silently breaking search
    for the realistic case of a phone photo, which is JPEG far more often than not."""
    catalog_admin.add_product("017-06", "80 mm.", "baubles", "2026", png_bytes())

    files = {"image": ("shop.jpg", io.BytesIO(jpeg_bytes()), "image/jpeg")}
    response = client.post("/api/catalog/products/017-06/photo", files=files)

    assert response.status_code == 200
    assert catalog.image_path("017-06").suffix == ".jpg"
    assert fake_vision.calls[0][1]["mime"] == "image/jpeg"
    descriptions = json.loads((temp_catalog / "descriptions.json").read_text(encoding="utf-8"))
    assert not descriptions["017-06"].get("error")


def test_a_colour_split_code_refuses_a_shop_photo(client, temp_catalog, local):
    catalog_admin.add_product("017-06", "80 mm.", "baubles", "2026", png_bytes())
    (temp_catalog / "variants.json").write_text(
        json.dumps({"017-06": ["017-06--1.png", "017-06--2.png"]}), encoding="utf-8"
    )
    catalog.refresh()

    with pytest.raises(ValidationError):
        catalog_admin.set_shop_photo("017-06", png_bytes())


def test_an_unknown_code_is_refused(temp_catalog):
    with pytest.raises(ValidationError):
        catalog_admin.set_shop_photo("99999-9", png_bytes())


def test_shop_photo_upload_is_localhost_only(client, temp_catalog, monkeypatch):
    monkeypatch.setattr(settings, "is_local", lambda request: False)
    catalog_admin.add_product("017-06", "80 mm.", "baubles", "2026", png_bytes())

    assert upload_photo(client, "017-06").status_code == 403
    assert client.delete("/api/catalog/products/017-06/photo").status_code == 403


def test_product_detail_reports_whether_a_shop_photo_is_set(
    client, temp_catalog, local, fake_vision, fake_embed
):
    catalog_admin.add_product("017-06", "80 mm.", "baubles", "2026", png_bytes())
    assert catalog.product_detail(catalog.find("017-06"))["has_shop_photo"] is False

    upload_photo(client, "017-06")

    assert catalog.product_detail(catalog.find("017-06"))["has_shop_photo"] is True
