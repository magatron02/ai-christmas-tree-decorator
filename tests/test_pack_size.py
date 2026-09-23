"""Some products sell by the pack, not the piece (issue #25).

The app already says how many pieces of a product a tree takes. A shop reading that still has
to divide by the pack size before it means anything they can order, so a product that carries
one now says both.
"""

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
    catalog.refresh()
    yield tmp_path
    catalog.refresh()


@pytest.fixture
def local(monkeypatch):
    monkeypatch.setattr(settings, "is_local", lambda request: True)


def add(code, size_raw="80 mm.", section="baubles"):
    catalog_admin.add_product(code, size_raw, section, "2026", png_bytes())


# ---- the conversion ----


def test_a_product_with_no_pack_size_reports_pieces_only(temp_catalog):
    add("LOOSE")
    catalog.refresh()

    assert catalog.packs_for("LOOSE", 10) is None


def test_pieces_become_packs_rounded_up(temp_catalog):
    """Nobody sells two thirds of a box: 10 pieces out of a pack of 6 is two packs."""
    add("BOXED")
    catalog_admin.set_pack_size("BOXED", 6)
    catalog.refresh()

    assert catalog.packs_for("BOXED", 10) == {"packs": 2, "pack_size": 6}


def test_an_exact_multiple_is_not_rounded_past(temp_catalog):
    add("BOXED")
    catalog_admin.set_pack_size("BOXED", 6)
    catalog.refresh()

    assert catalog.packs_for("BOXED", 12)["packs"] == 2


def test_fewer_pieces_than_one_pack_is_still_a_pack(temp_catalog):
    add("BOXED")
    catalog_admin.set_pack_size("BOXED", 6)
    catalog.refresh()

    assert catalog.packs_for("BOXED", 1)["packs"] == 1


# ---- the shop sets and corrects it ----


def test_the_shop_can_set_and_correct_a_pack_size(client, temp_catalog, local):
    add("BOXED")
    catalog.refresh()

    client.post("/api/catalog/products/BOXED/pack-size", data={"pack_size": "6"})
    assert catalog.find("BOXED")["pack_size"] == 6

    client.post("/api/catalog/products/BOXED/pack-size", data={"pack_size": "12"})
    assert catalog.find("BOXED")["pack_size"] == 12


def test_setting_a_pack_size_leaves_the_rest_of_the_product_alone(client, temp_catalog, local):
    """Its own endpoint, because update_product diffs every field against the book and would
    read a form carrying only a pack size as "clear the size, section and book as well"."""
    add("BOXED", "80 mm.", "baubles")
    catalog.refresh()

    client.post("/api/catalog/products/BOXED/pack-size", data={"pack_size": "6"})

    row = catalog.find("BOXED")
    assert row["size_raw"] == "80 mm."
    assert row["section"] == "baubles"


def test_the_endpoint_is_localhost_only(client, temp_catalog, monkeypatch):
    monkeypatch.setattr(settings, "is_local", lambda request: False)
    add("BOXED")
    catalog.refresh()

    response = client.post("/api/catalog/products/BOXED/pack-size", data={"pack_size": "6"})

    assert response.status_code == 403


def test_clearing_a_pack_size_puts_the_product_back_to_pieces(temp_catalog):
    add("BOXED")
    catalog_admin.set_pack_size("BOXED", 6)
    catalog.refresh()

    catalog_admin.set_pack_size("BOXED", None)
    catalog.refresh()

    assert catalog.packs_for("BOXED", 10) is None


def test_a_pack_size_shows_as_the_shops_own_opinion(client, temp_catalog, local):
    """It is a shop fact like a price, so the find-and-correct screen badges it the same way
    and it survives a re-import (ADR-0001)."""
    add("BOXED")
    catalog_admin.set_pack_size("BOXED", 6)
    catalog.refresh()

    detail = client.get("/api/catalog/products/BOXED").json()

    assert detail["pack_size"] == 6
    assert "pack_size" in detail["overridden"]


def test_a_pack_size_of_one_is_refused(temp_catalog):
    """A pack of one is a piece — recording it would put "1 แพ็ค (แพ็คละ 1)" on every line for
    nothing."""
    add("BOXED")
    with pytest.raises(ValidationError):
        catalog_admin.set_pack_size("BOXED", 1)


def test_a_pack_size_below_one_is_refused(temp_catalog):
    add("BOXED")
    for bad in (0, -3):
        with pytest.raises(ValidationError):
            catalog_admin.set_pack_size("BOXED", bad)


def test_a_pack_size_that_is_not_a_number_is_refused(temp_catalog):
    add("BOXED")
    with pytest.raises(ValidationError):
        catalog_admin.set_pack_size("BOXED", "หกชิ้น")


def test_packs_for_a_code_the_catalogue_no_longer_has(temp_catalog):
    """A finished run outlives the rows it was made from — an orphaned code is sold loose as
    far as this is concerned, rather than an error."""
    assert catalog.packs_for("GONE-FOREVER", 10) is None


# ---- what a finished generation reports ----


def test_a_finished_run_reports_packs_for_a_packed_product(client, temp_catalog, conn, local,
                                                           fake_gen, fake_rembg):
    from helpers import upload

    add("TREE-1", "5 Ft.", "tree")
    add("BOXED")
    catalog_admin.set_pack_size("BOXED", 6)
    catalog.refresh()

    cut = client.post("/api/remove-bg", files=[upload(png_bytes(), "element.png")]).json()["element"]
    prepared = client.post(
        "/api/prepare",
        files=[upload(png_bytes(), "tree.png")],
        data={"element": cut, "size": "4:5", "tree_code": "TREE-1", "element_code": "BOXED"},
    ).json()

    body = client.post(f"/api/generate/{prepared['request_id']}").json()

    item = next(e for e in body["elements"] if e["code"] == "BOXED")
    assert item["quantity"]["low"] >= 1
    assert item["packs"]["pack_size"] == 6
    # the pack count covers the pieces the estimate asks for
    assert item["packs"]["low"] * 6 >= item["quantity"]["low"]
    assert item["packs"]["high"] * 6 >= item["quantity"]["high"]


def test_a_loose_product_reports_no_packs(client, temp_catalog, conn, local, fake_gen, fake_rembg):
    from helpers import upload

    add("TREE-1", "5 Ft.", "tree")
    add("LOOSE")
    catalog.refresh()

    cut = client.post("/api/remove-bg", files=[upload(png_bytes(), "element.png")]).json()["element"]
    prepared = client.post(
        "/api/prepare",
        files=[upload(png_bytes(), "tree.png")],
        data={"element": cut, "size": "4:5", "tree_code": "TREE-1", "element_code": "LOOSE"},
    ).json()

    body = client.post(f"/api/generate/{prepared['request_id']}").json()

    item = next(e for e in body["elements"] if e["code"] == "LOOSE")
    assert item["packs"] is None
    assert item["quantity"] is not None  # pieces still reported, exactly as before


def test_an_uncoded_item_reports_neither(client, temp_catalog, conn, local, fake_gen, fake_rembg):
    from helpers import upload

    cut = client.post("/api/remove-bg", files=[upload(png_bytes(), "element.png")]).json()["element"]
    prepared = client.post(
        "/api/prepare", files=[upload(png_bytes(), "tree.png")], data={"element": cut, "size": "4:5"},
    ).json()

    body = client.post(f"/api/generate/{prepared['request_id']}").json()

    assert body["elements"][0]["quantity"] is None
    assert body["elements"][0]["packs"] is None
