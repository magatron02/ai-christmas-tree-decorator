"""The vendor price-list base and its overlay, merged field by field — ADR-0001's pattern,
applied a second time to vendor-pricelists/bangkok-christmas/cleaned/lookup.json instead of
the catalogue. Same reason to test it the same way test_shop_overlay.py does: the thing that
matters is whether a shop's correction survives lookup.json being regenerated wholesale, which
is exactly what a real `build_lookup.py` re-run does.
"""

import json

import pytest

from backend import config
from backend.services import vendor_lookup, vendor_overlay
from backend.validation import ValidationError


@pytest.fixture
def temp_vendor_lookup(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "VENDOR_PRICELISTS_DIR", tmp_path)
    monkeypatch.setattr(
        config, "VENDOR_SUPPLIERS",
        {"bangkok-christmas": {"label": "Bangkok Christmas", "book": "Bangkok Christmas"}},
    )
    path = tmp_path / "bangkok-christmas" / "cleaned" / "lookup.json"
    path.parent.mkdir(parents=True)
    path.write_text("{}", encoding="utf-8")
    vendor_lookup.refresh()
    yield path
    vendor_lookup.refresh()


def regenerate(path, entries):
    """What a real build_lookup.py run does to lookup.json: rewrite it wholesale."""
    path.write_text(json.dumps(entries), encoding="utf-8")
    vendor_lookup.refresh()


def test_an_override_is_invisible_until_set(temp_vendor_lookup):
    assert vendor_overlay.fields_for("071-11") == {}


def test_a_price_override_wins_over_the_base(temp_vendor_lookup):
    regenerate(temp_vendor_lookup, {"071-11": {"price": 89.0}})
    vendor_overlay.set_fields("071-11", {"price": 120.0}, speaks_for=("price",))

    assert vendor_lookup.price_for("071-11") == 120.0


def test_the_override_survives_a_lookup_regeneration(temp_vendor_lookup):
    """The whole point of the split — a real build_lookup.py re-run must not erase it."""
    regenerate(temp_vendor_lookup, {"071-11": {"price": 89.0, "size_mm": 80.0}})
    vendor_overlay.set_fields("071-11", {"price": 120.0}, speaks_for=("price",))

    regenerate(temp_vendor_lookup, {"071-11": {"price": 95.0, "size_mm": 85.0}})

    assert vendor_lookup.price_for("071-11") == 120.0


def test_a_field_the_shop_never_touched_still_follows_the_regenerated_base(temp_vendor_lookup):
    regenerate(temp_vendor_lookup, {"071-11": {"price": 89.0, "size_mm": 80.0}})
    vendor_overlay.set_fields("071-11", {"price": 120.0}, speaks_for=("price",))

    regenerate(temp_vendor_lookup, {"071-11": {"price": 95.0, "size_mm": 85.0}})

    assert vendor_lookup.size_mm_for("071-11") == 85.0


def test_editing_a_field_back_to_the_base_value_returns_it_to_the_base(temp_vendor_lookup):
    """An opinion the shop retracts (nothing sent for a field it used to speak for) must not
    freeze the old number in place forever — same rule as shop_overlay.set_fields."""
    regenerate(temp_vendor_lookup, {"071-11": {"price": 89.0}})
    vendor_overlay.set_fields("071-11", {"price": 120.0}, speaks_for=("price",))

    vendor_overlay.set_fields("071-11", {}, speaks_for=("price",))  # cleared

    assert "price" not in vendor_overlay.fields_for("071-11")
    assert vendor_lookup.price_for("071-11") == 89.0


def test_pack_ambiguous_false_is_a_real_override_not_just_an_absent_key(temp_vendor_lookup):
    """A shop that checked the PDF page and confirmed a row is per-piece needs that to stick —
    it is an opinion, not the same as never having looked."""
    regenerate(temp_vendor_lookup, {"071-11": {"price": 45.0, "pack_ambiguous": True}})
    vendor_overlay.set_fields("071-11", {"pack_ambiguous": False}, speaks_for=("pack_ambiguous",))

    assert vendor_lookup.pack_for("071-11") is None  # no longer ambiguous, no pack either


def test_an_unknown_field_is_rejected(temp_vendor_lookup):
    with pytest.raises(ValidationError):
        vendor_overlay.set_fields("071-11", {"code": "071-12"})


def test_the_overlay_lives_beside_the_spend_log_not_beside_the_vendor_files(temp_vendor_lookup):
    """data/ is excluded from the installer's file list; vendor-pricelists/ ships committed
    files a shop should never lose to a reinstall touching this overlay."""
    assert vendor_overlay.overlay_path().parent == config.DATA_DIR
    assert vendor_overlay.overlay_path().parent == config.DB_PATH.parent
    assert vendor_overlay.overlay_path().parent != config.VENDOR_PRICELISTS_DIR
