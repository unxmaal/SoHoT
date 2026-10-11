"""A cold load or an idle sleep is never graded as the candidate being slow (#694)."""
import subprocess
from pathlib import Path

import pytest

from evals.core import Case, Receipt, comparable
from evals.runners.base import BaseRunner, RunnerError
from evals.runners.text import CompletionRunner
from harness import completion, delegate, gateway, knobs, reasons, router, serving
from tests.test_context_store import _serve
from tests.test_mcp_delegate import fake  # noqa: F401
from tests.test_router_swaps import OURS, FakeRouter, _run, quiet_receipt  # noqa: F401

REPO = Path(__file__).resolve().parents[1]
#: The longest a request may need: the slowest load the knobs allow, then the largest reply at the slowest decode.
CEILING = max(knobs.KNOBS["load_timeout"].values) + completion.timeout_for(max(knobs.KNOBS["reply_budget"].values))


class LoadsOnFirst(BaseRunner):
    """Its first request loads the model and overruns the case timeout; a warm-up pays for it instead."""

    def __init__(self):
        self.candidate = self.spec = "org/x"
        self.warmed = 0
        self.loaded = False

    def warm(self):
        self.warmed += 1
        self.loaded = True

    def generate(self, case):
        if not self.loaded:
            self.loaded = True
            raise RunnerError("timed out after 180s", failure_class=reasons.TIMEOUT, limit="timeout_s>180")
        return "", 0


def test_a_run_without_screen_warms_the_candidate_before_its_first_case(tmp_path, monkeypatch, quiet_receipt):  # noqa: F811
    runner = LoadsOnFirst()
    data = _run(tmp_path, monkeypatch, runner, "")
    assert runner.warmed == 1
    assert not [r for r in data["rows"] if r.get("failure_class") == reasons.TIMEOUT]


def test_a_cold_case_that_times_out_is_charged_to_the_load_not_the_request(monkeypatch):
    seen = []

    def slow(*a, **k):
        seen.append(k["timeout"])
        raise completion.CompletionError("timed out", reasons.TIMEOUT, ("timeout_s", k["timeout"]))
    monkeypatch.setattr(completion, "complete_full", slow)
    case = Case(id="add", modality="code", prompt="Write add(a, b).", assertions={"checks": ["add(2, 3) == 5"]})
    r = CompletionRunner("http://gw.test", "m")
    r.load_timeout = 900.0
    row = r.run(case)
    warm = max(r.timeout, completion.timeout_for(r.budget(case)))
    assert seen == [warm + 900.0]
    assert row.failure_class == reasons.TIMEOUT and row.limit == "load_timeout_s>900"
    r.answered = True
    assert r.run(case).limit == f"timeout_s>{warm:g}" and seen[-1] == warm


def test_a_model_that_slept_and_woke_between_cases_is_a_swap_and_the_run_is_not_ranked():
    fake_router = FakeRouter(**{OURS: "loaded"})
    w = router.Watch(OURS, get=fake_router.get)
    w.look("a", "end")
    fake_router.models[OURS] = "sleeping"
    w.look("b", "start")
    fake_router.models[OURS] = "loaded"
    w.look("b", "end")
    assert [s["status"] for s in w.swaps] == ["sleeping"]
    rec = Receipt(modality="code", case_ids=("a", "b"), repeat=1, sampling={}, gateway="http://gw.test",
                  router_swaps={"llamacpp:" + OURS: w.swaps})
    assert not comparable(rec, rec)[0]


@pytest.mark.parametrize("after", ["absent", "unloaded", "loading"])
def test_a_model_that_slept_then_was_evicted_is_recorded_as_the_eviction(after):
    fake_router = FakeRouter(**{OURS: "loaded"})
    w = router.Watch(OURS, get=fake_router.get)
    w.look("a", "end")
    fake_router.models[OURS] = "sleeping"
    w.look("b", "start")
    if after == "absent":
        del fake_router.models[OURS]
    else:
        fake_router.models[OURS] = after
    w.look("b", "end")
    assert [s["status"] for s in w.swaps] == [after]


def test_a_model_held_across_the_whole_run_records_no_swap():
    fake_router = FakeRouter(**{OURS: "loaded"})
    w = router.Watch(OURS, get=fake_router.get)
    for case in "abc":
        w.look(case, "start")
        w.look(case, "end")
    assert w.swaps == []


def _sleep_idle(gib, os_name):
    out = subprocess.run(["bash", str(REPO / "scripts" / "router-sleep-idle.sh"), str(gib * 1024 ** 3), os_name],
                         capture_output=True, text=True, check=True)
    return int(out.stdout.strip())


