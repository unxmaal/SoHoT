"""The agent lane's step cap, case deadline, step timeout, reply budget and padding are our limits, not the candidate's ability (#695)."""
import dataclasses
import json
import re
import types

import httpx
import pytest

from evals import agent_pad
from evals.runners import agent
from evals.runners.agent import AgentRunner
from harness import completion, knobs, paired, reasons
from tests.test_agent_lane import case


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def list_dir():
    return {"content": "", "tool_calls": [{"id": "c0", "type": "function",
                                           "function": {"name": "list_dir", "arguments": "{}"}}]}


def fake_chat(clock, seconds, prefill=None, script=None, seen=None):
    """A model that spends `seconds` per step, honouring the request timeout the way httpx does."""
    script = list(script or [])

    def chat(messages, model, gateway, tools, timeout, max_tokens, sampling):
        if seen is not None:
            seen.append(timeout)
        if seconds > timeout:
            clock.now += timeout
            raise completion.CompletionError(f"timed out after {timeout}s", reasons.TIMEOUT,
                                             ("timeout_s", timeout))
        clock.now += seconds
        turn = script.pop(0) if script else {"message": list_dir()}
        return completion.Completion(turn["message"].get("content") or "", {}, [],
                                     {"ttft_s": prefill, "first_reasoning_s": None,
                                      "prefill_s": prefill}, message=turn["message"],
                                     finish=turn.get("finish", ""))
    return chat


@pytest.fixture
def clock(monkeypatch):
    c = Clock()
    monkeypatch.setattr(agent, "time", types.SimpleNamespace(perf_counter=c))
    return c


def test_a_slow_model_stopped_by_the_case_deadline_is_a_timeout_naming_the_knob(clock):
    seen = []
    r = AgentRunner("http://x", "fake", chat=fake_chat(clock, 250.0, seen=seen)).run(
        case("agent-read-service-port"))
    assert not r.passed
    assert r.failure_class == reasons.TIMEOUT
    assert r.limit == "agent_case_timeout_s>900"
    assert seen[-1] <= 150.0 + 1e-6


def test_the_deadline_holds_inside_a_step_not_only_between_steps(clock):
    started = clock.now
    AgentRunner("http://x", "fake", chat=fake_chat(clock, 250.0)).run(case("agent-read-service-port"))
    assert clock.now - started <= agent.CASE_TIMEOUT_S + 1e-6


def test_a_step_timeout_names_the_agent_step_knob_not_the_text_lanes(clock):
    r = AgentRunner("http://x", "fake", chat=fake_chat(clock, 5000.0)).run(case("agent-read-service-port"))
    assert r.failure_class == reasons.TIMEOUT
    assert r.limit == f"agent_step_timeout_s>{completion.timeout_for(completion.budget('agent')):g}"


def test_prefill_time_does_not_count_against_the_case_deadline(clock):
    answer = {"message": {"content": "Production listens on 8443."}}
    script = [{"message": list_dir()}] * 4 + [answer]
    r = AgentRunner("http://x", "fake", chat=fake_chat(clock, 300.0, prefill=250.0, script=script)).run(
        case("agent-read-service-port"))
    assert json.loads(r.output)["stopped"] == "answered"


def test_the_step_cap_is_a_limit_naming_the_knob(clock):
    c = case("agent-read-service-port")
    r = AgentRunner("http://x", "fake", chat=fake_chat(clock, 1.0)).run(c)
    assert not r.passed
    assert r.limit == "agent_steps_scale>1"
    assert r.metrics["agent_steps"] == c.params["max_steps"]
    assert r.failure_class == reasons.STEP_CAP
    assert reasons.CLASSES[r.failure_class][1] == reasons.LIMIT


def test_a_case_that_names_no_steps_is_a_harness_error_not_a_default(clock):
    c = case("agent-read-service-port")
    c = dataclasses.replace(c, params={k: v for k, v in c.params.items() if k != "max_steps"})
    r = AgentRunner("http://x", "fake", chat=fake_chat(clock, 1.0)).run(c)
    assert r.failure_class == reasons.HARNESS_ERROR


def test_a_step_cut_at_the_reply_budget_is_budget_exhausted(clock):
    cut = {"message": {"content": "", "tool_calls": [{"id": "c0", "type": "function", "function": {
        "name": "write_file", "arguments": "{\"path\": \"x.py\", \"content\": \"def"}}]}, "finish": "length"}
    script = [cut, {"message": {"content": "It listens on 1234."}}]
    r = AgentRunner("http://x", "fake", chat=fake_chat(clock, 1.0, script=script)).run(
        case("agent-read-service-port"))
    assert not r.passed
    assert r.failure_class == reasons.TOKEN_BUDGET_EXHAUSTED
    assert r.limit == "max_tokens.agent>8000"


