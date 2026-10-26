"""#1235: a pool-full retry's lost attempt and retry-lock wait are not counted as model time."""
import threading

import httpx
import pytest
import respx

from evals.runners.text import CompletionRunner
from harness import completion, exclusive
from tests.test_busy_wait_timing_776 import GW, MODEL_S, URL, clock, ok, replies, svg_case  # noqa: F401

LOST = 0.4
FULL = {"error": {"code": 500, "message": "Context size has been exceeded.", "type": "server_error"}}


@pytest.fixture(autouse=True)
def _fast(monkeypatch):
    monkeypatch.setattr(completion, "POOL_FULL_POLL_S", 0.05)
    completion.POOL_FULL.clear()


def slow_full(clock):
    """A pool-full reply that took LOST on the fake clock before it came back."""
    def answer():
        clock.sleep(LOST)
        return httpx.Response(500, json=FULL)
    return answer


@respx.mock
def test_a_completion_reports_the_pool_full_attempt_it_lost(clock):
    respx.post(URL).mock(side_effect=replies(clock, slow_full(clock), ok))
    with completion.measuring():
        started = completion.time.perf_counter()
        got = completion.complete_full("hi", model="sohot-code", gateway=GW)
        mine = completion.since(started)
    assert mine == pytest.approx(MODEL_S)
    assert got.timing["pool_full_wait_s"] == LOST


@respx.mock
def test_an_eval_row_leaves_the_lost_pool_full_attempt_out_of_its_seconds(clock):
    respx.post(URL).mock(side_effect=replies(clock, slow_full(clock), ok))
    r = CompletionRunner(GW, "local-mid").run(svg_case())
    assert r.passed
    assert r.seconds == MODEL_S
    assert r.metrics["pool_full_wait_s"] == LOST


@respx.mock
def test_the_wait_for_the_retry_lock_is_left_out_too(clock):
    taken, attempted = threading.Event(), threading.Event()

    def full():
        attempted.set()
        return httpx.Response(500, json=FULL)
    respx.post(URL).mock(side_effect=replies(clock, full, ok))
    import hashlib
    name = f"pool-retry.{hashlib.sha256(GW.encode()).hexdigest()[:12]}.lock"

    def other_retry():
        with exclusive.alone(name, 10, 0.05):
            taken.set()
            attempted.wait(10)
            # The other retry holds the lock for LOST on the fake clock, after this request's first attempt.
            clock.sleep(LOST)

    t = threading.Thread(target=other_retry)
    t.start()
    taken.wait(10)
    with completion.measuring():
        started = completion.time.perf_counter()
        got = completion.complete_full("hi", model="sohot-code", gateway=GW)
        mine = completion.since(started)
    t.join()
    assert mine == pytest.approx(MODEL_S)
    assert got.timing["pool_full_wait_s"] == LOST


@respx.mock
def test_a_busy_wait_alone_reports_no_pool_full_wait(clock):
    from tests.test_busy_wait_timing_776 import busy
    respx.post(URL).mock(side_effect=replies(clock, busy, ok))
    got = completion.complete_full("hi", model="sohot-code", gateway=GW)
    assert got.timing["busy_wait_s"] > 0 and "pool_full_wait_s" not in got.timing
