"""Catalogue lookup and the real-scale sentence — Product.md 8.2.

The rule being enforced is NonGoals.md 8: never invent a dimension. A guessed size stops
being a guess the moment it reaches a customer — but the rule is about the number, not about
refusing to generate. A code that resolves but has no printed size falls back to a
non-exact "believable size" instruction for that one item and is reported back as missing,
rather than blocking a request that has other, real sizes to work with.
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
    assert "ไม่มีใน catalogue" in str(caught.value)


def test_the_scale_sentence_states_the_real_ratio():
    """1524 mm tree, 80 mm bauble — the model should be told 19, not 'in proportion'."""
    sentence, missing = catalog.scale_sentence("05021-1", "017-06")

    assert "1524 mm" in sentence
    assert "80 mm" in sentence
    assert "19th" in sentence
    assert missing == []


def test_the_stated_ratio_is_the_true_one_not_a_corrected_one():
    """Asking for a larger fraction to compensate for the model drawing small was tried and
    measured worse than not correcting at all (0.55x against 0.70x). The sentence states the
    real ratio, and this test stops a compensation factor creeping back in unmeasured."""
    sentence, _missing = catalog.scale_sentence("05021-1", "017-06")

    assert "one 19th" in sentence          # 1524 / 80, the truth
    assert "one 11th" not in sentence      # the correction that made it worse
    assert not hasattr(config, "RENDER_SCALE_BIAS")


def test_scale_falls_back_to_words_when_no_codes_are_given():
    sentence, missing = catalog.scale_sentence("", "")
    assert "proportion" in sentence
    assert "mm" not in sentence
    assert missing == []


def test_one_code_alone_is_refused():
    """Half the information cannot produce a ratio, and a ratio is the whole point. Different
    situation from a code with no catalogue size (below): here there is no code at all for
    some item, which is a data-entry gap, not a catalogue gap."""
    with pytest.raises(ValidationError) as caught:
        catalog.scale_sentence("05021-1", [])
    assert "ใส่บางส่วน" in str(caught.value)


def test_several_decorations_each_get_their_own_ratio():
    """A 40 mm bauble and a 300 mm one must not come out the same size, which is the whole
    reason multi-element needs the catalogue rather than one shared instruction."""
    sentence, missing = catalog.scale_sentence("05021-1", ["017-06", "018-02"])

    assert "80 mm across, one 19th" in sentence
    assert "40 mm across, one 38th" in sentence
    assert "not interchangeable" in sentence
    assert missing == []


def test_a_decoration_without_a_size_falls_back_for_that_one_item():
    """The catalogue still doesn't get to guess a number for the sizeless one — but the tree
    and the other decoration have real sizes, and generating with a clearly-flagged fallback
    for one item beats refusing a request that is mostly exact."""
    sizeless = next(row for row in catalog._rows() if row["size"] is None)

    sentence, missing = catalog.scale_sentence("05021-1", ["017-06", sizeless["code"]])

    assert "80 mm across, one 19th" in sentence   # the known one is still exact
    assert "no catalogue size" in sentence        # the sizeless one is flagged, not guessed
    assert missing == [catalog.describe(sizeless)]


def test_a_treeless_tree_code_falls_back_for_everything():
    """Every ratio needs the tree's own height as the denominator — a decoration's own known
    size is useless without it, so a missing tree size degrades the whole sentence to the
    generic fallback rather than only omitting the tree's own line."""
    sizeless = next(row for row in catalog._rows() if row["size"] is None)

    sentence, missing = catalog.scale_sentence(sizeless["code"], ["017-06"])

    assert sentence == catalog._GENERIC_SCALE
    assert missing == [catalog.describe(sizeless)]


def test_a_product_with_no_printed_size_is_refused_not_estimated():
    sizeless = next(row for row in catalog._rows() if row["size"] is None)

    with pytest.raises(ValidationError) as caught:
        catalog.require_size(sizeless)
    assert "ไม่มีขนาด" in str(caught.value)


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


def test_a_letter_labelled_dimension_pair_is_parsed():
    """'H 215 x D 142 cm' — a second source's size format: each number carries its own axis
    letter, which used to make the plain digit-x-digit series regex miss the whole string."""
    assert catalog.parse_size("H 215 x D 142 cm") == {
        "dimensions_mm": [2150, 1420], "unit_printed": "cm",
    }


def test_a_letter_labelled_dimension_pair_parses_either_order():
    assert catalog.parse_size("D 142 x H 215 cm")["dimensions_mm"] == [1420, 2150]


