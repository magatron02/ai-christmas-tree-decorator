"""Design system compliance — DESIGN.md, replacing the Factory rules it superseded.

DESIGN.md scopes itself to "colour + typography tokens only", so what survives from the old
Factory ruleset is the discipline, not the mechanism: one file of literal colours, everything
else references a token, and every accent means something rather than decorating. The old
colour-mix contrast trick is gone — this palette's colours are pre-verified AA pairs stated
directly in the doc, checked here and in test_theme_contrast.py rather than derived.
"""

import re

import pytest

from backend import config

FRONTEND = config.FRONTEND_DIR
TOKENS = FRONTEND / "styles" / "tokens.css"
COMPONENTS = FRONTEND / "styles" / "components.css"
PAGES = sorted(FRONTEND.glob("*.html"))
SCRIPTS = sorted(FRONTEND.glob("*.js"))

PIPELINE_STATES = ("pending", "calling_api", "api_success", "api_failed", "delivered")


def read(path):
    return path.read_text(encoding="utf-8")


def strip_comments(source):
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    return re.sub(r"(?<!:)//[^\n]*", "", source)


def component_sources():
    return [COMPONENTS, *PAGES, *SCRIPTS]


# ---- rule 1: never a literal colour outside the token file --------------------------------

HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")
FUNCTIONAL = re.compile(r"\b(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch|color-mix)\s*\(")
NAMED = re.compile(
    r"(?<![\w-])(?:white|black|red|green|blue|orange|yellow|gray|grey|silver|maroon|navy|gold|wine)(?![\w-])",
    re.I,
)


@pytest.mark.parametrize("path", component_sources(), ids=lambda p: p.name)
def test_rule_1_no_literal_colour_outside_the_token_file(path):
    text = strip_comments(read(path))
    assert not HEX.findall(text), f"{path.name}: literal hex colour"
    assert not FUNCTIONAL.findall(text), f"{path.name}: literal colour function"
    assert not NAMED.findall(text), f"{path.name}: named colour"


def test_rule_1_the_token_file_defines_every_token_the_doc_lists():
    text = read(TOKENS)
    for token in (
        "--surface-0", "--surface-1", "--border", "--text-primary", "--text-muted",
        "--fill-primary", "--on-primary", "--text-accent-red",
        "--fill-success", "--text-success",
        "--fill-gold-block", "--text-gold",
        "--btn-primary-bg", "--btn-primary-bg-hover", "--btn-primary-bg-disabled",
        "--btn-secondary-border", "--btn-secondary-text",
        "--btn-ghost-border", "--btn-ghost-text",
        "--btn-success-bg", "--btn-success-bg-hover",
        "--state-error-bg", "--state-error-border", "--state-error-text",
        "--state-warning-bg", "--state-warning-border", "--state-warning-text",
        "--focus-ring-gap", "--focus-ring-color",
        "--font-header-en", "--font-body-en", "--font-th",
        "--radius-sm", "--radius-lg", "--space-4", "--text-base", "--transition-gentle",
    ):
        assert f"{token}:" in text, f"missing token {token}"


# ---- rule 2: gold is decorative-fill only, never text (DESIGN.md section 1's own audit) ---


def test_rule_2_the_raw_gold_fill_is_never_used_as_a_text_colour():
    """The doc's own contrast audit: --fill-gold-block is 2.75:1 as text and fails AA. Text
    must go through --text-gold instead. A component that puts --fill-gold-block in a
    `color:` declaration has reintroduced the failure the audit found."""
    css = strip_comments(read(COMPONENTS))
    for value in re.findall(r"(?<![\w-])color\s*:\s*([^;}]*)", css):
        assert "--fill-gold-block" not in value, f"gold fill used as text colour: {value.strip()}"


def test_rule_2_accents_appear_only_where_a_role_is_being_said():
    """Section 2: one accent per functional role, on a border or a label — never mixed into
    an unrelated element. Checked loosely: every rule touching a role token lives under a
    role class, a status chip, a button variant, or a notice."""
    css = strip_comments(read(COMPONENTS))
    role_tokens = ("--fill-primary", "--fill-success", "--fill-gold-block", "--text-gold",
                   "--text-success", "--text-accent-red")
    allowed = re.compile(
        r"\.role-|\.chip|\.btn\.(primary|success|danger)|\.notice|\.row\.active|"
        r"\.candidate|\.modal-item"
    )
    for selector, body in re.findall(r"([^{}]+)\{([^}]*)\}", css):
        if any(token in body for token in role_tokens):
            assert allowed.search(selector), f"role accent used outside a role context: {selector!r}"


