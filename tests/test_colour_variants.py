"""Colours restored into the overlay, and instant to pick (issue #13).

The colour-split mapping (one code, several colour photos, shot in one frame) used to live in
catalog/variants.json — a base file a book re-import can regenerate out from under it, which
is exactly what happened on 2026-08-19: 264 codes of splits went to nothing, orphaning 919
colour photographs that were still on disk. It now lives in the shop overlay instead, the same
place price and shop photos do, so a re-import cannot repeat that loss.
"""

import json

import pytest

from backend import config, main
from backend.services import catalog, catalog_admin, settings, shop_overlay

from helpers import png_bytes, transparent_png_bytes


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


def reimport(tmp_path, rows):
    (tmp_path / "products.json").write_text(json.dumps(rows), encoding="utf-8")
    catalog.refresh()


def set_split(code, names):
    catalog.set_colour_split(code, names)
    catalog.refresh()


def test_a_colour_split_lives_in_the_overlay(temp_catalog):
    catalog_admin.add_product("4400-1", "80 mm.", "garland", "2026", png_bytes())

    set_split("4400-1", ["4400-1--1.png", "4400-1--2.png", "4400-1--3.png"])

    assert catalog.variants_of("4400-1") == [
        "variants/4400-1--1.png", "variants/4400-1--2.png", "variants/4400-1--3.png",
    ]
    assert shop_overlay.fields_for("4400-1")["colours"] == [
        "4400-1--1.png", "4400-1--2.png", "4400-1--3.png",
    ]


def test_no_base_file_is_involved(temp_catalog):
    """catalog/variants.json is not read at all any more — the overlay is the only source."""
    catalog_admin.add_product("4400-1", "80 mm.", "garland", "2026", png_bytes())
    (temp_catalog / "variants.json").write_text(
        json.dumps({"4400-1": ["ignored--1.png", "ignored--2.png"]}), encoding="utf-8"
    )
    catalog.refresh()

    assert catalog.variants_of("4400-1") == [catalog.image_for("4400-1")]


def test_a_reimport_does_not_lose_the_colour_mapping(temp_catalog):
    """The whole point: a book re-import rewrites products.json wholesale, and the split
    survives it because it was never stored there in the first place."""
    catalog_admin.add_product("4400-1", "80 mm.", "garland", "2026", png_bytes())
    set_split("4400-1", ["4400-1--1.png", "4400-1--2.png"])

    base = json.loads((temp_catalog / "products.json").read_text(encoding="utf-8"))
    reimport(temp_catalog, base)  # same book, printed again

    assert catalog.variants_of("4400-1") == ["variants/4400-1--1.png", "variants/4400-1--2.png"]


def test_a_code_dropped_by_a_reimport_keeps_its_split_as_an_orphan(temp_catalog):
    """Same guarantee ADR-0001 makes for price and photos: dropping a code from the base does
    not delete the shop's overlay work, colour splits included."""
    catalog_admin.add_product("4400-1", "80 mm.", "garland", "2026", png_bytes())
    set_split("4400-1", ["4400-1--1.png", "4400-1--2.png"])

    reimport(temp_catalog, [])  # the next book no longer prints 4400-1

    assert shop_overlay.fields_for("4400-1")["colours"] == ["4400-1--1.png", "4400-1--2.png"]
    orphan = next(o for o in catalog.orphans() if o["code"] == "4400-1")
    assert orphan["colours"] == ["4400-1--1.png", "4400-1--2.png"]


def test_clearing_the_split_reverts_to_the_single_crop(temp_catalog):
    catalog_admin.add_product("4400-1", "80 mm.", "garland", "2026", png_bytes())
    set_split("4400-1", ["4400-1--1.png", "4400-1--2.png"])

    catalog.clear_colour_split("4400-1")
    catalog.refresh()

    assert catalog.variants_of("4400-1") == [catalog.image_for("4400-1")]


def test_the_picker_shows_one_card_per_colour(client, temp_catalog, local):
    catalog_admin.add_product("4400-1", "80 mm.", "garland", "2026", png_bytes())
    set_split("4400-1", ["4400-1--1.png", "4400-1--2.png", "4400-1--3.png"])

    response = client.get("/api/catalog/search")

    results = [r for r in response.json()["results"] if r["code"] == "4400-1"]
    assert len(results) == 3
    assert [r["colour"] for r in results] == [1, 2, 3]
    assert all(r["colours"] == 3 for r in results)


def test_split_codes_lists_every_overlay_split(temp_catalog):
    catalog_admin.add_product("4400-1", "80 mm.", "garland", "2026", png_bytes())
    catalog_admin.add_product("017-06", "80 mm.", "baubles", "2026", png_bytes())
    set_split("4400-1", ["4400-1--1.png", "4400-1--2.png"])

    assert catalog.split_codes() == {"4400-1": ["4400-1--1.png", "4400-1--2.png"]}


def test_choosing_a_colour_is_a_file_read_with_no_live_background_removal(
    client, temp_catalog, local, fake_rembg, monkeypatch
):
    """The whole reason every colour photo is pre-cut at build time: none of the 919 were, and
    a live cut measured at 10s warm, 68s cold — long enough to look like the picker had frozen
    (issue #13). Aligns main.py's own catalogue-images/cutouts constants to this test's
    isolated catalogue, the same way tests/test_precut_catalog.py does against the real one —
    both are bound once at import time and cannot follow config.CATALOG_PATH on their own.
    """
    catalog_admin.add_product("4400-1", "80 mm.", "garland", "2026", png_bytes())
    set_split("4400-1", ["4400-1--1.png", "4400-1--2.png"])
    name = "variants/4400-1--1.png"

    monkeypatch.setattr(main, "CATALOG_IMAGES", temp_catalog / "images")
    monkeypatch.setattr(main, "CATALOG_CUTOUTS", temp_catalog / "cutouts")
    source = temp_catalog / "images" / name
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(png_bytes())  # the endpoint checks the source file exists before precut
    cutout = temp_catalog / "cutouts" / name
    cutout.parent.mkdir(parents=True, exist_ok=True)
    cutout.write_bytes(transparent_png_bytes())

    response = client.post("/api/element/from-catalog", data={"code": "4400-1", "image": name})

    assert response.status_code == 200
    assert fake_rembg.count == 0, "a pre-cut colour photo must not be cut again"