def test_a_dedicated_server_never_sleeps_and_a_shared_desktop_gives_the_card_back():
    assert _sleep_idle(96, "Darwin") == -1 and _sleep_idle(64, "Darwin") == -1
    assert _sleep_idle(32, "Darwin") > 0
    assert _sleep_idle(64, "MINGW64_NT-10.0") > 0 and _sleep_idle(128, "Linux") > 0


def test_the_router_sleeps_as_this_machine_should_and_outlasts_the_longest_request(tmp_path, monkeypatch):
    args, _, _ = _serve(tmp_path, monkeypatch)
    here = subprocess.run(["bash", str(REPO / "scripts" / "router-sleep-idle.sh")],
                          capture_output=True, text=True, check=True).stdout.strip()
    assert args[args.index("--sleep-idle-seconds") + 1] == here
    assert float(args[args.index("--timeout") + 1]) >= CEILING


@pytest.mark.parametrize("name", ["config.yaml", "config.cuda.yaml"])
def test_the_served_gateway_never_retries_and_outlasts_the_longest_request(name):
    got = gateway.served(REPO / "gateway" / name, defaults={}, nodes=[])["litellm_settings"]
    assert got["num_retries"] == 0
    assert got["request_timeout"] >= CEILING


def _held(monkeypatch, get):
    monkeypatch.setattr(delegate, "busy", lambda: "eval")
    monkeypatch.setattr(delegate, "running_job", lambda conn=None: "")
    monkeypatch.setattr(delegate, "upstream", lambda where, config=None: ("http://127.0.0.1:8082", "m"))
    monkeypatch.setattr(serving, "engine_at", lambda base, **k: serving.LLAMACPP)
    monkeypatch.setattr(delegate, "_get_json", get)


def test_a_server_too_busy_to_say_what_it_holds_is_refused_as_unknown_not_as_a_load(monkeypatch):
    def slow(url):
        raise TimeoutError("timed out")
    _held(monkeypatch, slow)
    with pytest.raises(delegate.Refused) as got:
        delegate._gate(serving.Route("http://127.0.0.1:4000", "sohot-code", {}))
    assert "residency unknown" in str(got.value) and "would load" not in str(got.value)


def test_a_server_that_says_the_model_is_not_held_is_refused_as_a_load(monkeypatch):
    _held(monkeypatch, lambda url: {"data": [{"id": "m", "status": {"value": "unloaded"}}]})
    with pytest.raises(delegate.Refused, match="would load"):
        delegate._gate(serving.Route("http://127.0.0.1:4000", "sohot-code", {}))


@pytest.mark.parametrize("holder, resident, extra", [("", None, completion.LOAD_TIMEOUT_S),
                                                     ("", False, completion.LOAD_TIMEOUT_S),
                                                     ("", True, 0.0),
                                                     ("eval", True, 0.0)])
def test_a_delegated_call_waits_for_its_reply_budget_and_for_a_load_it_may_cause(
        fake, monkeypatch, holder, resident, extra):  # noqa: F811
    from harness import pressure
    monkeypatch.setattr(delegate, "loaded", lambda where, **k: resident)
    monkeypatch.setattr(delegate, "busy", lambda: holder)
    monkeypatch.setattr(delegate, "running_job", lambda conn=None: "")
    monkeypatch.setattr(pressure, "sample", lambda *a, **k: pressure.Pressure(level=pressure.NORMAL))
    seen = []
    real = completion.complete_full

    def spy(*a, **k):
        seen.append(k["timeout"])
        return real(*a, **k)
    monkeypatch.setattr(completion, "complete_full", spy)
    delegate.complete("code", "write add", max_tokens=8000)
    assert seen == [max(delegate.TIMEOUT_S, completion.timeout_for(8000)) + extra]


def test_the_desktop_idle_sleep_is_a_site_the_knob_inventory_sees():
    found = knobs.inventory(REPO)
    assert "scripts/router-sleep-idle.sh:LLAMACPP_SLEEP_IDLE" in found
    assert subprocess.run(["bash", str(REPO / "scripts" / "router-sleep-idle.sh"), "0", "Linux"],
                          env={"PATH": "/usr/bin:/bin", "LLAMACPP_SLEEP_IDLE": "120"},
                          capture_output=True, text=True, check=True).stdout.strip() == "120"


def test_an_agent_candidate_is_loaded_untimed_before_its_first_step():
    from evals.runners.agent import AgentRunner
    seen = []

    def chat(messages, **k):
        seen.append(k)
        return completion.Completion(text="ok", usage={}, timing={}, model="m")
    r = AgentRunner("http://gw.test", "m", chat=chat)
    r.warm()
    assert [k["timeout"] for k in seen] == [completion.LOAD_TIMEOUT_S]
    assert seen[0]["max_tokens"] <= 16 and not seen[0].get("tools") and r.answered
