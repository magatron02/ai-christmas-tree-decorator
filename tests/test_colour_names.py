"""Thai colour names, seeded once and correctable (issue #14, ADR-0002).

A colour is a named photo of a code, not a code of its own. Names live in the overlay
alongside the colour-split mapping itself (issue #13) — seeded by a one-off vision pass, one
call per photo, correctable by the shop, and never invented for a photo nobody has named yet.
"""

import json

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


def add_split(code="4400-1", names=None):
    names = names or ["4400-1--1.png", "4400-1--2.png", "4400-1--3.png"]
    catalog_admin.add_product(code, "80 mm.", "garland", "2026", png_bytes())
    catalog.set_colour_split(code, names)
    catalog.refresh()
    return names


def reimport(tmp_path, rows):
    (tmp_path / "products.json").write_text(json.dumps(rows), encoding="utf-8")
    catalog.refresh()


def test_an_unnamed_colour_falls_back_to_position(client, temp_catalog, local):
    add_split()

    results = client.get("/api/catalog/search?q=4400-1").json()["results"]

    assert [r["colour_name"] for r in results] == [None, None, None]
    assert [r["colour"] for r in results] == [1, 2, 3]
    assert [r["colours"] for r in results] == [3, 3, 3]


def test_a_named_colour_shows_up_in_search_results(client, temp_catalog, local):
    names = add_split()
    catalog_admin.set_colour_name("4400-1", names[0], "แดง")

    results = client.get("/api/catalog/search?q=4400-1").json()["results"]

    named = next(r for r in results if r["image"] == f"variants/{names[0]}")
    assert named["colour_name"] == "แดง"
    other = next(r for r in results if r["image"] == f"variants/{names[1]}")
    assert other["colour_name"] is None


def test_correcting_one_name_does_not_erase_the_others(client, temp_catalog, local):
    names = add_split()
    catalog_admin.set_colour_name("4400-1", names[0], "แดง")
    catalog_admin.set_colour_name("4400-1", names[1], "ทอง")

    catalog_admin.set_colour_name("4400-1", names[0], "แดงเข้ม")  # correcting the first

    assert catalog.colour_name("4400-1", f"variants/{names[0]}") == "แดงเข้ม"
    assert catalog.colour_name("4400-1", f"variants/{names[1]}") == "ทอง"


def test_a_correction_persists_across_a_reimport(client, temp_catalog, local):
    names = add_split()
    catalog_admin.set_colour_name("4400-1", names[0], "แดง")

    base = json.loads((temp_catalog / "products.json").read_text(encoding="utf-8"))
    reimport(temp_catalog, base)

    assert catalog.colour_name("4400-1", f"variants/{names[0]}") == "แดง"


def test_naming_a_photo_that_is_not_one_of_this_codes_colours_is_refused(temp_catalog):
    add_split()
    with pytest.raises(ValidationError):
        catalog_admin.set_colour_name("4400-1", "not-a-real-file.png", "แดง")


def test_an_orphaned_codes_colours_can_still_be_named(temp_catalog):
    """Regression: set_colour_name used to gate on catalog.find(code), which raises for any
    code the current book has dropped — silently blocking every one of an orphan's colour
    photos from ever being named, the same 146-of-264 restored codes issue #13 kept as
    orphans. A colour split survives being orphaned (issue #9); its names must too, ready for
    a future re-import that brings the code back."""
    names = add_split()
    reimport(temp_catalog, [])  # the next book no longer prints 4400-1 at all

    catalog_admin.set_colour_name("4400-1", names[0], "แดง")

    assert catalog.colour_name("4400-1", f"variants/{names[0]}") == "แดง"
    orphan = next(o for o in catalog.orphans() if o["code"] == "4400-1")
    assert orphan["colour_names"] == {names[0]: "แดง"}


def test_a_blank_name_is_refused(temp_catalog):
    names = add_split()
    with pytest.raises(ValidationError):
        catalog_admin.set_colour_name("4400-1", names[0], "")


def test_an_unknown_code_is_refused(temp_catalog):
    with pytest.raises(ValidationError):
        catalog_admin.set_colour_name("99999-9", "x.png", "แดง")


def test_the_http_seam_sets_a_name(client, temp_catalog, local):
    names = add_split()

    response = client.post(
        "/api/catalog/products/4400-1/colour-name",
        data={"image": f"variants/{names[0]}", "name_th": "แดง"},
    )

    assert response.status_code == 200
    assert response.json() == {"code": "4400-1", "image": f"variants/{names[0]}", "name_th": "แดง"}
    assert catalog.colour_name("4400-1", names[0]) == "แดง"


def test_the_colour_name_endpoint_is_localhost_only(client, temp_catalog, monkeypatch):
    monkeypatch.setattr(settings, "is_local", lambda request: False)
    names = add_split()

    response = client.post(
        "/api/catalog/products/4400-1/colour-name",
        data={"image": f"variants/{names[0]}", "name_th": "แดง"},
    )

    assert response.status_code == 403


def test_the_naming_pass_uses_the_vision_seam_not_real_money(temp_catalog, fake_colour_name):
    """Simulates what scripts/name_colours.py does per photo — vision.name_colour is the seam
    issue #12 introduced and #14 reuses; nothing here reaches the real API."""
    names = add_split()

    from backend.services import vision

    parsed, _usage = vision.name_colour(png_bytes())
    catalog_admin.set_colour_name("4400-1", names[0], parsed.name_th)

    assert fake_colour_name.count == 1
    assert catalog.colour_name("4400-1", names[0]) == "แดง"
