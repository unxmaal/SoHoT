"""#1231: a batch's gateway lease ends with the batch, so the next local batch is not refused for TTL_S."""
import asyncio
import importlib.util
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from harness import batch, completion, exclusive
from harness import memory_store as ms

REPO = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv(exclusive.HELD_ENV, raising=False)
    monkeypatch.delenv(batch.ENV, raising=False)
    monkeypatch.delenv(completion.GATEWAY_ENV, raising=False)


def _served():
    spec = importlib.util.spec_from_file_location("served_model_1231", REPO / "gateway" / "served_model.py")
    served = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(served)
    return served


def _request(batch_id: str, host: str = "", call: str = "") -> dict:
    headers = {batch.HEADER: batch_id, **({"host": host} if host else {})}
    return {"model": "sohot-code", "proxy_server_request": {"headers": headers},
            **({"litellm_call_id": call} if call else {})}


def _holder(deployment: str) -> dict:
    from harness import lease
    conn = ms.connect()
    try:
        return lease.holder(conn, batch.name(deployment))
    finally:
        conn.close()


def _ended_pid() -> int:
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    return proc.pid


def _ended_batch() -> str:
    return f"{socket.gethostname()}-{_ended_pid()}-abc123"


def test_a_released_lease_is_not_taken_back_by_the_finished_hook():
    served = _served()
    hook = served.proxy_handler_instance
    deployment = served.serving_machine("sohot-code")

    async def scenario():
        await hook.async_pre_call_hook(None, None, _request("b-1", call="c1"), "acompletion")
        conn = ms.connect()
        try:
            assert batch.let_go(conn, deployment, "b-1")
        finally:
            conn.close()
        await hook.async_log_success_event({"litellm_call_id": "c1"}, None, None, None)

    asyncio.run(scenario())
    assert _holder(deployment) == {}


def test_an_ended_batch_holds_no_lease_on_a_node_it_used():
    with exclusive.held("eval"):
        mine = batch.current()
        conn = ms.connect()
        try:
            assert batch.claim(conn, "node:n1", mine) == {}
        finally:
            conn.close()
    assert _holder("node:n1") == {}


def test_a_gateway_lease_of_an_ended_local_batch_does_not_refuse_the_next_batch():
    hook = _served().proxy_handler_instance.async_pre_call_hook
    asyncio.run(hook(None, None, _request(_ended_batch(), host="127.0.0.1:4000"), "acompletion"))
    got = asyncio.run(hook(None, None, _request("the-next", host="127.0.0.1:4000"), "acompletion"))
    assert got["model"] == "sohot-code"


def test_a_remote_batchs_lease_is_kept_until_it_expires():
    hook = _served().proxy_handler_instance.async_pre_call_hook
    asyncio.run(hook(None, None, _request(_ended_batch(), host="192.0.2.10:4000"), "acompletion"))
    with pytest.raises(Exception) as got:
        asyncio.run(hook(None, None, _request("the-next", host="127.0.0.1:4000"), "acompletion"))
    assert getattr(got.value, "status_code", None) == 503


def test_a_live_local_batchs_lease_is_kept():
    hook = _served().proxy_handler_instance.async_pre_call_hook
    live = f"{socket.gethostname()}-{os.getpid()}-abc123"
    asyncio.run(hook(None, None, _request(live, host="127.0.0.1:4000"), "acompletion"))
    with pytest.raises(Exception) as got:
        asyncio.run(hook(None, None, _request("the-next", host="127.0.0.1:4000"), "acompletion"))
    assert getattr(got.value, "status_code", None) == 503


def test_a_child_of_a_lock_holder_sends_the_holders_batch_id():
    child = "from harness import batch, exclusive\nwith exclusive.held('eval'):\n    print(batch.current())\n"
    with exclusive.held("eval"):
        mine = batch.current()
        out = subprocess.run([sys.executable, "-c", child], cwd=REPO, capture_output=True, text=True,
                             encoding="utf-8", timeout=120)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == mine


def test_a_refusal_names_the_refused_batch():
    hook = _served().proxy_handler_instance.async_pre_call_hook
    asyncio.run(hook(None, None, _request("the-holder"), "acompletion"))
    with pytest.raises(Exception) as got:
        asyncio.run(hook(None, None, _request("the-refused"), "acompletion"))
    detail = str(getattr(got.value, "detail", got.value))
    assert batch.BUSY in detail and "the-holder" in detail and "the-refused" in detail
