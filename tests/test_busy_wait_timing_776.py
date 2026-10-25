"""#776: a request that waits out a busy serving machine does not count the wait as model time."""
import dataclasses
import json
import threading
import types

import httpx
import pytest
import respx

from evals import craft
from evals.core import Case
from evals.runners import agent, repo_repair
from evals.runners import craft as craft_runner
from evals.runners.agent import AgentRunner
from evals.runners.method import BestOfRunner
from evals.runners.repair import RepairRunner
from evals.runners.text import CompletionRunner
from harness import batch, completion, throughput
from tests.test_agent_lane import case as agent_case
from tests.test_agent_limits import Clock, fake_chat, list_dir
from tests.test_craft_lane_1209 import SVG as RUN_BOOK
from tests.test_craft_lane_1209 import _calls, fake, scripted  # noqa: F401
from tests.test_craft_lane_1209 import case as craft_case
from tests.test_craft_lane_1209 import runner as craft_runner_of
from tests.test_repo_lane import DARWIN, upstream  # noqa: F401
from tests.test_repo_repair_890 import _call
from tests.test_repo_repair_890 import _runner as _repair_runner

GW = "http://127.0.0.1:4000"
URL = f"{GW}/v1/chat/completions"
POLL = 0.5
SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 2 2"><circle cx="1" cy="1" r="1"/></svg>'


@pytest.fixture(autouse=True)
def _poll(monkeypatch):
    monkeypatch.setattr(batch, "BUSY_POLL_S", POLL)


def busy():
    return httpx.Response(503, json={"error": {"message": f"{batch.BUSY} (batch b-1); retry once it finishes"}})


def ok(content=SVG, tokens=200):
    return httpx.Response(200, json={"choices": [{"message": {"content": content}, "finish_reason": "stop"}],
                                     "usage": {"prompt_tokens": 10, "completion_tokens": tokens}})


def replies(*seq):
    """A gateway that answers `seq` in order, whichever thread asks."""
    left, lock = list(seq), threading.Lock()

    def answer(request):
        with lock:
            return left.pop(0)()
    return answer


def svg_case():
    return Case(id="circle", modality="svg", prompt="Draw a red circle.", assertions={"min_shapes": 1})


@respx.mock
def test_a_completion_reports_the_busy_wait_it_sat_through():
    respx.post(URL).mock(side_effect=replies(busy, busy, ok))
    got = completion.complete_full("hi", model="sohot-code", gateway=GW)
    assert got.timing["busy_wait_s"] >= 2 * POLL - 0.05


@respx.mock
def test_a_chat_turn_reports_the_busy_wait_it_sat_through():
    respx.post(URL).mock(side_effect=replies(busy, ok))
    got = completion.chat([{"role": "user", "content": "hi"}], model="sohot-code", gateway=GW, stream=False)
    assert got.timing["busy_wait_s"] >= POLL - 0.05


@respx.mock
def test_a_completion_admitted_at_once_reports_no_busy_wait():
    respx.post(URL).mock(side_effect=replies(ok))
    assert "busy_wait_s" not in completion.complete_full("hi", model="sohot-code", gateway=GW).timing


@respx.mock
def test_an_eval_row_leaves_the_busy_wait_out_of_its_seconds_and_throughput():
    respx.post(URL).mock(side_effect=replies(busy, busy, ok))
    r = CompletionRunner(GW, "local-mid").run(svg_case())
    assert r.passed
    assert r.metrics["busy_wait_s"] >= 2 * POLL - 0.05
    assert r.seconds < POLL
    assert r.metrics["tokens_per_s"] > 200 / POLL


@respx.mock
def test_a_best_of_sample_that_waits_in_a_pool_thread_is_left_out_of_the_row():
    # The first sample fails, so the next two run together in a second wave and both wait once.
    respx.post(URL).mock(side_effect=replies(lambda: ok("I cannot draw."), busy, busy, ok, ok))
    r = BestOfRunner(CompletionRunner(GW, "local-mid"), 3, slots=3).run(svg_case())
    assert r.passed and r.metrics["method_calls"] == 3
    assert r.metrics["busy_wait_s"] >= POLL - 0.05
    assert r.seconds < POLL


