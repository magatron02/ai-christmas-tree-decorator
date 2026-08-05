"""Billing integrity — TestPlan.md section 1, AC-4.

The local credit balance was removed: money lives in the OpenAI account and OpenAI is the
only thing that knows how much is left. So the property under test is no longer "the balance
moved by one". It is the thing the balance was standing in for, stated directly:

    a confirmed request may cause at most one billable API call,
    and a request that fails must cause none at all.

That is still the highest-priority suite in the project, because it is still the only thing
between a double-click and a second image nobody asked for. `fake_gen.count` is the meter —
every call to it would have been real money.
"""

import json
import threading

import pytest
from fastapi.testclient import TestClient

from backend import config, main
from backend.models import request_log
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


def test_a_confirmed_request_bills_exactly_once(client, conn, fake_gen, fake_rembg):
    request_id = prepare(client)

    response = client.post(f"/api/generate/{request_id}")

    assert response.status_code == 200, response.text
    assert fake_gen.count == 1
    row = request_log.get(conn, request_id)
    assert row["status"] == request_log.API_SUCCESS
    assert row["output_path"]
    assert response.json()["billed"] is True


@pytest.mark.parametrize(
    "failure",
    [
        ImageGenError("APITimeoutError: Request timed out."),
        ImageGenError("BadRequestError: content policy violation"),
    ],
    ids=["timeout", "api_error"],
)
def test_a_failed_generation_records_no_cost(client, conn, fake_gen, fake_rembg, failure):
    fake_gen.error = failure
    request_id = prepare(client)

    response = client.post(f"/api/generate/{request_id}")

    assert response.status_code == 502
    row = request_log.get(conn, request_id)
    assert row["status"] == request_log.API_FAILED
    assert row["usage_json"] is None, "a failure must not look like a cost in the log"
    assert request_log.usage_totals(conn)["generations"] == 0


def test_an_exhausted_account_is_reported_readably(client, conn, fake_gen, fake_rembg):
    """With no local balance, OpenAI's billing limit is what says 'out of money'. It has to
    arrive as something a person can act on, not a raw error code."""
    fake_gen.error = ImageGenError(
        "OpenAI stopped the request: the account has hit its billing limit. "
        "Top up or raise the limit at platform.openai.com. Nothing was generated."
    )
    request_id = prepare(client)

    response = client.post(f"/api/generate/{request_id}")

    assert response.status_code == 502
    assert "billing limit" in response.json()["error"]
    assert request_log.get(conn, request_id)["status"] == request_log.API_FAILED
    assert request_log.usage_totals(conn)["generations"] == 0


def test_an_unexpected_crash_still_ends_the_request(client, conn, fake_gen, fake_rembg):
    """Anything thrown after the claim has to land the row in a terminal state. A request
    stranded at calling_api can never be retried, and this is exactly how a missing API key
    behaved before the handler was widened."""
    fake_gen.error = RuntimeError("Missing credentials.")
    request_id = prepare(client)

    response = client.post(f"/api/generate/{request_id}")

    assert response.status_code == 502
    assert request_log.get(conn, request_id)["status"] == request_log.API_FAILED
    assert request_log.usage_totals(conn)["generations"] == 0


def test_rembg_failure_bills_nothing_and_stops_the_pipeline(client, conn, fake_gen, fake_rembg):
    from backend.services.background_removal import BackgroundRemovalError

    fake_rembg.error = BackgroundRemovalError("could not separate the element")

    response = client.post("/api/remove-bg", files=[upload(png_bytes(), "element.png")])

    assert response.status_code == 422
    assert "could not separate the element" in response.json()["error"]
    assert fake_gen.count == 0, "background removal must never fall through to the paid call"
    assert request_log.recent(conn) == []


def test_double_click_through_confirm_bills_once(client, conn, fake_gen, fake_rembg):
    """Two clicks land on the same request_id, and only one of them can claim it."""
    request_id = prepare(client)

    first = client.post(f"/api/generate/{request_id}")
    second = client.post(f"/api/generate/{request_id}")

    assert first.status_code == 200
    assert second.status_code == 409
    assert fake_gen.count == 1
    assert request_log.usage_totals(conn)["generations"] == 1


def test_concurrent_double_click_bills_once(conn, fake_gen, fake_rembg):
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
    assert request_log.usage_totals(conn)["generations"] == 1


def test_a_finished_request_can_never_be_rerun(client, conn, fake_gen, fake_rembg):
    """Replaying the URL is not a way to buy a second image."""
    request_id = prepare(client)
    client.post(f"/api/generate/{request_id}")
    client.post(f"/api/delivered/{request_id}")

    replay = client.post(f"/api/generate/{request_id}")

    assert replay.status_code == 409
    assert fake_gen.count == 1


def test_the_free_steps_call_nothing_billable(client, conn, fake_gen, fake_rembg):
    prepare(client)

    assert fake_gen.count == 0
    assert request_log.usage_totals(conn) == {
        "generations": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
    }


def test_what_a_generation_cost_is_recorded_with_it(client, conn, fake_gen, fake_rembg):
    """With no balance to read, the log is the only spend record there is (Product.md 6)."""
    from conftest import FAKE_USAGE

    request_id = prepare(client)
    response = client.post(f"/api/generate/{request_id}")

    assert response.json()["usage"] == FAKE_USAGE
    stored = json.loads(request_log.get(conn, request_id)["usage_json"])
    assert stored["total_tokens"] == FAKE_USAGE["total_tokens"]

    totals = request_log.usage_totals(conn)
    assert totals["generations"] == 1
    assert totals["total_tokens"] == FAKE_USAGE["total_tokens"]

    entry = next(
        item
        for item in client.get("/api/history").json()["requests"]
        if item["request_id"] == request_id
    )
    assert entry["usage"]["output_tokens"] == FAKE_USAGE["output_tokens"]


def test_totals_only_count_generations_that_happened(client, conn, fake_gen, fake_rembg):
    """One success and one failure must total as one, or the spend record overstates itself."""
    from conftest import FAKE_USAGE

    client.post(f"/api/generate/{prepare(client)}")
    fake_gen.error = ImageGenError("APITimeoutError: Request timed out.")
    client.post(f"/api/generate/{prepare(client)}")

    totals = request_log.usage_totals(conn)
    assert totals["generations"] == 1
    assert totals["total_tokens"] == FAKE_USAGE["total_tokens"]


def test_nothing_claims_to_know_the_remaining_balance():
    """OpenAI exposes no remaining-balance endpoint to an API key. Anything here that looked
    like one would be a hand-maintained number, wrong as soon as the key is used elsewhere —
    which is the reason the local credit system was removed rather than reworked."""
    sources = list((config.ROOT / "backend").rglob("*.py")) + list(
        (config.FRONTEND_DIR).glob("*.js")
    )
    for path in sources:
        text = path.read_text(encoding="utf-8")
        assert "credits" not in text, f"{path.name} still tracks a local credit balance"
        assert "/api/balance" not in text, f"{path.name} still queries a balance endpoint"
