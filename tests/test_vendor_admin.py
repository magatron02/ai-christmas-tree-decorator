"""Vendor price-list admin: browse, check-for-errors, fix, and import — backend/services/
vendor_admin.py. Parallel to test_catalog_admin.py, against an isolated temp catalogue and an
isolated temp vendor lookup file so nothing here touches the real ~2875-row price list.
"""

import json

import pytest

from backend import config
from backend.services import catalog, catalog_admin, settings, vendor_admin, vendor_lookup, vendor_overlay
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


def add_catalog_product(code, book="Bangkok Christmas"):
    catalog_admin.add_product(code, "80 mm.", "baubles", book, png_bytes())


# ---------------------------------------------------------------- search


def test_search_with_no_query_returns_everything_up_to_the_limit(temp_vendor_lookup):
    set_lookup(temp_vendor_lookup, {"071-11": {"price": 89.0}, "071-12": {"price": 45.0}})

    results = vendor_admin.search(limit=1)

    assert len(results) == 1


def test_search_matches_code_or_name(temp_vendor_lookup):
    set_lookup(temp_vendor_lookup, {
        "071-11": {"price": 89.0, "name": "บอลแก้วสีแดง"},
        "071-12": {"price": 45.0, "name": "ริบบิ้นทอง"},
    })

    assert [r["code"] for r in vendor_admin.search("071-11")] == ["071-11"]
    assert [r["code"] for r in vendor_admin.search("ริบบิ้น")] == ["071-12"]


def test_search_reports_in_catalog(temp_catalog, temp_vendor_lookup):
    set_lookup(temp_vendor_lookup, {"071-11": {"price": 89.0}, "071-12": {"price": 45.0}})
    add_catalog_product("071-11")

    results = {r["code"]: r for r in vendor_admin.search()}

    assert results["071-11"]["in_catalog"] is True
    assert results["071-12"]["in_catalog"] is False


def test_search_reports_overridden_fields(temp_vendor_lookup):
    set_lookup(temp_vendor_lookup, {"071-11": {"price": 89.0}})
    vendor_overlay.set_fields("071-11", {"price": 120.0}, speaks_for=("price",))

    row = vendor_admin.find("071-11")

    assert row["price"] == 120.0
    assert row["overridden"] == ["price"]


def test_row_note_flags_missing_price_and_size(temp_vendor_lookup):
    set_lookup(temp_vendor_lookup, {"071-11": {"name": "บอลแก้ว"}})  # no price, no size
    row = vendor_admin.find("071-11")
    assert "ไม่มีราคา" in row["note"]
    assert "ไม่มีขนาด" in row["note"]


def test_row_note_flags_pack_ambiguous(temp_vendor_lookup):
    set_lookup(temp_vendor_lookup, {"071-11": {"price": 45.0, "size_mm": 40.0, "pack_ambiguous": True}})
    assert "ไม่ชัดเจน" in vendor_admin.find("071-11")["note"]


def test_row_note_is_empty_when_nothing_is_wrong(temp_vendor_lookup):
    set_lookup(temp_vendor_lookup, {"071-11": {"price": 45.0, "size_mm": 40.0}})
    assert vendor_admin.find("071-11")["note"] == ""


def test_find_unknown_code_raises(temp_vendor_lookup):
    with pytest.raises(ValidationError):
        vendor_admin.find("NOPE")


# ---------------------------------------------------------------- multiple suppliers


def add_supplier(temp_vendor_lookup, slug, label, book, entries):
    """Configures a second supplier alongside the one temp_vendor_lookup already set up (same
    helper as test_vendor_lookup.py's, duplicated rather than shared since these two test
    files never import from each other)."""
    tmp_path = temp_vendor_lookup.parents[2]  # .../<slug>/cleaned/lookup.json -> tmp_path
    path = tmp_path / slug / "cleaned" / "lookup.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(entries), encoding="utf-8")
    config.VENDOR_SUPPLIERS[slug] = {"label": label, "book": book}
    vendor_lookup.refresh()
    return path


def test_suppliers_lists_every_configured_one(temp_vendor_lookup):
    add_supplier(temp_vendor_lookup, "other-supplier", "Other Supplier", "Other Book", {})
    assert vendor_admin.suppliers() == [
        {"key": "bangkok-christmas", "label": "Bangkok Christmas"},
        {"key": "other-supplier", "label": "Other Supplier"},
    ]


