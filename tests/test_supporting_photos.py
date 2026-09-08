"""Several photos per colour, with a main photo for the generator (issue #17).

Staff choosing a product want the back, the detail shot, the one that shows scale. The
generator wants exactly one picture per colour — catalog.variants_of() (what /api/element/
from-catalog validates a pick against) is built from `colours` alone, and a supporting photo
is never part of it.
"""

import io

import pytest

from backend import config
from backend.services import catalog, catalog_admin, settings
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


def add_split(code="DECO-1", names=None):
    names = names or ["DECO-1--1.png", "DECO-1--2.png"]
    catalog_admin.add_product(code, "80 mm.", "baubles", "2026", png_bytes())
    catalog.set_colour_split(code, names)
    catalog.refresh()
    return names


def upload_photo(client, code, main_image):
    files = {"image": ("back.png", io.BytesIO(png_bytes()), "image/png")}
    return client.post(
        f"/api/catalog/products/{code}/photos",
        data={"main_image": main_image},
        files=files,
    )


def test_a_supporting_photo_is_listed_but_is_not_the_main(client, temp_catalog, local):
    names = add_split()
    main = f"variants/{names[0]}"
    response = upload_photo(client, "DECO-1", main)
    assert response.status_code == 200, response.text
    supporting = response.json()["image"]

    colours = client.get("/api/catalog/products/DECO-1/colours").json()["colours"]
    entry = next(c for c in colours if c["image"] == main)

    assert entry["supporting"] == [supporting]
    assert catalog.variants_of("DECO-1") == [main, f"variants/{names[1]}"]


def test_the_generator_only_ever_accepts_the_main_photo(client, temp_catalog, local):
    names = add_split()
    main = f"variants/{names[0]}"
    supporting = upload_photo(client, "DECO-1", main).json()["image"]

    response = client.post(
        "/api/element/from-catalog", data={"code": "DECO-1", "image": supporting}
    )

    assert response.status_code == 404


def test_removing_the_main_promotes_the_first_supporting_photo(client, temp_catalog, local):
    names = add_split()
    main = f"variants/{names[0]}"
    supporting = upload_photo(client, "DECO-1", main).json()["image"]

    response = client.delete("/api/catalog/products/DECO-1/photos", params={"image": main})

    assert response.status_code == 200, response.text
    assert catalog.variants_of("DECO-1") == [supporting, f"variants/{names[1]}"]
    # the promoted photo is now the main — no supporting photos left behind under either key
    colours = client.get("/api/catalog/products/DECO-1/colours").json()["colours"]
    assert colours[0]["image"] == supporting
    assert colours[0]["supporting"] == []


def test_the_promoted_photo_keeps_the_colours_name(client, temp_catalog, local):
    names = add_split()
    main = f"variants/{names[0]}"
    catalog_admin.set_colour_name("DECO-1", main, "แดง")
    supporting = upload_photo(client, "DECO-1", main).json()["image"]

    client.delete("/api/catalog/products/DECO-1/photos", params={"image": main})

    assert catalog.colour_name("DECO-1", supporting) == "แดง"
    assert catalog.colour_name("DECO-1", main) is None


def test_the_shop_can_choose_a_different_main_without_removing_anything(
    client, temp_catalog, local
):
    names = add_split()
    main = f"variants/{names[0]}"
    catalog_admin.set_colour_name("DECO-1", main, "แดง")
    supporting = upload_photo(client, "DECO-1", main).json()["image"]

    response = client.post(
        "/api/catalog/products/DECO-1/main-photo", data={"image": supporting}
    )

    assert response.status_code == 200, response.text
    assert catalog.variants_of("DECO-1") == [supporting, f"variants/{names[1]}"]
    assert catalog.colour_name("DECO-1", supporting) == "แดง"
    # the old main is demoted to supporting, not deleted
    colours = client.get("/api/catalog/products/DECO-1/colours").json()["colours"]
    assert colours[0]["supporting"] == [main]


def test_choosing_the_photo_already_main_is_a_no_op(client, temp_catalog, local):
    names = add_split()
    main = f"variants/{names[0]}"

    response = client.post("/api/catalog/products/DECO-1/main-photo", data={"image": main})

    assert response.status_code == 200
    assert catalog.variants_of("DECO-1") == [main, f"variants/{names[1]}"]


def test_removing_a_colours_only_photo_is_refused(client, temp_catalog, local):
    names = add_split()
    main = f"variants/{names[0]}"

    response = client.delete("/api/catalog/products/DECO-1/photos", params={"image": main})

    assert response.status_code != 200
    assert catalog.variants_of("DECO-1") == [main, f"variants/{names[1]}"]


def test_removing_a_supporting_photo_leaves_the_main_untouched(client, temp_catalog, local):
    names = add_split()
    main = f"variants/{names[0]}"
    supporting = upload_photo(client, "DECO-1", main).json()["image"]

    response = client.delete(
        "/api/catalog/products/DECO-1/photos", params={"image": supporting}
    )

    assert response.status_code == 200, response.text
    assert catalog.variants_of("DECO-1") == [main, f"variants/{names[1]}"]
    colours = client.get("/api/catalog/products/DECO-1/colours").json()["colours"]
    assert colours[0]["supporting"] == []


def test_adding_a_photo_to_a_nonexistent_colour_is_refused(client, temp_catalog, local):
    add_split()
    response = upload_photo(client, "DECO-1", "variants/not-a-real-colour.png")
    assert response.status_code != 200


def test_removing_an_unrelated_image_is_refused(client, temp_catalog, local):
    add_split()
    response = client.delete(
        "/api/catalog/products/DECO-1/photos", params={"image": "variants/not-a-real-file.png"}
    )
    assert response.status_code != 200


def test_photo_endpoints_are_localhost_only(client, temp_catalog, monkeypatch):
    monkeypatch.setattr(settings, "is_local", lambda request: False)
    names = add_split()
    main = f"variants/{names[0]}"

    assert upload_photo(client, "DECO-1", main).status_code == 403
    assert client.delete(
        "/api/catalog/products/DECO-1/photos", params={"image": main}
    ).status_code == 403
    assert client.post(
        "/api/catalog/products/DECO-1/main-photo", data={"image": main}
    ).status_code == 403


def test_direct_functions_reject_an_unknown_code(temp_catalog):
    with pytest.raises(ValidationError):
        catalog_admin.add_supporting_photo("99999-9", "variants/x.png", png_bytes())
    with pytest.raises(ValidationError):
        catalog_admin.remove_photo("99999-9", "variants/x.png")


def test_supporting_photos_are_visible_when_browsing(client, temp_catalog, local):
    """AC: "Supporting photos are visible when browsing and editing the product" — the
    picker's own search results carry them too, not just the editing screen."""
    names = add_split()
    main = f"variants/{names[0]}"
    supporting = upload_photo(client, "DECO-1", main).json()["image"]

    results = client.get("/api/catalog/search?q=DECO-1").json()["results"]

    entry = next(r for r in results if r["image"] == main)
    assert entry["supporting"] == [supporting]
