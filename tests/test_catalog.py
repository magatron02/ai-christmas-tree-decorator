"""Catalogue lookup and the real-scale sentence — Product.md 8.2.

The rule being enforced is NonGoals.md 8: never invent a dimension. A guessed size stops
being a guess the moment it reaches a customer, so a missing size has to be a refusal and
not a plausible number.
"""

import pytest

from backend import config
from backend.services import catalog
from backend.validation import ValidationError


def test_a_known_tree_resolves_to_its_real_height():
    row = catalog.find("05021-1")
    assert row["size"]["feet"] == 5
    assert catalog.longest_side_mm(row) == 1524


def test_a_known_bauble_resolves_to_its_diameter():
    assert catalog.longest_side_mm(catalog.find("017-06")) == 80


def test_lookup_is_case_insensitive_and_trims():
    assert catalog.find("  05021-1  ")["code"] == "05021-1"


def test_an_unknown_code_is_refused():
    with pytest.raises(ValidationError) as caught:
        catalog.find("99999-9")
    assert "not in the catalogue" in str(caught.value)


def test_the_scale_sentence_states_the_real_ratio():
    """1524 mm tree, 80 mm bauble — the model should be told 19, not 'in proportion'."""
    sentence = catalog.scale_sentence("05021-1", "017-06")

    assert "1524 mm" in sentence
    assert "80 mm" in sentence
    assert "19th" in sentence


def test_the_stated_ratio_is_the_true_one_not_a_corrected_one():
    """Asking for a larger fraction to compensate for the model drawing small was tried and
    measured worse than not correcting at all (0.55x against 0.70x). The sentence states the
    real ratio, and this test stops a compensation factor creeping back in unmeasured."""
    sentence = catalog.scale_sentence("05021-1", "017-06")

    assert "one 19th" in sentence          # 1524 / 80, the truth
    assert "one 11th" not in sentence      # the correction that made it worse
    assert not hasattr(config, "RENDER_SCALE_BIAS")


def test_scale_falls_back_to_words_when_no_codes_are_given():
    sentence = catalog.scale_sentence("", "")
    assert "proportion" in sentence
    assert "mm" not in sentence


def test_one_code_alone_is_refused():
    """Half the information cannot produce a ratio, and a ratio is the whole point."""
    with pytest.raises(ValidationError) as caught:
        catalog.scale_sentence("05021-1", "")
    assert "both" in str(caught.value)


def test_a_product_with_no_printed_size_is_refused_not_estimated():
    sizeless = next(row for row in catalog._rows() if row["size"] is None)

    with pytest.raises(ValidationError) as caught:
        catalog.require_size(sizeless)
    assert "no size" in str(caught.value)


def test_search_finds_by_code_and_by_page_heading():
    assert any(row["code"] == "05021-1" for row in catalog.search("05021"))
    # the word appears in the headings of the page those trees are printed on
    assert any(row["code"] == "05021-1" for row in catalog.search("norwood"))


def test_no_row_claims_a_product_name():
    """Names were guessed by proximity and got it wrong. A guessed name sitting in a data
    file is indistinguishable from a known one, which NonGoals.md 7 forbids."""
    assert all("name" not in row for row in catalog._rows())


def test_search_is_empty_for_an_empty_query():
    assert catalog.search("") == []


def test_every_parsed_size_is_a_positive_number():
    """A zero or negative dimension would sail into a prompt as a ratio and be nonsense."""
    for row in catalog._rows():
        millimetres = catalog.longest_side_mm(row)
        assert millimetres is None or millimetres > 0, row["code"]


def test_the_catalogue_covers_what_the_ac5_run_used():
    for code in ("05021-1", "04031-6", "017-04", "018-02", "5203-04"):
        catalog.find(code)