def test_search_filters_by_supplier(temp_vendor_lookup):
    set_lookup(temp_vendor_lookup, {"071-11": {"price": 89.0}})
    add_supplier(temp_vendor_lookup, "other-supplier", "Other Supplier", "Other Book",
                 {"900-01": {"price": 10.0}})

    assert [r["code"] for r in vendor_admin.search(supplier="bangkok-christmas")] == ["071-11"]
    assert [r["code"] for r in vendor_admin.search(supplier="other-supplier")] == ["900-01"]


def test_in_catalog_is_scoped_to_the_codes_own_supplier_book(temp_catalog, temp_vendor_lookup):
    """A code counts as catalogued against the book *its own supplier* maps to — not just any
    configured book — so two suppliers with different books never cross-credit each other."""
    add_catalog_product("071-11", book="Bangkok Christmas")
    add_catalog_product("900-01", book="Other Book")
    set_lookup(temp_vendor_lookup, {"071-11": {"price": 89.0}})
    add_supplier(temp_vendor_lookup, "other-supplier", "Other Supplier", "Other Book",
                 {"900-01": {"price": 10.0}})

    results = {r["code"]: r for r in vendor_admin.search()}
    assert results["071-11"]["in_catalog"] is True
    assert results["900-01"]["in_catalog"] is True


def test_in_catalog_filter_narrows_to_catalogued_or_uncatalogued(temp_catalog, temp_vendor_lookup):
    add_catalog_product("071-11")
    set_lookup(temp_vendor_lookup, {"071-11": {"price": 89.0}, "071-12": {"price": 45.0}})

    assert [r["code"] for r in vendor_admin.search(in_catalog=True)] == ["071-11"]
    assert [r["code"] for r in vendor_admin.search(in_catalog=False)] == ["071-12"]
    assert len(vendor_admin.search()) == 2  # in_catalog=None (default): no filter


def test_missing_size_filter(temp_vendor_lookup):
    set_lookup(temp_vendor_lookup, {
        "071-11": {"price": 89.0, "size_mm": 25.0}, "071-12": {"price": 45.0},
    })
    assert [r["code"] for r in vendor_admin.search(missing_size=True)] == ["071-12"]


def test_unmapped_char_filter(temp_vendor_lookup):
    set_lookup(temp_vendor_lookup, {
        "071-11": {"price": 89.0, "name": "บอลแก้ว"},
        "071-12": {"price": 45.0, "name": f"บอล{chr(0xE000)}แปลก"},
    })
    assert [r["code"] for r in vendor_admin.search(unmapped_char=True)] == ["071-12"]


def test_search_endpoint_honours_status_filters(client, temp_catalog, temp_vendor_lookup):
    add_catalog_product("071-11")
    set_lookup(temp_vendor_lookup, {
        "071-11": {"price": 89.0, "size_mm": 25.0}, "071-12": {"price": 45.0},
    })
    response = client.get("/api/vendor/products", params={"in_catalog": "false"})
    assert [r["code"] for r in response.json()["results"]] == ["071-12"]

    response = client.get("/api/vendor/products", params={"missing_size": "true"})
    assert [r["code"] for r in response.json()["results"]] == ["071-12"]


def test_suppliers_endpoint(client, temp_vendor_lookup):
    response = client.get("/api/vendor/suppliers")
    assert response.status_code == 200
    assert response.json()["suppliers"] == [{"key": "bangkok-christmas", "label": "Bangkok Christmas"}]


# ---------------------------------------------------------------- issues


def test_issues_flags_a_catalogued_code_with_no_vendor_entry_at_all(temp_catalog, temp_vendor_lookup):
    add_catalog_product("071-11")

    issues = vendor_admin.issues()

    assert issues["no_vendor_entry"] == [{"code": "071-11"}]
    assert issues["missing_price"] == []


def test_issues_flags_missing_price_and_size_for_catalogued_codes_only(temp_catalog, temp_vendor_lookup):
    add_catalog_product("071-11")
    set_lookup(temp_vendor_lookup, {
        "071-11": {"name": "บอลแก้ว"},        # no price, no size — catalogued, should flag
        "999-99": {},                          # not catalogued — must not appear anywhere
    })

    issues = vendor_admin.issues()

    assert [i["code"] for i in issues["missing_price"]] == ["071-11"]
    assert [i["code"] for i in issues["missing_size"]] == ["071-11"]
    assert issues["vendor_rows_without_catalog_match"] == 1  # 999-99


def test_issues_flags_pack_ambiguous(temp_catalog, temp_vendor_lookup):
    add_catalog_product("071-11")
    set_lookup(temp_vendor_lookup, {"071-11": {"price": 45.0, "pack_ambiguous": True}})

    issues = vendor_admin.issues()

    assert [i["code"] for i in issues["pack_ambiguous"]] == ["071-11"]


