"""A refusal by the runtime or by our request shape is not a verdict on the
model. #305."""
import json

import httpx
import pytest
import respx

from harness import completion as comp
from harness import memory_store as ms
from harness import screen

GW = "http://127.0.0.1:4000"
URL = f"{GW}/v1/chat/completions"


def reply(text):
    return httpx.Response(200, json={"choices": [{"message": {"content": text}}]})


# --- chat templates that refuse a system role --------------------------------

@pytest.mark.parametrize("body", [
    '{"error": "System role not supported"}',
    '{"error": "Conversation roles must alternate user/assistant/user/assistant/..."}',
])
@respx.mock
def test_a_template_that_refuses_a_system_role_gets_it_in_the_user_turn(body):
    route = respx.post(URL).mock(side_effect=[httpx.Response(404, text=body),
                                              reply("ok")])
    assert comp.complete("hi", model="m", gateway=GW, modality="code") == "ok"
    retry = json.loads(route.calls[1].request.content)["messages"]
    assert [m["role"] for m in retry] == ["user"]
    assert retry[0]["content"].startswith(comp.SYSTEM["code"])
    assert retry[0]["content"].endswith("hi")


@respx.mock
def test_any_other_refusal_is_not_retried():
    route = respx.post(URL).mock(
        return_value=httpx.Response(400, text="model not in config"))
    with pytest.raises(comp.CompletionError):
        comp.complete("hi", model="m", gateway=GW)
    assert route.call_count == 1


# --- what counts as an architecture gap --------------------------------------

def test_a_chat_template_refusal_is_not_an_architecture_gap():
    assert not screen.is_architecture_gap(
        'gateway returned HTTP 404: {"error": "System role not supported"}')
    assert screen.is_architecture_gap(
        'gateway returned HTTP 404: {"error": "Model type gpt_x not supported."}')


def _summary(cand, failure):
    return {cand: {"passed": 0, "failures": [failure]}}


def test_llama_server_failing_to_load_waits_on_a_newer_build(monkeypatch):
    monkeypatch.setattr(screen, "_llamacpp_build", lambda: "10809")
    cand = "llamacpp:K2-Horizon-7B-Q4_K_M"
    fail = ('chunk-bytes: gateway returned HTTP 500: {"error":{"code":500,'
            '"message":"model name=K2-Horizon-7B-Q4_K_M failed to load"}}')
    got, why = screen.outcome(0, _summary(cand, fail), candidate=cand)
    assert got == "declined", why
    assert screen.load_until(cand) == "version:llama.cpp>10809"


def test_an_mlx_candidate_still_waits_on_mlx_lm():
    assert screen.load_until("org/x").startswith("version:mlx-lm>")


def test_a_500_from_mlx_is_not_read_as_a_llama_cpp_load_failure():
    cand = "org/x"
    fail = 'gateway returned HTTP 500: {"error": "failed to load"}'
    assert screen.outcome(0, _summary(cand, fail), candidate=cand)[0] == "broken"


def test_a_newer_llama_cpp_build_meets_the_condition():
    assert ms.until_met("version:llama.cpp>10809",
                        {"versions": {"llama.cpp": "10810"}})
    assert not ms.until_met("version:llama.cpp>10809",
                            {"versions": {"llama.cpp": "10809"}})
