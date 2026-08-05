"""Storage housekeeping.

Uploads, outputs and abandoned requests accumulate forever otherwise: every cut-out the user
rejected, every request they prepared and then cancelled at the confirm dialog. Nothing
deletes them during normal operation on purpose — history is the reconciliation record
(Spec.md 7) and anything it points at must stay reachable. So cleanup is a command you run,
not a background job.

    python -m backend.services.storage prune --dry-run
    python -m backend.services.storage prune

Two kinds of rubbish, one age guard:

  * `pending` requests that were never confirmed. A pending row has no usage, so it provably
    never reached the API and never cost anything; deleting it removes no evidence. Rows in
    every other state are kept forever — that is the point of the log.
  * files no surviving request refers to.

Nothing is touched until it is old enough that it cannot belong to a session still in
progress. A cut-out preview exists on disk before any row mentions it, and a prepared request
sits at `pending` while the user is still looking at the confirm dialog.
"""

import time
from datetime import datetime, timedelta, timezone

from backend import config
from backend.models import request_log


def _cutoff_iso(older_than_hours):
    """The log stores ISO-8601 UTC strings, which compare correctly as text."""
    moment = datetime.now(timezone.utc) - timedelta(hours=older_than_hours)
    return moment.isoformat(timespec="seconds")


def abandoned(conn, older_than_hours=24):
    """Requests left at `pending` — prepared, then never confirmed.

    Safe to drop precisely because they are `pending`: the state machine only leaves a row
    there before `claim()`, so no API call was ever made for it and there is no cost to lose.
    """
    return [
        row["request_id"]
        for row in conn.execute(
            "SELECT request_id FROM requests WHERE status = ? AND updated_at < ?",
            (request_log.PENDING, _cutoff_iso(older_than_hours)),
        )
    ]


def referenced(conn, exclude=()):
    """Filenames the surviving requests point at, in any state — including failed ones, whose
    inputs are what you would re-run from. `exclude` is the set about to be deleted."""
    exclude = set(exclude)
    names = set()
    for row in conn.execute(
        "SELECT request_id, tree_path, element_path, output_path FROM requests"
    ):
        if row["request_id"] in exclude:
            continue
        names.update(row[key] for key in ("tree_path", "element_path", "output_path") if row[key])
    return names


def orphans(conn, older_than_hours=24, exclude=()):
    keep = referenced(conn, exclude)
    cutoff = time.time() - older_than_hours * 3600
    return sorted(
        path
        for path in config.STORAGE_DIR.glob("*")
        if path.is_file() and path.name not in keep and path.stat().st_mtime < cutoff
    )


def prune(conn, older_than_hours=24, dry_run=False):
    """Returns (abandoned request ids, files to delete).

    Both are worked out before anything is removed, so a dry run and a real run take the same
    path and report the same thing.
    """
    requests = abandoned(conn, older_than_hours)
    files = orphans(conn, older_than_hours, exclude=requests)

    if not dry_run:
        if requests:
            with conn:
                conn.executemany(
                    "DELETE FROM requests WHERE request_id = ?", [(r,) for r in requests]
                )
        for path in files:
            path.unlink()

    return requests, files


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Remove abandoned requests and orphaned files.")
    parser.add_argument("command", choices=["prune"])
    parser.add_argument("--hours", type=int, default=24, help="minimum age to delete (default 24)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    verb = "would remove" if args.dry_run else "removed"
    connection = request_log.connect()
    megabytes = (
        sum(path.stat().st_size for path in orphans(connection, args.hours)) / 1024 / 1024
        if args.dry_run
        else None
    )
    abandoned_ids, orphaned_files = prune(connection, args.hours, args.dry_run)

    for request_id in abandoned_ids:
        print(f"{verb} abandoned request {request_id}")
    for path in orphaned_files:
        print(f"{verb} file {path.name}")
    print(
        f"{len(abandoned_ids)} abandoned request(s), {len(orphaned_files)} orphaned file(s)"
        + (f", {megabytes:.1f} MB" if megabytes else "")
    )
