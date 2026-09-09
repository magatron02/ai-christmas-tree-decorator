"""Reference images — Product.md 8.3a, the setting half.

A reference photo changes what the prompt asks for, not just what it is given: with one,
replacing the background with that photo's own pixels is the point. Without one the
background is handled by whichever no-reference rule applies (a tree goes on white since
issue #30 — see tests/test_white_background.py). Whatever the two rules say, only one of them
may be in a prompt at a time: a stale "keep the setting exactly" line sitting under a "put it
somewhere new" line is the kind of contradiction that produces a plausible image of the wrong
thing at full price.
"""

import pytest

from backend import config
from backend.models import request_log
from backend.services import image_gen, storage

from helpers import png_bytes, upload


def prepare(client, **extra):
    cut = client.post("/api/remove-bg", files=[upload(png_bytes(), "element.png")])
    return client.post(
        "/api/prepare",
        files=[upload(png_bytes(), "tree.png")],
        data={"element": cut.json()["element"], "size": "4:5", **extra},
    )


def upload_reference(client):
    response = client.post("/api/reference", files=[upload(png_bytes(), "shop.png")])
    assert response.status_code == 200, response.text
    return response.json()["reference"]


def test_a_reference_is_optional(client, conn, fake_gen, fake_rembg):
    response = prepare(client)

    assert response.status_code == 200
    assert response.json()["reference_url"] is None


def test_a_reference_is_stored_and_recorded(client, conn, fake_gen, fake_rembg):
    name = upload_reference(client)

    response = prepare(client, reference=name)

    assert response.status_code == 200, response.text
    assert response.json()["reference_url"] == f"/files/{name}"
    assert request_log.get(conn, response.json()["request_id"])["reference_path"] == name


def test_the_reference_is_not_background_removed(client, fake_rembg):
    """A decoration gets cut out; a reference must not, because its background is the only
    thing being taken from it."""
    upload_reference(client)

    assert fake_rembg.count == 0


def test_the_reference_goes_last_so_the_prompt_can_point_at_it(
    client, conn, fake_gen, fake_rembg
):
    name = upload_reference(client)
    request_id = prepare(client, reference=name).json()["request_id"]

    client.post(f"/api/generate/{request_id}")

    args = fake_gen.calls[0][0]
    assert args[5] is not None, "the reference never reached the generator"


def test_without_a_reference_the_prompt_never_mentions_one():
    """What this file is really about: the two paths' instructions must never bleed into each
    other. A tree with no reference now gets a white backdrop rather than its own shop kept
    exactly (issue #30, tests/test_white_background.py) — but either way, nothing about a
    reference photo may appear in a prompt that was never given one."""
    prompt = image_gen.load_prompt("scale", 1, has_reference=False)

    assert "reference" not in prompt.lower()


def test_with_a_reference_the_prompt_keeps_the_reference_exactly():
    """Reworded from an earlier "take only the mood" design: the shop wants its actual room
    photo untouched, with only the decorated tree added — not a new scene "of that kind"."""
    prompt = image_gen.load_prompt("scale", 1, has_reference=True)

    assert "keep it exactly as it is" in prompt
    assert "composite the decorated tree into these actual pixels" in prompt
    assert "The last image is a reference for the setting" not in prompt, (
        "the old mood-only wording must not still be present alongside the new one"
    )


def test_the_reference_prompt_only_relights_the_tree():
    """The reference photo's own furniture/objects are now deliberately kept — the opposite
    of the old "do not copy any object" instruction, which asked the model to repaint them
    away. Only the tree may be touched."""
    prompt = image_gen.load_prompt("scale", 1, has_reference=True)

    assert "Relight only the tree" in prompt
    assert "Do not relight, move, add to, or remove anything else" in prompt
    assert "Do not copy any object" not in prompt, "that instruction described the old design"


def test_a_template_missing_the_scene_placeholder_is_refused(monkeypatch, tmp_path):
    broken = tmp_path / "prompt.txt"
    broken.write_text("Decorate. {elements} {scale}", encoding="utf-8")
    monkeypatch.setattr(config, "PROMPT_PATH", broken)

    with pytest.raises(image_gen.ImageGenError) as caught:
        image_gen.load_prompt("anything", 1, True)
    assert "{scene}" in str(caught.value)


def test_a_forged_reference_name_is_rejected(client, fake_gen, fake_rembg):
    response = prepare(client, reference="../../../etc/passwd")

    assert response.status_code == 422
    assert "ไม่รู้จักไฟล์" in response.json()["error"]


def test_pruning_keeps_the_reference_of_a_live_request(client, conn, fake_gen, fake_rembg):
    """A reference is an input like any other: deleting it under a request that still exists
    would break the record of what was actually asked for."""
    name = upload_reference(client)
    request_id = prepare(client, reference=name).json()["request_id"]
    request_log.claim(conn, request_id)
    request_log.mark_success(conn, request_id, "c_output.png", {"total_tokens": 1})

    _, removed = storage.prune(conn, older_than_hours=0)

    assert (config.STORAGE_DIR / name) not in removed
    assert (config.STORAGE_DIR / name).exists()