def test_the_agent_case_deadline_is_not_spent_by_a_busy_wait(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(agent, "time", types.SimpleNamespace(perf_counter=clock))
    inner = fake_chat(clock, 300.0, script=[{"message": list_dir()}] * 4
                      + [{"message": {"content": "Production listens on 8443."}}])

    def chat(*a, **k):
        got = inner(*a, **k)
        got.timing["busy_wait_s"] = 250.0
        return got
    r = AgentRunner("http://x", "fake", chat=chat).run(agent_case("agent-read-service-port"))
    out = json.loads(r.output)
    assert out["stopped"] == "answered"
    assert {s["seconds"] for s in out["steps"]} == {50.0}


@respx.mock
def test_a_throughput_level_leaves_the_busy_wait_out_of_its_latency_and_rate():
    respx.post(URL).mock(side_effect=replies(ok, busy, busy, ok))
    got = throughput.sweep("sohot-code", ["t"], levels=(1,), post=throughput._gateway_post(GW, 30.0))
    level = got[0]
    assert level["errors"] == 0
    assert level["busy_wait_s"] >= 2 * POLL - 0.05
    assert level["p50_s"] < POLL and level["wall_s"] < POLL


def _waiting(chat, clock, seconds, waited):
    """`chat`, but each turn takes `seconds` on `clock`, `waited` of them out a busy serving machine."""
    def turn(*a, **k):
        clock.now += seconds
        got = chat(*a, **k)
        got.timing["busy_wait_s"] = waited
        return got
    return turn


def test_a_craft_case_deadline_is_not_spent_by_a_busy_wait(fake, monkeypatch):
    clock = Clock()
    monkeypatch.setattr(agent, "time", types.SimpleNamespace(perf_counter=clock))
    monkeypatch.setattr(craft_runner, "time", types.SimpleNamespace(perf_counter=clock))
    c = craft_case(RUN_BOOK)
    c = dataclasses.replace(c, params={**c.params, "timeout_s": 10})
    steps = craft.reference_steps(c)
    turns = [{"content": "", "tool_calls": _calls(steps[:1])}, {"content": "", "tool_calls": _calls(steps[1:2])},
             {"content": "built"}]
    runner = craft_runner_of(_waiting(scripted(turns), clock, 6.0, 5.5))
    runner.step_seconds = lambda: 1.0
    record = json.loads(runner.run(c).output)
    assert record["stopped"] == "answered"
    assert record["metrics"]["agent_wall_s"] < 3 * (6.0 - 5.5) + 1.0


@DARWIN
def test_a_repo_repair_case_deadline_and_wall_leave_out_a_busy_wait(upstream, monkeypatch):
    clock = Clock()
    monkeypatch.setattr(agent, "time", types.SimpleNamespace(perf_counter=clock))
    monkeypatch.setattr(repo_repair, "time", types.SimpleNamespace(perf_counter=clock))
    monkeypatch.setattr(repo_repair, "CASE_TIMEOUT_S", 10.0)
    r = _repair_runner([_call("list_files"), _call("list_files"), _call("finish", summary="nothing")])
    r.chat = _waiting(r.chat, clock, 6.0, 5.5)
    row = r.run(upstream)
    assert json.loads(row.output)["stopped"] == "finished"
    assert row.seconds < 3 * (6.0 - 5.5) + 1.0


@respx.mock
def test_a_repair_loop_leaves_the_busy_wait_out_of_its_throughput():
    respx.post(URL).mock(side_effect=replies(busy, ok))
    r = RepairRunner(GW, "local-large", attempts=1).run(svg_case())
    assert r.metrics["busy_wait_s"] >= POLL - 0.05
    assert r.metrics["tokens_per_s"] > 200 / POLL
