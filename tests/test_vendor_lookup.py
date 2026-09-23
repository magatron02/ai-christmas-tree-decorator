"""backend/services/vendor_lookup.py — price and size from the supplier's own price list,
each with its own precedence against the shop's catalogue, decided and measured separately on
2026-09-10:

  - price: the vendor's own wholesale figure wins whenever it has one for a code, even over a
    price the shop already set itself (this deployment is partner-facing).
  - size: the catalogue's own printed size wins when it has one; the vendor's parsed size only
    fills the gap for a code the catalogue has none for. A "vendor everywhere" pass for size
    was tried first and reverted — see vendor_lookup.py's own docstring for the numbers.
"""

import json

import pytest

from backend import config
from backend.services import catalog, catalog_admin, vendor_lookup

from helpers import png_bytes, upload


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


def set_vendor_lookup(path, entries):
    path.write_text(json.dumps(entries), encoding="utf-8")
    vendor_lookup.refresh()


# ---------------------------------------------------------------- vendor_lookup module itself


def test_price_for_and_size_mm_for_read_the_configured_file(temp_vendor_lookup):
    set_vendor_lookup(temp_vendor_lookup, {"071-11": {"price": 89.0, "size_mm": 80.0}})

    assert vendor_lookup.price_for("071-11") == 89.0
    assert vendor_lookup.size_mm_for("071-11") == 80.0
    assert vendor_lookup.price_for("NOPE") is None
    assert vendor_lookup.size_mm_for("NOPE") is None


def test_a_code_with_only_one_of_the_two_fields(temp_vendor_lookup):
    set_vendor_lookup(temp_vendor_lookup, {"6020-03": {"price": 240.0}})  # no size_mm at all

    assert vendor_lookup.price_for("6020-03") == 240.0
    assert vendor_lookup.size_mm_for("6020-03") is None


def test_codeless_lookups_are_none(temp_vendor_lookup):
    assert vendor_lookup.price_for(None) is None
    assert vendor_lookup.size_mm_for("") is None


def test_base_field_ignores_the_overlay(temp_vendor_lookup):
    from backend.services import vendor_overlay

    set_vendor_lookup(temp_vendor_lookup, {"071-11": {"price": 89.0}})
    vendor_overlay.set_fields("071-11", {"price": 120.0}, speaks_for=("price",))
    vendor_lookup.refresh()

    assert vendor_lookup.base_field("071-11", "price") == 89.0
    assert vendor_lookup.price_for("071-11") == 120.0  # merged view still overridden
    assert vendor_lookup.base_field("NOPE", "price") is None
    assert vendor_lookup.base_field(None, "price") is None


def test_no_file_at_all_is_none(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "VENDOR_PRICELISTS_DIR", tmp_path)
    monkeypatch.setattr(
        config, "VENDOR_SUPPLIERS",
        {"bangkok-christmas": {"label": "Bangkok Christmas", "book": "Bangkok Christmas"}},
    )  # tmp_path/bangkok-christmas/cleaned/lookup.json is never created — fails soft
    vendor_lookup.refresh()
    try:
        assert vendor_lookup.price_for("071-11") is None
        assert vendor_lookup.size_mm_for("071-11") is None
    finally:
        vendor_lookup.refresh()


# ---------------------------------------------------------------- end-to-end (main._priced_extra)


def cut_out(client, n=1):
    tokens = []
    for _ in range(n):
        response = client.post("/api/remove-bg", files=[upload(png_bytes(), "element.png")])
        assert response.status_code == 200, response.text
        tokens.append(response.json()["element"])
    return tokens


def prepare(client, tokens, **extra):
    return client.post(
        "/api/prepare",
        files=[upload(png_bytes(), "tree.png")],
        data={"element": tokens, "size": "4:5", **extra},
    )


def prepare_and_generate(client, tokens, **extra):
    prepared = prepare(client, tokens, **extra)
    assert prepared.status_code == 200, prepared.text
    request_id = prepared.json()["request_id"]
    response = client.post(f"/api/generate/{request_id}")
    assert response.status_code == 200, response.text
    return response


def test_vendor_price_wins_over_catalog_price(
    client, conn, fake_gen, fake_rembg, temp_catalog, temp_vendor_lookup
):
    catalog_admin.add_product("TREE1", "150 cm.", "tree", "2026", png_bytes())
    catalog_admin.add_product("E001", "80 mm.", "ornament", "2026", png_bytes(), price="150")
    set_vendor_lookup(temp_vendor_lookup, {"E001": {"price": 65.0}})

    response = prepare_and_generate(
        client, cut_out(client, 1), tree_code="TREE1", element_code=["E001"]
    )

    element = response.json()["elements"][0]
    assert element["price"] == 65.0
    assert element["price_source"] == "vendor"


def test_catalog_price_used_when_vendor_has_none(
    client, conn, fake_gen, fake_rembg, temp_catalog, temp_vendor_lookup
):
    catalog_admin.add_product("TREE1", "150 cm.", "tree", "2026", png_bytes())
    catalog_admin.add_product("E001", "80 mm.", "ornament", "2026", png_bytes(), price="150")

    response = prepare_and_generate(
        client, cut_out(client, 1), tree_code="TREE1", element_code=["E001"]
    )

    element = response.json()["elements"][0]
    assert element["price"] == 150.0
    assert element["price_source"] == "catalog"