# ---- rule 3 (was colour-mix): every accent-as-text pairing is one DESIGN.md verified ------


def test_rule_3_no_component_reinvents_a_colour_mix_formula():
    """The old system computed contrast at runtime with color-mix; this one uses pre-verified
    literal pairs. A color-mix reappearing means someone reached for the old pattern instead
    of the new tokens, and it would not be checked by anything here."""
    assert "color-mix(" not in strip_comments(read(COMPONENTS))


# ---- rule 4: one primary button per view (unchanged) --------------------------------------

PRIMARY = re.compile(r'class\s*=\s*"[^"]*\bbtn\b[^"]*\bprimary\b[^"]*"')


def test_rule_4_the_decorate_page_has_exactly_one_primary():
    matches = PRIMARY.findall(read(FRONTEND / "index.html"))
    assert len(matches) == 1, f"expected 1 primary button, found {len(matches)}"


def test_rule_4_the_confirm_dialog_uses_success_not_a_second_primary():
    """The dialog's own action is 'confirm/save' (section 2's role table), which maps to the
    success variant — and keeping it off wine also means the button that spends money is
    never the most visually emphasised control on the page (AC-4).

    Sliced by id rather than by "the first <dialog>": the catalogue picker is a second dialog
    on this page, and a positional slice would silently start checking whichever one happened
    to be written first.
    """
    html = read(FRONTEND / "index.html")
    start = html.index('<dialog id="confirm-dialog"')
    dialog = html[start : html.index("</dialog>", start)]
    assert "primary" not in dialog
    assert 'class="btn success"' in dialog


def test_rule_4_the_history_page_has_no_primary():
    assert PRIMARY.findall(read(FRONTEND / "history.html")) == []


def test_rule_4_the_settings_page_has_exactly_one_primary():
    """Saving the key is the one action that changes something on this page."""
    assert len(PRIMARY.findall(read(FRONTEND / "settings.html"))) == 1


PRIMARY_WORD = re.compile(r"(?<![a-zA-Z_])primary(?![a-zA-Z_])")


@pytest.mark.parametrize("path", SCRIPTS, ids=lambda p: p.name)
def test_rule_4_scripts_do_not_mint_extra_primaries(path):
    """Looks for the word inside a className assignment, not inside prose — theme.js quotes
    DESIGN.md's "Light theme — primary" in a comment, which is not a second button.

    Bounded so it does not fire on an unrelated identifier that happens to contain "primary"
    as a substring, like the vision schema's own `primary_colour` field
    (backend/services/vision.py) — a data field, not a button class."""
    text = strip_comments(read(path))
    assert not PRIMARY_WORD.search(text), f"{path.name} mentions 'primary' outside a comment"


# ---- rule 5: borders are 1px --------------------------------------------------------------

BORDER_DECL = re.compile(r"(?<![\w-])border(?:-top|-right|-bottom|-left)?\s*:\s*([^;}]*)")


def test_rule_5_every_border_is_one_pixel():
    css = strip_comments(read(COMPONENTS))
    for value in BORDER_DECL.findall(css):
        widths = re.findall(r"(\d*\.?\d+)px", value)
        assert all(width == "1" for width in widths), f"border width other than 1px: {value.strip()}"


# ---- rule 6: shadows are tokens, not literals ----------------------------------------------


def test_rule_6_box_shadow_only_ever_reaches_for_a_token():
    """`none` is allowed — danger and disabled buttons deliberately drop the elevation
    shadow — but a literal shadow value (a hardcoded blur/colour) is not."""
    css = strip_comments(read(COMPONENTS))
    values = [v.strip() for v in re.findall(r"box-shadow\s*:\s*([^;}]*)", css)]
    assert values, "at least one component should declare box-shadow"
    assert all(v.startswith("var(--") or v == "none" for v in values), values


# ---- rule 7: heavy weight only on the app title and modal heading -------------------------


def test_rule_7_only_the_logo_and_the_modal_heading_carry_a_hardcoded_weight():
    css = strip_comments(read(COMPONENTS))
    heavy = [
        selector.strip()
        for selector, body in re.findall(r"([^{}]+)\{([^}]*)\}", css)
        if re.search(r"font-weight:\s*(500|600|700|800|900)\b", body)
    ]
    assert set(heavy) <= {".logo", "dialog h2", ".caption", ".panel-title", ".section-title"}, heavy


# ---- rule 8: unreachable controls are disabled, never hidden -------------------------------


