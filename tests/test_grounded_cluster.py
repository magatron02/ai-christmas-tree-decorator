"""Grounded: gift boxes and figures cluster at the tree's foot, separate from the hung recipe
(issue #21).

A gift box has been sitting inside AUTO_RECIPE since it was written, sharing the hung
"distribute over the whole tree / hang from a branch" instruction with ornaments and bells —
every auto-picked gift box has been generated as if nailed to a branch. These tests check the
prompt says something different for it, and that its own count is a pool of its own.
"""

import pytest

from backend import config
from backend.services import catalog, catalog_admin, image_gen
from backend.validation import ValidationError

from helpers import png_bytes, upload


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


def add(code, section):
    catalog_admin.add_product(code, "2 m.", section, "2026", png_bytes())


def cut(client):
    return client.post("/api/remove-bg", files=[upload(png_bytes(), "element.png")]).json()["element"]


def prepare(client, **extra):
    data = {"size": "4:5", "tree_code": "TREE-1", **extra}
    return client.post("/api/prepare", files=[upload(png_bytes(), "tree.png")], data=data)


# ---- catalog.placement_of (built in #19, exercised here) ----


def test_giftbox_and_figure_are_grounded():
    assert catalog.placement_of("giftbox") == "grounded"
    assert catalog.placement_of("figure") == "grounded"


# ---- describe_placement / describe_element_density (unit) ----


def test_a_grounded_element_gets_a_cluster_instruction_naming_its_image_number():
    # image 1 is the tree, so the grounded item (the 2nd decoration) is image 3
    elements = [{"code": "017-06", "placement": "hung"}, {"code": "BOX-1", "placement": "grounded"}]
    note = image_gen.describe_placement(elements)
    assert "image 3" in note
    assert "foot of the tree" in note
    assert "ignore the rules above" in note  # it is exempted, not additionally hung


def test_a_grounded_elements_density_is_ignored_when_mixed_with_hung():
    elements = [
        {"code": "017-06", "placement": "hung", "density": "light"},
        {"code": "BOX-1", "placement": "grounded", "density": "full"},
    ]
    assert image_gen.describe_element_density(elements) == config.DENSITY_PRESETS["light"]


def test_a_generation_with_both_a_wrapped_and_a_grounded_element_gets_both_notes():
    elements = [
        {"code": "BALL-1", "placement": "hung"},
        {"code": "GARLAND-1", "placement": "wrapped"},
        {"code": "BOX-1", "placement": "grounded"},
    ]
    note = image_gen.describe_placement(elements)
    assert "image 3" in note and "trunk" in note
    assert "image 4" in note and "foot of the tree" in note


# ---- HTTP seam: the two ceilings are independent ----


def test_ten_hung_and_one_grounded_together_are_accepted(client, temp_catalog, fake_gen, fake_rembg):
    """The regression this issue asks for: a full hung recipe plus a grounded item does not
    trip MAX_ELEMENTS, because the grounded item was never counted against it."""
    add("TREE-1", "tree")
    codes = []
    for i in range(config.MAX_ELEMENTS):
        add(f"BALL-{i}", "baubles")
        codes.append(f"BALL-{i}")
    add("BOX-1", "gift box")
    codes.append("BOX-1")

    response = prepare(
        client,
        element=[cut(client) for _ in codes],
        element_code=codes,
    )
    assert response.status_code == 200, response.text
    assert response.json()["element_count"] == config.MAX_ELEMENTS + 1


def test_exceeding_the_hung_ceiling_alone_is_still_refused(client, temp_catalog, fake_gen, fake_rembg):
    add("TREE-1", "tree")
    codes = []
    for i in range(config.MAX_ELEMENTS + 1):
        add(f"BALL-{i}", "baubles")
        codes.append(f"BALL-{i}")

    response = prepare(client, element=[cut(client) for _ in codes], element_code=codes)
    assert response.status_code == 422
    assert "ของแขวนต้น" in response.json()["error"]


def test_exceeding_the_grounded_ceiling_is_refused(client, temp_catalog, fake_gen, fake_rembg):
    add("TREE-1", "tree")
    codes = []
    for i in range(config.MAX_GROUNDED + 1):
        add(f"BOX-{i}", "gift box")
        codes.append(f"BOX-{i}")

    response = prepare(client, element=[cut(client) for _ in codes], element_code=codes)
    assert response.status_code == 422
    assert "ของตั้งพื้น" in response.json()["error"]


def test_the_generator_is_told_to_cluster_the_giftbox_at_the_foot(
    client, temp_catalog, conn, fake_gen, fake_rembg
):
    add("TREE-1", "tree")
    add("BALL-1", "baubles")
    add("BOX-1", "gift box")
    request_id = prepare(
        client,
        element=[cut(client), cut(client)],
        element_code=["BALL-1", "BOX-1"],
    ).json()["request_id"]

    client.post(f"/api/generate/{request_id}")

    placement_notes = fake_gen.calls[0][0][7]
    assert "foot of the tree" in placement_notes
    assert "image 3" in placement_notes


def test_direct_function_rejects_an_unknown_code():
    with pytest.raises(ValidationError):
        catalog.placement_of_code("99999-9")
