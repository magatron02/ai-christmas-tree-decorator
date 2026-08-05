"""Storage housekeeping.

Uploads and outputs accumulate forever otherwise: every cut-out the user rejected, every
request they prepared and cancelled. Nothing deletes them during normal operation on
purpose — history is the reconciliation record (Spec.md 7) and a file it points at must stay
reachable. So cleanup is a command you run, not a background job.

    python -m backend.services.storage prune --dry-run
    python -m backend.services.storage prune

Only files no request row refers to are removed, and only once they are old enough that they
cannot belong to a session still in progress.
"""

import time

from backend import config
from backend.models import request_log


def referenced(conn):
    """Every filename any request still points at, in any state — including failed ones,
    whose inputs are what you would re-run from."""
    names = set()
    for row in conn.execute("SELECT tree_path, element_path, output_path FROM requests"):
        names.update(name for name in row if name)
    return names


def orphans(conn, older_than_hours=24):
    """Files on disk that no request refers to and that are old enough to be safe.

    The age guard matters: a background-removal preview exists on disk before any request
    row mentions it, so a prune run mid-session would delete the cut-out the user is
    currently looking at.
    """
    cutoff = time.time() - older_than_hours * 3600
    keep = referenced(conn)
    return sorted(
        path
        for path in config.STORAGE_DIR.glob("*")
        if path.is_file() and path.name not in keep and path.stat().st_mtime < cutoff
    )


def prune(conn, older_than_hours=24, dry_run=False):
    removed = orphans(conn, older_than_hours)
    if not dry_run:
        for path in removed:
            path.unlink()
    return removed


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["prune"])
    parser.add_argument("--hours", type=int, default=24, help="minimum age to delete (default 24)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    connection = request_log.connect()
    files = prune(connection, args.hours, args.dry_run)
    total = sum(path.stat().st_size for path in files) if args.dry_run else None
    for path in files:
        print(("would remove " if args.dry_run else "removed ") + path.name)
    print(f"{len(files)} orphaned file(s)" + (f", {total / 1024 / 1024:.1f} MB" if total else ""))
