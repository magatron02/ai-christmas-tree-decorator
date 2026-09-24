"""Who edits what: price (and the supplier's own facts) are managed on the supplier-price page,
size on the catalogue page. The settings screens must not offer an edit that a run then ignores
(main._priced_extra: the supplier's price wins; main._resolved_size_mm: the catalogue's size
wins)."""

import json

import pytest

from backend import config
from backend.services import catalog, catalog_admin, settings, vendor_admin, vendor_lookup
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
def temp_vendor_lookup(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "VENDOR_PRICELISTS_DIR", tmp_path)
    monkeypatch.setattr(
        config, "VENDOR_SUPPLIERS",
        {"bangkok-christmas": {"label": "Bangkok Christmas", "book": "Bangkok Christmas"}},
    )
    path = tmp_path / "bangkok-christmas" / "cleaned" / "lookup.json"
    path.parent.mkdir(parents=True)
    path.write_text("{}", encoding="utf-8")
    vendor_lookup.refresh()
    yield path
    vendor_lookup.refresh()


@pytest.fixture
def local(monkeypatch):
    monkeypatch.setattr(settings, "is_local", lambda request: True)


def set_lookup(path, entries):
    path.write_text(json.dumps(entries), encoding="utf-8")
    vendor_lookup.refresh()


# ---- price: the catalogue screen shows what a quote would use ------------------------------


def test_the_catalogue_list_says_which_price_a_quote_would_use(
    client, temp_catalog, temp_vendor_lookup
):
    catalog_admin.add_product("BOTH-1", "80 mm.", "baubles", "Bangkok Christmas", png_bytes(), "100")
    catalog_admin.add_product("SHOP-1", "80 mm.", "baubles", "Bangkok Christmas", png_bytes(), "70")
    catalog_admin.add_product("NONE-1", "80 mm.", "baubles", "Bangkok Christmas", png_bytes())
    set_lookup(temp_vendor_lookup, {"BOTH-1": {"price": 55.0}})

    rows = {r["code"]: r for r in client.get("/api/catalog/products?limit=50").json()["results"]}

    assert (rows["BOTH-1"]["price_used"], rows["BOTH-1"]["price_source"]) == (55.0, "vendor")
    assert rows["BOTH-1"]["price"] == 100.0  # the catalogue's own figure is still reported as-is
    assert (rows["SHOP-1"]["price_used"], rows["SHOP-1"]["price_source"]) == (70.0, "catalog")
    assert (rows["NONE-1"]["price_used"], rows["NONE-1"]["price_source"]) == (None, None)


def test_saving_the_catalogue_form_without_a_price_keeps_the_existing_one(
    client, temp_catalog, local
):
    catalog_admin.add_product("KEEP-1", "80 mm.", "baubles", "Bangkok Christmas", png_bytes(), "70")

    response = client.post(
        "/api/catalog/products/KEEP-1",
        data={"size_raw": "90 mm.", "section": "baubles", "book": "Bangkok Christmas"},
    )

    assert response.status_code == 200
    assert catalog.find("KEEP-1")["price"] == 70.0


# ---- size: a supplier size the catalogue overrides is not editable -------------------------


def test_a_supplier_size_is_refused_when_the_catalogue_already_has_one(
    temp_catalog, temp_vendor_lookup
):
    catalog_admin.add_product("SIZED-1", "80 mm.", "baubles", "Bangkok Christmas", png_bytes())
    set_lookup(temp_vendor_lookup, {"SIZED-1": {"price": 10.0}})

    with pytest.raises(ValidationError, match="catalog"):
        vendor_admin.set_override("SIZED-1", "size_mm", "120")
    assert vendor_admin.find("SIZED-1")["catalog_size_mm"] == 80.0


def test_a_supplier_size_can_be_set_when_the_catalogue_has_none(temp_catalog, temp_vendor_lookup):
    catalog_admin.add_product("BARE-1", "", "baubles", "Bangkok Christmas", png_bytes())
    set_lookup(temp_vendor_lookup, {"BARE-1": {"price": 10.0}})

    row = vendor_admin.set_override("BARE-1", "size_mm", "120")

    assert row["size_mm"] == 120.0
    assert row["catalog_size_mm"] is None


def test_a_catalogue_product_the_supplier_never_listed_opens_as_an_empty_row(
    temp_catalog, temp_vendor_lookup
):
    catalog_admin.add_product("ONLY-1", "80 mm.", "baubles", "Bangkok Christmas", png_bytes())

    row = vendor_admin.find("ONLY-1")
    assert (row["code"], row["price"]) == ("ONLY-1", None)

    saved = vendor_admin.set_override("ONLY-1", "price", "42")
    assert saved["price"] == 42.0 and vendor_lookup.price_for("ONLY-1") == 42.0


def test_a_code_in_neither_place_is_still_refused(temp_catalog, temp_vendor_lookup):
    with pytest.raises(ValidationError):
        vendor_admin.find("NOWHERE-1")
