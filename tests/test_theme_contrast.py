"""Both themes meet WCAG AA — Product.md 8.4.

factory-design-system.md section 8 says a light variant needs both accents re-derived because
neither passes AA on a light background. Measured, the raw accents do fail: 1.77 for the
green, 3.18 for the orange. But Rule 3 already sends every accent used as text through
color-mix(… 55%, var(--text)), and --text flips with the theme, so the mix rescues both.

That is the sort of claim that quietly stops being true, so it is computed here rather than
believed. Numbers come from the token file, so editing a token runs the check.
"""

import re

import pytest

from backend import config

TOKENS = (config.FRONTEND_DIR / "styles" / "factory-tokens.css").read_text(encoding="utf-8")
MIX_SHARE = 0.55   # the literal in Rule 3, asserted separately by the design-system suite
AA, AA_LARGE = 4.5, 3.0


def block(selector):
    match = re.search(rf"{re.escape(selector)}\s*\{{(.*?)\}}", TOKENS, re.S)
    assert match, f"{selector} not found in the token file"
    return dict(re.findall(r"(--[\w-]+):\s*(#[0-9a-fA-F]{3,8})", match.group(1)))


DARK = block(":root")
LIGHT = {**DARK, **block(':root[data-theme="light"]')}


def rgb(value):
    value = value.lstrip("#")
    if len(value) == 3:
        value = "".join(c * 2 for c in value)
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))


def luminance(colour):
    def channel(value):
        c = value / 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(c) for c in colour)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    la, lb = luminance(a), luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def mixed(accent, text):
    return tuple(
        round(MIX_SHARE * a + (1 - MIX_SHARE) * t) for a, t in zip(rgb(accent), rgb(text))
    )


THEMES = [("dark", DARK), ("light", LIGHT)]


@pytest.mark.parametrize("name, theme", THEMES)
@pytest.mark.parametrize("token", ["--text", "--text-2", "--text-3"])
def test_body_text_passes_aa(name, theme, token):
    ratio = contrast(rgb(theme[token]), rgb(theme["--bg"]))
    assert ratio >= AA, f"{name}: {token} is {ratio:.2f} on --bg"


@pytest.mark.parametrize("name, theme", THEMES)
@pytest.mark.parametrize("accent", ["--accent-positive", "--accent-warning"])
def test_accent_text_passes_aa_once_mixed(name, theme, accent):
    """The raw accent is allowed to fail — the system never puts it on text raw."""
    ratio = contrast(mixed(theme[accent], theme["--text"]), rgb(theme["--bg"]))
    assert ratio >= AA, f"{name}: {accent} mixed is {ratio:.2f} on --bg"


@pytest.mark.parametrize("name, theme", THEMES)
def test_the_primary_button_is_maximum_contrast(name, theme):
    ratio = contrast(rgb(theme["--btn-primary-text"]), rgb(theme["--btn-primary-bg"]))
    assert ratio >= 10, f"{name}: primary button is only {ratio:.2f}"


@pytest.mark.parametrize("name, theme", THEMES)
def test_the_warning_accent_works_as_a_border(name, theme):
    """.chip.failed and .notice draw their border in the raw accent, and a border needs to
    be seen rather than read — AA-large is the right bar for it."""
    ratio = contrast(rgb(theme["--accent-warning"]), rgb(theme["--bg"]))
    assert ratio >= AA_LARGE, f"{name}: warning border is {ratio:.2f} on --bg"


def test_the_light_theme_does_not_introduce_a_new_accent():
    """Section 8 warns that adding a colour is almost always the wrong move. The mix rule
    made re-tuning unnecessary, so the accents stay identical across themes."""
    light_only = block(':root[data-theme="light"]')
    assert "--accent-positive" not in light_only
    assert "--accent-warning" not in light_only


def test_dark_is_still_the_default():
    """An install that never opens settings must look exactly as it did before themes."""
    assert "color-scheme: dark" in TOKENS
    assert TOKENS.index(":root {") < TOKENS.index(':root[data-theme="light"]')
