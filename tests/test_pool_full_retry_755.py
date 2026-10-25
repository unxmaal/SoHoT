"""#755: a request llama-server failed because its shared KV pool filled is sent again, one retry at a time."""
import json
import threading
import time

import httpx
import pytest
import respx

from evals.core import Receipt
from evals.runners.base import BaseRunner
from harness import completion, knobs, reasons
from tests.test_router_swaps import OURS, _run, quiet_receipt  # noqa: F401

GW = "http://127.0.0.1:4000"
URL = f"{GW}/v1/chat/completions"
#: llama-server 0.5.0's body to every task in flight when the pool fills, as the #748 probe recorded it.
FULL = {"error": {"code": 500, "message": "Context size has been exceeded.", "type": "server_error"}}


def _full():
    return httpx.Response(500, json=FULL)


def _ok(text="ok"):
    return httpx.Response(200, json={"choices": [{"message": {"content": text}, "finish_reason": "stop"}]})


def _sse(*events):
    body = "".join(f"data: {json.dumps(e)}\n\n" for e in events) + "data: [DONE]\n\n"
    return httpx.Response(200, headers={"content-type": "text/event-stream"}, text=body)


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    monkeypatch.delenv(completion.GATEWAY_ENV, raising=False)
    completion.POOL_FULL.clear()
    yield
    completion.POOL_FULL.clear()


@respx.mock
def test_a_pool_full_reply_is_sent_again_and_counted():
    route = respx.post(URL).mock(side_effect=[_full(), _ok()])
    assert completion.complete("hi", model="sohot-code", gateway=GW) == "ok"
    assert route.call_count == 2
    assert completion.pool_full_counts() == (1, 0)


@respx.mock
def test_past_its_retries_a_pool_full_request_is_pool_full_with_its_limit(monkeypatch):
    route = respx.post(URL).mock(side_effect=[_full(), _full()])
    with pytest.raises(completion.CompletionError) as got:
        completion.complete("hi", model="sohot-code", gateway=GW)
    assert route.call_count == 2
    assert got.value.failure_class == reasons.POOL_FULL
    assert got.value.limit == ("pool_full_retries", 1)
    assert reasons.classify(str(got.value)) == reasons.POOL_FULL
    assert completion.pool_full_counts() == (1, 1)


@respx.mock
def test_with_no_retries_the_first_pool_full_reply_is_the_row(monkeypatch):
    monkeypatch.setattr(completion, "POOL_FULL_RETRIES", 0)
    route = respx.post(URL).mock(side_effect=[_full(), _ok()])
    with pytest.raises(completion.CompletionError) as got:
        completion.complete("hi", model="sohot-code", gateway=GW)
    assert route.call_count == 1 and got.value.limit == ("pool_full_retries", 0)


@respx.mock
def test_a_stream_that_opens_with_the_pool_full_error_is_sent_again():
    route = respx.post(URL).mock(side_effect=[
        _sse({"error": FULL["error"]}),
        _sse({"choices": [{"delta": {"content": "ok"}, "finish_reason": "stop"}]})])
    got = completion.chat([{"role": "user", "content": "hi"}], model="sohot-code", gateway=GW, stream=True)
    assert got.text == "ok" and route.call_count == 2


@respx.mock
def test_another_server_error_is_not_retried():
    route = respx.post(URL).mock(side_effect=[
        httpx.Response(500, json={"error": {"message": "generation thread died"}}), _ok()])
    with pytest.raises(completion.CompletionError):
        completion.complete("hi", model="sohot-code", gateway=GW)
    assert route.call_count == 1 and completion.pool_full_counts() == (0, 0)


@respx.mock
def test_requests_the_pool_failed_together_retry_one_at_a_time():
    both = threading.Barrier(2, timeout=10)
    lock = threading.Lock()
    state = {"calls": 0, "now": 0, "most": 0}

    def answer(request):
        with lock:
            state["calls"] += 1
            first = state["calls"] <= 2
        if first:
            both.wait()
            return _full()
        with lock:
            state["now"] += 1
            state["most"] = max(state["most"], state["now"])
        time.sleep(0.2)
        with lock:
            state["now"] -= 1
        return _ok()

    respx.post(URL).mock(side_effect=answer)
    out = []
    threads = [threading.Thread(target=lambda: out.append(completion.complete("hi", model="sohot-code", gateway=GW)))
               for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert out == ["ok", "ok"] and state["calls"] == 4
    assert state["most"] == 1


def test_pool_full_retries_is_a_registered_limit_in_calls():
    assert knobs.hit("pool_full_retries", 1, "calls") == ("pool_full_retries", 1)
    assert completion.POOL_FULL_RETRIES in knobs.KNOBS["pool_full_retries"].values


class Asks(BaseRunner):
    """A runner whose one request per case goes through completion to a fake gateway."""

    def __init__(self):
        self.candidate = self.spec = "llamacpp:" + OURS

    def generate(self, case):
        return completion.complete("hi", model="sohot-code", gateway=GW), 0


def _answers(*first):
    queue = list(first)
    return lambda request: queue.pop(0) if queue else _ok()


def test_an_eval_receipt_counts_the_pool_full_retries_of_each_candidate(tmp_path, monkeypatch, quiet_receipt):
    with respx.mock:
        respx.post(URL).mock(side_effect=_answers(_full()))
        data = _run(tmp_path, monkeypatch, Asks(), OURS)
    assert data["receipt"]["pool_full"] == {"llamacpp:" + OURS: {"retried": 1, "lost": 0}}
    assert Receipt.from_dict(data["receipt"]).pool_full == data["receipt"]["pool_full"]


def test_a_run_that_met_no_full_pool_has_no_pool_full_entry(tmp_path, monkeypatch, quiet_receipt):
    with respx.mock:
        respx.post(URL).mock(side_effect=_answers())
        data = _run(tmp_path, monkeypatch, Asks(), OURS)
    assert "pool_full" not in data["receipt"]
    assert Receipt.from_dict(data["receipt"]).pool_full == {}
