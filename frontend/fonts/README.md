# Fonts

    fraunces.woff2                        @fontsource-variable/fraunces          (SIL OFL 1.1)
    inter.woff2                           @fontsource-variable/inter             (SIL OFL 1.1)
    ibm-plex-sans-thai-400.woff2          @fontsource/ibm-plex-sans-thai (Thai)  (SIL OFL 1.1)
    ibm-plex-sans-thai-600.woff2          @fontsource/ibm-plex-sans-thai (Thai)  (SIL OFL 1.1)
    ibm-plex-sans-thai-latin-400.woff2    @fontsource/ibm-plex-sans-thai (Latin) (SIL OFL 1.1)
    ibm-plex-sans-thai-latin-600.woff2    @fontsource/ibm-plex-sans-thai (Latin) (SIL OFL 1.1)

Self-hosted per DESIGN.md's typography section — Fraunces for the app title, Inter for Latin
UI text, IBM Plex Sans Thai for everything Thai (which is almost everything, since the UI
copy is Thai). Fraunces and Inter carry no Thai glyphs, so Thai strings always resolve
through IBM Plex Sans Thai rather than falling through to a system font.

Committed rather than fetched — no CDN link anywhere in the project, so a clone renders
correctly offline. `@font-face` is declared in `../styles/tokens.css`.

Every family has a system fallback stack (Georgia, -apple-system, Tahoma-class sans), so a
missing file degrades rather than breaks.