def test_no_price_anywhere_is_reported_missing(
    client, conn, fake_gen, fake_rembg, temp_catalog, temp_vendor_lookup
):
    catalog_admin.add_product("TREE1", "150 cm.", "tree", "2026", png_bytes())
    catalog_admin.add_product("E001", "80 mm.", "ornament", "2026", png_bytes())

    response = prepare_and_generate(
        client, cut_out(client, 1), tree_code="TREE1", element_code=["E001"]
    )

    body = response.json()
    assert body["price_total"] == 0.0
    assert len(body["price_missing"]) == 1
    element = body["elements"][0]
    assert element["price"] is None
    assert element["price_source"] is None


def test_catalog_size_wins_over_vendor_size(client, conn, temp_catalog, temp_vendor_lookup):
    catalog_admin.add_product("E001", "80 mm.", "ornament", "2026", png_bytes())
    set_vendor_lookup(temp_vendor_lookup, {"E001": {"size_mm": 999.0}})

    response = client.post("/api/element/from-catalog", data={"code": "E001"})

    assert response.status_code == 200, response.text
    assert response.json()["size_mm"] == 80.0


def test_vendor_size_fills_the_gap_when_catalog_has_none(
    client, conn, temp_catalog, temp_vendor_lookup
):
    catalog_admin.add_product("E001", "", "ornament", "2026", png_bytes())  # no size_raw
    set_vendor_lookup(temp_vendor_lookup, {"E001": {"size_mm": 65.0}})

    response = client.post("/api/element/from-catalog", data={"code": "E001"})

    assert response.status_code == 200, response.text
    assert response.json()["size_mm"] == 65.0


def test_vendor_size_feeds_the_actual_scale_sentence_not_just_the_picker(
    client, conn, fake_gen, fake_rembg, temp_catalog, temp_vendor_lookup
):
    """The point of threading size_lookup through catalog.scale_sentence() — a code the
    catalogue has no size for must still resolve to an exact-scale prompt via vendor, not just
    show a number in the picker while silently falling back to 'believable, not exact'."""
    catalog_admin.add_product("TREE1", "150 cm.", "tree", "2026", png_bytes())
    catalog_admin.add_product("E001", "", "ornament", "2026", png_bytes())  # no catalog size
    set_vendor_lookup(temp_vendor_lookup, {"E001": {"size_mm": 80.0}})

    prepared = prepare(client, cut_out(client, 1), tree_code="TREE1", element_code=["E001"])

    assert prepared.status_code == 200, prepared.text
    # scale_sentence() resolved a real size via the vendor fallback, so nothing is missing
    assert prepared.json()["missing_sizes"] == []


def test_no_size_anywhere_still_falls_back_honestly(
    client, conn, fake_gen, fake_rembg, temp_catalog, temp_vendor_lookup
):
    catalog_admin.add_product("TREE1", "150 cm.", "tree", "2026", png_bytes())
    catalog_admin.add_product("E001", "", "ornament", "2026", png_bytes())  # no catalog size

    prepared = prepare(client, cut_out(client, 1), tree_code="TREE1", element_code=["E001"])

    assert prepared.status_code == 200, prepared.text
    assert len(prepared.json()["missing_sizes"]) == 1


# ---------------------------------------------------------------- multiple suppliers


def add_supplier(temp_vendor_lookup, slug, label, book, entries):
    """Configures a second supplier alongside the one temp_vendor_lookup already set up,
    writing its own lookup.json under the same temp root (tmp_path/<slug>/cleaned/lookup.json,
    the shape config.VENDOR_PRICELISTS_DIR expects)."""
    tmp_path = temp_vendor_lookup.parents[2]  # .../<slug>/cleaned/lookup.json -> tmp_path
    path = tmp_path / slug / "cleaned" / "lookup.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(entries), encoding="utf-8")
    config.VENDOR_SUPPLIERS[slug] = {"label": label, "book": book}
    vendor_lookup.refresh()
    return path


def test_two_suppliers_merge_into_one_entries_table(temp_vendor_lookup):
    set_vendor_lookup(temp_vendor_lookup, {"071-11": {"price": 89.0}})
    add_supplier(
        temp_vendor_lookup, "other-supplier", "Other Supplier", "Other Book",
        {"900-01": {"price": 10.0}},
    )

    entries = vendor_lookup.entries()
    assert entries["071-11"]["supplier"] == "bangkok-christmas"
    assert entries["900-01"]["supplier"] == "other-supplier"


def test_a_code_claimed_by_two_suppliers_keeps_the_first_and_is_flagged(temp_vendor_lookup):
    set_vendor_lookup(temp_vendor_lookup, {"071-11": {"price": 89.0}})
    add_supplier(
        temp_vendor_lookup, "other-supplier", "Other Supplier", "Other Book",
        {"071-11": {"price": 999.0}},
    )

    assert vendor_lookup.price_for("071-11") == 89.0  # first-configured supplier wins
    assert vendor_lookup.entries()["071-11"]["supplier"] == "bangkok-christmas"
    assert vendor_lookup.conflicting_codes() == ["071-11"]


def test_no_conflicts_when_nothing_collides(temp_vendor_lookup):
    set_vendor_lookup(temp_vendor_lookup, {"071-11": {"price": 89.0}})
    add_supplier(
        temp_vendor_lookup, "other-supplier", "Other Supplier", "Other Book",
        {"900-01": {"price": 10.0}},
    )
    assert vendor_lookup.conflicting_codes() == []