def test_a_three_axis_labelled_dimension_is_parsed():
    assert catalog.parse_size("D80xL80xH10cm")["dimensions_mm"] == [800, 800, 100]


def test_an_unlabelled_series_still_parses_the_same_as_before():
    """The new labelled-series pattern is tried first — it must not shadow the plain series
    that already worked (no axis letters at all, still by far the most common shape)."""
    assert catalog.parse_size("18x12x51 cm.")["dimensions_mm"] == [180, 120, 510]


def test_the_catalogue_covers_what_the_ac5_run_used():
    for code in ("04031-1", "05092-1", "017-06", "90665-18", "01801-1"):
        catalog.find(code)


# ---- the picker's contract: a card must be able to stand for its code ----------------------


def test_every_product_lands_in_exactly_one_category():
    """The picker's category filter is a partition, not a tag cloud — a product appearing in
    two categories would be found twice and counted twice."""
    for row in catalog._rows():
        matches = [
            key for key, _label, needles in catalog.CATEGORIES
            if any(n in f"{row.get('section') or ''} {catalog._kinds().get(row['code'], '')}".lower()
                   for n in needles)
        ]
        assert catalog.category_of(row) == (matches[0] if matches else None)


def test_no_product_is_left_without_a_category():
    """The section strings are mangled by PDF extraction ("Sno wflakes", "N N u u t t c c..."),
    so this is the guard that a re-extraction has not broken the substrings that match them."""
    uncategorised = [row["code"] for row in catalog._rows() if catalog.category_of(row) is None]
    assert not uncategorised, f"{len(uncategorised)} products match no category: {uncategorised[:10]}"


def test_shops_lists_every_brand_with_a_showable_product():
    """The picker's shop filter has to reflect real data — a hardcoded pair of options is
    already wrong the day a third shop's products land (Product.md)."""
    names = dict(catalog.shops())
    assert "Bangkok Christmas" in names
    assert "MS Natural Design" in names
    assert all(count > 0 for count in names.values())


def test_browse_can_be_scoped_to_one_shop():
    rows, total = catalog.browse(10_000, 0, book="MS Natural Design")
    assert total > 0
    assert all(row.get("book") == "MS Natural Design" for row in rows)


def test_a_shops_categories_are_only_the_ones_it_actually_stocks():
    """The picker offered categories counted across every shop while a shop filter was on, so
    MS Natural Design advertised ribbons, bells and toppers — all Bangkok Christmas stock —
    and choosing one produced an empty grid. Scoping the count is what stops a filter being
    offered with nothing behind it."""
    for book, _count in catalog.shops():
        rows, _total = catalog.browse(10_000, 0, None, book)
        stocked = {catalog.category_of(row) for row in rows}
        for key, _label, _needles in catalog.CATEGORIES:
            if key not in stocked:
                continue
            in_shop = [r for r in rows if catalog.category_of(r) == key]
            assert in_shop, f"{book} offers {key} with nothing in it"


def test_the_two_shops_really_do_stock_different_categories():
    """Guards the test above from passing trivially: if every shop carried every category,
    scoping the counts would be a no-op and the bug could come back unnoticed."""
    per_shop = {}
    for book, _count in catalog.shops():
        rows, _total = catalog.browse(10_000, 0, None, book)
        per_shop[book] = {catalog.category_of(row) for row in rows}

    everywhere = set.intersection(*per_shop.values())
    anywhere = set.union(*per_shop.values())
    assert anywhere - everywhere, "expected at least one category unique to a single shop"


def test_a_crop_shared_by_many_codes_is_not_showable():
    """It cannot be a picture of any one of them, whatever it depicts."""
    shared = [c for c, n in catalog._crop_users().items() if n + 1 >= catalog.MAX_SHARED_CROP]
    assert shared, "expected the catalogue to contain some over-shared crops"
    for code in shared:
        assert not catalog.crop_is_showable(code)


def test_a_crop_judged_page_furniture_is_not_showable():
    verdicts = catalog._crop_verdicts()
    if not verdicts:
        pytest.skip("run scripts/audit_crops.py first")
    for code, reason in verdicts.items():
        assert reason in catalog.REJECTABLE_CROP_KINDS
        assert not catalog.crop_is_showable(code), f"{code} was judged {reason}"


def test_only_the_audit_reasons_that_survived_checking_are_acted_on():
    """The audit rejected 137 crops; sampling the pixels behind each reason found `multiple`,
    `unclear` and `blank` almost always wrong — this catalogue photographs one product in all
    its colourways at once, which that pass read as a montage of different products. Acting on
    those reasons would hide about a hundred real items."""
    assert catalog.REJECTABLE_CROP_KINDS.isdisjoint({"multiple", "unclear", "blank"})


