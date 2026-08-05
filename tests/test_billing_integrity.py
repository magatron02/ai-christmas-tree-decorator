"""Billing integrity — TestPlan.md section 1, AC-4, NonGoals.md #4.

Highest-priority suite in the project: pay-per-generation spends real money from the first
MVP run, so "no credit was taken" has to be provable, not assumed. Every test here answers
one question — did the balance move, and was it allowed to?
"""

import threading

import pytest
from fastapi.testclient import TestClient

from backend import config, main
from backend.models import request_log
from backend.services import credit
from backend.services.image_gen import ImageGenError

from helpers import png_bytes, upload


def prepare(client, size="4:5"):
    """Get as far as a `pending` request without spending anything."""
    cut = client.post("/api/remove-bg", files=[upload(png_bytes(), "element.png")])
    assert cut.status_code == 200, cut.text
    element = cut.json()["element"]

    ready = client.post(
        "/api/prepare",
        files=[upload(png_bytes(), "tree.png")],
        data={"element": element, "size": size},
    )
    assert ready.status_code == 200, ready.text
    return ready.json()["request_id"]


def test_successful_generation_charges_exactly_one_credit(client, conn, funded, fake_gen, fake_rembg):
    request_id = prepare(client)

    response = client.post(f"/api/generate/{request_id}")

    assert response.status_code == 200, response.text
    assert fake_gen.count == 1
    assert credit.balance(conn) == funded - 1
    row = request_log.get(conn, request_id)
    assert row["status"] == request_log.API_SUCCESS
    assert row["charged"] == 1
    assert row["output_path"]


def test_charge_is_idempotent(conn, funded):
    """The guard is in the SQL, so calling the charge site again cannot take a second credit."""
    request_id = request_log.create(conn, "a_tree.png", "b_element.png", "4:5")
    request_log.claim(conn, request_id)
    request_log.mark_success(conn, request_id, "c_output.png")

    assert credit.charge_for(conn, request_id) is True
    assert credit.charge_for(conn, request_id) is False
    assert credit.charge_for(conn, request_id) is False
    assert credit.balance(conn) == funded - 1


@pytest.mark.parametrize(
    "failure",
    [
        ImageGenError("APITimeoutError: Request timed out."),
        ImageGenError("BadRequestError: content policy violation"),
    ],
    ids=["timeout", "api_error"],
)
def test_api_failure_never_charges(client, conn, funded, fake_gen, fake_rembg, failure):
    fake_gen.error = failure
    request_id = prepare(client)

    response = client.post(f"/api/generate/{request_id}")

    assert response.status_code == 502
    assert "no credit was used" in response.json()["error"]
    assert credit.balance(conn) == funded
    row = request_log.get(conn, request_id)
    assert row["status"] == request_log.API_FAILED
    assert row["charged"] == 0


def test_an_unexpected_crash_still_ends_the_request(client, conn, funded, fake_gen, fake_rembg):
    """Anything thrown after the claim has to land the row in a terminal state. A request
    stranded at calling_api can never be retried, and this is exactly how a missing API key
    behaved before the handler was widened."""
    fake_gen.error = RuntimeError("Missing credentials.")
    request_id = prepare(client)

    response = client.post(f"/api/generate/{request_id}")

    assert response.status_code == 502
    assert "no credit was used" in response.json()["error"]
    assert credit.balance(conn) == funded
    assert request_log.get(conn, request_id)["status"] == request_log.API_FAILED


def test_charge_is_impossible_before_success(conn, funded):
    """Every state that is not api_success is refused at the charge site itself."""
    request_id = request_log.create(conn, "a_tree.png", "b_element.png", "4:5")

    assert credit.charge_for(conn, request_id) is False  # pending
    request_log.claim(conn, request_id)
    assert credit.charge_for(conn, request_id) is False  # calling_api
    request_log.mark_failed(conn, request_id, "boom")
    assert credit.charge_for(conn, request_id) is False  # api_failed
    assert credit.balance(conn) == funded


def test_rembg_failure_charges_nothing_and_stops_the_pipeline(
    client, conn, funded, fake_gen, fake_rembg
):
    from backend.services.background_removal import BackgroundRemovalError

    fake_rembg.error = BackgroundRemovalError("could not separate the element")

    response = client.post("/api/remove-bg", files=[upload(png_bytes(), "element.png")])

    assert response.status_code == 422
    assert "could not separate the element" in response.json()["error"]
    assert fake_gen.count == 0, "background removal must never fall through to the paid call"
    assert request_log.recent(conn) == []
    assert credit.balance(conn) == funded


def test_double_click_through_confirm_charges_once(client, conn, funded, fake_gen, fake_rembg):
    """Two clicks land on the same request_id, and only one of them can claim it."""
    request_id = prepare(client)

    first = client.post(f"/api/generate/{request_id}")
    second = client.post(f"/api/generate/{request_id}")

    assert first.status_code == 200
    assert second.status_code == 409
    assert fake_gen.count == 1
    assert credit.balance(conn) == funded - 1


def test_concurrent_double_click_charges_once(conn, funded, fake_gen, fake_rembg):
    """The same thing when the two clicks genuinely race, rather than arriving in order."""
    fake_gen.delay = 0.25  # hold the first call open so the second arrives mid-flight

    with TestClient(main.app) as setup_client:
        request_id = prepare(setup_client)

    results = {}

    def fire(key):
        with TestClient(main.app) as thread_client:
            response = thread_client.post(f"/api/generate/{request_id}")
            results[key] = response.status_code

    threads = [threading.Thread(target=fire, args=(i,)) for i in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(results.values()) == [200, 409]
    assert fake_gen.count == 1
    assert credit.balance(conn) == funded - 1


def test_no_credit_means_no_api_call(client, conn, fake_gen, fake_rembg):
    """Zero balance is caught before the money is spent, not after."""
    request_id = prepare(client)

    response = client.post(f"/api/generate/{request_id}")

    assert response.status_code == 402
    assert fake_gen.count == 0
    assert credit.balance(conn) == 0
    assert request_log.get(conn, request_id)["status"] == request_log.API_FAILED


def test_free_steps_never_touch_the_balance(client, conn, funded, fake_gen, fake_rembg):
    prepare(client)
    assert credit.balance(conn) == funded
    assert client.get("/api/balance").json()["credits"] == funded


def test_the_balance_is_only_written_in_one_module():
    """AC-4 should be auditable by reading one file. Keep it that way."""
    offenders = sorted(
        path.relative_to(config.ROOT).as_posix()
        for path in (config.ROOT / "backend").rglob("*.py")
        if "UPDATE account" in path.read_text(encoding="utf-8")
    )
    assert offenders == ["backend/services/credit.py"]
