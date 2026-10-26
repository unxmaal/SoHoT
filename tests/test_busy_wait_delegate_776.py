"""#776: a delegation's reported seconds leave out a wait for another batch on the serving machine."""
import types

import httpx
import respx

from harness import batch, completion, delegate, methods
from tests.test_busy_wait_timing_776 import MODEL_S, POLL, clock  # noqa: F401
from tests.test_mcp_delegate import fake  # noqa: F401

GW = "http://127.0.0.1:4000"


def test_a_delegations_seconds_are_its_model_time_exactly(fake, clock, monkeypatch):
    real, sent = completion._send, []

    def send(*a, **k):
        sent.append(1)
        if len(sent) == 1:
            return types.SimpleNamespace(status_code=503, text=batch.BUSY)
        got = real(*a, **k)
        clock.sleep(MODEL_S)
        return got
    monkeypatch.setattr(completion, "_send", send)
    got = delegate.complete("code", "write add")
    assert len(sent) == 2
    assert got["busy_wait_s"] == POLL
    assert got["seconds"] == MODEL_S


@respx.mock
def test_a_best_of_delegation_leaves_the_busy_wait_out_of_its_wall(clock):
    busy = httpx.Response(503, json={"error": {"message": f"{batch.BUSY} (batch b-1)"}})
    ok = httpx.Response(200, json={"choices": [{"message": {"content": "x = 1"}, "finish_reason": "stop"}]})
    left = [busy, ok, ok]

    def answer(request):
        got = left.pop(0)
        if got.status_code == 200:
            clock.sleep(MODEL_S)
        return got
    respx.post(f"{GW}/v1/chat/completions").mock(side_effect=answer)

    def ask(prompt, lane):
        return completion.complete(prompt, model="m", gateway=GW)
    _, cost = methods._serve_best_of(methods.parse("best-of:2:m"), "code", "write x", ask, slots=1)
    # The first sample is a clean pass, so best-of stops there (#807).
    assert cost["calls"] == 1 and cost["wall_s"] == MODEL_S
