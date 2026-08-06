"""Real product sizes reach the prompt — Product.md 8.2.

The whole point of extracting 1,092 codes was to stop asking the model for "a believable
size". These tests check the millimetres actually arrive, because a silently dropped
substitution would look exactly like the old behaviour and nothing would fail.
"""

import pytest

from backend import config
from backend.models import request_log
from backend.services import image_gen

from helpers import png_bytes, upload


def prepare(client, **extra):
    cut = client.post("/api/remove-bg", files=[upload(png_bytes(), "element.png")])
    data = {"element": cut.json()["element"], "size": "4:5", **extra}
    return client.post("/api/prepare", files=[upload(png_bytes(), "tree.png")], data=data)


def test_codes_are_recorded_on_the_request(client, conn, fake_gen, fake_rembg):
    response = prepare(client, tree_code="05021-1", element_code="017-06")

    assert response.status_code == 200, response.text
    assert response.json()["exact_scale"] is True
    row = request_log.get(conn, response.json()["request_id"])
    assert row["tree_code"] == "05021-1"
    assert row["element_code"] == "017-06"


def test_the_generator_is_handed_the_real_measurements(client, conn, fake_gen, fake_rembg):
    request_id = prepare(client, tree_code="05021-1", element_code="017-06").json()["request_id"]

    client.post(f"/api/generate/{request_id}")

    (_args, _kwargs) = fake_gen.calls[0]
    scale = _args[4] if len(_args) > 4 else _kwargs["scale"]
    assert "1524 mm" in scale and "80 mm" in scale


def test_without_codes_the_generator_gets_words_not_invented_numbers(
    client, conn, fake_gen, fake_rembg
):
    request_id = prepare(client).json()["request_id"]

    client.post(f"/api/generate/{request_id}")

    scale = fake_gen.calls[0][0][4]
    assert "mm" not in scale
    assert "proportion" in scale


def test_an_unknown_code_is_rejected_before_anything_is_billed(client, fake_gen, fake_rembg):
    response = prepare(client, tree_code="99999-9", element_code="017-06")

    assert response.status_code == 422
    assert "not in the catalogue" in response.json()["error"]
    assert fake_gen.count == 0


def test_one_code_alone_is_rejected(client, fake_gen, fake_rembg):
    response = prepare(client, tree_code="05021-1")

    assert response.status_code == 422
    assert "both" in response.json()["error"]


def test_the_prompt_template_still_carries_the_substitution():
    """If {scale} is edited out during prompt tuning the measurement vanishes silently, so
    the loader refuses rather than generating a weaker prompt at full price."""
    assert "{scale}" in config.PROMPT_PATH.read_text(encoding="utf-8")

    prompt = image_gen.load_prompt("THE-SCALE-SENTENCE")
    assert "THE-SCALE-SENTENCE" in prompt
    assert "{scale}" not in prompt


def test_a_template_without_the_placeholder_is_refused(monkeypatch, tmp_path):
    broken = tmp_path / "prompt.txt"
    broken.write_text("Decorate the tree. Keep it in proportion.", encoding="utf-8")
    monkeypatch.setattr(config, "PROMPT_PATH", broken)

    with pytest.raises(image_gen.ImageGenError) as caught:
        image_gen.load_prompt("anything")
    assert "{scale}" in str(caught.value)


def test_the_product_search_endpoint_answers(client):
    results = client.get("/api/products?q=05021").json()["results"]

    assert any(r["code"] == "05021-1" for r in results)
    assert next(r for r in results if r["code"] == "05021-1")["size_mm"] == 1524
