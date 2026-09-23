"""Mounted: a wreath or banner attaches flat to a wall or door backdrop (issue #23).

A wreath belongs on a door, not hanging off a branch, and an ornament belongs on a branch,
not stuck to a wall. The picker stops offering the wrong ones, and prepare refuses them even
if something gets past it.
"""

import pytest

from backend import config
from backend.services import catalog, catalog_admin

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


def stock():
    add("TREE-1", "tree")
    add("BALL-1", "baubles")
    add("WREATH-1", "wreath")


# ---- the rule itself (unit) ----


def test_a_tree_backdrop_takes_everything_except_mounted():
    assert catalog.suits_backdrop("ornament", "tree") is True
    assert catalog.suits_backdrop("garland", "tree") is True
    assert catalog.suits_backdrop("giftbox", "tree") is True
    assert catalog.suits_backdrop("light", "tree") is True  # no placement, unchanged from today
    assert catalog.suits_backdrop("wreath", "tree") is False
    assert catalog.suits_backdrop("banner", "tree") is False


def test_a_wall_backdrop_takes_only_mounted():
    assert catalog.suits_backdrop("wreath", "wall") is True
    assert catalog.suits_backdrop("banner", "wall") is True
    assert catalog.suits_backdrop("ornament", "wall") is False
    assert catalog.suits_backdrop("garland", "wall") is False
    assert catalog.suits_backdrop("giftbox", "wall") is False
    assert catalog.suits_backdrop("light", "wall") is False


def test_an_uncategorised_product_is_offered_on_either_backdrop():
    """A photo the shop uploaded itself has no category to judge — refusing it would take
    away the manual path that has always worked."""
    assert catalog.suits_backdrop(None, "tree") is True
    assert catalog.suits_backdrop(None, "wall") is True


# ---- prepare refuses a mismatched pick ----


def test_a_wreath_is_refused_on_a_tree(client, temp_catalog, fake_gen, fake_rembg):
    stock()
    response = prepare(client, element=cut(client), element_code="WREATH-1")

    assert response.status_code == 422
    assert "ผนัง" in response.json()["error"]
    assert fake_gen.count == 0


def test_an_ornament_is_refused_on_a_wall(client, temp_catalog, fake_gen, fake_rembg):
    stock()
    response = prepare(
        client, element=cut(client), element_code="BALL-1", backdrop="wall", tree_code=""
    )

    assert response.status_code == 422
    assert fake_gen.count == 0


def test_a_wreath_is_accepted_on_a_wall(client, temp_catalog, fake_gen, fake_rembg):
    """A wall or door is the shop's own photo, not a catalogue product, so there is no
    backdrop code to pair the element's code with — the tree's all-or-nothing rule cannot
    apply here."""
    stock()
    response = prepare(
        client, element=cut(client), element_code="WREATH-1", backdrop="wall", tree_code=""
    )

    assert response.status_code == 200, response.text


def test_a_wall_takes_more_than_one_mounted_item(client, temp_catalog, fake_gen, fake_rembg):
    """Nothing in the domain modelling ruled out a wreath and a banner together (#18)."""
    stock()
    add("BANNER-1", "blessing banner")
    response = prepare(
        client,
        element=[cut(client), cut(client)],
        element_code=["WREATH-1", "BANNER-1"],
        backdrop="wall",
        tree_code="",
    )

    assert response.status_code == 200, response.text
    assert response.json()["element_count"] == 2


def test_a_wall_carries_no_backdrop_code(client, temp_catalog, conn, fake_gen, fake_rembg):
    """A wall or door is the shop's own photo — a code sent for it anyway is dropped rather
    than stored unvalidated."""
    from backend.models import request_log

    stock()
    request_id = prepare(
        client, element=cut(client), element_code="WREATH-1", backdrop="wall",
        tree_code="NOT-A-REAL-CODE",
    ).json()["request_id"]

    assert request_log.get(conn, request_id)["tree_code"] is None


def test_an_uncoded_upload_still_works_on_either_backdrop(client, temp_catalog, fake_gen, fake_rembg):
    stock()
    for backdrop in config.BACKDROPS:
        response = prepare(client, element=cut(client), backdrop=backdrop, tree_code="")
        assert response.status_code == 200, response.text


# ---- the picker only offers what fits ----


def test_the_picker_hides_mounted_categories_on_a_tree(client, temp_catalog):
    stock()
    results = client.get("/api/catalog/search?backdrop=tree").json()["results"]

    offered = {r["category"] for r in results}
    assert "ornament" in offered
    assert "wreath" not in offered


def test_the_picker_shows_only_mounted_categories_on_a_wall(client, temp_catalog):
    stock()
    results = client.get("/api/catalog/search?backdrop=wall").json()["results"]

    offered = {r["category"] for r in results}
    assert offered == {"wreath"}


def test_searching_by_code_respects_the_backdrop_too(client, temp_catalog):
    """The query path filters separately from the browse path — both need the same rule."""
    stock()
    results = client.get("/api/catalog/search?q=WREATH&backdrop=tree").json()["results"]

    assert results == []


def test_the_category_filter_list_follows_the_backdrop(client, temp_catalog):
    stock()
    tree = {c["key"] for c in client.get("/api/catalog/categories?backdrop=tree").json()["categories"]}
    wall = {c["key"] for c in client.get("/api/catalog/categories?backdrop=wall").json()["categories"]}

    assert "wreath" not in tree and "ornament" in tree
    assert wall == {"wreath"}


def test_no_backdrop_given_browses_everything_as_before(client, temp_catalog):
    """The tree picker and any other caller that never asked about backdrops keep seeing the
    whole catalogue — this filter is opt-in."""
    stock()
    results = client.get("/api/catalog/search").json()["results"]

    assert {"ornament", "wreath", "tree"} <= {r["category"] for r in results}


# ---- what the generator is told ----


def test_a_mounted_element_is_told_to_mount_flat(client, temp_catalog, conn, fake_gen, fake_rembg):
    stock()
    request_id = prepare(
        client, element=cut(client), element_code="WREATH-1", backdrop="wall", tree_code=""
    ).json()["request_id"]

    client.post(f"/api/generate/{request_id}")

    from backend.services import image_gen

    # exactly what generate() was handed, rendered the way generate() renders it
    (_tree, elements, _w, _h, scale, reference, density, placement, backdrop) = fake_gen.calls[0][0]
    prompt = image_gen.load_prompt(
        scale, len(elements), reference is not None, density, placement, backdrop
    )
    assert "Mount each copy flat against the wall or door surface" in prompt
    assert "hanging from an existing" not in prompt
    # the scale sentence is the last place a tree could sneak into a wall prompt
    assert "tree" not in prompt.lower()
