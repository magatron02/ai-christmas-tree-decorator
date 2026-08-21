"""Catalogue admin: hand-added products, and editing them.

Everything here runs against an isolated temp catalogue, not the real ~1,092-row one —
catalog_admin's write paths bind from config.CATALOG_PATH at import time, so a test calling
add_product/update_product against the real path would mutate real data on disk.
"""

import json

import pytest

from backend import config
from backend.services import catalog, catalog_admin, settings
from backend.validation import ValidationError

from helpers import png_bytes


@pytest.fixture
def temp_catalog(tmp_path, monkeypatch):
    """Points catalog_admin's write paths, and catalog.py's read path, at an empty temp
    catalogue.

    catalog.py's lru_caches are process-global (maxsize=1, no arguments) — refresh() has to
    run on teardown too, or whichever test in test_catalog.py runs next would see this tiny
    temp dataset instead of the real catalogue.
    """
    products = tmp_path / "products.json"
    products.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(catalog_admin, "PRODUCTS_PATH", products)
    monkeypatch.setattr(catalog_admin, "IMAGES_DIR", tmp_path / "images")
    monkeypatch.setattr(catalog_admin, "PRODUCT_IMAGES_PATH", tmp_path / "product_images.json")
    monkeypatch.setattr(config, "CATALOG_PATH", products)
    catalog.refresh()
    yield tmp_path
    catalog.refresh()


def test_add_records_shared_with_like_the_pdf_pipeline_does(temp_catalog):
    """Regression: add_product's images.json entry used to omit shared_with entirely, so
    test_product_index.py's "every image row is counted" guarantee silently didn't hold for
    manual products — only caught once a real batch of them existed outside a temp catalogue."""
    catalog_admin.add_product("017-06", "80 mm.", "", "", png_bytes())
    images = json.loads((temp_catalog / "product_images.json").read_text(encoding="utf-8"))
    row = next(r for r in images if r["code"] == "017-06")
    assert row["shared_with"] == 0


def test_edit_updates_fields(temp_catalog):
    catalog_admin.add_product("017-06", "80 mm.", "baubles", "2026", png_bytes())
    catalog_admin.update_product("017-06", "90 mm.", "ornaments", "2027")
    row = catalog.find("017-06")
    assert row["size_raw"] == "90 mm."
    assert row["section"] == "ornaments"
    assert row["book"] == "2027"


def test_edit_with_a_new_photo_overwrites_the_file(temp_catalog):
    catalog_admin.add_product("017-06", "80 mm.", "", "", png_bytes(color=(10, 10, 10, 255)))
    original = (temp_catalog / "images" / "017-06.png").read_bytes()

    catalog_admin.update_product("017-06", "80 mm.", "", "", png_bytes(color=(250, 250, 250, 255)))
    updated = (temp_catalog / "images" / "017-06.png").read_bytes()

    assert updated != original


def test_edit_without_a_photo_leaves_the_image_untouched(temp_catalog):
    catalog_admin.add_product("017-06", "80 mm.", "", "", png_bytes())
    before = (temp_catalog / "images" / "017-06.png").read_bytes()

    catalog_admin.update_product("017-06", "90 mm.", "", "")
    after = (temp_catalog / "images" / "017-06.png").read_bytes()

    assert after == before


def test_an_unknown_code_is_refused():
    with pytest.raises(ValidationError) as caught:
        catalog_admin.update_product("99999-9", "80 mm.", "", "")
    assert "ไม่พบรหัส" in str(caught.value)


def test_a_variant_split_codes_photo_edit_is_refused(temp_catalog):
    """variants_of() always prefers the colour-split list over a single crop, so a lone new
    photo would never be shown — refusing this is the whole point of the check."""
    catalog_admin.add_product("017-06", "80 mm.", "", "", png_bytes())
    (temp_catalog / "variants.json").write_text(
        json.dumps({"017-06": ["017-06--1.png", "017-06--2.png"]}), encoding="utf-8"
    )
    catalog.refresh()

    with pytest.raises(ValidationError) as caught:
        catalog_admin.update_product("017-06", "80 mm.", "", "", png_bytes())
    assert "แยกเป็นหลายสี" in str(caught.value)

    # the field-only edit path is still fine for a variant-split code
    catalog_admin.update_product("017-06", "90 mm.", "", "")
    assert catalog.find("017-06")["size_raw"] == "90 mm."


def test_refresh_actually_clears_contested_codes(temp_catalog):
    """Regression: _contested_codes.cache_clear() used to sit outside refresh()'s body (an
    indentation slip), so it only ever ran once at import time."""
    assert catalog.code_is_contested("017-06") is False  # caches _contested_codes() as {}

    (temp_catalog / "book_conflicts.json").write_text(
        json.dumps([{"code": "017-06", "book": "2026", "pdf_page": 1,
                     "section": None, "size_raw": None}]),
        encoding="utf-8",
    )
    catalog.refresh()

    assert catalog.code_is_contested("017-06") is True