def test_resolving_pack_ambiguous_clears_the_issue(temp_catalog, temp_vendor_lookup):
    add_catalog_product("071-11")
    set_lookup(temp_vendor_lookup, {"071-11": {"price": 45.0, "pack_ambiguous": True}})

    vendor_admin.set_override("071-11", "pack_ambiguous", "false")

    assert vendor_admin.issues()["pack_ambiguous"] == []


# ---------------------------------------------------------------- set_override / clear_override


def test_set_override_parses_price_as_a_number(temp_vendor_lookup):
    set_lookup(temp_vendor_lookup, {"071-11": {"price": 89.0}})
    vendor_admin.set_override("071-11", "price", "120.5")
    assert vendor_lookup.price_for("071-11") == 120.5


def test_set_override_rejects_a_non_numeric_price(temp_vendor_lookup):
    set_lookup(temp_vendor_lookup, {"071-11": {"price": 89.0}})
    with pytest.raises(ValidationError):
        vendor_admin.set_override("071-11", "price", "not a number")


def test_set_override_rejects_a_negative_price(temp_vendor_lookup):
    set_lookup(temp_vendor_lookup, {"071-11": {"price": 89.0}})
    with pytest.raises(ValidationError):
        vendor_admin.set_override("071-11", "price", "-5")


def test_set_override_rejects_an_unknown_field(temp_vendor_lookup):
    set_lookup(temp_vendor_lookup, {"071-11": {"price": 89.0}})
    with pytest.raises(ValidationError):
        vendor_admin.set_override("071-11", "code", "071-12")


def test_clear_override_returns_to_the_base_value(temp_vendor_lookup):
    set_lookup(temp_vendor_lookup, {"071-11": {"price": 89.0}})
    vendor_admin.set_override("071-11", "price", "120")

    vendor_admin.clear_override("071-11", "price")

    assert vendor_lookup.price_for("071-11") == 89.0


def test_set_override_matching_the_base_value_clears_instead_of_storing(temp_vendor_lookup):
    """Retyping a value that happens to equal the supplier's own printed figure is "no opinion,
    follow the vendor" — not a redundant explicit override that happens to agree with it."""
    set_lookup(temp_vendor_lookup, {"071-11": {"price": 89.0}})
    vendor_admin.set_override("071-11", "price", "120")
    assert "price" in vendor_overlay.fields_for("071-11")

    row = vendor_admin.set_override("071-11", "price", "89")

    assert vendor_lookup.price_for("071-11") == 89.0
    assert vendor_overlay.fields_for("071-11") == {}
    assert row["overridden"] == []


def test_set_override_matching_the_base_value_on_a_never_overridden_code_is_a_no_op(temp_vendor_lookup):
    set_lookup(temp_vendor_lookup, {"071-11": {"price": 89.0}})

    row = vendor_admin.set_override("071-11", "price", "89")

    assert vendor_lookup.price_for("071-11") == 89.0
    assert vendor_overlay.fields_for("071-11") == {}
    assert row["overridden"] == []


def test_set_override_works_on_a_code_the_current_vendor_sheet_has_dropped(temp_vendor_lookup):
    """Same "orphans are kept" stance as the catalogue overlay — a correction ahead of a
    future import must not require the code to already exist in the current base."""
    vendor_admin.set_override("099-99", "price", "10")
    assert vendor_lookup.price_for("099-99") == 10.0


# ---------------------------------------------------------------- HTTP routes


def test_set_override_endpoint_works_end_to_end(client, temp_vendor_lookup, local):
    set_lookup(temp_vendor_lookup, {"071-11": {"price": 89.0}})

    response = client.post(
        "/api/vendor/products/071-11", data={"field": "price", "value": "120"}
    )

    assert response.status_code == 200, response.text
    assert vendor_lookup.price_for("071-11") == 120.0


def test_a_code_containing_slashes_works_on_every_route(client, temp_vendor_lookup, local):
    """A code like "018-03/6/THEME" is real data (a variant-suffix code, same shape as
    catalog.py's own) — the default FastAPI path parameter only matches one URL segment, so
    without `{code:path}` every one of these routes 404s the moment a code has a "/" in it."""
    code = "018-03/6/THEME"
    set_lookup(temp_vendor_lookup, {code: {"price": 90.0}})

    find = client.get(f"/api/vendor/products/{code}")
    assert find.status_code == 200, find.text
    assert find.json()["code"] == code

    saved = client.post(f"/api/vendor/products/{code}", data={"field": "price", "value": "99"})
    assert saved.status_code == 200, saved.text
    assert vendor_lookup.price_for(code) == 99.0

    # clear-override must reach its own handler, not be swallowed by the plainer
    # POST /api/vendor/products/{code:path} route registered after it for exactly this reason.
    cleared = client.post(f"/api/vendor/products/{code}/clear-override", data={"field": "price"})
    assert cleared.status_code == 200, cleared.text
    assert vendor_lookup.price_for(code) == 90.0


