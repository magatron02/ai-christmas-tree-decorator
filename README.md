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

Start the server:

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
backend/services/  image_gen · background_removal · storage
backend/models/    request_log — the SQLite state machine and the spend record
backend/prompts/   compositing_prompt.txt, read fresh on every generation
```

The pipeline is deliberately split so the expensive step is never reached by accident:

| step | endpoint | cost |
|---|---|---|
| remove the element's background, user approves the cut-out | `POST /api/remove-bg` | free |
| validate everything, write a `pending` request | `POST /api/prepare` | free |
| confirm dialog, then the actual generation | `POST /api/generate/{id}` | billed by OpenAI, on success only |
| browser confirms it rendered the result | `POST /api/delivered/{id}` | free |

### Where the money is

There is no local credit balance. Money lives in the OpenAI account, and OpenAI is the only
thing that can say whether any is left — it exposes no remaining-balance endpoint to an API
key, so a number here would be maintained by hand and wrong the moment the key is used
anywhere else. When the account is out, the generation call fails with a billing error and
`image_gen` turns that into a message naming what to do about it.

What survives is the property the balance was standing in for, stated directly:

> a confirmed request may cause at most one billable API call,
> and a request that fails must cause none at all.

A double-click cannot buy two images: the confirm dialog is bound to one `request_id`, and
`claim()` moves that row `pending → calling_api` in a single guarded `UPDATE`. The second
click loses the race and gets a 409. `tests/test_billing_integrity.py` counts calls to the
generator — every one of them would have been real money — and asserts nothing in the tree
has grown a local balance again.

### What a generation cost

The API's own token accounting for each image is stored on its request row and returned by
`/api/generate` and `/api/history` as `usage`. `/api/usage` sums it. A row carrying `usage`
is a row that cost money and a row without one is not, so `billed` is derived rather than
stored and cannot drift out of step with what happened:

```json
{"input_tokens": 2674, "input_tokens_details": {"image_tokens": 2126, "text_tokens": 548},
 "output_tokens": 565, "total_tokens": 3239}
```

Product.md 6 wanted a credit priced from real API cost. There is no credit any more, but the
underlying question — what does one generation cost — is answered by these numbers rather
than by a dashboard average.

Measured on byte-identical inputs and the same prompt, varying only the output size:

| run | size | pixels | input | output | total |
|---|---|---|---|---|---|
| 1 | 4:5 (1536×1920) | 2,949,120 | 2674 | 565 | 3239 |
| 2 | 1:1 (1024×1024) | 1,048,576 | 2674 | 781 | 3455 |
| 3 | 4:5 (1536×1920) | 2,949,120 | 2674 | 1030 | 3704 |

**Input tokens are deterministic** — 2674 on every run — so they follow the uploaded images
and the prompt exactly.

**Output tokens are not.** Runs 1 and 3 are the same size with the same inputs and differ by
1.8×. That spread is wider than the gap between the two different sizes, so output cost
cannot be attributed to size from this data, and probably cannot be attributed to size at
all: per-size pricing would be false precision dressed up as accounting.

Per-image cost is therefore not predictable in advance. Budget from observed totals, not from
a model — which is a second reason a local pre-paid balance was the wrong shape: it would
have had to guess a price per image that does not exist.

Three samples is enough to establish the non-determinism and not enough to give a mean worth
quoting. The AC-5 quality run will generate 30 real images and record `usage` for every one
of them; take the cost distribution from there rather than buying more samples now.

`text_tokens` is the prompt, so editing `compositing_prompt.txt` moves the cost slightly.

### Reconciliation

Cost is recorded *after* the API returns an image, so "this was billed" and "an image exists"
are the same event. If the browser never receives the response, the row stays at
`api_success` and the image is still on disk and downloadable from `/history` — no retry
queue, no background worker, which is the right size for a single-user local-disk MVP
(Spec.md 7).

A request left at `calling_api` means the process died mid-call. It stays visible in the
history rather than being retried automatically. Note that this is the one state where the
log cannot be trusted about money: the call may or may not have reached OpenAI before the
process died. The OpenAI usage page is the tiebreaker.

Cancelling the confirm dialog leaves a `pending` row behind. It is never billed and never
resumes; it is just a record that you started and changed your mind.

### Output size

Default 4:5 at 1536×1920 (Product.md). Every preset in `backend/config.py` has both sides
divisible by 16 and an aspect ratio inside 1:3–3:1, and `validation.resolve_size()` re-checks
that at runtime rather than trusting the table.

### Housekeeping

Nothing is deleted during normal operation — history points at it and a paid-for result must
stay reachable. Cleanup is a command:

```bash
.venv/Scripts/python -m backend.services.storage prune --dry-run
```

It removes two things, both at least 24 hours old so nothing is taken out from under a live
session:

- **requests left at `pending`** — prepared, then cancelled at the confirm dialog. A pending
  row is one the state machine never let past `claim()`, so it provably never reached the API
  and cost nothing; deleting it destroys no evidence. Every other state is kept forever,
  because every other state is the spend record.
- **files no surviving request refers to** — rejected cut-outs, and the uploads belonging to
  the abandoned requests just removed.

### Fonts

Self-hosted and committed, no CDN. See `frontend/fonts/README.md`.

## Not built yet

AC-5 — the 30-image run measuring the ≥70% "good enough to sell" rate — is a measurement to
take once the system is running, not part of this build.
