"""Wrapped: a garland is always exactly one piece around the trunk (issue #20).

A garland is not several copies scattered over branches the way an ornament is — it wraps
once, and density has no meaning for it. These tests check the prompt actually says so, and
that a second garland in the same generation is refused before anything is billed.
"""

import pytest

from backend import config
from backend.services import catalog, catalog_admin, image_gen

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


# ---- describe_placement (unit) ----


def test_an_all_hung_generation_gets_no_placement_addendum():
    elements = [{"code": "017-06", "placement": "hung"}, {"code": "05021-1"}]
    assert image_gen.describe_placement(elements) == ""


def test_a_garland_gets_a_wrap_instruction_naming_its_image_number():
    # image 1 is always the tree, so the garland (the 2nd decoration) is image 3
    elements = [{"code": "017-06", "placement": "hung"}, {"code": "GARLAND-1", "placement": "wrapped"}]
    note = image_gen.describe_placement(elements)
    assert "image 3" in note
    assert "trunk" in note
    assert "garland" in note.lower()


# ---- load_prompt: byte-identical when nothing exceptional is present ----


def test_no_placement_argument_leaves_the_prompt_unchanged():
    prompt = image_gen.load_prompt("scale", 1)
    assert "{placement_notes}" not in prompt
    assert "\n\n\n" not in prompt


def test_a_placement_note_is_inserted_after_the_default_placement_rules():
    prompt = image_gen.load_prompt("scale", 2, placement="- wrap the garland around the trunk")
    assert "Work around the tree that is there" in prompt
    assert "- wrap the garland around the trunk" in prompt
    assert prompt.index("Work around the tree that is there") < prompt.index("wrap the garland")
    assert prompt.index("wrap the garland") < prompt.index("Density")


# ---- describe_element_density: a wrapped element has no density ----


def test_a_wrapped_elements_density_is_ignored_when_mixed_with_hung():
    elements = [
        {"code": "017-06", "placement": "hung", "density": "light"},
        {"code": "GARLAND-1", "placement": "wrapped", "density": "full"},
    ]
    assert image_gen.describe_element_density(elements) == config.DENSITY_PRESETS["light"]


def test_a_generation_of_only_a_garland_still_gets_a_density_sentence():
    elements = [{"code": "GARLAND-1", "placement": "wrapped", "density": "full"}]
    assert image_gen.describe_element_density(elements) == config.DENSITY_PRESETS[config.DEFAULT_DENSITY]


# ---- HTTP seam ----


def test_a_second_garland_is_refused(client, temp_catalog):
    add("TREE-1", "tree")
    add("GARLAND-1", "garland")
    add("GARLAND-2", "garland")
    response = prepare(
        client,
        element=[cut(client), cut(client)],
        element_code=["GARLAND-1", "GARLAND-2"],
    )
    assert response.status_code == 422
    assert "การ์แลนด์" in response.json()["error"]


def test_one_garland_alongside_a_hung_item_is_accepted(client, temp_catalog, fake_gen, fake_rembg):
    add("TREE-1", "tree")
    add("GARLAND-1", "garland")
    add("BALL-1", "baubles")
    response = prepare(
        client,
        element=[cut(client), cut(client)],
        element_code=["BALL-1", "GARLAND-1"],
    )
    assert response.status_code == 200, response.text


def test_the_generator_is_told_to_wrap_the_garland_not_hang_it(
    client, temp_catalog, conn, fake_gen, fake_rembg
):
    add("TREE-1", "tree")
    add("GARLAND-1", "garland")
    add("BALL-1", "baubles")
    request_id = prepare(
        client,
        element=[cut(client), cut(client)],
        element_code=["BALL-1", "GARLAND-1"],
    ).json()["request_id"]

    client.post(f"/api/generate/{request_id}")

    placement_notes = fake_gen.calls[0][0][7]
    assert "trunk" in placement_notes
    # image 1 is the tree, BALL-1 is image 2, GARLAND-1 (the 2nd decoration) is image 3
    assert "image 3" in placement_notes


def test_the_garlands_own_density_choice_does_not_affect_the_prompt(
    client, temp_catalog, conn, fake_gen, fake_rembg
):
    add("TREE-1", "tree")
    add("GARLAND-1", "garland")
    add("BALL-1", "baubles")
    request_id = prepare(
        client,
        element=[cut(client), cut(client)],
        element_code=["BALL-1", "GARLAND-1"],
        element_density=["light", "full"],
    ).json()["request_id"]

    client.post(f"/api/generate/{request_id}")

    density_sentence = fake_gen.calls[0][0][6]
    assert density_sentence == config.DENSITY_PRESETS["light"]