def test_set_override_endpoint_is_localhost_only(client, temp_vendor_lookup, monkeypatch):
    monkeypatch.setattr(settings, "is_local", lambda request: False)
    set_lookup(temp_vendor_lookup, {"071-11": {"price": 89.0}})

    response = client.post(
        "/api/vendor/products/071-11", data={"field": "price", "value": "120"}
    )

    assert response.status_code == 403


def test_clear_override_endpoint_is_localhost_only(client, temp_vendor_lookup, monkeypatch):
    monkeypatch.setattr(settings, "is_local", lambda request: False)
    response = client.post(
        "/api/vendor/products/071-11/clear-override", data={"field": "price"}
    )
    assert response.status_code == 403


def test_import_endpoint_is_localhost_only(client, monkeypatch):
    monkeypatch.setattr(settings, "is_local", lambda request: False)
    response = client.post(
        "/api/vendor/import",
        data={"supplier": "bangkok-christmas"},
        files={"pdf": ("list.pdf", b"%PDF-1.4 fake", "application/pdf")},
    )
    assert response.status_code == 403


def test_search_endpoint_returns_results(client, temp_vendor_lookup):
    set_lookup(temp_vendor_lookup, {"071-11": {"price": 89.0}})
    response = client.get("/api/vendor/products", params={"q": "071-11"})
    assert response.status_code == 200
    assert response.json()["results"][0]["code"] == "071-11"


def test_count_reflects_the_full_match_not_just_the_limited_page(temp_vendor_lookup):
    set_lookup(temp_vendor_lookup, {
        "071-11": {"price": 89.0}, "071-12": {"price": 45.0}, "071-13": {"price": 10.0},
    })
    assert vendor_admin.count() == 3
    assert len(vendor_admin.search(limit=1)) == 1


def test_search_offset_moves_to_the_next_page(temp_vendor_lookup):
    set_lookup(temp_vendor_lookup, {
        "071-11": {"price": 89.0}, "071-12": {"price": 45.0}, "071-13": {"price": 10.0},
    })
    page1 = [r["code"] for r in vendor_admin.search(limit=2, offset=0)]
    page2 = [r["code"] for r in vendor_admin.search(limit=2, offset=2)]
    assert page1 == ["071-11", "071-12"]
    assert page2 == ["071-13"]


def test_search_endpoint_honours_offset(client, temp_vendor_lookup):
    set_lookup(temp_vendor_lookup, {"071-11": {"price": 89.0}, "071-12": {"price": 45.0}})
    response = client.get("/api/vendor/products", params={"limit": 1, "offset": 1})
    body = response.json()
    assert [r["code"] for r in body["results"]] == ["071-12"]
    assert body["total"] == 2


def test_search_endpoint_reports_total_separately_from_the_limited_results(client, temp_vendor_lookup):
    set_lookup(temp_vendor_lookup, {"071-11": {"price": 89.0}, "071-12": {"price": 45.0}})
    response = client.get("/api/vendor/products", params={"limit": 1})
    body = response.json()
    assert len(body["results"]) == 1
    assert body["total"] == 2


# ---------------------------------------------------------------- import_pricelist


@pytest.fixture
def temp_vendor_dir(tmp_path, monkeypatch):
    """Isolates every path import_pricelist() touches: the source PDF folder and the
    CSV/lookup.json pair build_lookup.py's own constants point at, for the one
    "bangkok-christmas" supplier these tests use."""
    monkeypatch.setattr(config, "VENDOR_PRICELISTS_DIR", tmp_path)
    monkeypatch.setattr(
        config, "VENDOR_SUPPLIERS",
        {"bangkok-christmas": {"label": "Bangkok Christmas", "book": "Bangkok Christmas"}},
    )
    vendor_dir = tmp_path / "bangkok-christmas"
    (vendor_dir / "source").mkdir(parents=True)
    (vendor_dir / "cleaned").mkdir(parents=True)
    lookup_path = vendor_dir / "cleaned" / "lookup.json"
    lookup_path.write_text("{}", encoding="utf-8")
    # parse_script/build_script (from _paths_for) stay pointed at the real repo files — every
    # test here mocks subprocess.run, so those paths are never actually executed, only
    # pattern-matched by name (see fake_run below); only source_dir is load-bearing
    # (import_pricelist writes the uploaded PDF there and checks it for a name collision).
    monkeypatch.setattr(
        vendor_admin, "_build_lookup_paths",
        lambda build_script: (vendor_dir / "cleaned" / "all-products.csv", lookup_path),
    )
    vendor_lookup.refresh()
    yield vendor_dir
    vendor_lookup.refresh()


