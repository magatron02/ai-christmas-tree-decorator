"""Request state log (Spec.md 2 and 7).

    pending -> calling_api -> api_success | api_failed -> delivered

Every transition is a single guarded UPDATE and the caller checks the row count. The guard
lives in the SQL, not in a Python `if`, which is what makes two racing requests safe without
a lock: SQLite serialises the write, the loser gets rowcount 0. `claim()` is the double-click
backstop behind the confirm dialog.

The log is also the reconciliation record: if the browser never receives the response, the
row is still api_success with an output path, and /api/history hands it back (Spec.md 7.3).

Since the local credit balance was removed, this log is additionally the only record of
spending: a row that carries `usage_json` is a row that cost money, and one that does not
did not. There is no separate charged flag to drift out of step with that.
"""

import json
import sqlite3
import uuid
from datetime import datetime, timezone

from backend import config

PENDING = "pending"
CALLING_API = "calling_api"
API_SUCCESS = "api_success"
API_FAILED = "api_failed"
DELIVERED = "delivered"
STATUSES = (PENDING, CALLING_API, API_SUCCESS, API_FAILED, DELIVERED)

SCHEMA = """
CREATE TABLE IF NOT EXISTS requests (
    request_id   TEXT PRIMARY KEY,
    status       TEXT NOT NULL,
    tree_path    TEXT NOT NULL,
    element_path TEXT NOT NULL,
    output_path  TEXT,
    size         TEXT NOT NULL,
    tree_code    TEXT,
    -- elements_json is the truth: [{"path": ..., "code": ...}, ...], one to five of them.
    -- element_path and element_code hold the first entry so rows written before
    -- multi-element still read, and so the history thumbnail has something to point at.
    elements_json TEXT,
    element_code TEXT,
    -- optional photo whose setting and light the result should adopt (Product.md 8.3)
    reference_path TEXT,
    error        TEXT,
    usage_json   TEXT,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);
"""


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path=None):
    """One connection per caller. Opening SQLite is cheap, and a fresh connection per
    request is what keeps FastAPI's threadpool out of trouble without a lock."""
    path = path or config.DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, isolation_level="DEFERRED")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.executescript(SCHEMA)
    # older databases keep their rows and gain whatever columns arrived since — the log is
    # the spend record, so it outlives schema changes rather than being rebuilt
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(requests)")}
    for column in ("usage_json", "tree_code", "element_code", "elements_json", "reference_path"):
        if column not in existing:
            conn.execute(f"ALTER TABLE requests ADD COLUMN {column} TEXT")
    conn.commit()
    return conn


def create(conn, tree_path, elements, size, tree_code=None, reference_path=None):
    """`elements` is a list of {"path": ..., "code": ...}, one to five of them."""
    request_id = uuid.uuid4().hex
    stamp = now()
    first = elements[0]
    with conn:
        conn.execute(
            "INSERT INTO requests (request_id, status, tree_path, element_path,"
            " elements_json, size, tree_code, element_code, reference_path,"
            " created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (request_id, PENDING, tree_path, first["path"], json.dumps(elements), size,
             tree_code, first.get("code"), reference_path, stamp, stamp),
        )
    return request_id


def elements_of(row):
    """The decorations on a request, whichever schema the row was written under."""
    raw = row["elements_json"] if "elements_json" in row.keys() else None
    if raw:
        return json.loads(raw)
    return [{"path": row["element_path"], "code": row["element_code"]}]


def _transition(conn, request_id, from_status, to_status, **fields):
    """Move a request between states, only from the state that is allowed to precede it.

    Returns True if this caller made the move, False if it was already made.
    """
    assignments = "".join(f", {k} = ?" for k in fields)
    with conn:
        cur = conn.execute(
            f"UPDATE requests SET status = ?, updated_at = ?{assignments}"
            " WHERE request_id = ? AND status = ?",
            (to_status, now(), *fields.values(), request_id, from_status),
        )
    return cur.rowcount == 1


def claim(conn, request_id):
    """pending -> calling_api. False means somebody already took it: a double-click, a
    retry, or a refresh. The caller must not call the paid API on a False."""
    return _transition(conn, request_id, PENDING, CALLING_API)


def mark_success(conn, request_id, output_path, usage=None):
    """`usage` is the API's own token accounting for this one image, stored verbatim so the
    cost of a generation is a recorded fact rather than something reconstructed later."""
    return _transition(
        conn,
        request_id,
        CALLING_API,
        API_SUCCESS,
        output_path=output_path,
        usage_json=json.dumps(usage) if usage else None,
    )


def mark_failed(conn, request_id, error):
    return _transition(conn, request_id, CALLING_API, API_FAILED, error=str(error)[:1000])


def mark_delivered(conn, request_id):
    """api_success -> delivered, set by the browser once it has actually rendered the result.
    A request stuck at api_success is exactly the reconciliation case Spec.md 7 describes."""
    return _transition(conn, request_id, API_SUCCESS, DELIVERED)


def get(conn, request_id):
    return conn.execute("SELECT * FROM requests WHERE request_id = ?", (request_id,)).fetchone()


def recent(conn, limit=100):
    return conn.execute(
        "SELECT * FROM requests ORDER BY created_at DESC, rowid DESC LIMIT ?", (limit,)
    ).fetchall()


def usage_totals(conn):
    """What has been spent, summed from the rows that actually cost something.

    This replaces the credit balance. It counts what happened rather than predicting what
    is left — OpenAI does not expose a remaining balance to an API key, so the account page
    is the only place a figure for that exists.
    """
    totals = {"generations": 0, "input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    for (raw,) in conn.execute("SELECT usage_json FROM requests WHERE usage_json IS NOT NULL"):
        usage = json.loads(raw)
        totals["generations"] += 1
        for key in ("input_tokens", "output_tokens", "total_tokens"):
            totals[key] += usage.get(key) or 0
    return totals
