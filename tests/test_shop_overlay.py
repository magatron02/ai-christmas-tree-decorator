"""The catalogue base and the shop overlay, merged field by field — ADR-0001.

The failure this exists to stop already happened once: the 2026-08-19 re-import wiped work the
shop had done by hand. So the tests that matter here are the ones that re-import. A re-import
is simulated the way the real one behaves — products.json rewritten wholesale from the books,
then catalog.refresh() — because that is the only thing the overlay has to survive.
"""

import json

import pytest

from backend import config
from backend.services import catalog, catalog_admin, settings, shop_overlay
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
    """An empty temp catalogue base and an empty temp overlay.

    Same reasoning as test_catalog_admin's fixture — catalog.py's lru_caches are
    process-global, so refresh() has to run on teardown as well as on entry.
    """
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
    """The catalogue edit endpoints are localhost-only."""
    monkeypatch.setattr(settings, "is_local", lambda request: True)


def reimport(tmp_path, rows):
    """What a re-import does: rewrite the base wholesale from the books, and drop the caches."""
    (tmp_path / "products.json").write_text(json.dumps(rows), encoding="utf-8")
    catalog.refresh()


def price_017_06(client, price):
    return client.post(
        "/api/catalog/products/017-06",
        data={"size_raw": "80 mm.", "section": "baubles", "book": "2026", "price": price},
    )


def test_a_typed_price_goes_to_the_overlay_and_not_into_the_base(client, temp_catalog, local):
    assert price_017_06(client, "250").status_code == 200

    base = json.loads((temp_catalog / "products.json").read_text(encoding="utf-8"))
    assert base[0]["price"] is None, "the base is book data and must stay untouched"
    assert shop_overlay.fields_for("017-06") == {"price": 250.0}


def test_the_shops_price_survives_a_re_import(client, temp_catalog, local):
    """The whole point of the split, and the one demo in the ticket."""
    price_017_06(client, "250")

    reimport(temp_catalog, BOOK)

    assert catalog.find("017-06")["price"] == 250.0


def test_a_field_the_shop_never_touched_follows_the_re_imported_book(client, temp_catalog, local):
    """A corrected book still corrects everything the shop has no opinion on."""
    price_017_06(client, "250")

    corrected = [{**BOOK[0], "size_raw": "85 mm.",
                  "size": {"diameter_mm": 85.0, "unit_printed": "mm"}}]
    reimport(temp_catalog, corrected)

    row = catalog.find("017-06")
    assert row["size_raw"] == "85 mm."
    assert catalog.longest_side_mm(row) == 85
    assert row["price"] == 250.0


def test_editing_a_field_back_to_what_the_book_says_returns_it_to_the_book(
    client, temp_catalog, local
):
    """An opinion the shop retracts must not freeze the old value in place forever."""
    client.post(
        "/api/catalog/products/017-06",
        data={"size_raw": "90 mm.", "section": "baubles", "book": "2026", "price": ""},
    )
    assert shop_overlay.fields_for("017-06")["size_raw"] == "90 mm."

    price_017_06(client, "")  # size typed back to the book's "80 mm."

    assert "size_raw" not in shop_overlay.fields_for("017-06")
    reimport(temp_catalog, [{**BOOK[0], "size_raw": "85 mm."}])
    assert catalog.find("017-06")["size_raw"] == "85 mm."


def test_every_reader_sees_the_merged_record_at_its_own_call_site(client, temp_catalog, local):
    """No caller learns there are two layers: they all derive from catalog._rows()."""
    price_017_06(client, "250")

    assert catalog.find("017-06")["price"] == 250.0
    assert catalog.search("017-06")[0]["price"] == 250.0
    assert catalog.recent(1)[0]["price"] == 250.0

    listed = client.get("/api/catalog/recent").json()["results"]
    assert next(r for r in listed if r["code"] == "017-06")["price"] == 250.0


def test_the_code_is_not_overlayable(temp_catalog):
    """It is the key the overlay, the history and the worksheet all join on (ADR-0001)."""
    with pytest.raises(ValidationError):
        shop_overlay.set_fields("017-06", {"code": "017-07"})


@pytest.mark.parametrize("field", ["bbox", "pdf_page"])
def test_a_position_in_a_pdf_is_not_overlayable(temp_catalog, field):
    """These describe where a crop sat on a page, not anything about the product."""
    with pytest.raises(ValidationError):
        shop_overlay.set_fields("017-06", {field: 99})


def test_the_edit_form_never_offers_a_position_field(client, temp_catalog, local):
    """Not surfaced either — posting one is ignored, not written through."""
    client.post(
        "/api/catalog/products/017-06",
        data={"size_raw": "80 mm.", "section": "baubles", "book": "2026",
              "price": "250", "pdf_page": "999", "bbox": "[9,9,9,9]"},
    )

    assert shop_overlay.fields_for("017-06") == {"price": 250.0}
    assert catalog.find("017-06")["pdf_page"] == 12


def test_the_overlay_lives_beside_the_spend_log_not_beside_the_catalogue(temp_catalog):
    """data/ is excluded from the installer's file list and created empty; catalog/ is shipped.
    An overlay written next to products.json is work a reinstall can throw away."""
    assert shop_overlay.overlay_path().parent == config.DATA_DIR
    assert shop_overlay.overlay_path().parent == config.DB_PATH.parent
    assert shop_overlay.overlay_path().parent != config.CATALOG_PATH.parent


def test_an_edit_still_reports_the_derived_fields_back(client, temp_catalog, local):
    """The form's existing feedback (Product.md 8.1) comes off the merged record now."""
    response = client.post(
        "/api/catalog/products/017-06",
        data={"size_raw": "5 Ft.", "section": "ต้นคริสต์มาส", "book": "2026", "price": ""},
    )

    assert response.json() == {"code": "017-06", "size_mm": 1524.0, "category": "tree"}


def test_a_hand_added_product_can_still_be_edited(client, temp_catalog, local):
    """add_product writes a base row; editing it goes to the overlay like any other."""
    catalog_admin.add_product("099-01", "40 mm.", "baubles", "2026", png_bytes())

    client.post(
        "/api/catalog/products/099-01",
        data={"size_raw": "40 mm.", "section": "baubles", "book": "2026", "price": "99"},
    )

    assert catalog.find("099-01")["price"] == 99.0
    base = json.loads((temp_catalog / "products.json").read_text(encoding="utf-8"))
    assert next(r for r in base if r["code"] == "099-01")["price"] is None
