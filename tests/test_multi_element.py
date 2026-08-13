"""One to five decorations in one picture — Product.md 8.2.

The risk this suite is about is quiet loss. A second or fifth decoration that gets dropped
somewhere between the form and the API produces a perfectly good-looking image of the wrong
thing, at full price, with nothing failing.
"""

import pytest

from backend import config
from backend.models import request_log
from backend.services import image_gen, storage

from helpers import png_bytes, upload


def cut_out(client, n=1):
    """Background-remove n decorations, one call each, and return their tokens."""
    tokens = []
    for _ in range(n):
        response = client.post("/api/remove-bg", files=[upload(png_bytes(), "element.png")])
        assert response.status_code == 200, response.text
        tokens.append(response.json()["element"])
    return tokens


def prepare(client, tokens, **extra):
    return client.post(
        "/api/prepare",
        files=[upload(png_bytes(), "tree.png")],
        data={"element": tokens, "size": "4:5", **extra},
    )


@pytest.mark.parametrize("count", [1, 2, 3, 5])
def test_between_one_and_five_decorations_all_reach_the_api(
    client, conn, fake_gen, fake_rembg, count
):
    tokens = cut_out(client, count)
    ready = prepare(client, tokens)
    assert ready.status_code == 200, ready.text
    assert ready.json()["element_count"] == count

    client.post(f"/api/generate/{ready.json()['request_id']}")

    element_images = fake_gen.calls[0][0][1]
    assert len(element_images) == count, "a decoration went missing on the way to the API"


def test_six_is_refused(client, fake_gen, fake_rembg):
    response = prepare(client, cut_out(client, 6))

    assert response.status_code == 422
    assert "มากสุด 5" in response.json()["error"]
    assert fake_gen.count == 0


def test_zero_is_refused(client, fake_gen, fake_rembg):
    response = prepare(client, [])

    assert response.status_code == 422
    assert fake_gen.count == 0


def test_the_same_decoration_twice_is_refused(client, fake_gen, fake_rembg):
    token = cut_out(client, 1)[0]

    response = prepare(client, [token, token])

    assert response.status_code == 422
    assert "ซ้ำ" in response.json()["error"]


def test_every_decoration_is_recorded_on_the_request(client, conn, fake_gen, fake_rembg):
    tokens = cut_out(client, 3)
    request_id = prepare(client, tokens).json()["request_id"]

    elements = request_log.elements_of(request_log.get(conn, request_id))

    assert [e["path"] for e in elements] == tokens


def test_the_prompt_says_how_many_decorations_there_are(client, conn, fake_gen, fake_rembg):
    """The template used to say 'the second image'. With four decorations that sentence is
    an instruction to ignore three of them."""
    single = image_gen.load_prompt("scale text", 1)
    several = image_gen.load_prompt("scale text", 4)

    assert "The second image is the decoration" in single
    assert "The 4 images after the first" in several
    assert "Use all 4 kinds" in several


def test_a_template_missing_the_elements_placeholder_is_refused(monkeypatch, tmp_path):
    broken = tmp_path / "prompt.txt"
    broken.write_text("Decorate the tree. {scale}", encoding="utf-8")
    monkeypatch.setattr(config, "PROMPT_PATH", broken)

    with pytest.raises(image_gen.ImageGenError) as caught:
        image_gen.load_prompt("anything", 3)
    assert "{elements}" in str(caught.value)


def test_each_decoration_keeps_its_own_size_in_the_prompt(client, conn, fake_gen, fake_rembg):
    tokens = cut_out(client, 2)
    ready = prepare(
        client, tokens, tree_code="05021-1", element_code=["017-06", "018-02"]
    )
    assert ready.status_code == 200, ready.text
    client.post(f"/api/generate/{ready.json()['request_id']}")

    scale = fake_gen.calls[0][0][4]
    assert "80 mm across, one 19th" in scale
    assert "40 mm across, one 38th" in scale


def test_codes_are_all_or_nothing(client, fake_gen, fake_rembg):
    """Two decorations, one code. Sizing one and guessing the other is exactly the mixed
    state NonGoals 8 rules out."""
    response = prepare(
        client, cut_out(client, 2), tree_code="05021-1", element_code=["017-06"]
    )

    assert response.status_code == 422
    assert "ใส่รหัสให้ครบทุกชิ้น" in response.json()["error"]
    assert fake_gen.count == 0


def test_pruning_keeps_every_decoration_of_a_live_request(conn, tmp_path):
    """prune used to read only element_path, which holds the first decoration. The others
    looked like orphans, so cleaning up would have deleted the inputs of a request that
    still exists."""
    import os
    import time

    names = []
    for n in range(3):
        name = f"{n:032x}_element.png"
        path = config.STORAGE_DIR / name
        path.write_bytes(b"x")
        old = time.time() - 48 * 3600
        os.utime(path, (old, old))
        names.append(name)

    request_id = request_log.create(
        conn, "a_tree.png", [{"path": n} for n in names], "4:5"
    )
    request_log.claim(conn, request_id)
    request_log.mark_success(conn, request_id, "c_output.png", {"total_tokens": 1})

    _, removed = storage.prune(conn, older_than_hours=0)

    assert removed == []
    assert all((config.STORAGE_DIR / name).exists() for name in names)