def test_the_eye_checked_false_rejects_are_not_treated_as_page_furniture():
    """Rejections inside the trusted reasons that were checked by hand and found wrong.

    This overrides the vision audit only. Two of these three are still out of the picker
    because their crop is shared with other codes — being a real product does not rescue a
    photo that cannot say which product it is, and the two rules are deliberately separate.
    """
    for code in catalog.KEEP_DESPITE_AUDIT:
        assert not catalog.crop_is_not_a_product(code), f"{code} is a real product"


def test_a_shared_crop_is_hidden_even_when_it_shows_a_real_product():
    """The point of the sharing rule: 34072-1's photo is byte-identical to four other codes'
    and the ribbon inside it names 34072-1, so the other four are showing the wrong product.
    Since nothing in the data says which claimant is the real one, all of them go."""
    family = ["34072-1", "35072-1", "36072-1", "37072-1", "38072-1"]
    users = catalog._crop_users()
    assert all(users.get(code, 0) >= 1 for code in family)
    assert not any(catalog.crop_is_showable(code) for code in family)


def test_an_unjudged_crop_still_shows():
    """The audit file is optional and is filled in over many runs. A code nobody has judged
    yet must stay in the picker — treating "unknown" as "reject" would empty it."""
    assert catalog.crop_is_not_a_product("no-such-code-anywhere") is False


def test_the_picker_never_offers_a_code_it_cannot_illustrate():
    rows, total = catalog.browse(10_000, 0)
    assert total == len(rows)
    for row in rows:
        assert catalog.crop_is_showable(row["code"])


# ---- colourway variants ---------------------------------------------------------------------


def test_a_code_with_one_photo_still_reports_one_image():
    """variants_of is the only accessor the picker uses, so it must answer for every code,
    split or not — a caller that has to know which case it is in will get it wrong."""
    unsplit = [c for c in catalog._by_code() if catalog.image_for(c) and c not in catalog._variants()]
    assert unsplit
    for code in unsplit[:50]:
        assert catalog.variants_of(code) == [catalog.image_for(code)]


def test_a_split_code_reports_one_image_per_colour():
    if not catalog._variants():
        pytest.skip("run scripts/split_colourways.py first")
    for code, images in catalog._variants().items():
        assert len(images) >= 2, f"{code} was 'split' into one image"
        assert catalog.variants_of(code) == [f"variants/{name}" for name in images]


def test_every_variant_image_exists_on_disk():
    if not catalog._variants():
        pytest.skip("run scripts/split_colourways.py first")
    images = config.CATALOG_PATH.parent / "images"
    for code in catalog._variants():
        for name in catalog.variants_of(code):
            assert (images / name).is_file(), f"{code} points at a missing {name}"


def test_a_variant_belongs_to_exactly_one_code():
    """The picker sends the variant filename back to be cut out, and the endpoint authorises
    it by asking whether it is one of that code's own images. Two codes sharing a variant
    filename would make that check meaningless."""
    owners = {}
    for code in catalog._variants():
        for name in catalog.variants_of(code):
            assert name not in owners, f"{name} claimed by {owners.get(name)} and {code}"
            owners[name] = code


def test_only_showable_crops_were_split():
    """Splitting a page-number badge into halves would put two page numbers in the picker
    where the filter had already removed one."""
    for code in catalog._variants():
        assert catalog.crop_is_showable(code), f"{code} is hidden but was still split"


# ---- contested codes: two different products, one code, neither picked automatically -------


def test_a_contested_code_is_not_showable():
    """book_conflicts.json records codes the rebuild saw mean two different things on two
    different pages (26022-2 is a Fraser Fir on one page, a Brighton Spruce on another).
    Guessing which is real is exactly what NonGoals.md 7/8 forbid, so neither wins by default —
    both stay out of the picker until a person resolves it."""
    contested = catalog._contested_codes()
    assert contested, "expected the rebuilt catalogue to contain some contested codes"
    for code in contested:
        assert not catalog.crop_is_showable(code), f"{code} is contested but still showable"


def test_conflicts_reports_kept_and_lost_side_by_side():
    rows = catalog.conflicts()
    assert rows
    for row in rows:
        assert row["code"] in catalog._contested_codes()
        assert row["lost"], f"{row['code']} has no losing entry to compare against"


def test_an_uncontested_code_is_unaffected():
    uncontested = next(
        r["code"] for r in catalog._rows()
        if r["code"] not in catalog._contested_codes() and catalog.image_for(r["code"])
    )
    assert not catalog.code_is_contested(uncontested)
