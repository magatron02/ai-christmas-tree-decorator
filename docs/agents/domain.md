# Domain Docs

How the engineering skills should consume this repo's domain documentation when exploring the codebase.

## Existing domain docs — read these first

This repo predates the CONTEXT.md/ADR convention. Its domain knowledge already lives in `docs/`:

- `docs/Product.md` — product behaviour and rationale
- `docs/Spec.md` — technical spec
- `docs/NonGoals.md` — deliberate exclusions (what this app will not do, and why)
- `docs/AcceptanceCriteria.md` — AC-numbered acceptance criteria, referenced in code comments (e.g. `AC-4`)
- `docs/DESIGN.md` — current colour/typography design system (supersedes `docs/factory-design-system.md`)
- `docs/TestPlan.md` — test plan

These are authoritative until `/domain-modeling` distills them into a `CONTEXT.md`. Read the relevant one(s) before treating a domain term as undefined.

## Before exploring, also read these

- **`CONTEXT.md`** at the repo root, or
- **`CONTEXT-MAP.md`** at the repo root if it exists — it points at one `CONTEXT.md` per context. Read each one relevant to the topic.
- **`docs/adr/`** — read ADRs that touch the area you're about to work in. In multi-context repos, also check `src/<context>/docs/adr/` for context-scoped decisions.

If any of these three don't exist yet, proceed silently — don't flag their absence beyond what's already covered by the `docs/*.md` files above. The `/domain-modeling` skill (reached via `/grill-with-docs` and `/improve-codebase-architecture`) creates them lazily when terms or decisions actually get resolved.

## File structure

Single-context repo (this repo):

```
/
├── docs/                   ← existing domain docs (see above)
│   └── adr/                 (not yet created)
├── CONTEXT.md               (not yet created — see /domain-modeling)
├── backend/
└── frontend/
```

## Use the glossary's vocabulary

When your output names a domain concept (in an issue title, a refactor proposal, a hypothesis, a test name), use the term as defined in `CONTEXT.md` if it exists, otherwise as used in `docs/Product.md` / `docs/Spec.md`. Don't drift to synonyms the glossary explicitly avoids.

If the concept you need isn't defined anywhere, that's a signal — either you're inventing language the project doesn't use (reconsider) or there's a real gap (note it for `/domain-modeling`).

## Flag ADR conflicts

If your output contradicts an existing ADR or an existing `docs/*.md` decision (e.g. a NonGoals.md exclusion), surface it explicitly rather than silently overriding:

> _Contradicts NonGoals.md #8 (never invent a dimension) — but worth reopening because…_
