"""#776: a delegation's reported seconds leave out a wait for another batch on the serving machine."""
import types

import httpx
import pytest
import respx

from harness import batch, completion, delegate, methods
from tests.test_mcp_delegate import fake  # noqa: F401

POLL = 0.5
GW = "http://127.0.0.1:4000"


@pytest.fixture(autouse=True)
def _poll(monkeypatch):
    monkeypatch.setattr(batch, "BUSY_POLL_S", POLL)


def test_a_delegation_leaves_the_busy_wait_out_of_its_seconds(fake, monkeypatch):
    real, sent = completion._send, []

    def send(*a, **k):
        sent.append(1)
        return types.SimpleNamespace(status_code=503, text=batch.BUSY) if len(sent) == 1 else real(*a, **k)
    monkeypatch.setattr(completion, "_send", send)
    got = delegate.complete("code", "write add")
    assert len(sent) == 2
    assert got["busy_wait_s"] >= POLL - 0.05
    assert got["seconds"] < POLL


@respx.mock
def test_a_best_of_delegation_leaves_the_busy_wait_out_of_its_wall():
    busy = httpx.Response(503, json={"error": {"message": f"{batch.BUSY} (batch b-1)"}})
    ok = httpx.Response(200, json={"choices": [{"message": {"content": "x = 1"}, "finish_reason": "stop"}]})
    respx.post(f"{GW}/v1/chat/completions").mock(side_effect=[busy, ok, ok])

    def ask(prompt, lane):
        return completion.complete(prompt, model="m", gateway=GW)
    _, cost = methods._serve_best_of(methods.parse("best-of:2:m"), "code", "write x", ask, slots=1)
    assert cost["wall_s"] < POLL
