# DESIGN.md — AI Christmas Tree Decorator

Scope: color + typography design tokens only. No layout/component work yet
(layout comes after multi-element + reference-image features per product spec).

Theme: warm/cozy Christmas — desaturated, not literal red/green/gold.

---

## 1. Color Tokens (Light theme — primary)

```css
:root {
  /* surfaces */
  --surface-0: #F7F1E8;   /* page background — cream */
  --surface-1: #FFFFFF;   /* card background */
  --border: rgba(0, 0, 0, 0.06);

  /* text */
  --text-primary: #2E2A22;
  --text-muted: #8A7D68;

  /* wine red — primary action (CTA / Generate) */
  --fill-primary: #7A2E2E;
  --on-primary: #FFFFFF;
  --text-accent-red: #7A2E2E;

  /* forest green — success / result state */
  --fill-success: #2E4A3B;
  --text-success: #2E4A3B;

  /* muted gold — DECORATIVE ONLY (swatches, image blocks, badge fills) */
  --fill-gold-block: #B08D57;
  /* darker variant — required if gold is ever used as text */
  --text-gold: #7A5A1E;

  /* fonts */
  --font-header-en: 'Fraunces', Georgia, serif;
  --font-body-en: 'Inter', -apple-system, sans-serif;
  --font-th: 'IBM Plex Sans Thai', 'Inter', sans-serif;
}
```

### Contrast audit (WCAG AA, verified — not eyeballed)

