"""Prompt mode: a free-text description that replaces the density system outright for a
request that has one, verbatim, in exactly the {density} slot every other request already
uses (backend.services.image_gen.load_prompt).
"""

from backend import config
from backend.models import request_log
from backend.validation import ValidationError
import pytest

from backend.validation import parse_custom_prompt
from helpers import png_bytes, upload


def prepare(client, **extra):
    cut = client.post("/api/remove-bg", files=[upload(png_bytes(), "element.png")])
    data = {"element": cut.json()["element"], "size": "4:5", **extra}
    return client.post("/api/prepare", files=[upload(png_bytes(), "tree.png")], data=data)


# ---------------------------------------------------------------- parse_custom_prompt


def test_empty_string_passes_through_unchanged():
    assert parse_custom_prompt("") == ""
    assert parse_custom_prompt(None) == ""


def test_whitespace_only_becomes_empty():
    assert parse_custom_prompt("   \n  ") == ""


def test_a_normal_prompt_is_trimmed_and_kept():
    assert parse_custom_prompt("  แต่งโทนแดง-ทอง  ") == "แต่งโทนแดง-ทอง"


def test_over_the_limit_is_refused():
    with pytest.raises(ValidationError) as caught:
        parse_custom_prompt("a" * (config.PROMPT_MODE_MAX_CHARS + 1))
    assert str(config.PROMPT_MODE_MAX_CHARS) in str(caught.value)


def test_exactly_the_limit_is_accepted():
    text = "a" * config.PROMPT_MODE_MAX_CHARS
    assert parse_custom_prompt(text) == text


# ---------------------------------------------------------------- /api/prepare -> /api/generate


def test_custom_prompt_is_stored(client, conn, fake_gen, fake_rembg):
    prepared = prepare(client, custom_prompt="แต่งโทนทองหรูหรา")
    row = request_log.get(conn, prepared.json()["request_id"])
    assert row["custom_prompt"] == "แต่งโทนทองหรูหรา"


def test_custom_prompt_reaches_the_prompt_verbatim(client, conn, fake_gen, fake_rembg):
    prepared = prepare(client, custom_prompt="แต่งโทนทองหรูหรา เว้นระยะห่างสวยงาม")
    client.post(f"/api/generate/{prepared.json()['request_id']}")
    # generate(tree, elements, width, height, scale, reference, density) — density is
    # index 6, same convention test_manual_size.py already established
    density_sentence = fake_gen.calls[0][0][6]
    assert density_sentence == "แต่งโทนทองหรูหรา เว้นระยะห่างสวยงาม"


def test_an_empty_custom_prompt_falls_back_to_the_usual_density(client, conn, fake_gen, fake_rembg):
    prepared = prepare(client)  # no custom_prompt at all
    client.post(f"/api/generate/{prepared.json()['request_id']}")
    density_sentence = fake_gen.calls[0][0][6]
    assert density_sentence == config.DENSITY_PRESETS[config.DEFAULT_DENSITY]


def test_custom_prompt_overrides_per_item_density_too(client, conn, fake_gen, fake_rembg):
    """Even if per-item densities were somehow set differently, a custom_prompt still wins —
    it replaces the whole density system outright, not just the single-density path."""
    element_a = client.post("/api/remove-bg", files=[upload(png_bytes(), "a.png")]).json()["element"]
    element_b = client.post("/api/remove-bg", files=[upload(png_bytes(), "b.png")]).json()["element"]
    prepared = client.post(
        "/api/prepare",
        files=[upload(png_bytes(), "tree.png")],
        data={
            "element": [element_a, element_b],
            "size": "4:5",
            "element_code": ["017-06", "05021-1"],
            "tree_code": "05021-1",
            "element_density": ["light", "full"],
            "custom_prompt": "จัดวางอิสระตามใจ",
        },
    )
    assert prepared.status_code == 200, prepared.text
    client.post(f"/api/generate/{prepared.json()['request_id']}")
    density_sentence = fake_gen.calls[0][0][6]
    assert density_sentence == "จัดวางอิสระตามใจ"


def test_an_over_length_custom_prompt_is_refused(client, fake_gen, fake_rembg):
    response = prepare(client, custom_prompt="a" * (config.PROMPT_MODE_MAX_CHARS + 1))
    assert response.status_code == 422


def test_config_reports_the_character_limit(client):
    body = client.get("/api/config").json()
    assert body["prompt_mode_max_chars"] == config.PROMPT_MODE_MAX_CHARS
