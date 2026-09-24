"""The settings page's catalogue table: every product, paged, with problem filters.

Unlike the picker's browse(), this has to list what the picker withholds — a product with no
photo, or a crop several codes claim — because fixing those is what the screen is for.
"""

import json

import pytest

from backend import config
from backend.services import catalog, catalog_admin

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
    catalog.refresh()
    yield tmp_path
    catalog.refresh()


def add(code, size="80 mm.", section="baubles", book="Shop A", price=None):
    catalog_admin.add_product(code, size, section, book, png_bytes(), price=price)


def codes(rows):
    return [row["code"] for row in rows]


def test_lists_every_product_with_a_total(temp_catalog):
    add("A-1")
    add("A-2")

    rows, total = catalog.admin_list()

    assert total == 2
    assert set(codes(rows)) == {"A-1", "A-2"}


def test_pages_through_the_list(temp_catalog):
    for n in range(5):
        add(f"P-{n}")

    first, total = catalog.admin_list(limit=2, offset=0)
    last, _ = catalog.admin_list(limit=2, offset=4)

    assert total == 5
    assert len(first) == 2 and len(last) == 1


def test_q_matches_part_of_a_code_or_the_section(temp_catalog):
    add("017-06", section="baubles")
    add("099-01", section="ribbons")

    assert codes(catalog.admin_list(q="017")[0]) == ["017-06"]
    assert codes(catalog.admin_list(q="ribbon")[0]) == ["099-01"]


def test_narrows_by_shop(temp_catalog):
    add("A-1", book="Shop A")
    add("B-1", book="Shop B")

    assert codes(catalog.admin_list(book="Shop B")[0]) == ["B-1"]


def test_no_price_filter(temp_catalog):
    add("PRICED", price="10")
    add("BARE")

    assert codes(catalog.admin_list(issue="no_price")[0]) == ["BARE"]


def test_no_size_filter(temp_catalog):
    add("SIZED", size="80 mm.")
    add("NOSIZE", size="")

    assert codes(catalog.admin_list(issue="no_size")[0]) == ["NOSIZE"]


def test_shared_photo_filter_finds_what_the_picker_withholds(temp_catalog):
    add("FINE")
    add("SHARED")
    images = temp_catalog / "product_images.json"
    rows = json.loads(images.read_text(encoding="utf-8"))
    for row in rows:
        row["shared_with"] = 3 if row["code"] == "SHARED" else 0
    images.write_text(json.dumps(rows), encoding="utf-8")
    catalog.refresh()

    assert codes(catalog.admin_list(issue="shared_photo")[0]) == ["SHARED"]
    # the picker hides it, the admin list still has it
    assert not catalog.crop_is_showable("SHARED")
    assert "SHARED" in codes(catalog.admin_list()[0])


def test_no_photo_filter(temp_catalog):
    add("HAS")
    add("NONE")
    images = temp_catalog / "product_images.json"
    rows = json.loads(images.read_text(encoding="utf-8"))
    for row in rows:
        if row["code"] == "NONE":
            row["image"] = None
    images.write_text(json.dumps(rows), encoding="utf-8")
    catalog.refresh()

    assert codes(catalog.admin_list(issue="no_photo")[0]) == ["NONE"]


def test_endpoint_returns_the_detail_shape_the_edit_form_takes(client, temp_catalog):
    add("017-06", price="99")

    body = client.get("/api/catalog/products", params={"q": "017"}).json()

    assert body["total"] == 1
    item = body["results"][0]
    assert item["code"] == "017-06" and item["price"] == 99.0
    assert {"image", "size_raw", "section", "book", "category", "overridden", "has_shop_photo"} <= set(item)


def test_endpoint_refuses_an_unknown_issue(client, temp_catalog):
    assert client.get("/api/catalog/products", params={"issue": "nonsense"}).status_code != 200
