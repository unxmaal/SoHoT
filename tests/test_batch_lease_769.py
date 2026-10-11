"""#769: the batch lock lives with the serving machine, carried by an x-sohot-batch header."""
import asyncio
import importlib.util
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx
import pytest
import respx

from harness import completion, exclusive, reasons

REPO = Path(__file__).resolve().parent.parent
#: A gateway on another machine: an address no interface here holds.
REMOTE = "http://192.0.2.10:4000"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv(exclusive.HELD_ENV, raising=False)
    monkeypatch.delenv("SOHOT_BATCH", raising=False)
    monkeypatch.delenv(completion.GATEWAY_ENV, raising=False)


def _gateway():
    spec = importlib.util.spec_from_file_location("served_model_769", REPO / "gateway" / "served_model.py")
    served = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(served)
    return served.proxy_handler_instance.async_pre_call_hook


def _request(batch: str) -> dict:
    return {"model": "sohot-code", "proxy_server_request": {"headers": {"x-sohot-batch": batch}}}


def _short_ttl(monkeypatch, ttl: float) -> None:
    from harness import batch
    monkeypatch.setattr(batch, "TTL_S", ttl)


def test_a_remote_eval_is_refused_while_a_local_eval_holds_the_serving_machine():
    hook = _gateway()
    with exclusive.held("eval"):
        with pytest.raises(Exception) as got:
            asyncio.run(hook(None, None, _request("a-remote-eval"), "acompletion"))
    assert getattr(got.value, "status_code", None) == 503
    detail = str(getattr(got.value, "detail", got.value))
    assert reasons.CLASSES[reasons.classify(f"gateway returned HTTP 503: {detail}")][1] == reasons.HARNESS


def test_a_local_eval_waits_while_a_remote_eval_holds_the_serving_machine(monkeypatch):
    _short_ttl(monkeypatch, 1.5)
    hook = _gateway()
    asyncio.run(hook(None, None, _request("a-remote-eval"), "acompletion"))
    said, out = [], {}

    def local_eval():
        start = time.monotonic()
        with exclusive.held("eval", announce=said.append, poll=0.05) as waited:
            out["waited"], out["after"] = waited, time.monotonic() - start

    t = threading.Thread(target=local_eval)
    t.start()
    t.join(timeout=10)
    assert not t.is_alive()
    assert out["waited"] and out["after"] >= 1.0, out
    assert said and "a-remote-eval" in said[0]


def test_a_local_evals_own_requests_pass_its_own_lease():
    hook = _gateway()
    with exclusive.held("eval"):
        mine = os.environ["SOHOT_BATCH"]
        assert asyncio.run(hook(None, None, _request(mine), "acompletion"))["model"] == "sohot-code"


def test_a_request_with_no_batch_is_never_refused_for_one():
    hook = _gateway()
    with exclusive.held("eval"):
        assert asyncio.run(hook(None, None, {"model": "sohot-code"}, "acompletion"))["model"] == "sohot-code"


_IMAGE_JOB = """
import sys, time
from harness import exclusive
start = time.monotonic()
with exclusive.held("image", poll=0.05):
    print(round(time.monotonic() - start, 2), flush=True)
"""


def _image_job_waits_s() -> float:
    env = {k: v for k, v in os.environ.items() if k not in (exclusive.HELD_ENV, "SOHOT_BATCH")}
    env.pop(completion.GATEWAY_ENV, None)
    proc = subprocess.run([sys.executable, "-c", _IMAGE_JOB], cwd=REPO, env=env,
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    return float(proc.stdout.strip())


def _blocked(seconds: float) -> bool:
    def run():
        out["s"] = _image_job_waits_s()
    out = {}
    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(timeout=seconds)
    return t.is_alive()


def test_a_remote_eval_does_not_block_this_machines_image_job(monkeypatch):
    monkeypatch.setenv(completion.GATEWAY_ENV, REMOTE)
    with exclusive.held("eval"):
        assert not _blocked(20.0)


def test_a_local_eval_still_blocks_this_machines_image_job():
    with exclusive.held("eval"):
        assert _blocked(3.0)


@respx.mock
def test_a_remote_eval_names_its_batch_on_every_request(monkeypatch):
    monkeypatch.setenv(completion.GATEWAY_ENV, REMOTE)
    route = respx.post(f"{REMOTE}/v1/chat/completions").mock(return_value=httpx.Response(
        200, json={"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}))
    with exclusive.held("eval"):
        completion.complete("hi", model="sohot-code")
        completion.chat([{"role": "user", "content": "hi"}], model="sohot-code", stream=False)
    sent = {c.request.headers.get("x-sohot-batch") for c in route.calls}
    assert len(route.calls) == 2 and len(sent) == 1 and None not in sent and "" not in sent


@respx.mock
def test_a_busy_gateway_is_waited_out(monkeypatch):
    from harness import batch
    monkeypatch.setattr(batch, "BUSY_POLL_S", 0.01)
    gw = "http://127.0.0.1:4000"
    busy = httpx.Response(503, json={"error": {"message": f"{batch.BUSY} (batch b-1); retry once it finishes"}})
    ok = httpx.Response(200, json={"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]})
    respx.post(f"{gw}/v1/chat/completions").mock(side_effect=[busy, busy, ok])
    assert completion.complete("hi", model="sohot-code", gateway=gw) == "ok"


@respx.mock
def test_a_busy_gateway_past_the_clients_deadline_is_charged_to_the_harness(monkeypatch):
    from harness import batch
    monkeypatch.setattr(batch, "BUSY_POLL_S", 0.01)
    monkeypatch.setattr(batch, "BUSY_WAIT_S", 0.1)
    gw = "http://127.0.0.1:4000"
    respx.post(f"{gw}/v1/chat/completions").mock(return_value=httpx.Response(
        503, json={"error": {"message": f"{batch.BUSY} (batch b-1); retry once it finishes"}}))
    with pytest.raises(completion.CompletionError) as got:
        completion.complete("hi", model="sohot-code", gateway=gw)
    assert got.value.failure_class == reasons.REFUSED_BY_GATEWAY
    assert reasons.classify(str(got.value)) == reasons.REFUSED_BY_GATEWAY
    assert reasons.CLASSES[reasons.classify(str(got.value))][1] == reasons.HARNESS


def test_a_batch_request_still_in_flight_keeps_the_serving_machine(monkeypatch):
    _short_ttl(monkeypatch, 0.3)
    hook = _gateway()

    async def scenario():
        await hook(None, None, {**_request("a-long-reply"), "litellm_call_id": "c1"}, "acompletion")
        await asyncio.sleep(1.0)
        with pytest.raises(Exception) as got:
            await hook(None, None, _request("another"), "acompletion")
        return got.value

    assert getattr(asyncio.run(scenario()), "status_code", None) == 503


def test_chaos_does_not_start_while_a_remote_batch_holds_this_machine():
    hook = _gateway()
    asyncio.run(hook(None, None, _request("a-remote-eval"), "acompletion"))
    with exclusive.try_held("chaos") as got:
        assert got is False
