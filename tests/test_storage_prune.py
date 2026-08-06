"""Storage housekeeping.

The dangerous mistake here is deleting something a history row still points at — that turns
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


def age_request(conn, request_id, hours=48):
    """Backdate a row so the age guard lets it through."""
    stale = storage._cutoff_iso(hours)
    with conn:
        conn.execute("UPDATE requests SET updated_at = ? WHERE request_id = ?", (stale, request_id))


# ---- files ------------------------------------------------------------------------------


def test_orphaned_files_are_removed(conn):
    stray = write("0123456789abcdef0123456789abcdef_element.png")

    _, files = storage.prune(conn)

    assert files == [stray]
    assert not stray.exists()


def test_referenced_files_are_never_removed(conn):
    tree = write("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa_tree.png")
    element = write("bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb_element.png")
    output = write("cccccccccccccccccccccccccccccccc_output.png")
    request_id = request_log.create(conn, tree.name, [{"path": element.name}], "4:5")
    request_log.claim(conn, request_id)
    request_log.mark_success(conn, request_id, output.name)
    age_request(conn, request_id)

    assert storage.prune(conn) == ([], [])
    assert tree.exists() and element.exists() and output.exists()


def test_a_failed_requests_inputs_are_kept(conn):
    """You re-run from them, so they are not rubbish just because the generation failed."""
    tree = write("dddddddddddddddddddddddddddddddd_tree.png")
    element = write("eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee_element.png")
    request_id = request_log.create(conn, tree.name, [{"path": element.name}], "4:5")
    request_log.claim(conn, request_id)
    request_log.mark_failed(conn, request_id, "timeout")
    age_request(conn, request_id)

    assert storage.prune(conn) == ([], [])
    assert tree.exists() and element.exists()


def test_recent_files_are_left_alone(conn):
    """A cut-out exists on disk before any row mentions it. Pruning mid-session must not
    delete the preview the user is looking at."""
    fresh = write("ffffffffffffffffffffffffffffffff_element.png", age_hours=0)

    assert storage.prune(conn) == ([], [])
    assert fresh.exists()


# ---- abandoned requests -----------------------------------------------------------------


def test_an_abandoned_pending_request_is_removed_with_its_uploads(conn):
    """Cancelling the confirm dialog leaves this behind. It never reached the API."""
    tree = write("11111111111111111111111111111111_tree.png")
    element = write("22222222222222222222222222222222_element.png")
    request_id = request_log.create(conn, tree.name, [{"path": element.name}], "4:5")
    age_request(conn, request_id)

    requests, files = storage.prune(conn)

    assert requests == [request_id]
    assert sorted(files) == sorted([element, tree])
    assert request_log.get(conn, request_id) is None
    assert not tree.exists() and not element.exists()


def test_a_fresh_pending_request_survives(conn):
    """It is `pending` because the user is looking at the confirm dialog right now."""
    tree = write("33333333333333333333333333333333_tree.png", age_hours=0)
    element = write("44444444444444444444444444444444_element.png", age_hours=0)
    request_id = request_log.create(conn, tree.name, [{"path": element.name}], "4:5")

    assert storage.prune(conn) == ([], [])
    assert request_log.get(conn, request_id) is not None


def test_requests_that_cost_money_are_never_removed(conn):
    """Only `pending` is deletable. Everything else is the spend record."""
    kept = []
    for status in ("calling_api", "api_success", "api_failed", "delivered"):
        request_id = request_log.create(conn, "a_tree.png", [{"path": "b_element.png"}], "4:5")
        request_log.claim(conn, request_id)
        if status == "api_success":
            request_log.mark_success(conn, request_id, "c_output.png", {"total_tokens": 1})
        elif status == "api_failed":
            request_log.mark_failed(conn, request_id, "boom")
        elif status == "delivered":
            request_log.mark_success(conn, request_id, "c_output.png", {"total_tokens": 1})
            request_log.mark_delivered(conn, request_id)
        age_request(conn, request_id)
        kept.append(request_id)

    requests, _ = storage.prune(conn)

    assert requests == []
    assert all(request_log.get(conn, request_id) is not None for request_id in kept)


def test_pruning_does_not_change_the_spend_record(conn):
    """Whatever else it removes, the totals must survive it untouched."""
    paid = request_log.create(conn, "a_tree.png", [{"path": "b_element.png"}], "4:5")
    request_log.claim(conn, paid)
    request_log.mark_success(conn, paid, "c_output.png", {"total_tokens": 3239})
    abandoned_id = request_log.create(conn, "d_tree.png", [{"path": "e_element.png"}], "4:5")
    age_request(conn, paid)
    age_request(conn, abandoned_id)

    before = request_log.usage_totals(conn)
    storage.prune(conn)

    assert request_log.usage_totals(conn) == before
    assert before["total_tokens"] == 3239


def test_dry_run_reports_without_deleting(conn):
    stray = write("99999999999999999999999999999999_output.png")
    request_id = request_log.create(conn, "f_tree.png", [{"path": "g_element.png"}], "4:5")
    age_request(conn, request_id)

    requests, files = storage.prune(conn, dry_run=True)

    assert requests == [request_id]
    assert files == [stray]
    assert stray.exists(), "a dry run must not delete anything"
    assert request_log.get(conn, request_id) is not None
