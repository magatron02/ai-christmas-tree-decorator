# AI Christmas Tree Decorator

Takes a photo of a bare Christmas tree and a photo of one decoration, and returns a photo of
that tree decorated with it — so a shop can show a customer what an element looks like on a
real tree without decorating and photographing every combination by hand.

Internal single-user tool. See `Product.md`, `Spec.md`, `AcceptanceCriteria.md`,
`NonGoals.md`, `TestPlan.md` and `factory-design-system.md` for the decisions behind it.

## Run it

```bash
uv venv --python 3.11
uv pip install -r backend/requirements.txt
```

Copy `.env.example` to `.env` and put your key in it. That is the only environment variable
the project reads; everything else is a constant in `backend/config.py`, deliberately, so the
image model cannot be swapped without going through the Architect (NonGoals.md #2).

Before anything else, confirm the engine actually works. Spec.md 5 flags a reported bug where
`images.edit` rejects `gpt-image-2`, and the whole tool sits on that one call:

```bash
.venv/Scripts/python scripts/check_edit_endpoint.py
```

This makes one real, billed generation. If it fails, stop and take the printed error back to
the Architect — do not switch models to get past it.

Give the account some credit, then start the server:

```bash
.venv/Scripts/python -m backend.services.credit topup 10
```

```bash
.venv/Scripts/python -m uvicorn backend.main:app --port 8000
```

Open <http://localhost:8000>. History is at <http://localhost:8000/history>.

```bash
.venv/Scripts/python -m pytest tests/ -q
```

Nothing in the test suite calls OpenAI or loads the rembg model, so it is safe and free to
run on every change.

## How it fits together

```
frontend/          static HTML + vanilla JS, Factory design system, no build step
backend/main.py    four endpoints, one of which costs money
backend/services/  credit · image_gen · background_removal
backend/models/    request_log — the SQLite state machine
backend/prompts/   compositing_prompt.txt, read fresh on every generation
```

The pipeline is deliberately split so the expensive step is never reached by accident:

| step | endpoint | cost |
|---|---|---|
| remove the element's background, user approves the cut-out | `POST /api/remove-bg` | free |
| validate everything, write a `pending` request | `POST /api/prepare` | free |
| confirm dialog, then the actual generation | `POST /api/generate/{id}` | 1 credit, on success only |
| browser confirms it rendered the result | `POST /api/delivered/{id}` | free |

### Where the money is

`backend/services/credit.py` is the only module in the repo that changes the balance, and
`charge_for()` is the only function that takes one. Both of its preconditions — the request
reached `api_success`, and it has never been charged — are in the SQL `WHERE` clause, so
calling it twice, early, or on a failed request simply does nothing.
`tests/test_billing_integrity.py` greps the tree to keep it the only such file.

A double-click cannot buy two images: the confirm dialog is bound to one `request_id`, and
`claim()` moves that row `pending → calling_api` in a single guarded `UPDATE`. The second
click loses the race and gets a 409.

### What a generation cost

A credit is one generation whatever the output size. The money is not: a 2048×1152 image
costs more than a 1024×1024 one. So the API's own token accounting for each image is stored
on its request row and returned by `/api/generate` and `/api/history` as `usage`:

```json
{"input_tokens": 2674, "input_tokens_details": {"image_tokens": 2126, "text_tokens": 548},
 "output_tokens": 565, "total_tokens": 3239}
```

Pricing a credit is still open in Product.md 6. This is the raw material for it — real
per-image numbers rather than a dashboard average. Note that `text_tokens` is the prompt, so
editing `compositing_prompt.txt` moves the cost a little.

### Reconciliation

Credit is taken *after* the API returns an image, so "charged" and "an image exists" are the
same event. If the browser never receives the response, the row stays at `api_success` and
the image is still on disk and downloadable from `/history` — no retry queue, no background
worker, which is the right size for a single-user local-disk MVP (Spec.md 7).

A request left at `calling_api` means the process died mid-call. It stays visible in the
history rather than being retried automatically.

Cancelling the confirm dialog leaves a `pending` row behind. It is never charged and never
resumes; it is just a record that you started and changed your mind.

### Output size

Default 4:5 at 1536×1920 (Product.md). Every preset in `backend/config.py` has both sides
divisible by 16 and an aspect ratio inside 1:3–3:1, and `validation.resolve_size()` re-checks
that at runtime rather than trusting the table.

### Housekeeping

Nothing deletes stored images during normal operation — history points at them and a paid-for
result must stay reachable. Cleanup is a command:

```bash
.venv/Scripts/python -m backend.services.storage prune --dry-run
```

It only removes files no request row refers to, and only once they are at least 24 hours old,
so a cut-out preview that exists on disk before its request does is never taken out from
under a live session.

### Fonts

Self-hosted and committed, no CDN. See `frontend/fonts/README.md`.

## Not built yet

AC-5 — the 30-image run measuring the ≥70% "good enough to sell" rate — is a measurement to
take once the system is running, not part of this build.
