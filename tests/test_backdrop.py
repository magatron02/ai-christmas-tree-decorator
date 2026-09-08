"""Backdrop: a wall or door photo is a valid destination, not just a tree (issue #22).

The compositing prompt has always assumed a tree — "the tree itself, its branch structure,
how full or sparse it is." A wall or door needs its own preservation rules entirely; these
tests check the right template is used for each, and that leaving the field untouched still
produces exactly today's tree behaviour.
"""

import re

import pytest

from backend import config, validation
from backend.services import image_gen
from backend.validation import ValidationError

from helpers import png_bytes, upload


def prepare(client, **extra):
    cut = client.post("/api/remove-bg", files=[upload(png_bytes(), "element.png")]).json()["element"]
    data = {"element": cut, "size": "4:5", **extra}
    return client.post("/api/prepare", files=[upload(png_bytes(), "tree.png")], data=data)


# ---- resolve_backdrop (unit) ----


def test_an_empty_backdrop_defaults_to_tree():
    assert validation.resolve_backdrop("") == "tree"
    assert validation.resolve_backdrop(None) == "tree"


def test_a_known_backdrop_passes_through():
    assert validation.resolve_backdrop("wall") == "wall"


def test_an_unknown_backdrop_is_refused():
    with pytest.raises(ValidationError):
        validation.resolve_backdrop("ceiling")


# ---- load_prompt reads a different template per backdrop (unit) ----


def test_the_default_backdrop_is_byte_identical_to_before_this_existed():
    prompt = image_gen.load_prompt("scale", 1)
    assert "bare Christmas tree" in prompt
    assert "branch structure" in prompt
    assert "wall or door" not in prompt


def test_the_tree_prompt_is_the_template_with_only_its_own_words_in_it():
    """Guards the shared fragments (scene, elements, density) that now bend around a subject
    noun: a rewrap or a reworded default would change the tree prompt without any wall test
    noticing. The template's own text plus today's substitutions, exactly."""
    prompt = image_gen.load_prompt("THE-SCALE", 2, has_reference=True)
    expected = (
        config.PROMPT_PATH.read_text(encoding="utf-8").strip()
        .replace("{scene}", image_gen.REFERENCE_SCENE.format(subject="tree"))
        .replace("{elements}", image_gen.describe_elements(2))
        .replace("{scale}", "THE-SCALE")
        .replace("{density}", config.DENSITY_PRESETS[config.DEFAULT_DENSITY])
        .replace("{placement_notes}", "")
    )
    assert prompt == expected
    assert "keep it exactly as it is" in prompt  # the exact wording, unwrapped


def test_a_wall_backdrop_uses_the_wall_template():
    prompt = image_gen.load_prompt("scale", 1, backdrop="wall")
    assert "wall or door" in prompt
    assert "branch structure" not in prompt
    assert "bare Christmas tree" not in prompt


def test_the_picker_offers_exactly_the_backdrops_the_backend_knows():
    """The two <option>s are hardcoded in the HTML rather than fetched — this is what stops
    them drifting from config.BACKDROPS."""
    html = (config.FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
    block = html.split('id="backdrop-select"')[1].split("</select>")[0]
    offered = re.findall(r'<option value="([^"]+)"', block)
    assert offered == list(config.BACKDROPS)


def test_a_wall_prompt_never_narrates_a_tree():
    """Splitting the template was not enough on its own: the text substituted into it —
    the scene, the element wording, the density sentence — all said "tree" of their own."""
    prompt = image_gen.load_prompt("scale", 3, has_reference=True, backdrop="wall")
    assert "tree" not in prompt.lower()


def test_a_tree_only_placement_note_is_not_offered_on_a_wall():
    elements = [
        {"code": "GARLAND-1", "placement": "wrapped"},
        {"code": "BOX-1", "placement": "grounded"},
    ]
    assert image_gen.describe_placement(elements, "wall") == ""
    assert image_gen.describe_placement(elements, "tree") != ""


def test_both_templates_still_carry_every_substitution():
    for backdrop in config.BACKDROPS:
        prompt = image_gen.load_prompt("THE-SCALE", 1, density="THE-DENSITY", backdrop=backdrop)
        assert "THE-SCALE" in prompt
        assert "THE-DENSITY" in prompt
        assert "{scale}" not in prompt
        assert "{density}" not in prompt
        assert "{placement_notes}" not in prompt


# ---- HTTP seam ----


def test_leaving_backdrop_untouched_reaches_the_generator_as_tree(
    client, conn, fake_gen, fake_rembg
):
    request_id = prepare(client).json()["request_id"]

    client.post(f"/api/generate/{request_id}")

    assert fake_gen.calls[0][0][8] == "tree"


def test_choosing_wall_reaches_the_generator(client, conn, fake_gen, fake_rembg):
    request_id = prepare(client, backdrop="wall").json()["request_id"]

    client.post(f"/api/generate/{request_id}")

    assert fake_gen.calls[0][0][8] == "wall"


def test_an_unknown_backdrop_is_refused_before_anything_is_billed(client, fake_gen, fake_rembg):
    response = prepare(client, backdrop="ceiling")

    assert response.status_code == 422
    assert fake_gen.count == 0


def test_an_old_row_with_no_backdrop_falls_back_to_tree(client, conn, fake_gen, fake_rembg):
    """Rows written before this column existed have backdrop=NULL — must not crash, must
    generate exactly as a tree always did."""
    import uuid

    from backend.models import request_log

    tree_name = f"{uuid.uuid4().hex}_tree.png"
    (config.STORAGE_DIR / tree_name).write_bytes(png_bytes())
    element_name = f"{uuid.uuid4().hex}_element.png"
    (config.STORAGE_DIR / element_name).write_bytes(png_bytes())

    request_id = request_log.create(
        conn, tree_name, [{"path": element_name, "code": None}], "4:5"
    )  # backdrop omitted, same as a pre-migration row

    response = client.post(f"/api/generate/{request_id}")
    assert response.status_code == 200, response.text

    assert fake_gen.calls[0][0][8] == "tree"
