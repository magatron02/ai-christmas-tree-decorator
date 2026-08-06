# Factory — a dark UI design system

A machine tool, not an app. Flat surfaces, hairline borders, no shadows, and
colour reserved for saying something.

Drop-in, framework-free, one file of CSS custom properties. Nothing below
depends on a build step, a component library, or a font CDN.

---

## 1. Tokens

Paste this once, at the top of your stylesheet.

```css
:root {
  color-scheme: dark;

  /* surface */
  --bg:              #101010;   /* canvas, chrome, input fields */
  --bg-elevated:     #1d1a18;   /* hover, active row, dividers  */
  --border:          #3d3a39;   /* every hairline — always 1px  */

  /* text */
  --text:            #eeeeee;   /* primary     "Bone"           */
  --text-2:          #b8b3b0;   /* secondary   "Pale Stone"     */
  --text-3:          #8a8380;   /* quietest    "Warm Granite"   */

  /* accent — two, and only for meaning */
  --accent-positive: #a0ca92;   /* metric green: done, clean, fine */
  --accent-warning:  #ee6018;   /* signal orange: running, stale, destructive */

  /* button ramp */
  --btn-bg:               #1d1a18;
  --btn-hover-bg:         #28241f;
  --btn-primary-bg:       #fafafa;
  --btn-primary-hover-bg: #ececec;
  --btn-primary-text:     #101010;

  /* shape */
  --radius-sm: 3px;    /* buttons, inputs, chips, nav rows */
  --radius-lg: 10px;   /* cards, panels                    */
  --shadow:    none;

  /* type */
  --font-ui:   Inter, system-ui, -apple-system, "Segoe UI", sans-serif;
  --font-mono: "JetBrains Mono", "IBM Plex Mono", ui-monospace, Consolas, monospace;
  --weight-heading:   500;
  --tracking-heading: -0.02em;

  font-family: var(--font-ui);
}

body {
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font-weight: 400;
}
```

**`--bg-elevated` is warmer than `--bg`**, not lighter-grey. That warm lift is
the entire depth model — there is no shadow helping it, so it has to be a hue
shift or the surfaces read as flat noise.

**Heading and body are the same family.** Factory has no display face. The
hierarchy is size and weight, and 500 is the only weight above 400 anywhere.

---

## 2. The caption

The one recurring shape that makes this look like Factory rather than like
every other dark theme:

```css
.caption {
  font-family: var(--font-mono);
  font-size: 11px;              /* 12px in wide fields */
  text-transform: uppercase;
  letter-spacing: -0.24px;      /* negative — this is the trick */
  color: var(--text-3);
}
```

Negative tracking on uppercase mono tightens it into a **stamped label**.
Positive tracking — the reflex on small caps — spreads it into a fashion
heading and the whole character is gone. Use it for section heads, key names,
stat labels, status lines. Never for prose.

---

## 3. Colour rules

### Accents are status, never decoration

An accent is **never a button fill**. Orange is what an alarm lamp is for; if
every button is orange, nothing is. Accents appear as *text colour* and as
*border colour on hover* — chips, result lines, the danger outline.

### Accents as text always go through `color-mix`

```css
color: color-mix(in srgb, var(--accent-warning) 55%, var(--text));
```

Never `color: var(--accent-warning)` on body copy. The raw values are tuned
for borders and fills and fail WCAG AA as small text on `--bg`. Mixing 55%
toward `--text` lands every accent at ≥4.5:1 without changing the token.

If your project has a lint or test layer, assert that the literal `color-mix`
string is present. It is the kind of rule that gets quietly unwound during a
refactor, and the failure is invisible to anyone with good eyesight.

### One primary per view

Primary is near-white on near-black — maximum contrast carrying the emphasis
that colour is not allowed to carry.

---

## 4. Components

```css
/* ---- buttons ---- */
.btn {
  background: var(--btn-bg);
  border: none;
  border-radius: var(--radius-sm);
  color: var(--text);
  padding: 8px 16px;
  font: inherit;
  font-size: 13px;
  cursor: pointer;
}
.btn:hover    { background: var(--btn-hover-bg) }
.btn:disabled { opacity: .5; cursor: default }

.btn.primary       { background: var(--btn-primary-bg); color: var(--btn-primary-text) }
.btn.primary:hover { background: var(--btn-primary-hover-bg) }

/* danger is outlined, never filled — a filled red button is easier to
   press by accident than to read */
.btn.danger {
  background: transparent;
  border: 1px solid var(--border);
  color: color-mix(in srgb, var(--accent-warning) 55%, var(--text));
}
.btn.danger:hover    { border-color: var(--accent-warning) }
.btn.danger:disabled { color: var(--text-3); border-color: var(--border) }

/* ---- inputs ---- */
.input {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--text);
  padding: 6px 8px;
  font: inherit;
  font-size: 12px;
}
.input::placeholder { color: var(--text-3) }

/* ---- card ---- */
.card {
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 16px;
  box-shadow: var(--shadow);
}

/* ---- status chip ---- */
.chip {
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 10px;
  text-align: center;
  font-size: 12px;
  color: var(--text-3);
}
.chip.done    { color: color-mix(in srgb, var(--accent-positive) 55%, var(--text)) }
.chip.running,
.chip.stale   { color: color-mix(in srgb, var(--accent-warning)  55%, var(--text)) }

/* ---- stat tile ---- */
.tile           { flex: 1; padding: 0 16px; border-right: 1px solid var(--bg-elevated) }
.tile:last-child{ border-right: none }
.tile .k        { /* .caption */ font-size: 12px; display: block; margin-bottom: 4px }
.tile .v        { font-size: 24px; letter-spacing: -0.5px; color: var(--text) }

/* ---- nav row ---- */
.row          { display: block; width: 100%; text-align: left; border: none;
                background: none; color: inherit; font: inherit; font-size: 12px;
                padding: 8px; border-radius: var(--radius-sm); cursor: pointer }
.row:hover,
.row.active   { background: var(--bg-elevated) }
```