def test_rule_8_disabled_controls_stay_visible_at_reduced_opacity():
    css = strip_comments(read(COMPONENTS))
    assert re.search(r"\.btn:disabled\s*\{[^}]*opacity:\s*\.5", css)


def test_rule_8_the_page_ships_its_controls_disabled_rather_than_absent():
    html = read(FRONTEND / "index.html")
    for element_id in ("cut-btn", "size-select", "generate-btn"):
        match = re.search(rf'<[^>]*id="{element_id}"[^>]*>', html)
        assert match and "disabled" in match.group(0), f"{element_id} should start disabled"


# ---- a closed <dialog> must never be given `display` outside an [open] guard --------------
#
# The browser's own UA stylesheet is `dialog:not([open]) { display: none }`. An author rule for
# a dialog-related class that sets `display` WITHOUT `[open]` in its selector overrides that —
# author-origin beats user-agent-origin regardless of specificity — so the dialog renders
# inline on the page even while closed (happened for real: adding `.stack` to
# #vendor-import-dialog left it sitting at the bottom of settings.html at all times, 2026-09-11).
_DIALOG_DISPLAY_RULE = re.compile(r"([^{}]*\bdialog\b[^{}]*)\{([^}]*)\}", re.I)


def test_rule_8_a_dialog_class_only_sets_display_when_scoped_to_open():
    css = strip_comments(read(COMPONENTS))
    for selector, body in _DIALOG_DISPLAY_RULE.findall(css):
        if "display" not in body:
            continue
        # the bare reset (`dialog { ... }` with no display at all) and `dialog h2` never hit
        # this branch; every selector that both mentions "dialog" and sets `display` must be
        # scoped to the open state.
        assert "[open]" in selector, f"{selector.strip()!r} sets display outside [open]"


def test_every_dialog_element_uses_an_open_scoped_display_class_or_none():
    """Every <dialog ... class="..."> in the frontend either uses no class-based display rule
    at all (bare `dialog { ... }` already handles open/closed correctly) or a class that only
    appears in components.css alongside `[open]` — catches the same mistake from the HTML side,
    in case a page adds a new "helper" class to a dialog without also scoping it."""
    css = strip_comments(read(COMPONENTS))
    open_scoped_classes = {
        cls
        for selector, body in _DIALOG_DISPLAY_RULE.findall(css)
        if "display" in body and "[open]" in selector
        for cls in re.findall(r"\.([\w-]+)", selector)
    }
    for path in PAGES:
        for match in re.finditer(r'<dialog\b[^>]*\bclass="([^"]*)"', read(path)):
            for cls in match.group(1).split():
                assert cls in open_scoped_classes, (
                    f"{path.name}: <dialog class=\"{cls}\"> has no [open]-scoped display rule "
                    f"for that class — it will render even while closed"
                )


# ---- typography: Thai always resolves through the Thai face -------------------------------


def test_thai_pages_declare_the_thai_language():
    for path in PAGES:
        assert '<html lang="th">' in read(path), f"{path.name} must declare lang=th"


def test_the_logo_is_the_only_thing_in_the_header_font():
    css = strip_comments(read(COMPONENTS))
    owners = [
        selector.strip()
        for selector, body in re.findall(r"([^{}]+)\{([^}]*)\}", css)
        if "var(--font-header-en)" in body
    ]
    assert owners == [".logo"]


def test_body_text_defaults_to_the_thai_face():
    """Fraunces and Inter carry no Thai glyphs (DESIGN.md section 3): the base stack has to
    be Thai-first or Thai strings fall through to whatever the OS ships."""
    assert 'font-family: var(--font-th)' in read(TOKENS)


# ---- the app's own contract with the design system -----------------------------------------


def test_every_pipeline_state_has_a_chip_class():
    app_js = read(FRONTEND / "app.js")
    history_js = read(FRONTEND / "history.js")
    for state in PIPELINE_STATES:
        assert state in app_js, f"{state} missing from the decorate page"
        assert state in history_js, f"{state} missing from the history page"

    css = strip_comments(read(COMPONENTS))
    for chip in (".chip.done", ".chip.running", ".chip.stale", ".chip.failed"):
        assert chip in css, f"{chip} is referenced by the UI but not defined"


def test_no_font_is_loaded_from_a_network():
    for path in [COMPONENTS, TOKENS, *PAGES]:
        text = read(path)
        assert "fonts.googleapis" not in text
        assert not re.search(r'src:\s*url\(\s*["\']?https?://', text)
