"""Placement is a fixed property of a category (issue #19).

A garland wraps a trunk, a gift box sits at the tree's foot, a wreath mounts to a wall — not
every category hangs from a branch the way an ornament does. Placement says which, so later
work (wrapped/grounded/mounted generation) reads it instead of hardcoding category lists.
"""

from backend.services import catalog

HUNG = {"ornament", "bell", "ribbon", "topper", "flower"}
WRAPPED = {"garland"}
GROUNDED = {"giftbox", "figure"}
MOUNTED = {"wreath", "banner"}


def test_every_category_has_exactly_one_placement():
    known = HUNG | WRAPPED | GROUNDED | MOUNTED | catalog.NO_PLACEMENT
    categories = {key for key, _label, _needles in catalog.CATEGORIES}
    assert categories == known, "a category was added without deciding its placement"


def test_hung_categories():
    for key in HUNG:
        assert catalog.placement_of(key) == "hung"


def test_wrapped_categories():
    for key in WRAPPED:
        assert catalog.placement_of(key) == "wrapped"


def test_grounded_categories():
    for key in GROUNDED:
        assert catalog.placement_of(key) == "grounded"


def test_mounted_categories():
    for key in MOUNTED:
        assert catalog.placement_of(key) == "mounted"


def test_light_and_tree_have_no_placement():
    for key in catalog.NO_PLACEMENT:
        assert catalog.placement_of(key) is None


def test_an_unknown_category_has_no_placement():
    assert catalog.placement_of("not-a-real-category") is None
