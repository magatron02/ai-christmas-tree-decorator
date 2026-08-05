"""Factory design system compliance — section 6, rules 1 to 9.

The design system asks for this itself: "If your project has a lint or test layer, assert
that the literal color-mix string is present. It is the kind of rule that gets quietly
unwound during a refactor, and the failure is invisible to anyone with good eyesight."

So this suite is a linter, not a rendering test. It reads the frontend as text.
"""

import re

import pytest

from backend import config

FRONTEND = config.FRONTEND_DIR
TOKENS = FRONTEND / "styles" / "factory-tokens.css"
COMPONENTS = FRONTEND / "styles" / "factory.css"
PAGES = sorted(FRONTEND.glob("*.html"))
SCRIPTS = sorted(FRONTEND.glob("*.js"))

PIPELINE_STATES = ("pending", "calling_api", "api_success", "api_failed", "delivered")


def read(path):
    return path.read_text(encoding="utf-8")


def strip_comments(css):
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def component_sources():
    """Everything except the token file — that is the one place literals are allowed."""
    return [COMPONENTS, *PAGES, *SCRIPTS]


# ---- rule 1: never a literal colour in a component ---------------------------------------

HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")
FUNCTIONAL = re.compile(r"\b(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch)\s*\(")
NAMED = re.compile(
    r"(?<![\w-])(?:white|black|red|green|blue|orange|yellow|gray|grey|silver|maroon|navy)(?![\w-])",
    re.I,
)


@pytest.mark.parametrize("path", component_sources(), ids=lambda p: p.name)
def test_rule_1_no_literal_colour_outside_the_token_file(path):
    text = strip_comments(read(path))
    assert not HEX.findall(text), f"{path.name}: literal hex colour"
    assert not FUNCTIONAL.findall(text), f"{path.name}: literal colour function"
    assert not NAMED.findall(text), f"{path.name}: named colour"


def test_rule_1_the_token_file_still_defines_every_token():
    text = read(TOKENS)
    for token in (
        "--bg", "--bg-elevated", "--border",
        "--text", "--text-2", "--text-3",
        "--accent-positive", "--accent-warning",
        "--btn-bg", "--btn-hover-bg", "--btn-primary-bg", "--btn-primary-hover-bg",
        "--btn-primary-text",
        "--radius-sm", "--radius-lg", "--shadow",
        "--font-ui", "--font-mono", "--weight-heading", "--tracking-heading",
    ):
        assert f"{token}:" in text, f"missing token {token}"


# ---- rule 2: accents mean status, never decoration, never a fill --------------------------


def test_rule_2_no_accent_is_ever_a_background():
    css = strip_comments(read(COMPONENTS))
    fills = re.findall(r"(?<![\w-])background(?:-color)?\s*:\s*([^;}]*)", css)
    offenders = [value.strip() for value in fills if "--accent" in value]
    assert offenders == [], f"accent used as a fill: {offenders}"


def test_rule_2_accents_only_appear_where_a_status_is_being_said():
    """Every accent reference belongs to a chip, the danger button or the error notice."""
    css = strip_comments(read(COMPONENTS))
    for block in re.findall(r"([^{}]+)\{([^}]*)\}", css):
        selector, body = block[0].strip(), block[1]
        if "--accent" not in body:
            continue
        assert re.search(r"\.chip|\.danger|\.notice", selector), (
            f"accent used outside a status context: {selector!r}"
        )


# ---- rule 3: accents as text go through color-mix(… 55%, var(--text)) --------------------

COLOR_DECL = re.compile(r"(?<![\w-])color\s*:\s*([^;}]*)")
MIXED = re.compile(r"color-mix\(\s*in\s+srgb\s*,\s*var\(--accent-[a-z]+\)\s+55%\s*,\s*var\(--text\)\s*\)")


def test_rule_3_accent_text_is_always_mixed_to_pass_contrast():
    css = strip_comments(read(COMPONENTS))
    accent_colours = [value for value in COLOR_DECL.findall(css) if "--accent" in value]
    assert accent_colours, "expected at least one accent-coloured text rule"
    for value in accent_colours:
        assert MIXED.search(value), f"raw accent used as text: color: {value.strip()}"


def test_rule_3_the_literal_mix_string_is_present():
    """The check the design system explicitly asks for."""
    assert "color-mix(in srgb, var(--accent-" in read(COMPONENTS)


# ---- rule 4: one primary button per view -------------------------------------------------

PRIMARY = re.compile(r'class\s*=\s*"[^"]*\bbtn\b[^"]*\bprimary\b[^"]*"')


def test_rule_4_the_decorate_page_has_exactly_one_primary():
    matches = PRIMARY.findall(read(FRONTEND / "index.html"))
    assert len(matches) == 1, f"expected 1 primary button, found {len(matches)}"


