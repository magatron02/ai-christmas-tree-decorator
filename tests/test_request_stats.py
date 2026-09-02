"""category_counts() — the wizard's reference-only history display (wayfinder ticket #5).

Real catalogue codes, same two the exact-scale tests already use: "05021-1" is a tree,
"017-06" is an ornament (backend.services.catalog.category_of confirms both).
"""

from backend.models import request_log
from backend.services import request_stats


def _write_request(conn, *element_codes):
    elements = [{"path": f"{code}.png", "code": code} for code in element_codes]
    return request_log.create(conn, "tree.png", elements, "4:5", tree_code="05021-1")


def test_counts_one_request_per_category_it_touched(conn):
    _write_request(conn, "017-06")
    counts = request_stats.category_counts(conn)
    assert counts == {"ornament": 1}


def test_a_request_with_two_of_the_same_category_counts_once(conn):
    _write_request(conn, "017-06", "017-06")
    counts = request_stats.category_counts(conn)
    assert counts["ornament"] == 1


def test_counts_accumulate_across_requests(conn):
    _write_request(conn, "017-06")
    _write_request(conn, "017-06")
    counts = request_stats.category_counts(conn)
    assert counts["ornament"] == 2


def test_an_element_with_no_code_is_ignored(conn):
    _write_request(conn, None)
    counts = request_stats.category_counts(conn)
    assert counts == {}


def test_no_history_returns_an_empty_dict(conn):
    assert request_stats.category_counts(conn) == {}