Note `box-shadow: var(--shadow)` on `.card` even though the value is `none`.
Keep it: if you ever add a light or a soft variant, the property has to
already be there for the token to reach it.

---

## 5. Scale

Not tokens — the literals to reuse, so a new panel matches the old ones
instead of inventing a sixth value.

**Type** — 11 caption · 12 dense UI, chips, hints · 13 buttons and body ·
14 option names · 16 modal heading · 22 logo · 24 stat value (tracked `-0.5px`)

**Space** — 4 · 6 · 8 · 10 · 12 · 14 · 16 · 20
Button `8px 16px` · card `16px` · page `20px` · button-row gap `10px` ·
chip gap `8px` · section head margin `14px 0 6px`

**Shape** — `3px` on controls, `10px` on panels. That single step is what
separates "control" from "container" with no other cue. 3px reads as a
machined edge; 0 reads as a raw rectangle, 8+ reads as soft.

**Frame** — fixed chrome (`64px` top bar, `220px` sidebar), fluid scrolling
body. Both chrome edges are `--bg` with a 1px `--border`, so the frame is
drawn by line alone, never by a different fill.

---

## 6. Rules

1. Never a literal colour in a component. Only `var(--token)`.
2. Accents mean status. Never decoration, never a fill.
3. Accents as text go through `color-mix(… 55%, var(--text))`.
4. One primary button per view.
5. Borders are 1px. Emphasis is the border *colour* changing, never its width.
6. No shadows — but keep writing `box-shadow: var(--shadow)`.
7. Weight 400 everywhere. 500 only for the logo and modal headings.
8. A control that cannot work yet is `disabled` at `opacity:.5`, never hidden.
   The user should see the whole shape of the thing and what is not reachable.
9. Nothing may depend on letter case. `text-transform: uppercase` is styling
   only — it must still read correctly in a script that has no case (Thai,
   Arabic, CJK, Hebrew). Where a caption carries mixed content, switch the
   transform off for that span:
   `.sub { text-transform: none; letter-spacing: 0; opacity: .7 }`

---

## 7. Fonts

Self-host. Both faces have a full system fallback stack, so a missed download
degrades rather than breaks — but Inter and JetBrains Mono are what makes the
caption work, and neither ships on Windows.

```css
@font-face { font-family: "Inter";
  src: url("/fonts/inter.woff2") format("woff2");
  font-weight: 400 700; font-display: swap }
@font-face { font-family: "JetBrains Mono";
  src: url("/fonts/jetbrains-mono.woff2") format("woff2");
  font-weight: 400 700; font-display: swap }
```

Variable `.woff2` files, one per family, ~100–350 KB each. No CDN — a design
system that stops looking right without a network is not a system.

---

## 8. Extending it

Adding a **new colour** is almost always the wrong move. Ask first whether the
thing is *status* (use an existing accent), *hierarchy* (use the text ramp),
or *decoration* (delete it).

Adding a **light variant**: `--bg` and `--text` swap roles, `--bg-elevated`
becomes the *lighter* neutral, and both accents need re-tuning — `#ee6018`
fails AA as small text on a light background too, and `#a0ca92` fails badly.
Re-derive them with the same `color-mix` rule and check both before shipping.

> **Measured 2026-08-05 — the accents did not need re-tuning.** Built and checked
> against a real light theme (`tests/test_theme_contrast.py`).
>
> The raw accents fail exactly as warned: on `#fafafa`, `#a0ca92` is **1.77:1**
> and `#ee6018` is **3.18:1**. But Rule 3 already routes every accent-as-text
> through `color-mix(in srgb, … 55%, var(--text))`, and `--text` flips with the
> theme. With `--text: #0a0a0a` that mix lands at **4.93:1** and **7.67:1** —
> both AA — with the accent tokens untouched.
>
> So the light variant needs no sixth colour, which is what section 8 asks for
> in the first place. What it does need is `--text` dark enough: at `#141414`
> the green mix is 4.64:1, passing by 3%, which is too thin to rely on.
>
> The raw `#ee6018` is still used as a border (`.chip.failed`, `.notice`) and
> holds at 3.18:1 against a light background, above the 3:1 a border needs.
> `#a0ca92` is never a border, so its 1.77:1 does not matter.

Keeping this **portable across projects**: the tokens are the contract, the
component CSS is a suggestion. Copy section 1 verbatim; rewrite section 4 in
whatever your project already speaks.
