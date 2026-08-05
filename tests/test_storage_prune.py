"""Storage housekeeping.

The dangerous mistake here is deleting a file some history row still points at — that turns
a paid-for generation into a broken link, which is the one thing the reconciliation design
exists to prevent. These tests are mostly about what prune refuses to touch.
"""

import os
import time

from backend import config
from backend.models import request_log
from backend.services import storage


def write(name, age_hours=48):
    path = config.STORAGE_DIR / name
    path.write_bytes(b"x")
    old = time.time() - age_hours * 3600
    os.utime(path, (old, old))
    return path


def test_orphans_are_removed(conn):
    stray = write("0123456789abcdef0123456789abcdef_element.png")

    removed = storage.prune(conn)

    assert removed == [stray]
    assert not stray.exists()


def test_referenced_files_are_never_removed(conn):
    tree = write("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa_tree.png")
    element = write("bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb_element.png")
    output = write("cccccccccccccccccccccccccccccccc_output.png")
    request_id = request_log.create(conn, tree.name, element.name, "4:5")
    request_log.claim(conn, request_id)
    request_log.mark_success(conn, request_id, output.name)

    assert storage.prune(conn) == []
    assert tree.exists() and element.exists() and output.exists()


def test_a_failed_requests_inputs_are_kept(conn):
    """You re-run from them, so they are not rubbish just because the generation failed."""
    tree = write("dddddddddddddddddddddddddddddddd_tree.png")
    element = write("eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee_element.png")
    request_id = request_log.create(conn, tree.name, element.name, "4:5")
    request_log.claim(conn, request_id)
    request_log.mark_failed(conn, request_id, "timeout")

    assert storage.prune(conn) == []
    assert tree.exists() and element.exists()


def test_recent_files_are_left_alone(conn):
    """A cut-out exists on disk before any row mentions it. Pruning mid-session must not
    delete the preview the user is looking at."""
    fresh = write("ffffffffffffffffffffffffffffffff_element.png", age_hours=0)

    assert storage.prune(conn) == []
    assert fresh.exists()


def test_dry_run_reports_without_deleting(conn):
    stray = write("99999999999999999999999999999999_output.png")

    reported = storage.prune(conn, dry_run=True)

    assert reported == [stray]
    assert stray.exists(), "a dry run must not delete anything"
