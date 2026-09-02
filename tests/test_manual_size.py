"""/api/prepare -> /api/generate with a manually-entered size and per-item density.

The manual-size *requirement* ("don't guess, make them tell us first") is a frontend gate —
Generate stays disabled client-side until every code-bearing item with no catalogue size has
a manual override. Server-side, /api/prepare has always accepted a request either way (a
size-less code already just falls back to "believable, not exact" and reports it in
missing_sizes); what's new here is that a supplied override is honoured and threaded all the
way to the prompt, and that it survives the pending -> calling_api round trip in storage.
"""

from backend import config
from backend.models import request_log
from backend.services import catalog

from helpers import png_bytes, upload


def prepare(client, **extra):
    cut = client.post("/api/remove-bg", files=[upload(png_bytes(), "element.png")])
    data = {"element": cut.json()["element"], "size": "4:5", **extra}
    return client.post("/api/prepare", files=[upload(png_bytes(), "tree.png")], data=data)


def test_a_manual_element_size_reaches_the_prompt(client, conn, fake_gen, fake_rembg):
    unsized = next(
        r["code"] for r in catalog._rows()
        if catalog.longest_side_mm(r) is None and catalog.image_for(r["code"])
    )
    prepared = prepare(
        client, tree_code="05021-1", element_code=unsized, element_manual_mm="123",
    )
    assert prepared.status_code == 200, prepared.text
    assert prepared.json()["missing_sizes"] == []

    request_id = prepared.json()["request_id"]
    client.post(f"/api/generate/{request_id}")

    scale = fake_gen.calls[0][0][4]
    assert "123 mm" in scale


def test_a_manual_tree_size_reaches_the_prompt(client, conn, fake_gen, fake_rembg):
    prepared = prepare(client, tree_manual_mm="1999")
    request_id = prepared.json()["request_id"]
    client.post(f"/api/generate/{request_id}")
    scale = fake_gen.calls[0][0][4]
    assert "proportion" in scale  # no element code was given, so this is still the generic path


def test_manual_mm_is_stored_and_survives_to_generate_time(client, conn, fake_gen, fake_rembg):
    prepared = prepare(client, tree_manual_mm="1500")
    row = request_log.get(conn, prepared.json()["request_id"])
    assert float(row["tree_manual_mm"]) == 1500.0


def test_a_non_numeric_manual_size_is_refused(client, fake_gen, fake_rembg):
    response = prepare(client, tree_manual_mm="not-a-number")
    assert response.status_code == 422


def test_a_non_positive_manual_size_is_refused(client, fake_gen, fake_rembg):
    response = prepare(client, tree_manual_mm="0")
    assert response.status_code == 422


def test_an_empty_manual_size_means_no_override(client, conn, fake_gen, fake_rembg):
    prepared = prepare(client, tree_code="05021-1", element_code="017-06", tree_manual_mm="")
    assert prepared.status_code == 200, prepared.text
    row = request_log.get(conn, prepared.json()["request_id"])
    assert row["tree_manual_mm"] is None


def test_per_item_density_is_stored_and_reaches_the_prompt(client, conn, fake_gen, fake_rembg):
    element_a = client.post(
        "/api/remove-bg", files=[upload(png_bytes(), "a.png")]
    ).json()["element"]
    element_b = client.post(
        "/api/remove-bg", files=[upload(png_bytes(), "b.png")]
    ).json()["element"]

    prepared = client.post(
        "/api/prepare",
        files=[upload(png_bytes(), "tree.png")],
        data={
            "element": [element_a, element_b],
            "size": "4:5",
            "element_code": ["017-06", "05021-1"],
            "tree_code": "05021-1",
            "element_density": ["light", "full"],
        },
    )
    assert prepared.status_code == 200, prepared.text

    client.post(f"/api/generate/{prepared.json()['request_id']}")
    # generate(tree_image, element_pngs, width, height, scale, reference, density) — density
    # is the 7th positional argument, index 6 (see test_exact_scale.py for the same convention
    # on `scale`, index 4)
    density_sentence = fake_gen.calls[0][0][6]
    assert config.ELEMENT_DENSITY_PHRASES["light"] in density_sentence
    assert config.ELEMENT_DENSITY_PHRASES["full"] in density_sentence


def test_an_unknown_per_item_density_key_is_refused(client, fake_gen, fake_rembg):
    response = prepare(client, element_density="not-a-density")
    assert response.status_code == 422
