"""/api/count/{request_id} — exact per-code counts from the finished picture.

vision.count_decorations() is fed each accepted element's own cut-out back in as a labelled
reference photo, so a count is attributed to a catalogue code rather than a free-text guess
the caller has no way to price. This only checks the endpoint's own plumbing (which codes it
builds references for, and how it reshapes the result) — the vision call itself is faked, same
as fake_gen fakes the paid image call elsewhere.
"""

import pytest

from backend import config
from backend.services import catalog, catalog_admin, vision

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


def cut_out(client, n=1):
    tokens = []
    for _ in range(n):
        response = client.post("/api/remove-bg", files=[upload(png_bytes(), "element.png")])
        assert response.status_code == 200, response.text
        tokens.append(response.json()["element"])
    return tokens


def prepare_and_generate(client, tokens, **extra):
    prepared = client.post(
        "/api/prepare",
        files=[upload(png_bytes(), "tree.png")],
        data={"element": tokens, "size": "4:5", **extra},
    )
    assert prepared.status_code == 200, prepared.text
    request_id = prepared.json()["request_id"]
    response = client.post(f"/api/generate/{request_id}")
    assert response.status_code == 200, response.text
    return request_id


FAKE_COUNT_USAGE = {"input_tokens": 200, "output_tokens": 40, "total_tokens": 240}


def test_count_builds_one_reference_per_coded_element(
    client, conn, fake_gen, fake_rembg, monkeypatch, temp_catalog
):
    from conftest import Spy

    catalog_admin.add_product("TREE1", "150 cm.", "tree", "2026", png_bytes())
    catalog_admin.add_product("E001", "80 mm.", "ornament", "2026", png_bytes(), price="150")

    tokens = cut_out(client, 1)
    request_id = prepare_and_generate(client, tokens, tree_code="TREE1", element_code=["E001"])

    fake_counted = vision.DecorationCounts(items=[vision.CountedItem(code="E001", count=7)])
    spy = Spy(result=(fake_counted, FAKE_COUNT_USAGE))
    monkeypatch.setattr(vision, "count_decorations", spy)

    response = client.post(f"/api/count/{request_id}")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["items"] == [{"code": "E001", "count": 7}]
    assert body["usage"] == FAKE_COUNT_USAGE

    assert spy.count == 1
    (_output_bytes, references), _kwargs = spy.calls[0]
    codes = [ref[0] for ref in references]
    mimes = [ref[2] for ref in references]
    assert codes == ["E001"]
    assert mimes == ["image/png"]


def test_count_result_is_persisted_and_shows_up_on_a_later_read(
    client, conn, fake_gen, fake_rembg, monkeypatch, temp_catalog
):
    """request_log.set_counted() — a later /api/request/{id} (the "จัดการต่อ" resume read)
    must see the same count without a second billed vision call."""
    from conftest import Spy

    catalog_admin.add_product("TREE1", "150 cm.", "tree", "2026", png_bytes())
    catalog_admin.add_product("E001", "80 mm.", "ornament", "2026", png_bytes(), price="150")

    tokens = cut_out(client, 1)
    request_id = prepare_and_generate(client, tokens, tree_code="TREE1", element_code=["E001"])

    # before counting, a fresh read has nothing to replay
    before = client.get(f"/api/request/{request_id}")
    assert before.json()["counted_items"] is None

    fake_counted = vision.DecorationCounts(items=[vision.CountedItem(code="E001", count=7)])
    monkeypatch.setattr(vision, "count_decorations", Spy(result=(fake_counted, FAKE_COUNT_USAGE)))
    counted = client.post(f"/api/count/{request_id}")
    assert counted.status_code == 200, counted.text

    after = client.get(f"/api/request/{request_id}")
    assert after.json()["counted_items"] == [{"code": "E001", "count": 7}]


def test_a_second_count_overwrites_the_first(
    client, conn, fake_gen, fake_rembg, monkeypatch, temp_catalog
):
    from conftest import Spy

    catalog_admin.add_product("TREE1", "150 cm.", "tree", "2026", png_bytes())
    catalog_admin.add_product("E001", "80 mm.", "ornament", "2026", png_bytes(), price="150")

    tokens = cut_out(client, 1)
    request_id = prepare_and_generate(client, tokens, tree_code="TREE1", element_code=["E001"])

    first = vision.DecorationCounts(items=[vision.CountedItem(code="E001", count=3)])
    monkeypatch.setattr(vision, "count_decorations", Spy(result=(first, FAKE_COUNT_USAGE)))
    client.post(f"/api/count/{request_id}")

    second = vision.DecorationCounts(items=[vision.CountedItem(code="E001", count=9)])
    monkeypatch.setattr(vision, "count_decorations", Spy(result=(second, FAKE_COUNT_USAGE)))
    client.post(f"/api/count/{request_id}")

    after = client.get(f"/api/request/{request_id}")
    assert after.json()["counted_items"] == [{"code": "E001", "count": 9}]


def test_count_refuses_a_request_with_no_coded_decorations(
    client, conn, fake_gen, fake_rembg, temp_catalog
):
    tokens = cut_out(client, 1)
    # no tree_code and no element_code — an own-photo tree and decoration, neither matched to
    # the catalogue (scale_sentence's all-or-nothing rule forbids a mixed half-set instead)
    request_id = prepare_and_generate(client, tokens)

    response = client.post(f"/api/count/{request_id}")

    assert response.status_code == 422, response.text


def test_count_before_generate_is_refused(client, conn, temp_catalog):
    tokens = cut_out(client, 1)
    prepared = client.post(
        "/api/prepare",
        files=[upload(png_bytes(), "tree.png")],
        data={"element": tokens, "size": "4:5"},
    )
    request_id = prepared.json()["request_id"]

    response = client.post(f"/api/count/{request_id}")

    assert response.status_code == 422, response.text
