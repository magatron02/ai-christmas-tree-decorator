# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Internal single-user tool: upload a photo of a bare Christmas tree and a photo of one
decoration, get back a photo of the tree decorated with it, so a shop can show customers
combinations without physically decorating and photographing every one. Backend is FastAPI +
SQLite, frontend is static HTML/vanilla JS with no build step, image generation goes through
OpenAI's `gpt-image-2` `images.edit` endpoint.

Read `docs/Product.md`, `docs/Spec.md`, `docs/NonGoals.md`, `docs/AcceptanceCriteria.md`,
`docs/DESIGN.md` and `docs/TestPlan.md` before treating a domain decision as open — they are
authoritative until distilled into ADRs (`docs/adr/`) or a `CONTEXT.md`. `CONTEXT.md` at the
repo root is a glossary of shop/catalogue vocabulary (catalogue base vs. shop overlay, colour
vs. code, tone/recipe/density, etc.) — use its terms, not synonyms, when naming these concepts
in code, commits, or issues. `docs/NonGoals.md` lists things that must not be done even if they
look like an obvious improvement mid-implementation (e.g. never swap the image model, never add
a local credit/balance, never skip background removal, never guess a product's size) — if you
find yourself wanting to do one of these, stop and flag it rather than deciding unilaterally.

## Commands

Setup (Windows dev):
```bash
uv venv --python 3.11
uv pip install -r backend/requirements.txt
```
Copy `.env.example` to `.env` and set `OPENAI_API_KEY` — the only environment variable this
project reads; everything else is a constant in `backend/config.py` on purpose (NonGoals #2).

Before anything else on a fresh setup, confirm the OpenAI call actually works (this makes one
real, billed generation):
```bash
.venv/Scripts/python scripts/check_edit_endpoint.py
```

Run the server:
```bash
.venv/Scripts/python -m uvicorn backend.main:app --port 8000
```
App at <http://localhost:8000>, history at <http://localhost:8000/history>.

Run tests (no OpenAI calls, no rembg model load — safe and free on every change):
```bash
.venv/Scripts/python -m pytest tests/ -q
```
Run a single test file or test: `pytest tests/test_billing_integrity.py -q` or
`pytest tests/test_billing_integrity.py::test_name -q`.

Housekeeping (deletes only `pending`-state requests ≥24h old and files no surviving request
refers to — never anything that represents a completed spend):
```bash
.venv/Scripts/python -m backend.services.storage prune --dry-run
```

Build the desktop installer (needs Inno Setup 6 + `pyinstaller` in the venv):
```bash
build_installer.bat
```

Catalogue indexing (optional; without it the app runs but catalogue search returns nothing):
```bash
.venv/Scripts/python scripts/describe_catalog.py   # billed vision call per photo
.venv/Scripts/python scripts/embed_catalog.py       # billed embedding call per photo
.venv/Scripts/python scripts/precut_catalog.py      # pre-run background removal, offline optimisation
```
These and the quality-run harness (`scripts/run_quality_batch.py`) make real billed API calls —
never run them speculatively; see README.md for what each one costs and why it's resumable.

## Architecture

```
frontend/          static HTML + vanilla JS, DESIGN.md tokens, no build step
backend/main.py    the generation pipeline plus catalogue search/admin endpoints (~1200 lines, all routes)
backend/services/  image_gen · background_removal · storage · catalog · catalog_admin ·
                    matching · vision · settings · shop_overlay · vendor_lookup · vendor_overlay ·
                    vendor_admin
backend/models/    request_log — the SQLite state machine and the spend record
backend/prompts/   compositing_prompt.txt, read fresh on every generation (no restart needed to edit)
catalog/           product data (committed) + images/embeddings (not committed — see README)
scripts/           one-off/offline tooling: catalogue extraction, quality runs, housekeeping
```

### Generation pipeline is deliberately split so the billed step is never reached by accident

| step | endpoint | cost |
|---|---|---|
| remove element's background, user approves cut-out | `POST /api/remove-bg` | free |
| validate everything, write a `pending` request | `POST /api/prepare` | free |
| confirm dialog, then the actual generation | `POST /api/generate/{id}` | billed, on success only |
| browser confirms it rendered the result | `POST /api/delivered/{id}` | free |

### Request state machine (`backend/models/request_log.py`)

```
pending -> calling_api -> api_success | api_failed -> delivered
```
Every transition is a single guarded `UPDATE ... WHERE status = <from>`, checked by rowcount —
the guard lives in SQL, not a Python `if`, so two racing requests (e.g. a double-click on
confirm) are safe without a lock: SQLite serialises the write, the loser gets rowcount 0 and a
409. `claim()` (`pending -> calling_api`) is what a caller checks before calling the paid API.

There is no local credit/balance system — a row with `usage_json` set is a row that cost money,
a row without one did not, and `usage_totals()` sums real API accounting rather than tracking a
counter that could drift. Do not reintroduce a local balance (NonGoals #4); OpenAI exposes no
remaining-balance endpoint, so any such number would be maintained by hand and wrong.

A request stuck at `calling_api` means the process died mid-call — the log cannot say for
certain whether OpenAI was actually charged; the OpenAI usage page is the tiebreaker. This is
intentional (Spec.md 7): no retry queue, no background worker, right-sized for a single-user
local-disk tool.

### Catalogue: base + overlay (ADR-0001)

Product data is a **catalogue base** (extracted from the shop's printed book, regenerated
wholesale on re-import, never hand-edited) merged field-by-field with a **shop overlay** (the
shop's own corrections — price, photo, colour name — which survives every re-import). The
merged result is the **product record**. A **code** is the shop's catalogue identifier and is
never itself editable — fixing a wrong code means deleting and recreating the product. An
overlay whose code no longer exists in any base after a re-import becomes an **orphan product**:
kept and flagged, never silently dropped. See `backend/services/catalog.py`,
`catalog_admin.py`, `shop_overlay.py`.

A **colour** (ADR-0002) is a named photo of a code, not a separate identifier — these catalogues
photograph a whole colour range in one frame, and the app splits that into one card per colour.
Never mint per-colour sub-codes.

### Vendor price list: a second, independent base + overlay

`vendor-pricelists/bangkok-christmas/cleaned/lookup.json` is price/size/name/pack data for the
Bangkok Christmas book, extracted from the supplier's own PDF (`parse_pricelist.py` →
`build_lookup.py`) and read exclusively by `backend/services/vendor_lookup.py` — never
`catalog.py`. It gets the exact same base+overlay treatment ADR-0001 gives the catalogue,
applied to a second, unrelated pair of files: `data/vendor_overlay.json`
(`vendor_overlay.py`) holds a shop's corrections and survives a `build_lookup.py` re-run the
way `shop_overlay.json` survives a book re-import. `vendor_admin.py` is the settings-page
surface for browsing this data, listing what's wrong with it (no vendor entry, no price, no
size, an unresolved pack), fixing one field at a time, and importing a refreshed PDF end to
end. Vendor data and catalogue data are never mixed at the file level — two bases, two
overlays, the same merge pattern, never one writer touching both.

**Auto pick** (ADR-0003) asks only for a **tone** and fills a fixed **recipe** of category
counts (`AUTO_RECIPE` in `backend/config.py`) — tree size and budget are deliberately not
inputs (the old "wizard" gating on those was retired because most products have no price). It
always produces a proposal for the shop to review, never a finished picture directly.

### Frozen (PyInstaller) vs. source layout

`backend/config.py`'s `ROOT` points at the exe's own folder when frozen (`sys.frozen`) instead
of the repo root, because the installed app must keep writable state (`.env`, `data/app.db`,
`storage/`, the catalogue overlay) beside itself rather than in PyInstaller's read-only
`_internal/` bundle. This is also why the installer uses `PrivilegesRequired=lowest` — it
installs per-user under `%LOCALAPPDATA%`, not Program Files, so those writes actually succeed.

### Sizing and density are prompt-driven, not corrected numerically

`gpt-image-2` does not render decorations at a size linearly controllable by the instructed
fraction (measured 0.55–0.70× of what's asked, and compensating with a multiplier made it
worse, not better — see `backend/config.py` comment above `MAX_DIMENSION`). There is
deliberately no scale-correction constant. Likewise density presets (`light`/`normal`/`full`)
were tuned by real billed measurement (`scripts/check_per_item_density.py`) — the "light" phrasing
uses a hard ceiling ("never more than 6") rather than a range, because the model's failure mode
is specifically overshooting on the sparse side. Don't "simplify" these prompt strings without
rerunning that kind of check.

## Testing conventions

`tests/conftest.py` redirects `config.DATA_DIR` / `STORAGE_DIR` / `DB_PATH` to a temp directory
**before** `backend.main` is imported (the app mounts its storage directory at import time), and
an autouse `fresh_db` fixture gives each test an empty database and storage dir. Nothing in the
suite calls OpenAI or loads the rembg ONNX model — `tests/test_billing_integrity.py` in
particular asserts the generator is called exactly the number of times expected, since every
call is real money in production.

## Agent-specific notes

- **Issue tracker**: GitHub Issues on `magatron02/ai-christmas-tree-decorator`, via `gh` CLI —
  see `docs/agents/issue-tracker.md` for conventions (creating/reading/labeling issues, the
  wayfinder map/child-ticket pattern).
- **Domain docs**: see `docs/agents/domain.md` for how to consume `docs/*.md` vs. `CONTEXT.md`
  vs. ADRs, and how to flag when new work would contradict an existing ADR or NonGoals entry.
- **Web browsing**: use the gstack `/browse` skill, not `mcp__claude-in-chrome__*` tools.
