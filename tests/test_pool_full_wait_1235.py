"""#1235: a pool-full retry's lost attempt and retry-lock wait are not counted as model time."""
import threading
import time

import httpx
import pytest
import respx

from evals.runners.text import CompletionRunner
from harness import batch, completion, exclusive
from tests.test_busy_wait_timing_776 import GW, URL, ok, replies, svg_case

LOST = 0.4
FULL = {"error": {"code": 500, "message": "Context size has been exceeded.", "type": "server_error"}}


@pytest.fixture(autouse=True)
def _fast(monkeypatch):
    monkeypatch.setattr(batch, "BUSY_POLL_S", 0.2)
    monkeypatch.setattr(completion, "POOL_FULL_POLL_S", 0.05)
    completion.POOL_FULL.clear()


def slow_full():
    time.sleep(LOST)
    return httpx.Response(500, json=FULL)


@respx.mock
def test_a_completion_reports_the_pool_full_attempt_it_lost():
    respx.post(URL).mock(side_effect=replies(slow_full, ok))
    with completion.measuring():
        started = time.perf_counter()
        got = completion.complete_full("hi", model="sohot-code", gateway=GW)
        mine = completion.since(started)
    assert mine < LOST - 0.1
    assert got.timing["pool_full_wait_s"] >= LOST - 0.05


@respx.mock
def test_an_eval_row_leaves_the_lost_pool_full_attempt_out_of_its_seconds():
    respx.post(URL).mock(side_effect=replies(slow_full, ok))
    r = CompletionRunner(GW, "local-mid").run(svg_case())
    assert r.passed
    assert r.seconds < LOST - 0.1
    assert r.metrics["pool_full_wait_s"] >= LOST - 0.05


@respx.mock
def test_the_wait_for_the_retry_lock_is_left_out_too():
    respx.post(URL).mock(side_effect=replies(lambda: httpx.Response(500, json=FULL), ok))
    import hashlib
    name = f"pool-retry.{hashlib.sha256(GW.encode()).hexdigest()[:12]}.lock"
    taken, free = threading.Event(), threading.Event()

    def other_retry():
        with exclusive.alone(name, 10, 0.05):
            taken.set()
            free.wait(10)

    t = threading.Thread(target=other_retry)
    t.start()
    taken.wait(10)
    threading.Timer(LOST, free.set).start()
    with completion.measuring():
        started = time.perf_counter()
        got = completion.complete_full("hi", model="sohot-code", gateway=GW)
        mine = completion.since(started)
    t.join()
    assert mine < LOST - 0.1
    assert got.timing["pool_full_wait_s"] >= LOST - 0.1


@respx.mock
def test_a_busy_wait_alone_reports_no_pool_full_wait():
    from tests.test_busy_wait_timing_776 import busy
    respx.post(URL).mock(side_effect=replies(busy, ok))
    got = completion.complete_full("hi", model="sohot-code", gateway=GW)
    assert got.timing["busy_wait_s"] > 0 and "pool_full_wait_s" not in got.timing