def test_chat_reports_the_finish_reason(monkeypatch):
    body = {"choices": [{"message": {"content": "x"}, "finish_reason": "length"}], "usage": {}}
    resp = types.SimpleNamespace(status_code=200, text="", json=lambda: body, raise_for_status=lambda: None)
    monkeypatch.setattr(completion, "_post", lambda gateway, payload, timeout: resp)
    assert completion.chat([{"role": "user", "content": "x"}], model="m", gateway="http://x").finish == "length"


def test_limit_stops_are_unjudged_in_a_pair():
    for cls in (reasons.TIMEOUT, reasons.STEP_CAP, reasons.CONTEXT_EXCEEDED):
        assert cls in paired.UNJUDGED


#: GPT-2's byte-level BPE pre-tokenizer, exact for ASCII text like the padding.
_PRETOKEN = re.compile(r"'s|'t|'re|'ve|'m|'ll|'d| ?[A-Za-z]+| ?[0-9]+| ?[^\sA-Za-z0-9]+|\s+(?!\S)|\s+")


def _pieces(text):
    return len(_PRETOKEN.findall(text))


def _total(files):
    return sum(_pieces(t) for t in files.values())


def test_four_chars_per_token_overshoots_a_real_bpe_pre_tokenizer():
    # Evidence, not protection: the estimate is wrong, so the lane must not pad by it (next test and the runner wiring).
    assert _total(agent_pad.padding("agent-long32k-edit-slugify", 32000)) > 32000


def test_padding_is_sized_by_the_counter_it_is_given():
    got = _total(agent_pad.padding("agent-long32k-edit-slugify", 32000, count=_pieces))
    assert abs(got - 32000) <= 32000 * 0.02
    small = agent_pad.padding("agent-long32k-edit-slugify", 32000, count=_pieces)
    assert set(small) <= set(agent_pad.padding("agent-long32k-edit-slugify", 32000))


def test_a_long32k_case_against_a_32k_context_is_unrunnable_not_failed(clock):
    asked = []

    def chat(*a, **kw):
        asked.append(1)
        raise AssertionError("a case that cannot fit must not be sent")
    r = AgentRunner("http://x", "fake", chat=chat, served_ctx=32768).run(case("agent-long32k-edit-slugify"))
    assert not asked
    assert r.failure_class == reasons.CONTEXT_EXCEEDED
    assert reasons.CLASSES[r.failure_class][1] == reasons.LIMIT
    assert r.metrics["agent_ctx"] == 32768


def test_a_server_context_overflow_is_context_exceeded(clock):
    def chat(*a, **kw):
        raise completion.CompletionError("gateway returned HTTP 400: the request exceeds the available context size")
    r = AgentRunner("http://x", "fake", chat=chat, served_ctx=262144).run(case("agent-read-service-port"))
    assert r.failure_class == reasons.CONTEXT_EXCEEDED


def test_the_runner_counts_with_the_served_tokenizer_when_given_one(clock):
    counted = []

    def count(text):
        counted.append(len(text))
        return len(text) // 3
    AgentRunner("http://x", "fake", chat=fake_chat(clock, 1.0, script=[{"message": {"content": "x"}}]),
                count=count).run(case("agent-long16k-fix-median"))
    assert counted


def test_token_counter_asks_llama_server_and_is_none_without_one(monkeypatch):
    calls = []

    def post(url, json, timeout):
        calls.append((url, json))
        return httpx.Response(200, json={"tokens": [1] * len(json["content"].split())},
                              request=httpx.Request("POST", url))
    monkeypatch.setattr(httpx, "post", post)
    count = completion.token_counter("http://h:8082/", "Ornith")
    assert count("a b c") == 3
    assert calls[-1] == ("http://h:8082/tokenize", {"model": "Ornith", "content": "a b c"})

    def missing(url, json, timeout):
        return httpx.Response(404, request=httpx.Request("POST", url))
    monkeypatch.setattr(httpx, "post", missing)
    assert completion.token_counter("http://h:8082", "Ornith") is None


@pytest.mark.parametrize("name, limit", [("agent_steps_scale", "agent_steps_scale"),
                                         ("agent_case_timeout", "agent_case_timeout_s"),
                                         ("agent_step_timeout", "agent_step_timeout_s")])
