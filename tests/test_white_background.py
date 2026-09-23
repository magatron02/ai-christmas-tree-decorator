"""A tree with no scene reference goes on a plain white backdrop (issue #30).

This reverses what the no-reference path used to ask for. The old instruction kept the shop's
own background exactly as photographed, on the reasoning that the shop wanted its own tree in
its own shop. A picture whose job is to show a customer a product is more useful as a clean
product shot than as a photo of the shop floor, so the background goes and white takes its
place — while everything the template says about preserving the tree itself stays untouched.

Only the tree backdrop changes. A wall or a door IS its own background; cutting one out and
floating it on white would mean nothing, so that path keeps the wording it already had.
"""

from backend.services import image_gen


# ---- the new instruction, tree + no reference ----


def test_a_tree_with_no_reference_asks_for_a_white_background():
    prompt = image_gen.load_prompt("scale", 1, has_reference=False)

    assert "white" in prompt.lower()
    assert "Keep the setting exactly as it is" not in prompt, (
        "the old keep-the-shop-background instruction must not sit alongside the new one"
    )


def test_the_white_background_instruction_names_what_has_to_go():
    """A bare "white background" leaves the model free to keep the floor line or a prop and
    call it styling — the parts of the original shot that must not survive are named."""
    scene = image_gen.describe_scene(has_reference=False, backdrop="tree")

    for gone in ("floor", "furniture"):
        assert gone in scene.lower(), f"the instruction never says the {gone} goes"


def test_the_tree_still_gets_a_shadow_rather_than_floating():
    scene = image_gen.describe_scene(has_reference=False, backdrop="tree")

    assert "shadow" in scene.lower()


def test_the_shadow_is_rendered_not_kept():
    """The only shadow in the source photo belongs to the shop floor. "Keep" invites dragging
    that shape, and its colour, onto the white."""
    scene = image_gen.describe_scene(has_reference=False, backdrop="tree")

    assert "Render a clearly visible soft grey shadow" in scene
    assert "Keep a soft contact shadow" not in scene


def test_the_shadow_is_asked_for_strongly_enough_to_show_up():
    """First run of this prompt came back with a shadow so faint the tree read as floating on
    the white. "Soft contact shadow" was too easy to satisfy with nothing — the instruction
    now says where the shadow sits, which way it falls off, and that it has to be visible."""
    scene = image_gen.describe_scene(has_reference=False, backdrop="tree")

    assert "clearly visible" in scene
    assert "darkest" in scene, "the instruction never says where the shadow is strongest"
    assert "fading outward" in scene, "nothing tells it how the shadow falls off"


def test_the_gaps_between_the_branches_go_white_too():
    """The failure mode neither a prompt nor a cut-out fixes on its own: the room surviving in
    the holes through the foliage, where it is least likely to be noticed before printing."""
    scene = image_gen.describe_scene(has_reference=False, backdrop="tree")

    assert "gaps between the branches" in scene


def test_the_tree_is_not_relit_for_the_new_backdrop():
    """The template tells decorations to pick up "the scene's light", and the scene is now a
    white backdrop — so which light is meant has to be said outright, or a warm shop tree gets
    half-relit to studio neutral."""
    scene = image_gen.describe_scene(has_reference=False, backdrop="tree")

    assert "do not relight" in scene.lower()


def test_a_decoration_takes_its_highlight_from_the_light_on_the_tree():
    """"The scene's light" meant the shop's, unambiguously, while the shop was the scene. A
    blank white backdrop has no light of its own, so the phrase had to name the one light
    that is actually still there."""
    prompt = image_gen.load_prompt("scale", 1, has_reference=False)

    assert "a highlight from the\n  light already on the tree" in prompt
    assert "scene's light" not in prompt


def test_the_template_scopes_photographic_character_to_the_tree():
    """"Preserve exactly ... the same white balance, exposure and colour" read as a claim over
    the whole frame, which is the opposite of replacing the setting. Scoped to the subject it
    means what it always meant for the tree, and stops fighting both background-replacing
    paths (white here, the reference photo's own pixels on the other one)."""
    prompt = image_gen.load_prompt("scale", 1, has_reference=False)

    assert "the photographic character of the tree itself" in prompt
    assert "the same grain, focus, white balance, exposure and colour" not in prompt


def test_the_white_background_never_contradicts_preserving_the_tree(tmp_path):
    """The template's hard rules above the {scene} slot are what keep the returned tree the
    same tree. A scene sentence that told the model to regenerate the subject would quietly
    undo them, so this checks the instruction is scoped to the background."""
    prompt = image_gen.load_prompt("scale", 1, has_reference=False)

    assert "Preserve exactly" in prompt
    assert "the tree itself" in prompt


# ---- everything else is untouched ----


def test_a_wall_with_no_reference_still_keeps_its_own_setting():
    """A wall is its own background — there is nothing to cut it out of."""
    prompt = image_gen.load_prompt("scale", 1, has_reference=False, backdrop="wall")

    assert "Keep the setting exactly as it is" in prompt
    assert "white" not in image_gen.describe_scene(has_reference=False, backdrop="wall").lower()


def test_a_reference_photo_still_wins_for_a_tree():
    """With a reference, replacing the background with that photo's actual pixels is the whole
    point of the path — white has nothing to do with it."""
    scene = image_gen.describe_scene(has_reference=True, backdrop="tree")

    assert "composite the decorated tree into these actual pixels" in scene
    assert "white" not in scene.lower()


def test_a_reference_photo_still_wins_for_a_wall():
    scene = image_gen.describe_scene(has_reference=True, backdrop="wall")

    assert "composite the decorated wall or door into these actual pixels" in scene
    assert "white" not in scene.lower()
