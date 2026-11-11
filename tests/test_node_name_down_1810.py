"""A server error for one name skips that name on the node; a node that did not answer skips every name. #1810."""
import asyncio
import importlib.util
import socket
import threading
import time
import types
from pathlib import Path

import pytest

from harness import gateway, node_reach, nodes

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("served_model_1810", REPO / "gateway" / "served_model.py")
served = importlib.util.module_from_spec(spec)
spec.loader.exec_module(served)

A, B = "Qwen2.5-7B-Instruct-Q4_K_M", "imajev-4b-Q8_0"
BASE = "model_list:\n" + "".join(f"""  - model_name: {m}
    engine: llama-server
    litellm_params:
      model: openai/{m}
      api_base: http://127.0.0.1:8082/v1
      api_key: not-needed
""" for m in (A, B))
LOCAL = "http://127.0.0.1:8082/v1"
COOLDOWN = 30.0


class APIStatusError(Exception):
    pass


class InternalServerError(APIStatusError):
    status_code = 500


class APIConnectionError(Exception):
    status_code = 500


class APITimeoutError(APIConnectionError):
    pass


class Timeout(APITimeoutError):
    status_code = 408


class TransportError(Exception):
    pass


class RemoteProtocolError(TransportError):
    pass


def _dropped():
    """What LiteLLM 1.100.0 hands over for a node that closed the connection: a 500 caused by a transport error."""
    try:
        try:
            raise RemoteProtocolError("Server disconnected without sending a response.")
        except RemoteProtocolError:
            raise InternalServerError("litellm.InternalServerError: OpenAIException - Server disconnected")
    except InternalServerError as e:
        return e


class Response:
    def __init__(self, base):
        self._hidden_params = {"api_base": base}


@pytest.fixture
def gw(tmp_path, monkeypatch):
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen(64)

    def accept():
        try:
            while True:
                s.accept()[0].close()
        except OSError:
            return
    threading.Thread(target=accept, daemon=True).start()
    monkeypatch.setenv("LOCALHARNESS_HOME", str(tmp_path / "home"))
    cfg = tmp_path / "config.yaml"
    cfg.write_text(BASE, encoding="utf-8")
    base = f"http://127.0.0.1:{s.getsockname()[1]}/v1"
    gateway.write_served(cfg, defaults={}, nodes=nodes.parse({"nodes": [{
        "name": "styx", "api_base": base, "engine": "llama-server", "models": [A, B],
        "key": "keychain:svc/acct", "cooldown": COOLDOWN}]}))
    monkeypatch.setenv("GATEWAY_CONFIG", str(cfg))
    clock = [1000.0]
    monkeypatch.setattr(served, "time", types.SimpleNamespace(monotonic=lambda: clock[0], time=time.time))
    for cache in (served._REACH, served._REACHING, served._ROUTED, served._NAME_DOWN, served._FAULT):
        cache.clear()
    yield types.SimpleNamespace(clock=clock, node=base, log=tmp_path / "home" / "nodes" / "reach.jsonl")
    s.close()


def _send(model):
    data = {"model": model}
    return asyncio.run(served.proxy_handler_instance.async_pre_call_hook(None, None, data, "acompletion"))["model"]


def _fails_on_the_node(model, exc):
    """A request sent to the node that LiteLLM fell back from, with the exception it fell back on."""
    data = {"model": model}
    assert asyncio.run(served.proxy_handler_instance.async_pre_call_hook(None, None, data, "acompletion")) \
        ["model"] == model, "the node was not tried"
    handler = served.proxy_handler_instance
    asyncio.run(handler.log_success_fallback_event(original_model_group=model, kwargs={}, original_exception=exc))
    got = asyncio.run(handler.async_post_call_response_headers_hook(
        data=data, user_api_key_dict=None, response=Response(LOCAL)))
    assert got["x-sohot-fallback"] == "styx"


def test_a_server_error_for_one_name_leaves_the_other_names_on_the_node(gw):
    _fails_on_the_node(A, InternalServerError("boom"))
    assert _send(B) == B, "a 500 for one name took the node's other name out of routing"
    assert _send(A) == A + nodes.LOCAL_SUFFIX, "the name that failed was sent to the node again at once"
    rows = node_reach.read(gw.log)
    assert [(r["node"], r.get("model"), r["state"]) for r in rows] == [("styx", A, node_reach.DOWN)]
    assert rows[0]["why"] == f"{A} answered InternalServerError 500"


def test_the_failed_name_returns_after_its_cooldown_and_the_log_says_so(gw):
    _fails_on_the_node(A, InternalServerError("boom"))
    gw.clock[0] += COOLDOWN - 1
    assert _send(A) == A + nodes.LOCAL_SUFFIX
    gw.clock[0] += 1
    assert _send(A) == A
    got = [(r.get("model"), r["state"]) for r in node_reach.read(gw.log)]
    assert got == [(A, node_reach.DOWN), (A, node_reach.UP)]
    assert [n["node"] for n in node_reach.summary(0, time.time() + 1, gw.log)] == [f"styx/{A}"]


@pytest.mark.parametrize("exc", [APIConnectionError("refused"), Timeout("slow"), _dropped(),
                                 InternalServerError("OpenAIException - Connection error.")],
                         ids=["connect", "timeout", "dropped", "connection-error-500"])
def test_a_node_that_did_not_answer_takes_every_name_out(gw, exc):
    _fails_on_the_node(A, exc)
    assert _send(B) == B + nodes.LOCAL_SUFFIX
    assert _send(A) == A + nodes.LOCAL_SUFFIX
    rows = node_reach.read(gw.log)
    assert [(r["node"], r.get("model"), r["state"]) for r in rows] == [("styx", None, node_reach.DOWN)]
    assert rows[0]["why"].startswith(f"{A} fell back: {type(exc).__name__} {exc.status_code}")


def test_a_stale_reason_left_by_an_earlier_request_is_not_used(gw):
    asyncio.run(served.proxy_handler_instance.log_failure_fallback_event(
        original_model_group=A, kwargs={}, original_exception=InternalServerError("x")))
    gw.clock[0] += served.FAULT_TTL_S + 1
    data = {"model": A}
    asyncio.run(served.proxy_handler_instance.async_post_call_response_headers_hook(
        data=data, user_api_key_dict=None, response=Response(LOCAL)))
    assert _send(B) == B + nodes.LOCAL_SUFFIX


def test_a_fallback_with_no_reason_still_takes_the_node_out(gw):
    data = {"model": A}
    asyncio.run(served.proxy_handler_instance.async_post_call_response_headers_hook(
        data=data, user_api_key_dict=None, response=Response(LOCAL)))
    assert _send(B) == B + nodes.LOCAL_SUFFIX


@pytest.mark.parametrize("exc,kind", [
    (InternalServerError("x"), served.NAME), (APIConnectionError("x"), served.NODE), (Timeout("x"), served.NODE),
    (ValueError("x"), served.NODE), (types.SimpleNamespace(status_code=503), served.NAME),
    (types.SimpleNamespace(status_code=401), served.NODE), (types.SimpleNamespace(status_code="bad"), served.NODE)])
def test_fault_names_the_node_unless_it_answered_a_server_error(exc, kind):
    assert served.fault(exc)[0] == kind
