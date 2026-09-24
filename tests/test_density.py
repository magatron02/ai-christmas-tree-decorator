"""How tightly the tree gets decorated — threaded through exactly like size (Product.md,
user request: a density control for how packed the render looks).

"normal" is worded identically to what the prompt always hardcoded, so the default behaviour
of every existing test/run is unchanged; the other two levels are new.
"""

from backend import config, validation
from backend.services import image_gen
from backend.validation import ValidationError

from helpers import png_bytes, upload


def test_the_default_density_is_the_prompt_s_old_hardcoded_text():
    prompt = image_gen.load_prompt("scale", 1)

    assert config.DENSITY_PRESETS[config.DEFAULT_DENSITY] in prompt
    assert "roughly 12 to 20 decorations" in prompt


def test_a_chosen_density_reaches_the_prompt():
    prompt = image_gen.load_prompt("scale", 1, density=config.DENSITY_PRESETS["full"])

    assert "roughly 20 to 30 decorations" in prompt
    assert "roughly 12 to 20 decorations" not in prompt


def test_resolve_density_rejects_an_unknown_key():
    try:
        validation.resolve_density("extreme")
        assert False, "expected a ValidationError"
    except ValidationError as exc:
        assert "extreme" in str(exc)


def test_resolve_density_returns_the_sentence_for_a_known_key():
    assert validation.resolve_density("light") == config.DENSITY_PRESETS["light"]


def test_prepare_then_generate_threads_the_chosen_density(client, conn, fake_gen, fake_rembg):
    cut = client.post("/api/remove-bg", files=[upload(png_bytes(), "element.png")])
    prepared = client.post(
        "/api/prepare",
        files=[upload(png_bytes(), "tree.png")],
        data={"element": [cut.json()["element"]], "size": "4:5", "density": "full"},
    )
    assert prepared.status_code == 200, prepared.text

    client.post(f"/api/generate/{prepared.json()['request_id']}")

    density_sentence = fake_gen.calls[0][0][6]
    assert density_sentence == config.DENSITY_PRESETS["full"]


def test_an_old_row_with_no_density_falls_back_to_default(client, conn, fake_gen, fake_rembg):
    """Rows written before this column existed have density=NULL — must not crash, must fall
    back to the same text every request used to get."""
    import uuid

    from backend.models import request_log

    tree_name = f"{uuid.uuid4().hex}_tree.png"
    (config.STORAGE_DIR / tree_name).write_bytes(png_bytes())
    element_name = f"{uuid.uuid4().hex}_element.png"
    (config.STORAGE_DIR / element_name).write_bytes(png_bytes())

    request_id = request_log.create(
        conn, tree_name, [{"path": element_name, "code": None}], "4:5"
    )  # density omitted, same as a pre-migration row

    response = client.post(f"/api/generate/{request_id}")
    assert response.status_code == 200, response.text

    density_sentence = fake_gen.calls[0][0][6]
    assert density_sentence == config.DENSITY_PRESETS[config.DEFAULT_DENSITY]