def test_refresh_actually_clears_variants(temp_catalog):
    """Regression: _variants() had no cache_clear() call anywhere, so it was never
    invalidated at runtime at all."""
    assert catalog.variants_of("017-06") == []  # caches _variants() as {}

    catalog_admin.add_product("017-06", "80 mm.", "", "", png_bytes())
    (temp_catalog / "variants.json").write_text(
        json.dumps({"017-06": ["017-06--1.png", "017-06--2.png"]}), encoding="utf-8"
    )
    catalog.refresh()

    assert catalog.variants_of("017-06") == ["variants/017-06--1.png", "variants/017-06--2.png"]


def test_a_lowercase_typed_code_is_stored_uppercase_and_findable(temp_catalog):
    """Regression: add_product used to store the code exactly as typed, but find() always
    uppercases its query first — a lowercase-typed code was silently unfindable."""
    catalog_admin.add_product("017-06a", "80 mm.", "", "", png_bytes())
    assert catalog.find("017-06a")["code"] == "017-06A"
    assert catalog.find("017-06A")["code"] == "017-06A"


def test_recent_endpoint_includes_section(client, temp_catalog, monkeypatch):
    """Regression: /api/catalog/recent used to omit "section" entirely, so the edit form
    that pre-fills from this response silently blanked it — and would have overwritten a
    real section with an empty string the moment someone saved an edit."""
    monkeypatch.setattr(settings, "is_local", lambda request: True)
    catalog_admin.add_product("017-06", "80 mm.", "baubles", "2026", png_bytes())

    response = client.get("/api/catalog/recent")

    assert response.status_code == 200
    row = next(r for r in response.json()["results"] if r["code"] == "017-06")
    assert row["section"] == "baubles"


def test_the_edit_endpoint_works_end_to_end(client, temp_catalog, monkeypatch):
    monkeypatch.setattr(settings, "is_local", lambda request: True)
    catalog_admin.add_product("017-06", "80 mm.", "baubles", "2026", png_bytes())

    response = client.post(
        "/api/catalog/products/017-06",
        data={"size_raw": "90 mm.", "section": "ornaments", "book": "2027"},
    )

    assert response.status_code == 200
    assert catalog.find("017-06")["size_raw"] == "90 mm."
    assert catalog.find("017-06")["section"] == "ornaments"


def test_the_edit_endpoint_is_localhost_only(client, temp_catalog, monkeypatch):
    monkeypatch.setattr(settings, "is_local", lambda request: False)
    catalog_admin.add_product("017-06", "80 mm.", "", "", png_bytes())

    response = client.post(
        "/api/catalog/products/017-06",
        data={"size_raw": "90 mm.", "section": "", "book": ""},
    )

    assert response.status_code == 403


# ---- size_raw feeds catalog.parse_size(), same as the PDF pipeline ------------------------


def test_add_parses_size_raw_into_the_structured_size(temp_catalog):
    """A hand-added product used to get size: None unconditionally, which meant
    require_size() always refused it — exact-scale math was never reachable for anything
    typed in through the settings page."""
    catalog_admin.add_product("017-06", "80 mm.", "", "", png_bytes())
    row = catalog.find("017-06")
    assert row["size"] == {"diameter_mm": 80.0, "unit_printed": "mm"}
    assert catalog.longest_side_mm(row) == 80.0


def test_edit_reparses_size_raw_when_it_changes(temp_catalog):
    catalog_admin.add_product("017-06", "80 mm.", "", "", png_bytes())
    catalog_admin.update_product("017-06", "5 Ft.", "", "")
    row = catalog.find("017-06")
    assert row["size"]["height_mm"] == 1524


def test_an_unparseable_size_raw_leaves_size_null_not_a_guess(temp_catalog):
    catalog_admin.add_product("017-06", "large-ish", "", "", png_bytes())
    assert catalog.find("017-06")["size"] is None


# ---- price: optional, numeric, never invented -----------------------------------------


def test_add_stores_a_price(temp_catalog):
    catalog_admin.add_product("017-06", "80 mm.", "", "", png_bytes(), price="350")
    assert catalog.find("017-06")["price"] == 350.0


def test_a_blank_price_stays_unset_rather_than_zero(temp_catalog):
    catalog_admin.add_product("017-06", "80 mm.", "", "", png_bytes(), price="")
    assert catalog.find("017-06")["price"] is None


def test_a_non_numeric_price_is_refused(temp_catalog):
    with pytest.raises(ValidationError):
        catalog_admin.add_product("017-06", "80 mm.", "", "", png_bytes(), price="cheap")


def test_a_negative_price_is_refused(temp_catalog):
    with pytest.raises(ValidationError):
        catalog_admin.add_product("017-06", "80 mm.", "", "", png_bytes(), price="-5")


def test_edit_updates_the_price(temp_catalog):
    catalog_admin.add_product("017-06", "80 mm.", "", "", png_bytes(), price="350")
    catalog_admin.update_product("017-06", "80 mm.", "", "", price="400")
    assert catalog.find("017-06")["price"] == 400.0


def test_recent_endpoint_includes_price(client, temp_catalog, monkeypatch):
    monkeypatch.setattr(settings, "is_local", lambda request: True)
    catalog_admin.add_product("017-06", "80 mm.", "", "", png_bytes(), price="350")

    response = client.get("/api/catalog/recent")

    row = next(r for r in response.json()["results"] if r["code"] == "017-06")
    assert row["price"] == 350.0