def test_the_agent_limits_are_registered_knobs(name, limit):
    k = knobs.KNOBS[name]
    assert k.limit == limit and "agent" in k.lanes and k.receipt == "knobs"
    assert name in knobs.UNRECORDED


def test_the_padding_estimate_is_a_registered_knob():
    assert knobs.KNOBS["agent_pad_chars_per_token"].sites == ("evals/agent_pad.py:CHARS_PER_TOKEN",)


def test_the_served_counter_asks_once_and_falls_back_to_the_estimate(monkeypatch):
    asked = []
    monkeypatch.setattr(completion, "token_counter", lambda base, model: asked.append(base))
    count = agent.served_counter("http://h:8082", "Ornith")
    assert not asked
    assert count("abcdefgh") == 8 / agent_pad.CHARS_PER_TOKEN and count("abcd") == 1
    assert asked == ["http://h:8082"]


def test_the_lane_runner_pads_by_the_served_tokenizer(monkeypatch):
    from evals import run
    from harness import context, serving
    where = types.SimpleNamespace(base="http://h:8082", model="Ornith", sampling=None)
    monkeypatch.setattr(serving, "route", lambda candidate, gateway: where)
    monkeypatch.setattr(context, "served_ctx", lambda candidate: 32768)
    monkeypatch.setattr(completion, "token_counter", lambda base, model: _pieces)
    r = run._agent_runner("llamacpp:Ornith", "http://gw")
    assert r.count is not None and r.count("a b c") == _pieces("a b c")


def test_the_step_scale_moves_every_shipped_cases_cap(clock, monkeypatch):
    monkeypatch.setattr(agent, "MAX_STEPS_SCALE", 2.0)
    c = case("agent-read-service-port")
    r = AgentRunner("http://x", "fake", chat=fake_chat(clock, 1.0)).run(c)
    assert r.metrics["agent_steps"] == 2 * c.params["max_steps"]
    assert r.limit == "agent_steps_scale>2"


def test_every_shipped_agent_case_names_its_steps():
    from tests.test_agent_lane import agent_cases
    assert all(int(c.params["max_steps"]) > 0 for c in agent_cases())


def test_a_bigger_reply_budget_stretches_the_case_deadline(clock):
    r = AgentRunner("http://x", "fake", max_tokens=4 * completion.budget("agent"),
                    chat=fake_chat(clock, 500.0)).run(case("agent-read-service-port"))
    assert r.failure_class == reasons.TIMEOUT
    assert r.limit == f"agent_case_timeout_s>{4 * agent.CASE_TIMEOUT_S:g}"


def test_a_late_steps_own_prefill_is_not_charged_to_the_case(clock):
    c = case("agent-read-service-port")
    c = dataclasses.replace(c, params={**c.params, "timeout_s": 1})
    runner = AgentRunner("http://x", "fake")
    seconds = runner.step_seconds() - 20
    script = [{"message": list_dir()}] * 4 + [{"message": {"content": "Production listens on 8443."}}]
    runner.chat = fake_chat(clock, seconds, prefill=seconds - 10, script=script)
    r = runner.run(c)
    assert json.loads(r.output)["stopped"] == "answered", r.limit


def test_an_unrunnable_case_names_the_served_context(clock):
    r = AgentRunner("http://x", "fake", chat=None, served_ctx=32768).run(case("agent-long32k-edit-slugify"))
    assert r.limit == "served_ctx>32768"


def test_a_server_overflow_names_the_served_context(clock):
    def chat(*a, **kw):
        raise completion.CompletionError("gateway returned HTTP 400: the request exceeds the available context size")
    r = AgentRunner("http://x", "fake", chat=chat, served_ctx=262144).run(case("agent-read-service-port"))
    assert r.limit == "served_ctx>262144"


def test_a_load_fault_that_mentions_n_ctx_is_not_an_overflow(clock):
    def chat(*a, **kw):
        raise completion.CompletionError("gateway returned HTTP 500: failed to load model: invalid n_ctx 0",
                                         reasons.CRASHED)
    r = AgentRunner("http://x", "fake", chat=chat).run(case("agent-read-service-port"))
    assert r.failure_class == reasons.CRASHED


def test_a_tokenizer_that_fails_after_the_probe_falls_back_to_the_estimate(monkeypatch):
    def served(text):
        raise httpx.ConnectError("gone")
    monkeypatch.setattr(completion, "token_counter", lambda base, model: served)
    count = agent.served_counter("http://h:8082", "Ornith")
    assert count("abcdefgh") == agent_pad.estimate("abcdefgh")
    assert count("abcd") == agent_pad.estimate("abcd")
