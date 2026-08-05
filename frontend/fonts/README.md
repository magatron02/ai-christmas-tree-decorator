# Fonts

    inter.woff2            @fontsource-variable/inter          (SIL OFL 1.1)
    jetbrains-mono.woff2   @fontsource-variable/jetbrains-mono  (SIL OFL 1.1)

Variable `.woff2`, latin subset, ~45 KB each. Committed rather than fetched, and there is no
CDN link anywhere in the project: "a design system that stops looking right without a network
is not a system" (factory-design-system.md section 7). A clone renders correctly offline.

`@font-face` is declared in `../styles/factory.css` and points at these filenames, so
replacing a file is enough to change the face — nothing else refers to them.

Both have a full system fallback stack, so a missing file degrades to `Segoe UI` / `Consolas`
rather than breaking. The caption's negative tracking is tuned for JetBrains Mono, though, so
the stamped-label look only works with the real file present.
