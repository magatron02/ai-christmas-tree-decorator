"""Both themes meet WCAG AA — DESIGN.md's own contrast audit, independently recomputed.

DESIGN.md ships tables of pre-verified ratios (sections 1, 10, 12, 15). Trusting a table in a
doc is how a value drifts silently the next time someone edits a hex in tokens.css, so this
recomputes luminance and contrast from the token file itself rather than believing the
numbers written down next to it.
"""

import re

import pytest

from backend import config

TOKENS = (config.FRONTEND_DIR / "styles" / "tokens.css").read_text(encoding="utf-8")
AA, AA_LARGE = 4.5, 3.0


def block(selector):
    match = re.search(rf"{re.escape(selector)}\s*\{{(.*?)\n\}}", TOKENS, re.S)
    assert match, f"{selector} not found in the token file"
    return dict(re.findall(r"(--[\w-]+):\s*(#[0-9a-fA-F]{3,8})", match.group(1)))


LIGHT = block(":root")
DARK = {**LIGHT, **block(':root[data-theme="dark"]')}
THEMES = [("light", LIGHT), ("dark", DARK)]


def rgb(value):
    value = value.lstrip("#")
    if len(value) == 3:
        value = "".join(c * 2 for c in value)
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))


def luminance(colour):
    def channel(v):
        c = v / 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(c) for c in colour)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    la, lb = luminance(a), luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


@pytest.mark.parametrize("name, theme", THEMES)
@pytest.mark.parametrize("token", ["--text-primary", "--text-muted"])
def test_body_text_passes_aa(name, theme, token):
    ratio = contrast(rgb(theme[token]), rgb(theme["--surface-0"]))
    assert ratio >= AA, f"{name}: {token} is {ratio:.2f} on --surface-0"
    ratio = contrast(rgb(theme[token]), rgb(theme["--surface-1"]))
    assert ratio >= AA, f"{name}: {token} is {ratio:.2f} on --surface-1"


@pytest.mark.parametrize("name, theme", THEMES)
def test_the_primary_button_passes_aa(name, theme):
    ratio = contrast(rgb(theme["--on-primary"]), rgb(theme["--btn-primary-bg"]))
    assert ratio >= AA, f"{name}: primary button text is {ratio:.2f}"


@pytest.mark.parametrize("name, theme", THEMES)
def test_the_success_button_passes_aa(name, theme):
    ratio = contrast(rgb(theme["--btn-success-text"]), rgb(theme["--btn-success-bg"]))
    assert ratio >= AA, f"{name}: success button text is {ratio:.2f}"


@pytest.mark.parametrize("name, theme", THEMES)
def test_fill_primary_as_text_on_surface_passes_aa(name, theme):
    """--fill-primary doubles as --text-accent-red in the light theme (same hex). Checked on
    both surfaces since the wine appears on cards and on the page background alike."""
    for surface in ("--surface-0", "--surface-1"):
        ratio = contrast(rgb(theme["--text-accent-red"]), rgb(theme[surface]))
        assert ratio >= AA, f"{name}: text-accent-red on {surface} is {ratio:.2f}"


@pytest.mark.parametrize("name, theme", THEMES)
def test_success_text_on_surface_passes_aa(name, theme):
    ratio = contrast(rgb(theme["--text-success"]), rgb(theme["--surface-0"]))
    assert ratio >= AA, f"{name}: text-success is {ratio:.2f}"


@pytest.mark.parametrize("name, theme", THEMES)
def test_gold_text_token_passes_aa(name, theme):
    ratio = contrast(rgb(theme["--text-gold"]), rgb(theme["--surface-0"]))
    assert ratio >= AA, f"{name}: text-gold is {ratio:.2f}"


def test_the_raw_gold_fill_fails_as_text_in_the_light_theme():
    """This is the exact pairing DESIGN.md's own audit exists to enforce: 2.75:1, fails AA.
    --text-gold is the corrected value for that theme, which is why component code must
    never put --fill-gold-block in a `color:` declaration (test_ui_design_system.py)."""
    raw = contrast(rgb(LIGHT["--fill-gold-block"]), rgb(LIGHT["--surface-0"]))
    assert raw < AA, f"light: --fill-gold-block now passes AA as text ({raw:.2f}) — audit stale"


def test_the_raw_gold_fill_happens_to_pass_in_the_dark_theme():
    """DESIGN.md keeps the gold hex unchanged for dark ('already works on dark') rather than
    re-deriving it. Recorded rather than assumed: on the dark surface it does clear AA, so
    --text-gold is not rescuing a failure there the way it is in light — it exists for
    consistency with the light theme's token name, not because dark needs the correction."""
    raw = contrast(rgb(DARK["--fill-gold-block"]), rgb(DARK["--surface-0"]))
    assert raw >= AA, f"dark: --fill-gold-block is {raw:.2f} — DESIGN.md's 'unchanged' claim is wrong if this fails"


@pytest.mark.parametrize("name, theme", THEMES)
def test_state_banner_text_passes_aa_on_its_own_background(name, theme):
    for kind in ("error", "warning"):
        ratio = contrast(rgb(theme[f"--state-{kind}-text"]), rgb(theme[f"--state-{kind}-bg"]))
        assert ratio >= AA, f"{name}: state-{kind}-text on its own bg is {ratio:.2f}"


@pytest.mark.parametrize("name, theme", THEMES)
def test_focus_ring_is_visible_against_whatever_it_actually_surrounds(name, theme):
    """box-shadow: 0 0 0 2px gap, 0 0 0 4px ring draws the gap immediately against the
    focused element's own fill, and the outer ring immediately against the gap. A first
    version of this test required the gap alone to contrast against every fill and failed on
    a white gap around a white input (1.00:1) — a real number, but not a real problem: with
    gap and fill indistinguishable, the very next layer (the outer ring) becomes the visible
    boundary in its place, and that ring is always high-contrast against the gap by
    construction. What has to hold is that *one* of the two layers is visible against the
    fill, not that both independently are. It also caught a genuine bug this way: an earlier
    dark-theme guess (gap = dark surface tone) failed for the dark wine button on *both*
    layers at once (2.26 gap, and the ring by then is inherited from the gap's own low
    contrast) — that one needed an actual fix, now mirroring the light theme's white-gap/
    dark-ring structure.
    """
    outer_vs_gap = contrast(rgb(theme["--focus-ring-color"]), rgb(theme["--focus-ring-gap"]))
    assert outer_vs_gap >= AA_LARGE, f"{name}: outer ring vs its own gap is {outer_vs_gap:.2f}"

    for fill in ("--btn-primary-bg", "--surface-1", "--surface-0"):
        gap_vs_fill = contrast(rgb(theme["--focus-ring-gap"]), rgb(theme[fill]))
        outer_vs_fill = contrast(rgb(theme["--focus-ring-color"]), rgb(theme[fill]))
        assert max(gap_vs_fill, outer_vs_fill) >= AA_LARGE, (
            f"{name}: neither ring layer clears 3:1 against {fill} "
            f"(gap {gap_vs_fill:.2f}, outer {outer_vs_fill:.2f})"
        )


def test_light_is_still_the_default():
    """DESIGN.md names light as primary. An install that never opens settings must show it."""
    assert "color-scheme: light" in TOKENS
    assert TOKENS.index(":root {") < TOKENS.index(':root[data-theme="dark"]')


def test_dark_is_reachable_as_an_explicit_opt_in():
    assert ':root[data-theme="dark"]' in TOKENS
