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
        catalog.scale_sentence("05021-1", [])
    assert "partial set" in str(caught.value)


def test_several_decorations_each_get_their_own_ratio():
    """A 40 mm bauble and a 300 mm one must not come out the same size, which is the whole
    reason multi-element needs the catalogue rather than one shared instruction."""
    sentence = catalog.scale_sentence("05021-1", ["017-06", "018-02"])

    assert "80 mm across, one 19th" in sentence
    assert "40 mm across, one 38th" in sentence
    assert "not interchangeable" in sentence


def test_a_decoration_without_a_size_blocks_the_whole_set():
    """Four known sizes and one unknown cannot produce a consistent instruction, and
    guessing the fifth is what NonGoals 8 forbids."""
    sizeless = next(row for row in catalog._rows() if row["size"] is None)

    with pytest.raises(ValidationError):
        catalog.scale_sentence("05021-1", ["017-06", sizeless["code"]])


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


def test_the_eye_checked_false_rejects_stay_in_the_picker():
    """Rejections inside the trusted reasons that were checked by hand and found wrong."""
    for code in catalog.KEEP_DESPITE_AUDIT:
        assert catalog.crop_is_showable(code), f"{code} is a real product the audit got wrong"


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
