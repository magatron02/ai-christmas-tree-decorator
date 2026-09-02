"""describe_element_density() — per-item density (light/normal/full chosen per decoration,
not once for the whole tree). The common case must stay byte-identical to the old flat
DENSITY_PRESETS sentence — this is what makes the feature safe to ship without regenerating
every existing prompt shape.
"""

from backend import config
from backend.services import image_gen


def test_a_single_element_uses_the_whole_tree_sentence_verbatim():
    elements = [{"code": "017-06", "density": "full"}]
    assert image_gen.describe_element_density(elements) == config.DENSITY_PRESETS["full"]


def test_matching_densities_across_items_collapse_to_one_sentence():
    elements = [
        {"code": "A", "density": "light"},
        {"code": "B", "density": "light"},
        {"code": "C", "density": "light"},
    ]
    assert image_gen.describe_element_density(elements) == config.DENSITY_PRESETS["light"]


def test_no_density_key_at_all_falls_back_to_default_and_still_collapses():
    """Rows written before per-item density existed have no "density" key on any element."""
    elements = [{"code": "A"}, {"code": "B"}]
    assert image_gen.describe_element_density(elements) == config.DENSITY_PRESETS[config.DEFAULT_DENSITY]


def test_differing_densities_produce_one_line_per_item():
    elements = [
        {"code": "017-06", "density": "light"},
        {"code": "05021-1", "density": "full"},
    ]
    sentence = image_gen.describe_element_density(elements)
    assert sentence != config.DENSITY_PRESETS["light"]
    assert sentence != config.DENSITY_PRESETS["full"]
    assert "017-06" in sentence and config.ELEMENT_DENSITY_PHRASES["light"] in sentence
    assert "05021-1" in sentence and config.ELEMENT_DENSITY_PHRASES["full"] in sentence


def test_a_code_less_item_gets_a_generic_label_in_the_mixed_case():
    elements = [
        {"code": None, "density": "light"},
        {"code": "05021-1", "density": "full"},
    ]
    sentence = image_gen.describe_element_density(elements)
    assert "this decoration" in sentence