| Pair | Ratio | Result |
|---|---|---|
| `--fill-primary` (#7A2E2E) on `--surface-0` (#F7F1E8) | 8.28:1 | PASS |
| `--on-primary` (#FFF) on `--fill-primary` button | 9.30:1 | PASS |
| `--text-success` (#2E4A3B) on `--surface-0` | 8.66:1 | PASS |
| `--text-primary` (#2E2A22) on `--surface-0` | 12.72:1 | PASS |
| `--text-primary` on `--surface-1` (white card) | 14.28:1 | PASS |
| `--fill-primary` on `--surface-1` (white card) | 9.30:1 | PASS |
| `--fill-gold-block` (#B08D57) as **text** on `--surface-0` | 2.75:1 | **FAIL — do not use as text** |
| `--text-gold` (#7A5A1E) as text on `--surface-0` | 5.65:1 | PASS |

**Rule:** `--fill-gold-block` is for filled shapes only (photo placeholders, tag
backgrounds, swatches). Any gold *text* or *icon* must use `--text-gold`
instead — never the base gold hex.

---

## 2. Color role mapping (tied to the 3-panel flow)

| Panel | Role | Token |
|---|---|---|
| Bare tree (input) | neutral | `--surface-1` card, `--text-muted` label |
| Element (input) | secondary / decorative | `--fill-gold-block` block, `--text-gold` label |
| Result (output) | success / completion | `--fill-success` block + border, `--text-success` label |
| Generate button | primary action | `--fill-primary` fill, `--on-primary` text |

One accent color per functional role — do not mix red/green/gold within the
same UI element.

---

## 3. Typography

- **English headers** (app name, branding): `--font-header-en` (Fraunces,
  weight 500–600 only — load selectively, it's a variable font, don't pull
  the full family).
- **English body/UI** (buttons, labels, descriptions): `--font-body-en`
  (Inter).
- **Thai text** (any label, button, tooltip, error message in Thai):
  `--font-th` (IBM Plex Sans Thai), with `Inter` as fallback — never let Thai
  glyphs fall through to a system font.

```css
.app-title       { font-family: var(--font-header-en); }
.ui-text-en      { font-family: var(--font-body-en); }
.ui-text-th      { font-family: var(--font-th); }
```

Fraunces and Inter have no Thai glyph coverage — Thai strings must always
resolve through `--font-th`, including inside components that otherwise use
`--font-body-en`.

---

## 4. Button variants & states

```css
:root {
  /* primary — main action (Generate) */
  --btn-primary-bg: #7A2E2E;
  --btn-primary-bg-hover: #651F1F;   /* ~10% darker */
  --btn-primary-bg-disabled: #D9C3C1;
  --btn-primary-text: #FFFFFF;
  --btn-primary-text-disabled: #F7F1E8;

  /* secondary — outline (Reset / cancel) */
  --btn-secondary-border: #D9B0AC;
  --btn-secondary-text: #7A2E2E;
  --btn-secondary-bg-hover: #F7ECE9;  /* light red tint */

  /* ghost — text-only, low emphasis (Download) */
  --btn-ghost-border: rgba(0, 0, 0, 0.1);
  --btn-ghost-text: #8A7D68;
  --btn-ghost-bg-hover: rgba(0, 0, 0, 0.03);

  /* success — confirm/save result */
  --btn-success-bg: #2E4A3B;
  --btn-success-bg-hover: #233A2E;   /* ~10% darker */
  --btn-success-text: #FFFFFF;
}
```

| Variant | Use for | Default | Hover | Disabled |
|---|---|---|---|---|
| Primary | Generate / main action | `--btn-primary-bg` fill, white text | 10% darker fill | desaturated fill + muted text |
| Secondary | Reset / cancel | Transparent, red border+text | light red tint fill | — |
| Ghost | Download / low-emphasis | Transparent, gray border+text | subtle black tint fill | — |
| Success | Save / confirm result | `--btn-success-bg` fill, white text | 10% darker fill | — |

Hover/disabled values are derived (base color ±10% lightness, or desaturated)
— confirmed by product owner, not independently re-audited for AA since they
inherit contrast from their base tokens (already verified in §1).

---

## 5. File picker

```css
:root {
  --picker-border-idle: #D9B0AC;       /* dashed */
  --picker-bg-idle: #FFFFFF;
  --picker-icon-idle: #7A2E2E;

  --picker-border-dragover: #7A2E2E;   /* solid */
  --picker-bg-dragover: #F7ECE9;
  --picker-icon-dragover-bg: #7A2E2E;

  --picker-bg-filled: #FFFFFF;
  --picker-thumbnail-bg: #ECE4D6;
  --picker-change-link: #7A2E2E;       /* underlined */
}
```

3 states: idle (dashed wine-red border, upload icon) → dragover (solid
border, tinted fill, filled icon) → filled (white card, thumbnail preview,
"เปลี่ยนไฟล์" link in wine red).

---

## 6. Modal / scrollable panel

```css
:root {
  --modal-bg: #FFFFFF;
  --modal-shadow: 0 2px 8px rgba(46, 42, 34, 0.06);   /* subtle */
  --modal-border: rgba(0, 0, 0, 0.06);        /* header/footer dividers */
  --modal-item-selected-bg: #F7ECE9;
  --modal-item-selected-text: #7A2E2E;
}
```

Structure: header (title + close) → scrollable body (`max-height` +
`overflow-y: auto`, list items with `--modal-item-selected-bg` for the
active/selected row) → footer (secondary "ยกเลิก" + primary confirm button,
per §4 variants).

---

## 7. Custom scrollbar

```css
:root {
  --scrollbar-track: #FFFFFF;      /* matches --surface-1 (card bg) */
  --scrollbar-thumb: #8A7D68;      /* reuses --text-muted */
  --scrollbar-arrow-bg: #F2EDE4;
  --scrollbar-arrow-icon: #8A7D68;
  --scrollbar-divider: rgba(0, 0, 0, 0.04);  /* thin separator from content */
}
```

```css
/* WebKit */
::-webkit-scrollbar { width: 16px; }
::-webkit-scrollbar-track {
  background: var(--scrollbar-track);
  border-left: 1px solid var(--scrollbar-divider);
}
::-webkit-scrollbar-thumb {
  background: var(--scrollbar-thumb);
  border-radius: 5px;
}
::-webkit-scrollbar-button {
  background: var(--scrollbar-arrow-bg);
  height: 11px;
}
```

Track matches the card surface (`--surface-1`) so the scrollbar reads as part
of the card rather than a separate strip — a thin divider keeps it visually
distinct from the scrollable content. `--scrollbar-thumb` against a white
track measures 4.03:1, comfortably above the 3:1 minimum for non-text UI
components (WCAG 1.4.11). Only apply within scrollable panels (e.g. the
element picker modal), not page-level.

### Hover feedback

```css
:root {
  --scrollbar-thumb-hover: #7A2E2E;   /* reuses --fill-primary */
  --scrollbar-arrow-bg-hover: #E6DDD0;
}
```

```css
::-webkit-scrollbar-thumb {
  background: var(--scrollbar-thumb);
  border-radius: 5px;
  width: 9px;
  transition: background var(--transition-gentle), width var(--transition-gentle);
}
::-webkit-scrollbar-thumb:hover {
  background: var(--scrollbar-thumb-hover);
  width: 11px;
}
::-webkit-scrollbar-button:hover {
  background: var(--scrollbar-arrow-bg-hover);
}
.scroll-container {
  scroll-behavior: smooth;
}
```

Thumb shifts to `--fill-primary` and widens slightly (9px → 11px) on hover —
signals interactivity and gives a marginally easier target, both at
`--transition-gentle` (200ms ease-out) for consistency with the rest of the
system. `scroll-behavior: smooth` applies to the scrollable content itself so
programmatic or keyboard-triggered scrolling glides rather than jumps.

---

## 8. Transitions

```css
:root {
  --transition-gentle: 200ms ease-out;
}
```

Single standard timing across the system — hover states (buttons, list
items), modal entrance/exit (opacity + scale), and dropdown open/close all
use `--transition-gentle`. Keeps motion consistent instead of mixing speeds
per component.

```css
.btn { transition: background var(--transition-gentle); }
.modal { transition: opacity var(--transition-gentle), transform var(--transition-gentle); }
```

### Button hover + press

```css
:root {
  --transition-press: 100ms ease-out;   /* faster than gentle — press needs
                                             to feel immediate, not eased */
}
```

```css
.btn {
  transition: background var(--transition-gentle),
              transform var(--transition-gentle),
              box-shadow var(--transition-gentle);
  box-shadow: 0 1px 2px rgba(46, 42, 34, 0.08);
}
.btn:hover {
  transform: translateY(-1px);
  box-shadow: 0 4px 10px rgba(122, 46, 46, 0.2);
}
.btn:active {
  transform: scale(0.97);
  transition: transform var(--transition-press);
}
```

Hover lifts the button 1px with a deepened shadow (200ms). Press overrides to
a faster 100ms scale-down — the one place in the system that deliberately
breaks from `--transition-gentle`, because a press needs to register
instantly rather than ease in.

### Dropdown open/close

```css
:root {
  --transition-dropdown-close: 150ms ease-out;  /* faster than open */
}
```

```css
.dropdown-panel {
  transform-origin: top;
}
/* opening: opacity 0→1, transform translateY(-6px) scaleY(0.95)→none,
   both at --transition-gentle (200ms) */
/* closing: same properties reversed, at --transition-dropdown-close (150ms) */
```

Opens with fade + scale from the top edge at the standard 200ms. Closes
faster (150ms) — dismissal should feel snappier than appearance.

---

## 9. Spacing, radius, type scale

```css
:root {
  /* spacing — 4px base */
  --space-1: 4px;
  --space-2: 8px;
  --space-3: 12px;
  --space-4: 16px;
  --space-6: 24px;
  --space-8: 32px;
  --space-12: 48px;

  /* radius */
  --radius-sm: 4px;
  --radius-md: 8px;
  --radius-lg: 12px;
  --radius-xl: 20px;
  --radius-full: 999px;

  /* type scale */
  --text-xs: 11px;
  --text-sm: 12px;
  --text-base: 14px;
  --text-lg: 16px;
  --text-xl: 20px;
  --text-2xl: 26px;    /* app title, uses --font-header-en */
}
```

Usage: `--text-2xl` is reserved for the app title in Fraunces. All other
sizes use `--font-body-en` / `--font-th` depending on language.

---

## 10. Error / warning / success / loading states

```css
:root {
  /* error */
  --state-error-bg: #FBEDEC;
  --state-error-border: #E8A6A0;
  --state-error-text: #8A2E2E;
  --state-error-icon: #C0392B;

  /* warning */
  --state-warning-bg: #FBF3E4;
  --state-warning-border: #D9B877;
  --state-warning-text: #6B4E1A;

  /* success toast (reuses --fill-success / --text-success-accent) */
  --state-success-bg: #2E4A3B;
  --state-success-text: #FFFFFF;
  --state-success-icon: #A9C9A0;

  /* loading spinner */
  --spinner-track: #F0D9D8;
  --spinner-active: #7A2E2E;
}
```

### Contrast audit

| Pair | Ratio | Result |
|---|---|---|
| `--state-error-text` on `--state-error-bg` | 7.34:1 | PASS |
| `--state-warning-text` on `--state-warning-bg` | 6.98:1 | PASS |
| `--state-success-icon` on `--state-success-bg` | 5.35:1 | PASS |

Error and warning states use inline banners (icon + bold title + description)
directly beneath the relevant input (e.g. file picker). Success uses a
transient toast, not inline — confirms an action completed (e.g. "generate"
finished) without blocking the layout.

Loading state (during image generation): spinner using `--spinner-active`
over `--spinner-track`, paired with a status line ("กำลังสร้างรูป...") and an
estimated duration. Applies inside the result panel while generation is in
progress.

---

## 11. Icon system

- **Library:** Lucide (outline style, consistent stroke width, free, has a
  React component — fits the existing Codex → Claude Code pipeline).
- **Sizes:** `--icon-sm: 14px`, `--icon-md: 18px`, `--icon-lg: 24px`.
- **Colors:** icons inherit `--text-primary` by default; use
  `--text-accent-red` for icons inside primary-colored contexts, `--text-muted`
  for de-emphasized icons (e.g. inside ghost buttons).
- Core icons needed for MVP: upload, close (×), check (✓), download, reset
  (↻), warning (⚠).

---

## 12. Focus state (keyboard navigation)

Single outline color doesn't work here — `--fill-primary` (wine) and
`--surface-0` (cream) sit at different luminance levels, so no single ring
color clears 3:1 against both. Uses a **double ring** instead: a white gap
layer isolates the outer ring from whatever surface/fill sits underneath.

```css
:root {
  --focus-ring-gap: #FFFFFF;
  --focus-ring-color: #2E2A22;   /* reuses --text-primary */
}
```

```css
:focus-visible {
  box-shadow: 0 0 0 2px var(--focus-ring-gap), 0 0 0 4px var(--focus-ring-color);
  outline: none;
}
```

### Contrast audit

| Pair | Ratio | Result |
|---|---|---|
| White gap ring vs wine button fill | 9.30:1 | PASS |
| Dark outer ring vs white gap ring | 14.28:1 | PASS |

A single gold ring was tested first and rejected: 3.01:1 against the wine
button (barely passes) but only 2.75:1 against the cream page background
(fails WCAG 2.4.11's 3:1 minimum). The double-ring pattern sidesteps this by
never depending on contrast against the variable surface underneath.

---

## 13. Empty state

Used when the user has no generations yet (first visit / after clearing
history).

```css
:root {
  --empty-icon-bg: #ECE4D6;      /* reuses tone from --picker-thumbnail-bg */
  --empty-title-text: #2E2A22;   /* --text-primary */
  --empty-body-text: #8A7D68;    /* --text-muted */
}
```

Structure: centered icon (48px, rounded square, muted background) → title
(`--text-lg`, semibold) → one-line description (`--text-sm`, muted) → single
primary CTA button. Lives on a white card (`--surface-1`) matching other
panels, not full-bleed.

---

## 14. Approved reference

Mockup validated against the actual 3-panel flow (bare tree → element →
result) using the tokens above — approved by product owner. Button variants
(§4), file picker (§5), modal (§6), and scrollbar (§7) approved separately as
standalone component sheets.

## 15. Dark theme

Derived from the light palette — same wine/green/gold hues, lightened for
dark-background contrast. Surfaces are warm dark-brown, not neutral gray, to
keep the cozy character in dark mode.

```css
[data-theme="dark"] {
  --surface-0: #1E1815;
  --surface-1: #26201C;
  --border: rgba(255, 255, 255, 0.06);

  --text-primary: #F2ECE4;
  --text-muted: #9C9188;

  --fill-primary: #8A3838;
  --on-primary: #FFFFFF;
  --text-accent-red: #E8A6A0;

  --fill-success: #2E4A3B;
  --text-success: #A9C9A0;

  --fill-gold-block: #B08D57;   /* unchanged — already works on dark */
  --text-gold: #D9B877;
}
```

### Contrast audit

| Pair | Ratio | Result |
|---|---|---|
| `--text-primary` on `--surface-0` | 14.95:1 | PASS |
| `--text-primary` on `--surface-1` | 13.70:1 | PASS |
| `--text-accent-red` on `--surface-0` | 8.69:1 | PASS |
| `--text-success` on `--surface-0` | 9.65:1 | PASS |
| `--text-gold` on `--surface-0` | 9.25:1 | PASS |
| `--text-muted` on `--surface-0` | 5.70:1 | PASS |
| `--on-primary` on `--fill-primary` button | 7.77:1 | PASS |

Replaces the app's previous dark-only accents (`#ee6018`, `#a0ca92`), which
were unrelated to this palette. Toggle via `data-theme="dark"` on the root,
same mechanism as the light theme.

---

## 16. Explicitly out of scope (this doc)

- Layout / spacing grid (component-level composition, not the token scale)
- Multi-element and reference-image UI (blocked on product decisions 8.2–8.3)

- Layout / spacing / grid system
- Component states (hover, disabled, loading)
- Multi-element and reference-image UI (blocked on product decisions 8.2–8.3)
- Dark theme token set
