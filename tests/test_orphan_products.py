"""Orphan products: an overlay whose code no longer appears in any base after a re-import.

Kept and surfaced, never dropped silently (ADR-0001, issue #9) — the failure this exists to
stop already happened once, when the 2026-08-19 re-import wiped 264 codes of colour splits
with nothing to show the shop it had happened.
"""

import json

import pytest

from backend import config
from backend.services import catalog, catalog_admin, settings, shop_overlay

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


def reimport(tmp_path, rows):
    """What a book re-import does: rewrite the base wholesale, then drop the caches."""
    (tmp_path / "products.json").write_text(json.dumps(rows), encoding="utf-8")
    catalog.refresh()


def price_017_06(client, price="250"):
    return client.post(
        "/api/catalog/products/017-06",
        data={"size_raw": "80 mm.", "section": "baubles", "book": "2026", "price": price},
    )


def test_the_overlay_is_retained_when_its_code_vanishes_from_the_base(
    client, temp_catalog, local
):
    price_017_06(client)

    reimport(temp_catalog, [])  # the next book simply no longer prints 017-06

    assert shop_overlay.fields_for("017-06") == {"price": 250.0}


def test_an_orphan_no_longer_resolves_as_a_real_product(client, temp_catalog, local):
    """Not resurrected in the normal catalogue views — it has no book position or photo left
    to show there; it belongs in the dedicated orphan listing instead."""
    price_017_06(client)
    reimport(temp_catalog, [])

    with pytest.raises(Exception):
        catalog.find("017-06")
    assert catalog.search("017-06") == []
    rows, _total = catalog.browse(limit=1000)
    assert all(row["code"] != "017-06" for row in rows)


def test_an_orphan_is_listed_with_the_fields_the_shop_set(client, temp_catalog, local):
    price_017_06(client)
    reimport(temp_catalog, [])

    response = client.get("/api/catalog/orphans")

    assert response.status_code == 200
    orphans = response.json()["orphans"]
    assert orphans == [{"code": "017-06", "price": 250.0}]


def test_a_product_still_in_the_base_is_not_listed_as_an_orphan(client, temp_catalog, local):
    price_017_06(client)
    reimport(temp_catalog, BOOK)  # unchanged: 017-06 still printed

    assert client.get("/api/catalog/orphans").json()["orphans"] == []


def test_the_settings_status_counts_orphans(client, temp_catalog, local):
    price_017_06(client)
    reimport(temp_catalog, [])

    status = client.get("/api/settings").json()

    assert status["catalog_orphans"] == 1


def test_a_reimported_book_that_brings_the_code_back_reunites_it_with_its_overlay(
    client, temp_catalog, local
):
    price_017_06(client)
    reimport(temp_catalog, [])
    assert client.get("/api/catalog/orphans").json()["orphans"] == [
        {"code": "017-06", "price": 250.0}
    ]

    reimport(temp_catalog, BOOK)  # the code is printed again in the next book

    assert catalog.find("017-06")["price"] == 250.0
    assert client.get("/api/catalog/orphans").json()["orphans"] == []


def test_an_orphans_overlay_never_leaks_onto_an_unrelated_code(client, temp_catalog, local):
    """A per-field merge keyed strictly by code — dropping one code from the base must never
    make its overlay opinions bleed onto whatever code the next re-import prints instead."""
    price_017_06(client)
    reimport(temp_catalog, [{**BOOK[0], "code": "099-01"}])  # a different code entirely

    assert catalog.find("099-01")["price"] is None
    assert shop_overlay.fields_for("017-06") == {"price": 250.0}


def test_add_product_can_recreate_an_orphaned_code(client, temp_catalog, local):
    """ADR-0001: a wrong code is fixed by deleting the product and creating it again — the
    orphan path must not block the manual add door from reusing that code."""
    price_017_06(client)
    reimport(temp_catalog, [])

    catalog_admin.add_product("017-06", "80 mm.", "baubles", "2026", png_bytes())

    assert catalog.find("017-06")["code"] == "017-06"
