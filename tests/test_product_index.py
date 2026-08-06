"""The product-photo index — Product.md 8.1 phase B.

The index says which catalogue photo sits next to which code. It is built by a geometric
rule and is not verified, so what these tests protect is the honesty of the record rather
than its accuracy: every row must say which rule produced it, and nothing may claim a
certainty the rule cannot deliver (NonGoals.md 7).
"""

import json

import pytest

from backend import config

INDEX = config.ROOT / "catalog" / "product_images.json"

pytestmark = pytest.mark.skipif(
    not INDEX.is_file(), reason="run scripts/build_product_index.py first"
)


@pytest.fixture(scope="module")
def rows():
    return json.loads(INDEX.read_text(encoding="utf-8"))


def test_every_row_says_how_it_was_matched(rows):
    allowed = {"directly_above", "above_far", "beside", "no_rule_fitted", "no_photo_found"}
    assert {row["match"] for row in rows} <= allowed


def test_no_row_claims_confidence(rows):
    """These were once labelled high/medium/low. Spot-checking found 'high' rows that were
    coin tosses between a retail pack and a loose ball printed above the same label, so the
    names now describe the rule that fired and nothing more."""
    for row in rows:
        assert "confidence" not in row
        assert row["match"] not in {"high", "medium", "low"}


def test_rows_without_a_photo_say_so_rather_than_pointing_somewhere(rows):
    for row in rows:
        if row["match"] == "no_photo_found":
            assert row["image"] is None


def test_shared_photos_are_counted_not_hidden(rows):
    """A ribbon listing two sizes points at one pack, so sharing is legitimate — but it has
    to be visible in the data, because a shared photo means the code is less pinned down."""
    for row in rows:
        if row["image"]:
            assert "shared_with" in row
    assert any(row.get("shared_with") for row in rows), "expected some legitimate sharing"


def test_the_index_covers_the_same_codes_as_the_size_table(rows):
    products = json.loads((config.ROOT / "catalog" / "products.json").read_text(encoding="utf-8"))
    assert {row["code"] for row in rows} == {row["code"] for row in products}


def test_a_meaningful_share_of_codes_got_a_photo(rows):
    """Not a quality bar — a smoke alarm. If a layout change drops this to near zero the
    index is silently empty and 8.3c would recommend nothing while looking fine."""
    with_photo = [row for row in rows if row["image"]]
    assert len(with_photo) / len(rows) > 0.8
