"""Reconciliation — Spec.md 7.

The case being defended against: the API succeeds, the credit is taken, and the response
never reaches the browser. The design answer for a single-user MVP is not a retry queue —
it is that the state log always knows, and the history page always shows.
"""

from backend.models import request_log
from backend.services import credit

from helpers import png_bytes, upload


def make(conn, size="4:5"):
    return request_log.create(conn, "a_tree.png", "b_element.png", size)


def test_the_happy_path_walks_the_states_in_order(conn):
    request_id = make(conn)
    assert request_log.get(conn, request_id)["status"] == request_log.PENDING

    assert request_log.claim(conn, request_id) is True
    assert request_log.get(conn, request_id)["status"] == request_log.CALLING_API

    assert request_log.mark_success(conn, request_id, "c_output.png") is True
    assert request_log.get(conn, request_id)["status"] == request_log.API_SUCCESS

    assert request_log.mark_delivered(conn, request_id) is True
    assert request_log.get(conn, request_id)["status"] == request_log.DELIVERED


def test_transitions_out_of_order_are_refused(conn):
    request_id = make(conn)

    assert request_log.mark_success(conn, request_id, "c_output.png") is False
    assert request_log.mark_delivered(conn, request_id) is False
    assert request_log.mark_failed(conn, request_id, "nope") is False
    assert request_log.get(conn, request_id)["status"] == request_log.PENDING


def test_a_request_can_only_be_claimed_once(conn):
    request_id = make(conn)
    assert request_log.claim(conn, request_id) is True
    assert request_log.claim(conn, request_id) is False


def test_a_terminal_request_cannot_be_reopened(conn):
    request_id = make(conn)
    request_log.claim(conn, request_id)
    request_log.mark_failed(conn, request_id, "timeout")

    assert request_log.claim(conn, request_id) is False
    assert request_log.mark_success(conn, request_id, "c_output.png") is False


def test_an_undelivered_success_is_still_recoverable(client, conn, funded, fake_gen, fake_rembg):
    """The network drops before the browser sees the image. The credit is spent, so the
    image has to still be reachable — this is the whole point of the history page."""
    cut = client.post("/api/remove-bg", files=[upload(png_bytes(), "element.png")])
    ready = client.post(
        "/api/prepare",
        files=[upload(png_bytes(), "tree.png")],
        data={"element": cut.json()["element"], "size": "4:5"},
    )
    request_id = ready.json()["request_id"]
    client.post(f"/api/generate/{request_id}")
    # ...and the browser never calls /api/delivered, because it is gone.

    row = request_log.get(conn, request_id)
    assert row["status"] == request_log.API_SUCCESS
    assert row["charged"] == 1

    history = client.get("/api/history").json()
    entry = next(item for item in history["requests"] if item["request_id"] == request_id)
    assert entry["status"] == request_log.API_SUCCESS
    assert entry["output_url"], "the paid-for image must be downloadable after the fact"
    assert entry["charged"] is True
    assert history["credits"] == funded - 1


def test_marking_delivered_does_not_charge_again(client, conn, funded, fake_gen, fake_rembg):
    cut = client.post("/api/remove-bg", files=[upload(png_bytes(), "element.png")])
    ready = client.post(
        "/api/prepare",
        files=[upload(png_bytes(), "tree.png")],
        data={"element": cut.json()["element"], "size": "4:5"},
    )
    request_id = ready.json()["request_id"]
    client.post(f"/api/generate/{request_id}")

    client.post(f"/api/delivered/{request_id}")
    client.post(f"/api/delivered/{request_id}")

    assert credit.balance(conn) == funded - 1
    assert request_log.get(conn, request_id)["status"] == request_log.DELIVERED


def test_a_request_stuck_mid_call_stays_visible(client, conn):
    """A crash during the API call leaves calling_api behind. Spec.md 7.4 says a human
    notices it in the log; the minimum requirement is that it is not hidden."""
    request_id = make(conn)
    request_log.claim(conn, request_id)

    history = client.get("/api/history").json()
    entry = next(item for item in history["requests"] if item["request_id"] == request_id)
    assert entry["status"] == request_log.CALLING_API
    assert entry["charged"] is False


def test_history_is_newest_first(conn, client):
    first = make(conn)
    second = make(conn)

    ids = [item["request_id"] for item in client.get("/api/history").json()["requests"]]
    assert ids.index(second) < ids.index(first)


def test_delivered_on_an_unknown_request_is_a_clean_404(client):
    response = client.post("/api/delivered/does-not-exist")
    assert response.status_code == 404
    assert "error" in response.json()


def test_generate_on_an_unknown_request_is_a_clean_404(client, fake_gen):
    response = client.post("/api/generate/does-not-exist")
    assert response.status_code == 404
    assert fake_gen.count == 0
