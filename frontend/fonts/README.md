# Fonts

    fraunces.woff2                    @fontsource-variable/fraunces   (SIL OFL 1.1)
    inter.woff2                       @fontsource-variable/inter      (SIL OFL 1.1)
    jetbrains-mono.woff2              JetBrains Mono                  (SIL OFL 1.1)
    bai-jamjuree-400.woff2            Bai Jamjuree (Thai subset)      (SIL OFL 1.1)
    bai-jamjuree-600.woff2            Bai Jamjuree (Thai subset)      (SIL OFL 1.1)
    bai-jamjuree-latin-400.woff2      Bai Jamjuree (Latin subset)     (SIL OFL 1.1)
    bai-jamjuree-latin-600.woff2      Bai Jamjuree (Latin subset)     (SIL OFL 1.1)
    anuphan.woff2                     Anuphan variable (Thai subset)  (SIL OFL 1.1)
    anuphan-latin.woff2               Anuphan variable (Latin subset) (SIL OFL 1.1)

Fraunces for the app title, Bai Jamjuree for headings and the sidebar, Anuphan for body copy
and every description. Both Thai families carry Latin as well, so a mixed Thai/English line
stays in one typeface instead of splitting across two.

The Bai Jamjuree and Anuphan files are the Google Fonts woff2 subsets, downloaded once and
committed. Latin and Thai ship separately with their own `unicode-range`, so a Thai page never
downloads Latin glyphs it will not draw. Anuphan is a variable font, so one file per subset
covers the whole 400-600 range; Bai Jamjuree is not, hence a file per weight.

Committed rather than fetched — no CDN link anywhere in the project, so a clone renders
correctly offline (`test_no_font_is_loaded_from_a_network` enforces this). `@font-face` is
declared in `../styles/tokens.css` with `font-display: block`, not `swap`: swap paints the
fallback first and re-paints when the webfont lands, which is a visible flash of the wrong
font on every page load. Served from localhost the block period is imperceptible.

Every family has a system fallback stack, so a missing file degrades rather than breaks.
