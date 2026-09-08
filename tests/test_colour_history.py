"""Colour rides with the code into history and the worksheet (issue #16, ADR-0002).

"Code 4400-1" is not enough to pull stock when the product was shot in six colours — the
order is "4400-1, red". The colour name is resolved from the catalogue at /api/prepare time
(never trusted as freeform text from the browser) and travels with the code from there into
both the request record and /api/history.

Isolated fixtures throughout: colour names live in the shop overlay (issue #14), which every
test session sandboxes into its own temp data/ directory (tests/conftest.py) — the real
catalogue's own colour names are never visible here, by design.
"""

import pytest

from backend import config
from backend.models import request_log
from backend.services import catalog, catalog_admin

from helpers import png_bytes, upload


@pytest.fixture
def temp_catalog(tmp_path, monkeypatch):
    """Isolates the catalogue base only. DATA_DIR/DB_PATH/SHOP_PHOTOS_DIR are left at whatever
    conftest.py's session-wide sandbox already set — the `conn` fixture and the app's own
    request handling both resolve config.DB_PATH at call time, so repointing it again here
    would just make `conn` and the server look at two different files.
    """
    products = tmp_path / "products.json"
    products.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(catalog_admin, "PRODUCTS_PATH", products)
    monkeypatch.setattr(catalog_admin, "IMAGES_DIR", tmp_path / "images")
    monkeypatch.setattr(catalog_admin, "PRODUCT_IMAGES_PATH", tmp_path / "product_images.json")
    monkeypatch.setattr(config, "CATALOG_PATH", products)

    catalog_admin.add_product("TREE-1", "5 Ft.", "trees", "2026", png_bytes())
    catalog_admin.add_product("DECO-1", "80 mm.", "baubles", "2026", png_bytes())
    names = ["DECO-1--1.png", "DECO-1--2.png"]
    catalog.set_colour_split("DECO-1", names)
    catalog_admin.set_colour_name("DECO-1", names[0], "แดง")
    catalog.refresh()

    yield tmp_path
    catalog.refresh()


def prepare(client, **extra):
    cut = client.post("/api/remove-bg", files=[upload(png_bytes(), "element.png")])
    assert cut.status_code == 200, cut.text
    return client.post(
        "/api/prepare",
        files=[upload(png_bytes(), "tree.png")],
        data={"element": [cut.json()["element"]], "size": "4:5", **extra},
    )


def test_the_chosen_colour_is_recorded_on_the_request(
    client, conn, fake_gen, fake_rembg, temp_catalog
):
    ready = prepare(
        client, tree_code="TREE-1",
        element_code=["DECO-1"], element_image=["variants/DECO-1--1.png"],
    )
    assert ready.status_code == 200, ready.text

    elements = request_log.elements_of(request_log.get(conn, ready.json()["request_id"]))

    assert elements[0]["code"] == "DECO-1"
    assert elements[0]["colour"] == "แดง"


def test_history_shows_the_colour_beside_the_code(
    client, conn, fake_gen, fake_rembg, temp_catalog
):
    ready = prepare(
        client, tree_code="TREE-1",
        element_code=["DECO-1"], element_image=["variants/DECO-1--1.png"],
    )
    client.post(f"/api/generate/{ready.json()['request_id']}")

    history = client.get("/api/history").json()
    row = next(r for r in history["requests"] if r["request_id"] == ready.json()["request_id"])

    assert row["elements"][0]["code"] == "DECO-1"
    assert row["elements"][0]["colour"] == "แดง"


def test_an_element_with_no_image_records_no_colour(
    client, conn, fake_gen, fake_rembg, temp_catalog
):
    ready = prepare(client, tree_code="TREE-1", element_code=["DECO-1"])
    assert ready.status_code == 200, ready.text

    elements = request_log.elements_of(request_log.get(conn, ready.json()["request_id"]))

    assert elements[0]["colour"] is None


def test_an_unnamed_colour_records_no_colour(client, conn, fake_gen, fake_rembg, temp_catalog):
    """The second colour was split but never named — falls back to no colour, not a guess."""
    ready = prepare(
        client, tree_code="TREE-1",
        element_code=["DECO-1"], element_image=["variants/DECO-1--2.png"],
    )
    assert ready.status_code == 200, ready.text

    elements = request_log.elements_of(request_log.get(conn, ready.json()["request_id"]))

    assert elements[0]["colour"] is None


def test_an_image_that_is_not_this_codes_colour_records_no_colour(
    client, conn, fake_gen, fake_rembg, temp_catalog
):
    """The value arrives from the browser; a stale or tampered one must not produce an
    invented colour on the permanent record."""
    ready = prepare(
        client, tree_code="TREE-1",
        element_code=["DECO-1"], element_image=["variants/not-a-real-file.png"],
    )
    assert ready.status_code == 200, ready.text

    elements = request_log.elements_of(request_log.get(conn, ready.json()["request_id"]))

    assert elements[0]["colour"] is None


def test_an_element_with_no_code_records_no_colour(client, conn, fake_gen, fake_rembg):
    ready = prepare(client)
    assert ready.status_code == 200, ready.text

    elements = request_log.elements_of(request_log.get(conn, ready.json()["request_id"]))

    assert elements[0]["colour"] is None


def test_an_older_run_recorded_before_colours_existed_still_reads_back_fine(client, conn):
    """elements_of()/the history endpoint must not choke on a row whose elements never had a
    "colour" key at all — this predates the ticket's schema, not the shape being tested."""
    request_id = request_log.create(
        conn, "a_tree.png", [{"path": "old_element.png", "code": "DECO-1"}], "4:5",
    )
    request_log.claim(conn, request_id)
    request_log.mark_success(conn, request_id, "output.png", {"total_tokens": 1})

    history = client.get("/api/history").json()
    row = next(r for r in history["requests"] if r["request_id"] == request_id)

    assert row["elements"][0]["code"] == "DECO-1"
    assert row["elements"][0]["colour"] is None