def fake_pdf_bytes():
    return b"%PDF-1.4\n%fake pdf for tests\n"


def test_import_rejects_an_unconfigured_supplier(temp_vendor_dir):
    with pytest.raises(ValidationError):
        vendor_admin.import_pricelist("no-such-supplier", fake_pdf_bytes(), "list.pdf")


def test_import_rejects_a_non_pdf_extension(temp_vendor_dir):
    with pytest.raises(ValidationError):
        vendor_admin.import_pricelist("bangkok-christmas", fake_pdf_bytes(), "list.csv")


def test_import_rejects_bytes_that_are_not_really_a_pdf(temp_vendor_dir):
    with pytest.raises(ValidationError):
        vendor_admin.import_pricelist("bangkok-christmas", b"just some text", "list.pdf")


def test_import_rejects_a_filename_that_already_exists(temp_vendor_dir):
    (temp_vendor_dir / "source" / "list.pdf").write_bytes(fake_pdf_bytes())
    with pytest.raises(ValidationError):
        vendor_admin.import_pricelist("bangkok-christmas", fake_pdf_bytes(), "list.pdf")


def test_import_runs_the_two_scripts_and_reports_a_diff(temp_vendor_dir, monkeypatch):
    lookup_path = temp_vendor_dir / "cleaned" / "lookup.json"
    lookup_path.write_text(json.dumps({"071-11": {"price": 89.0}}), encoding="utf-8")

    calls = []

    class FakeResult:
        returncode = 0
        stdout = "wrote 2 codes"
        stderr = ""

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if "build_lookup.py" in cmd[1]:
            # simulate build_lookup.py rewriting lookup.json from the new CSV
            lookup_path.write_text(
                json.dumps({"071-11": {"price": 95.0}, "071-12": {"price": 45.0}}),
                encoding="utf-8",
            )
        return FakeResult()

    monkeypatch.setattr("backend.services.vendor_admin.subprocess.run", fake_run)

    result = vendor_admin.import_pricelist("bangkok-christmas", fake_pdf_bytes(), "list.pdf")

    assert len(calls) == 2  # parse_pricelist.py, then build_lookup.py
    assert result["added"] == 1     # 071-12
    assert result["changed"] == 1   # 071-11's price moved
    assert result["removed"] == 0
    assert result["total_codes"] == 2
    assert (temp_vendor_dir / "source" / "list.pdf").is_file()


def test_import_surfaces_a_parse_failure(temp_vendor_dir, monkeypatch):
    class FakeResult:
        returncode = 1
        stdout = ""
        stderr = "pypdf blew up"

    monkeypatch.setattr("backend.services.vendor_admin.subprocess.run", lambda cmd, **kw: FakeResult())

    with pytest.raises(ValidationError, match="pypdf"):
        vendor_admin.import_pricelist("bangkok-christmas", fake_pdf_bytes(), "list.pdf")


def test_import_does_not_count_an_overridden_code_as_changed(temp_vendor_dir, monkeypatch):
    """The diff is against the base file, not the merged (base+overlay) view — a shop's own
    correction reproduced verbatim by the new base must not read as "changed"."""
    lookup_path = temp_vendor_dir / "cleaned" / "lookup.json"
    lookup_path.write_text(json.dumps({"071-11": {"price": 89.0}}), encoding="utf-8")
    vendor_overlay.set_fields("071-11", {"price": 120.0}, speaks_for=("price",))

    class FakeResult:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(cmd, **kwargs):
        if "build_lookup.py" in cmd[1]:
            lookup_path.write_text(json.dumps({"071-11": {"price": 95.0}}), encoding="utf-8")
        return FakeResult()

    monkeypatch.setattr("backend.services.vendor_admin.subprocess.run", fake_run)

    result = vendor_admin.import_pricelist("bangkok-christmas", fake_pdf_bytes(), "list.pdf")

    assert result["changed"] == 1  # the base's own price did move, 89 -> 95
    assert vendor_lookup.price_for("071-11") == 120.0  # but the shop's override still wins
