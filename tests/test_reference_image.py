"""Reference images — Product.md 8.3a, the setting half.

A reference photo changes what the prompt asks for, not just what it is given: without one
the background must survive untouched, with one replacing it is the point. Both instructions
cannot be in the prompt at once, and a stale "keep the setting exactly" line sitting under a
"put it somewhere new" line is the kind of contradiction that produces a plausible image of
the wrong thing at full price.
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


def test_without_a_reference_the_prompt_protects_the_background():
    prompt = image_gen.load_prompt("scale", 1, has_reference=False)

    assert "Keep the setting exactly as it is" in prompt
    assert "reference" not in prompt.lower()


def test_with_a_reference_the_prompt_asks_for_a_new_setting():
    prompt = image_gen.load_prompt("scale", 1, has_reference=True)

    assert "The last image is a reference for the setting" in prompt
    assert "Keep the setting exactly as it is" not in prompt, (
        "the two instructions contradict each other; only one may be present"
    )


def test_the_reference_prompt_forbids_copying_objects_from_it():
    """Taking the mood is the feature. Taking someone's furniture or their decorations is a
    different picture than the one that was asked for."""
    prompt = image_gen.load_prompt("scale", 1, has_reference=True)

    assert "Do not copy any object" in prompt
    assert "Relight the tree to match" in prompt


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
    assert "Unknown file" in response.json()["error"]


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
