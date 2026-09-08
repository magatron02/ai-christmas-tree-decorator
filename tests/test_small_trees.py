"""Small Christmas trees are no longer offered (issue #26).

The tree category runs down to 9 inches — desk ornaments the shop does not want offered as
something to decorate. The cut is computed from the printed size on every read, so a
re-import that corrects a size changes what is cut; nothing is stored, and nothing is deleted.
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
    catalog.refresh()
    yield products
    catalog.refresh()


def add(code, size_raw, section="tree"):
    catalog_admin.add_product(code, size_raw, section, "2026", png_bytes())


def codes(rows):
    return {row["code"] for row in rows}


# ---- the rule (unit) ----


def test_a_tree_at_or_under_the_line_is_not_offered(temp_catalog):
    add("TINY", "9 inc.")        # 229mm
    add("SMALL", "1 Ft.")        # 305mm
    add("EDGE", "1.5 Ft.")       # 457mm — the largest size the shop asked to cut
    catalog.refresh()

    for code in ("TINY", "SMALL", "EDGE"):
        assert catalog.is_offered(catalog.find(code)) is False


def test_a_tree_above_the_line_is_offered(temp_catalog):
    add("JUST-OVER", "2 Ft.")    # 610mm — the smallest size that stays on offer
    add("BIG", "7 Ft.")
    catalog.refresh()

    for code in ("JUST-OVER", "BIG"):
        assert catalog.is_offered(catalog.find(code)) is True


def test_a_tree_measured_by_its_width_is_not_cut_for_it():
    """The parser used to drop a height printed with its own unit (tests/test_catalog.py),
    which measured five 60-75cm trees by their diameter and cut four of them."""
    assert catalog.longest_side_mm({"size": catalog.parse_size("D 41 cm x H 75 cm")}) == 750


def test_the_line_sits_between_the_two_sizes_that_decide_it():
    """1.5 ft reads as 450mm and parses as 457mm — a line set at the number the shop said
    would have kept every one of them."""
    assert catalog.longest_side_mm({"size": catalog.parse_size("1.5 Ft.")}) < config.MIN_TREE_MM
    assert catalog.longest_side_mm({"size": catalog.parse_size("2 Ft.")}) > config.MIN_TREE_MM


def test_only_trees_are_cut(temp_catalog):
    """A 9-inch bauble is an ordinary product; a 9-inch tree is a desk ornament."""
    add("BAUBLE", "9 inc.", section="baubles")
    add("WREATH", "9 inc.", section="wreath")
    catalog.refresh()

    assert catalog.is_offered(catalog.find("BAUBLE")) is True
    assert catalog.is_offered(catalog.find("WREATH")) is True


def test_a_tree_with_no_parsable_size_is_not_cut(temp_catalog):
    """The app never invents a dimension (NonGoals.md 8), and will not guess one in order to
    hide something either."""
    add("NO-SIZE", "")
    catalog.refresh()

    assert catalog.longest_side_mm(catalog.find("NO-SIZE")) is None
    assert catalog.is_offered(catalog.find("NO-SIZE")) is True


def test_the_cut_follows_a_corrected_size(temp_catalog):
    """Nothing is stored, so a re-import that corrects a printed size changes what is cut."""
    add("GROWS", "1 Ft.")
    catalog.refresh()
    assert catalog.is_offered(catalog.find("GROWS")) is False

    # what a re-import does: the whole row rewritten from the book, parsed size and all
    rows = json.loads(temp_catalog.read_text(encoding="utf-8"))
    for row in rows:
        if row["code"] == "GROWS":
            row["size_raw"] = "6 Ft."
            row["size"] = catalog.parse_size("6 Ft.")
    temp_catalog.write_text(json.dumps(rows), encoding="utf-8")
    catalog.refresh()

    assert catalog.is_offered(catalog.find("GROWS")) is True


# ---- every surface the picker looks at ----


def test_browsing_does_not_offer_it(temp_catalog):
    add("SMALL", "1 Ft.")
    add("BIG", "7 Ft.")
    catalog.refresh()

    rows, total = catalog.browse(100, 0)

    assert codes(rows) == {"BIG"}
    assert total == 1


def test_searching_does_not_offer_it(client, temp_catalog):
    add("SMALL", "1 Ft.")
    add("BIG", "7 Ft.")
    catalog.refresh()

    results = client.get("/api/catalog/search?q=SMALL").json()["results"]

    assert results == []


def test_the_category_counts_do_not_include_it(client, temp_catalog):
    add("SMALL", "1 Ft.")
    add("BIG", "7 Ft.")
    catalog.refresh()

    categories = client.get("/api/catalog/categories").json()["categories"]
    trees = next(c for c in categories if c["key"] == "tree")

    assert trees["count"] == 1


def test_a_photo_match_does_not_offer_it_either(temp_catalog):
    """The photo-match index keeps codes, not rows, and used to ask only whether the crop was
    trustworthy — a cut tree could still come back through that side door."""
    add("SMALL", "1 Ft.")
    add("BIG", "7 Ft.")
    catalog.refresh()

    assert catalog.is_offered_code("SMALL") is False
    assert catalog.is_offered_code("BIG") is True


def test_a_code_the_catalogue_no_longer_has_is_simply_not_offered(temp_catalog):
    """That index is built ahead of time and outlives the rows it was built from."""
    assert catalog.is_offered_code("GONE-FOREVER") is False


def test_it_leaves_the_pricing_queue(temp_catalog):
    """No point pricing something the shop does not offer."""
    add("SMALL", "1 Ft.")
    add("BIG", "7 Ft.")
    catalog.refresh()

    assert codes(catalog.pricing_queue()) == {"BIG"}


# ---- nothing is destroyed ----


def test_the_product_is_kept_not_deleted(temp_catalog):
    add("SMALL", "1 Ft.")
    catalog.refresh()

    assert catalog.find("SMALL")["size_raw"] == "1 Ft."
    assert "SMALL" in temp_catalog.read_text(encoding="utf-8")
