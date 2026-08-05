"""Request state log (Spec.md 2 and 7).

    pending -> calling_api -> api_success | api_failed -> delivered

Every transition is a single guarded UPDATE and the caller checks the row count. The guard
lives in the SQL, not in a Python `if`, which is what makes two racing requests safe without
a lock: SQLite serialises the write, the loser gets rowcount 0. `claim()` is the double-click
backstop behind the confirm dialog.

The log is also the reconciliation record: if the browser never receives the response, the
row is still api_success with an output path, and /api/history hands it back (Spec.md 7.3).
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
CREATE TABLE IF NOT EXISTS account (
    id      INTEGER PRIMARY KEY CHECK (id = 1),
    credits INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS requests (
    request_id   TEXT PRIMARY KEY,
    status       TEXT NOT NULL,
    charged      INTEGER NOT NULL DEFAULT 0,
    tree_path    TEXT NOT NULL,
    element_path TEXT NOT NULL,
    output_path  TEXT,
    size         TEXT NOT NULL,
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
    # databases created before usage accounting existed keep their rows and gain the column
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(requests)")}
    if "usage_json" not in existing:
        conn.execute("ALTER TABLE requests ADD COLUMN usage_json TEXT")
    conn.execute("INSERT OR IGNORE INTO account (id, credits) VALUES (1, 0)")
    conn.commit()
    return conn


def create(conn, tree_path, element_path, size):
    request_id = uuid.uuid4().hex
    stamp = now()
    with conn:
        conn.execute(
            "INSERT INTO requests (request_id, status, tree_path, element_path, size,"
            " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (request_id, PENDING, tree_path, element_path, size, stamp, stamp),
        )
    return request_id


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
