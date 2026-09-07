"""Find a product by code, see its merged record, and correct it (issue #11).

The screen shows the base merged with the overlay and marks which fields are the shop's own
opinion rather than the book's. The code is never editable — the documented fix for a wrong
code is delete-and-recreate (ADR-0001) — and the book-derived position fields (bbox, pdf_page)
never reach this screen at all.
"""

import json

import pytest

from backend import config
from backend.services import catalog, catalog_admin, settings
from backend.validation import ValidationError

from helpers import png_bytes


BOOK = [{
    "code": "017-06",
    "size_raw": "80 mm.",
    "size": {"diameter_mm": 80.0, "unit_printed": "mm"},
    "section": "baubles",
    "page_headings": [],
    "pdf_page": 12,
    "bbox": [1.0, 2.0, 3.0, 4.0],
    "duplicate": False,
    "book": "2026",
    "price": None,
}]


@pytest.fixture
def temp_catalog(tmp_path, monkeypatch):
    products = tmp_path / "products.json"
    products.write_text(json.dumps(BOOK), encoding="utf-8")
    monkeypatch.setattr(catalog_admin, "PRODUCTS_PATH", products)
    monkeypatch.setattr(catalog_admin, "IMAGES_DIR", tmp_path / "images")
    monkeypatch.setattr(catalog_admin, "PRODUCT_IMAGES_PATH", tmp_path / "product_images.json")
    monkeypatch.setattr(config, "CATALOG_PATH", products)
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "data" / "app.db")
    catalog.refresh()
    yield tmp_path
    catalog.refresh()


@pytest.fixture
def local(monkeypatch):
    monkeypatch.setattr(settings, "is_local", lambda request: True)


def edit(client, **overrides):
    data = {"size_raw": "80 mm.", "section": "baubles", "book": "2026", "price": ""}
    data.update(overrides)
    return client.post("/api/catalog/products/017-06", data=data)


def test_finding_a_known_code_returns_its_merged_record(client, temp_catalog):
    response = client.get("/api/catalog/products/017-06")

    assert response.status_code == 200
    body = response.json()
    assert body["code"] == "017-06"
    assert body["size_raw"] == "80 mm."
    assert body["price"] is None
    assert body["overridden"] == []


def test_an_unknown_code_is_refused(client, temp_catalog):
    response = client.get("/api/catalog/products/99999-9")
    assert response.status_code == 422


def test_position_fields_never_reach_the_response(client, temp_catalog):
    body = client.get("/api/catalog/products/017-06").json()
    assert "bbox" not in body
    assert "pdf_page" not in body


def test_a_field_the_shop_corrected_is_marked_overridden(client, temp_catalog, local):
    edit(client, price="250")

    body = client.get("/api/catalog/products/017-06").json()

    assert body["price"] == 250.0
    assert body["overridden"] == ["price"]
    assert "size_raw" not in body["overridden"]


def test_correcting_price_size_section_and_book_all_mark_themselves_overridden(
    client, temp_catalog, local
):
    edit(client, size_raw="90 mm.", section="ornaments", book="2027", price="99")

    body = client.get("/api/catalog/products/017-06").json()

    assert sorted(body["overridden"]) == ["book", "price", "section", "size_raw"]
    assert body["size_raw"] == "90 mm."
    assert body["section"] == "ornaments"
    assert body["book"] == "2027"
    assert body["price"] == 99.0


def test_the_recent_listing_reports_the_same_overridden_fields(client, temp_catalog, local):
    edit(client, price="250")

    row = next(
        r for r in client.get("/api/catalog/recent").json()["results"] if r["code"] == "017-06"
    )
    assert row["overridden"] == ["price"]


def test_clearing_an_override_returns_that_field_to_the_books_value(
    client, temp_catalog, local
):
    edit(client, size_raw="90 mm.")
    assert client.get("/api/catalog/products/017-06").json()["overridden"] == ["size_raw"]

    response = client.post(
        "/api/catalog/products/017-06/clear-override", data={"field": "size_raw"}
    )

    assert response.status_code == 200
    body = client.get("/api/catalog/products/017-06").json()
    assert body["size_raw"] == "80 mm."  # the book's own value
    assert body["overridden"] == []


def test_clearing_size_raw_also_drops_its_derived_size(client, temp_catalog, local):
    edit(client, size_raw="5 Ft.")
    assert catalog.find("017-06")["size"]["height_mm"] == 1524

    client.post("/api/catalog/products/017-06/clear-override", data={"field": "size_raw"})

    assert catalog.find("017-06")["size"] == BOOK[0]["size"]


def test_clearing_one_field_leaves_other_overrides_in_place(client, temp_catalog, local):
    edit(client, size_raw="90 mm.", price="250")

    client.post("/api/catalog/products/017-06/clear-override", data={"field": "size_raw"})

    body = client.get("/api/catalog/products/017-06").json()
    assert body["overridden"] == ["price"]
    assert body["price"] == 250.0


def test_the_code_cannot_be_cleared_or_overridden(temp_catalog):
    from backend.services import catalog_admin

    with pytest.raises(ValidationError):
        catalog_admin.clear_override("017-06", "code")


def test_clearing_an_unrecognised_field_is_refused(client, temp_catalog, local):
    response = client.post(
        "/api/catalog/products/017-06/clear-override", data={"field": "bbox"}
    )
    assert response.status_code != 200


def test_clear_override_is_localhost_only(client, temp_catalog, monkeypatch):
    monkeypatch.setattr(settings, "is_local", lambda request: False)
    response = client.post(
        "/api/catalog/products/017-06/clear-override", data={"field": "price"}
    )
    assert response.status_code == 403
