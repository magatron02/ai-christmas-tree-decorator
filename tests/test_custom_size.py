""""Match the scene photo's own ratio" end to end — a shop with a room photo picks "auto"
instead of one of the five fixed presets (Product.md, user request)."""

from backend import validation

from helpers import png_bytes, upload


def test_prepare_resolves_auto_into_a_literal_size(client, conn, fake_gen, fake_rembg):
    cut = client.post("/api/remove-bg", files=[upload(png_bytes(), "element.png")])
    prepared = client.post(
        "/api/prepare",
        files=[upload(png_bytes(), "tree.png")],
        data={
            "element": [cut.json()["element"]],
            "size": "auto",
            "scene_ratio": "1.5",
        },
    )

    assert prepared.status_code == 200, prepared.text
    body = prepared.json()
    assert body["size"] not in ("auto",)
    assert "x" in body["size"]
    width, height = (int(part) for part in body["size"].split("x"))
    assert (width, height) == (body["width"], body["height"])


def test_generate_re_resolves_the_stored_literal_size(client, conn, fake_gen, fake_rembg):
    cut = client.post("/api/remove-bg", files=[upload(png_bytes(), "element.png")])
    prepared = client.post(
        "/api/prepare",
        files=[upload(png_bytes(), "tree.png")],
        data={
            "element": [cut.json()["element"]],
            "size": "auto",
            "scene_ratio": "0.5",
        },
    )
    assert prepared.status_code == 200, prepared.text
    expected_width, expected_height = prepared.json()["width"], prepared.json()["height"]

    client.post(f"/api/generate/{prepared.json()['request_id']}")

    width, height, *_rest = fake_gen.calls[0][0][2:]
    assert (width, height) == (expected_width, expected_height)


def test_auto_without_a_scene_ratio_is_refused(client, conn, fake_gen, fake_rembg):
    cut = client.post("/api/remove-bg", files=[upload(png_bytes(), "element.png")])
    prepared = client.post(
        "/api/prepare",
        files=[upload(png_bytes(), "tree.png")],
        data={"element": [cut.json()["element"]], "size": "auto"},
    )

    assert prepared.status_code == 422
    assert fake_gen.count == 0


def test_a_preset_key_still_works_unchanged(client, conn, fake_gen, fake_rembg):
    cut = client.post("/api/remove-bg", files=[upload(png_bytes(), "element.png")])
    prepared = client.post(
        "/api/prepare",
        files=[upload(png_bytes(), "tree.png")],
        data={"element": [cut.json()["element"]], "size": "1:1"},
    )

    assert prepared.status_code == 200, prepared.text
    assert prepared.json()["size"] == "1:1"
    assert (prepared.json()["width"], prepared.json()["height"]) == validation.resolve_size("1:1")
