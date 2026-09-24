"""The per-item piece count the quote and history price ranges are built on.

It used to be a fixed range per density (8-12 for "normal") — the same for a 2 ft tree as a
7 ft one, and for a six-foot garland as an 80 mm bauble, which quoted 16-24 garlands for a
two-foot tree. backend/main.py's _estimate_for now works from the real sizes.
"""

from backend import config, main

TWO_FT_TREE = "02002-1"   # 610 mm
FIVE_FT_TREE = "05021-1"  # 1524 mm
BAUBLE_80 = "053-07"      # 80 mm
GARLAND = "60850-2"       # placement "wrapped"; no catalogue size, vendor has one


def test_a_wrapped_garland_is_exactly_one_whatever_the_tree():
    assert main._estimate_for(TWO_FT_TREE, GARLAND, "normal", "wrapped") == (1, 1)
    assert main._estimate_for(FIVE_FT_TREE, GARLAND, "full", "wrapped") == (1, 1)


def test_a_small_tree_takes_fewer_than_a_big_one():
    small = main._estimate_for(TWO_FT_TREE, BAUBLE_80, "normal", "hung")
    big = main._estimate_for(FIVE_FT_TREE, BAUBLE_80, "normal", "hung")

    assert small[1] < big[1]
    assert small[0] >= 1


def test_the_reference_case_matches_the_density_guidance():
    """A 5 ft tree with 80 mm baubles is what the 12-20 guidance was written for."""
    assert main._estimate_for(FIVE_FT_TREE, BAUBLE_80, "normal", "hung") == (12, 20)


def test_a_bigger_decoration_takes_fewer():
    small = main._estimate_for(FIVE_FT_TREE, BAUBLE_80, "normal", "hung")
    large_code = "017-08"  # 60 mm — smaller, so more of them
    smaller_piece = main._estimate_for(FIVE_FT_TREE, large_code, "normal", "hung")

    assert smaller_piece[1] > small[1]


def test_density_scales_the_size_aware_count():
    light = main._estimate_for(FIVE_FT_TREE, BAUBLE_80, "light", "hung")
    normal = main._estimate_for(FIVE_FT_TREE, BAUBLE_80, "normal", "hung")
    full = main._estimate_for(FIVE_FT_TREE, BAUBLE_80, "full", "hung")

    assert light[1] < normal[1] < full[1]


def test_no_size_falls_back_to_the_plain_density_range():
    assert main._estimate_for(None, BAUBLE_80, "normal", "hung") == config.ELEMENT_DENSITY_QTY_RANGE["normal"]
    assert main._estimate_for(FIVE_FT_TREE, None, "light", "hung") == config.ELEMENT_DENSITY_QTY_RANGE["light"]


def test_a_dropped_code_falls_back_instead_of_failing(client):
    """An old history row can name a code a later re-import removed — the row must still open."""
    assert main._estimate_for(FIVE_FT_TREE, "GONE-FOREVER", "normal", "hung") == config.ELEMENT_DENSITY_QTY_RANGE["normal"]
    assert main._placement_of("GONE-FOREVER") is None