def test_rule_4_the_confirm_dialog_is_not_a_second_primary():
    """The dialog is a view of its own and the page already spent its primary on Generate.
    The button that costs money being the quieter one is also the right call for AC-4."""
    html = read(FRONTEND / "index.html")
    dialog = html[html.index("<dialog") : html.index("</dialog>")]
    assert "primary" not in dialog


def test_rule_4_the_history_page_has_no_primary():
    assert PRIMARY.findall(read(FRONTEND / "history.html")) == []


@pytest.mark.parametrize("path", SCRIPTS, ids=lambda p: p.name)
def test_rule_4_scripts_do_not_mint_extra_primaries(path):
    assert "primary" not in read(path)


# ---- rule 5: borders are 1px, emphasis is the colour --------------------------------------

BORDER_DECL = re.compile(r"(?<![\w-])border(?:-top|-right|-bottom|-left)?\s*:\s*([^;}]*)")


def test_rule_5_every_border_is_one_pixel():
    css = strip_comments(read(COMPONENTS))
    for value in BORDER_DECL.findall(css):
        widths = re.findall(r"(\d*\.?\d+)px", value)
        assert all(width == "1" for width in widths), f"border width other than 1px: {value.strip()}"


# ---- rule 6: no shadows, but keep writing box-shadow ---------------------------------------


def test_rule_6_box_shadow_only_ever_reaches_for_the_token():
    css = strip_comments(read(COMPONENTS))
    values = re.findall(r"box-shadow\s*:\s*([^;}]*)", css)
    assert values, "the card should still declare box-shadow so a future token can reach it"
    assert all(value.strip() == "var(--shadow)" for value in values), values


# ---- rule 7: weight 400 everywhere, 500 only for the logo and modal headings ---------------


def test_rule_7_no_hardcoded_heavy_weights():
    css = strip_comments(read(COMPONENTS))
    values = [value.strip() for value in re.findall(r"font-weight\s*:\s*([^;}]*)", css)]
    allowed = {"var(--weight-heading)", "400 700"}  # the second is the @font-face range
    assert set(values) <= allowed, f"unexpected font weights: {sorted(set(values) - allowed)}"


def test_rule_7_only_the_logo_and_the_modal_heading_are_heavy():
    css = strip_comments(read(COMPONENTS))
    heavy = [
        selector.strip()
        for selector, body in re.findall(r"([^{}]+)\{([^}]*)\}", css)
        if "var(--weight-heading)" in body
    ]
    assert sorted(heavy) == [".logo", "dialog h2"]


# ---- rule 8: unreachable controls are disabled, never hidden -------------------------------


def test_rule_8_disabled_controls_stay_visible_at_half_opacity():
    css = strip_comments(read(COMPONENTS))
    assert re.search(r"\.btn:disabled\s*\{[^}]*opacity:\s*\.5", css)


def test_rule_8_the_page_ships_its_controls_disabled_rather_than_absent():
    """Every control the user cannot use yet is in the markup with `disabled` on it, so the
    whole shape of the tool is visible from the first paint."""
    html = read(FRONTEND / "index.html")
    for element_id in ("cut-btn", "size-select", "generate-btn"):
        match = re.search(rf'<[^>]*id="{element_id}"[^>]*>', html)
        assert match and "disabled" in match.group(0), f"{element_id} should start disabled"


# ---- rule 9: nothing may depend on letter case ---------------------------------------------


def test_rule_9_uppercase_is_styling_only_and_has_an_escape_hatch():
    css = strip_comments(read(COMPONENTS))
    owners = [
        selector.strip()
        for selector, body in re.findall(r"([^{}]+)\{([^}]*)\}", css)
        if "text-transform: uppercase" in body
    ]
    assert owners == [".caption"], f"uppercase applied outside .caption: {owners}"
    assert re.search(r"\.caption\s+\.sub\s*\{[^}]*text-transform:\s*none", css)


# ---- the app's own contract with the design system -----------------------------------------


def test_every_pipeline_state_has_a_chip_class():
    """Spec.md 2 defines five states; all five must render as a chip, and api_failed uses the
    agreed .chip.failed rather than a new colour."""
    app_js = read(FRONTEND / "app.js")
    history_js = read(FRONTEND / "history.js")
    for state in PIPELINE_STATES:
        assert state in app_js, f"{state} missing from the decorate page"
        assert state in history_js, f"{state} missing from the history page"

    css = strip_comments(read(COMPONENTS))
    for chip in (".chip.done", ".chip.running", ".chip.stale", ".chip.failed"):
        assert chip in css, f"{chip} is referenced by the UI but not defined"


def test_no_font_is_loaded_from_a_network():
    """Section 7: a design system that stops looking right without a network is not a system."""
    for path in [COMPONENTS, *PAGES]:
        text = read(path)
        assert "fonts.googleapis" not in text
        assert "https://" not in text or "@font-face" not in text or "cdn" not in text.lower()
        assert not re.search(r'src:\s*url\(\s*["\']?https?://', text)
