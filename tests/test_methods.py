"""A method is a candidate: a named transform over a base, screened and measured like weights. #576."""
from __future__ import annotations

import argparse
import contextlib
import io
import json
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest
import yaml

from evals import run as er
from evals.core import Case, METRIC_DIRECTION, summarize
from evals.runners.base import BaseRunner, RunnerError
from harness import adopt, completion, gateway, methods, paired, screen
from harness import memory_store as ms

SERVER = "http://127.0.0.1:9"


# ---- the grammar ---------------------------------------------------------------

def test_the_registry_names_each_method_with_its_grammar_lanes_and_cases():
    got = {m.name: m for m in methods.REGISTRY.values()}
    assert {"trace", "trace-icon", "best-of", "plan"} <= set(got)
    assert got["best-of"].grammar == "best-of:<n>:<base>"
    assert got["plan"].grammar == "plan:<base>"
    assert got["trace"].grammar == "trace:<image engine>"
    assert got["trace"].lanes == ("svg",) and got["trace"].takes == "trace"
    assert "code" in got["best-of"].lanes and "agent" not in got["best-of"].lanes
    assert "decide" not in got["best-of"].lanes      # temperature 0: n identical draws
    assert got["best-of"].takes == ""                # whatever its base can take


@pytest.mark.parametrize("spec, name, args, base", [
    ("best-of:3:q3-4b", "best-of", (3,), "q3-4b"),
    ("best-of:5:llamacpp:Ornith-1.5-35B-Q4_K_M", "best-of", (5,),
     "llamacpp:Ornith-1.5-35B-Q4_K_M"),
    ("best-of:3:q3-4b,temperature=0.7", "best-of", (3,), "q3-4b,temperature=0.7"),
    ("plan:mlx-community/Qwen3-4B-4bit", "plan", (), "mlx-community/Qwen3-4B-4bit"),
    ("trace:mflux:flux2-klein-4b", "trace", (), "mflux:flux2-klein-4b"),
    ("trace-icon:mflux:flux2-klein-4b", "trace-icon", (), "mflux:flux2-klein-4b"),
])
def test_a_spec_parses_into_its_method_arguments_and_base(spec, name, args, base):
    got = methods.parse(spec)
    assert (got.method.name, got.args, got.base) == (name, args, base)
    assert methods.base_of(spec) == base


@pytest.mark.parametrize("spec", ["q3-4b", "mflux:flux2-klein-4b", "repair:q3-4b",
                                  "org/model", ""])
def test_anything_else_is_not_a_method(spec):
    assert methods.parse(spec) is None
    assert methods.base_of(spec) == ""


@pytest.mark.parametrize("spec", ["best-of:x:q3-4b", "best-of:1:q3-4b", "best-of:3:",
                                  "plan:", "best-of:3"])
def test_a_malformed_method_spec_is_a_bad_spec_before_anything_runs(spec, tmp_path):
    with pytest.raises(ValueError):
        methods.parse(spec)
    with pytest.raises(SystemExit):
        er.build_runner(spec, "http://gw", tmp_path)


def test_compose_is_the_inverse_of_parse():
    for m in methods.REGISTRY.values():
        spec = m.compose("q3-4b")
        assert methods.parse(spec).base == "q3-4b"
        assert methods.parse(spec).method is m


# ---- trace moved into the registry, behaviour unchanged ------------------------

def test_trace_is_read_from_the_registry():
    assert er.TRACE_PREFIXES == {"trace": "illustration", "trace-icon": "icon"}
    assert er.kind_of("trace:mflux:flux2-klein-4b") == "trace"
    assert er.method_of("trace-icon:mflux:flux2-klein-4b") == "trace"
    assert er.modality_of("trace:mflux:flux2-klein-4b") == "svg"


def test_a_trace_icon_candidate_keeps_its_preset_and_name(tmp_path):
    from evals.runners.trace import TraceRunner
    r = er.build_runner("trace-icon:mflux:flux2-klein-4b", "http://gw", tmp_path)
    assert isinstance(r, TraceRunner) and r.preset == "icon"
    assert r.candidate.startswith("trace-icon/")


# ---- a method spec is a candidate everywhere ----------------------------------

def test_a_text_method_takes_the_cases_its_base_takes_in_its_own_lanes():
    cases = [Case(id="c", modality="code", prompt="x"),
             Case(id="bars", modality="svg", prompt="bars", methods=("llm",)),
             Case(id="e", modality="extract", prompt="x"),
             Case(id="a", modality="agent", prompt="x")]
    assert [c.id for c in er.cases_for("best-of:3:q3-4b", cases)] == ["c", "bars"]
    assert [c.id for c in er.cases_for("plan:q3-4b", cases)] == ["c", "bars", "e"]
    assert er.method_of("best-of:3:q3-4b") == "llm"
    assert er.modality_of("best-of:3:q3-4b") is None


def test_a_method_over_a_text_base_is_routed_like_its_base(monkeypatch, tmp_path):
    from evals.runners.method import BestOfRunner, PlanRunner
    from evals.runners.text import CompletionRunner
    r = er.build_runner("best-of:3:q3-4b", "http://gw", tmp_path)
    assert isinstance(r, BestOfRunner) and isinstance(r.base, CompletionRunner)
    assert r.base.gateway == "http://gw" and r.base.model == "q3-4b"
    assert r.candidate == "best-of-3/q3-4b"
    p = er.build_runner("plan:q3-4b", "http://gw", tmp_path)
    assert isinstance(p, PlanRunner) and p.candidate == "plan/q3-4b"


def test_plan_needs_a_text_base(tmp_path):
    with pytest.raises(SystemExit) as e:
        er.build_runner("plan:mflux:flux2-klein-4b", "http://gw", tmp_path)
    assert "text" in str(e.value)


def test_a_method_has_its_own_receipt_key():
    assert er.receipt_key("best-of:3:q3-4b") == "best-of-3/q3-4b"
    assert er.receipt_key("q3-4b") == "q3-4b"


def test_the_method_cost_metrics_are_reported_and_never_ranked_on():
    for m in ("method_calls", "method_samples", "method_chosen"):
        assert METRIC_DIRECTION[m] == "neutral"


def test_the_receipt_records_each_methods_name_and_base():
    got = er.method_receipts({"best-of-3/q3-4b": "best-of:3:q3-4b", "q3-4b": "q3-4b"})
    assert got == {"best-of-3/q3-4b": {"spec": "best-of:3:q3-4b", "method": "best-of",
                                       "args": [3], "base": "q3-4b"}}


def test_the_screen_finds_nothing_to_fetch_for_a_method_over_a_served_alias():
    row = {"name": "best-of:3:q3-4b", "lane": "code"}
    got = screen.plan([row], missing=lambda name: [name])
    assert got[0]["state"] == screen.READY, got[0]["why_not"]
    assert got[0]["candidate"] == "best-of:3:q3-4b"


def test_the_screen_waits_on_the_bases_weights_for_a_method_over_a_repo():
    row = {"name": "best-of:3:org/new-coder", "lane": "code"}
    got = screen.plan([row], missing=lambda name: [name])
    assert got[0]["state"] == screen.WAITING
    assert "org/new-coder" in got[0]["why_not"]


def test_a_method_over_a_repo_is_routed_where_its_base_would_be(monkeypatch):
    monkeypatch.setattr(screen, "gateway_routes", lambda config=None: ({"q3-4b"}, f"{SERVER}/v1"))
    assert screen.routed_gateway("best-of:3:org/new-coder") == SERVER
    assert screen.routed_gateway("best-of:3:q3-4b") == ""


# ---- best-of and plan ----------------------------------------------------------

class Scripted(BaseRunner):
    """A base runner that answers from a script, one answer per call."""

    def __init__(self, answers, candidate="base"):
        self.answers, self.candidate, self.calls = list(answers), candidate, 0

    def generate(self, case):
        self.calls += 1
        got = self.answers.pop(0)
        if isinstance(got, Exception):
            raise got
        return got, 0

    def extra_metrics(self):
        return {"completion_tokens": 10}


def extract_case(answer="137"):
    return Case(id="e", modality="extract", prompt="what number?",
                assertions={"equals": answer})


def test_best_of_keeps_the_sample_the_lanes_own_checks_score_highest():
    from evals.runners.method import BestOfRunner
    base = Scripted(["12", "137", "99"])
    r = BestOfRunner(base, 3).run(extract_case())
    assert r.passed and r.output == "137"
    assert base.calls == 3
    assert r.metrics["method_calls"] == 3 and r.metrics["method_samples"] == 3
    assert r.metrics["method_chosen"] == 2
    assert r.metrics["completion_tokens"] == 30


def test_best_of_takes_the_first_of_equals_and_survives_a_failed_sample():
    from evals.runners.method import BestOfRunner
    r = BestOfRunner(Scripted([RunnerError("timed out"), "7", "7"]), 3).run(extract_case("7"))
    assert r.passed and r.metrics["method_chosen"] == 2 and r.metrics["method_calls"] == 3


def test_best_of_with_every_sample_failed_is_a_failed_row():
    from evals.runners.method import BestOfRunner
    r = BestOfRunner(Scripted([RunnerError("timed out")] * 3), 3).run(extract_case())
    assert not r.passed and "timed out" in r.detail


def test_best_of_reports_the_whole_latency_of_its_samples():
    import time
    from evals.runners.method import BestOfRunner

    class Slow(Scripted):
        def generate(self, case):
            time.sleep(0.02)
            return super().generate(case)
    r = BestOfRunner(Slow(["1", "2", "3"]), 3).run(extract_case())
    assert r.seconds >= 0.06


def test_plan_asks_for_a_plan_then_answers_with_it(monkeypatch):
    from evals.runners.method import PlanRunner
    from evals.runners.text import CompletionRunner
    asked = []

    def fake(prompt, model, gateway="", **kw):
        asked.append((prompt, model, gateway, kw.get("modality")))
        return "1. find the number 2. say it", {"completion_tokens": 5}
    monkeypatch.setattr(completion, "complete_with_usage", fake)
    base = CompletionRunner("http://gw", "q3-4b")
    answered = []
    monkeypatch.setattr(base, "generate",
                        lambda case: answered.append(case.prompt) or ("137", 0))
    r = PlanRunner(base).run(extract_case())
    assert r.passed
    assert len(asked) == 1 and asked[0][1:3] == ("q3-4b", "http://gw")
    assert "what number?" in asked[0][0] and asked[0][3] == ""
    assert "1. find the number" in answered[0] and "what number?" in answered[0]
    assert r.metrics["method_calls"] == 2


# ---- the negative controls, through evals.run and the paired adopt gate ---------

class Identity(BaseRunner):
    def __init__(self, base):
        self.base, self.candidate = base, f"identity/{base.candidate}"

    def generate(self, case):
        return self.base.generate(case)


class Corrupt(Identity):
    def __init__(self, base):
        super().__init__(base)
        self.candidate = f"corrupt/{base.candidate}"

    def generate(self, case):
        text, peak = self.base.generate(case)
        return f"not {text}", peak


def _control(name, runner):
    return methods.Method(name=name, grammar=f"{name}:<base>", lanes=("extract",),
                          takes="", note="a negative control",
                          build=lambda parsed, base, outdir: runner(base(parsed.base)),
                          crosses=False)


@pytest.fixture
def gateway_world(monkeypatch, tmp_path):
    config = tmp_path / "config.yaml"
    config.write_text(yaml.safe_dump({"model_list": [
        {"model_name": "q3-4b", "litellm_params": {
            "model": "openai/org/q3", "api_base": f"{SERVER}/v1", "api_key": "x"}}]}),
        encoding="utf-8")
    monkeypatch.setenv(gateway.ENV_VAR, str(config))
    cases = tmp_path / "cases" / "extract"
    cases.mkdir(parents=True)
    answers = {}
    for i in range(8):
        (cases / f"n{i}.yaml").write_text(yaml.safe_dump({
            "id": f"n{i}", "modality": "extract", "prompt": f"Say the number {100 + i}.",
            "assert": {"equals": str(100 + i)}}), encoding="utf-8")
        answers[f"Say the number {100 + i}."] = str(100 + i)

    def post(base, payload, timeout):
        user = payload["messages"][-1]["content"]
        text = next((a for q, a in answers.items() if q in user), "ok")
        body = {"model": payload["model"], "choices": [{"index": 0, "finish_reason": "stop",
                "message": {"role": "assistant", "content": text}}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 3}}
        if payload.get("stream"):
            return completion.Streamed(body, {"ttft_s": 0.01})
        return httpx.Response(200, json=body,
                              request=httpx.Request("POST", f"{base}/v1/chat/completions"))
    monkeypatch.setattr(completion, "_post", post)
    return tmp_path


def _measure(tmp_path, candidates):
    out = tmp_path / "run"
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        assert er.main(["--modality", "extract", "--cases", str(tmp_path / "cases"),
                        "--candidates", candidates, "--out", str(out)]) == 0
    data = json.loads((out / "results.json").read_text(encoding="utf-8"))
    return data


def _verdict(data, inc, ch):
    rows = data["rows"]
    s = data["summary"]
    return (adopt.decide("extract", {**s[inc], "candidate": inc}, {**s[ch], "candidate": ch},
                         rows),
            paired.head_to_head(rows, inc, ch))


def test_an_identity_method_measures_as_a_tie_against_its_base(gateway_world, monkeypatch):
    monkeypatch.setitem(methods.REGISTRY, "identity", _control("identity", Identity))
    data = _measure(gateway_world, "q3-4b,identity:q3-4b")
    verdict, cell = _verdict(data, "q3-4b", "identity/q3-4b")
    assert (cell.gained, cell.lost) == (0, 0)
    assert not verdict.adopt
    assert data["summary"]["identity/q3-4b"]["passed"] == data["summary"]["q3-4b"]["passed"] == 8
    assert data["receipt"]["methods"]["identity/q3-4b"]["base"] == "q3-4b"


def test_a_corrupting_method_loses_to_its_base(gateway_world, monkeypatch):
    monkeypatch.setitem(methods.REGISTRY, "corrupt", _control("corrupt", Corrupt))
    data = _measure(gateway_world, "q3-4b,corrupt:q3-4b")
    verdict, cell = _verdict(data, "q3-4b", "corrupt/q3-4b")
    assert cell.lost == 8 and cell.gained == 0 and cell.p <= adopt.ALPHA
    assert not verdict.adopt and "does not beat" in verdict.why


def test_plan_runs_through_evals_run_with_its_cost_in_the_table(gateway_world, capsys):
    data = _measure(gateway_world, "q3-4b,plan:q3-4b")
    s = data["summary"]["plan/q3-4b"]
    assert s["passed"] == 8 and s["metrics"]["method_calls"] == 2.0
    assert data["receipt"]["methods"]["plan/q3-4b"] == {
        "spec": "plan:q3-4b", "method": "plan", "args": [], "base": "q3-4b"}


def test_the_report_table_shows_the_calls_column(capsys):
    from evals.core import Result
    from evals.run import report
    report(summarize([Result("a", "q3-4b", True, 1.0, 0, ""),
                      Result("a", "best-of-3/q3-4b", True, 3.0, 0, "",
                             metrics={"method_calls": 3})]))
    out = capsys.readouterr().out
    assert "method_calls" in out


def test_a_methods_verdict_carries_its_cost(gateway_world, monkeypatch):
    monkeypatch.setitem(methods.REGISTRY, "identity", _control("identity", Identity))
    data = _measure(gateway_world, "q3-4b,identity:q3-4b")
    s = data["summary"]
    v = adopt.decide("extract", {**s["q3-4b"], "candidate": "q3-4b"},
                     {**s["identity/q3-4b"], "candidate": "identity/q3-4b"},
                     data["rows"], spec="identity:q3-4b")
    assert "cost: identity made" in v.why
    assert v.evidence["cost"]["method"] == "identity" and v.evidence["cost"]["calls"] == 1.0
    plain = adopt.decide("extract", {**s["q3-4b"], "candidate": "q3-4b"},
                         {**s["identity/q3-4b"], "candidate": "identity/q3-4b"},
                         data["rows"], spec="q3-4b")
    assert "cost:" not in plain.why


def test_the_cost_note_says_what_the_method_paid_for_its_result():
    note = methods.cost_note({"median_s": 2.0, "metrics": {}},
                             {"median_s": 10.0, "metrics": {"method_calls": 5.0}},
                             "best-of:5:q3-4b")
    assert "5.0 calls" in note and "5.0x" in note and "best-of" in note
    assert methods.cost_note({"median_s": 2.0}, {"median_s": 2.0}, "q3-4b") == ""


# ---- adopt: a method that wins is recorded, never served by a lane command yet ---

def test_a_winning_method_is_measured_but_not_served(tmp_path):
    conn = ms.connect(tmp_path / "d.db")
    try:
        v = adopt.Verdict("code", "q3-4b", "best-of-3/q3-4b", True,
                          "beats q3-4b on the lane's metric, 8 gained against 0 lost, p=0.01")
        adopt.record(conn, v, spec="best-of:3:q3-4b")
        assert adopt.current(conn) == {}
        row = conn.execute("SELECT outcome, detail FROM verdicts ORDER BY id DESC").fetchone()
        assert row["outcome"] == "measured"
        assert "not served" in row["detail"]
    finally:
        conn.close()


# ---- the loop crosses each method with each lane's incumbent --------------------

def _lane_defaults(monkeypatch, defaults):
    from harness import winners
    monkeypatch.setattr(winners, "typed", lambda: dict(defaults))


def test_the_loop_queues_each_applicable_method_over_each_lanes_incumbent(monkeypatch, tmp_path):
    from harness.commands import loop
    _lane_defaults(monkeypatch, {"code": "q3-4b", "web": "q3-4b", "svg": "local-large",
                                 "image": "mflux:flux2-klein-4b", "extract": "q3-1b",
                                 "decide": "decider:x", "agent": "q3-4b"})
    conn = ms.connect(tmp_path / "d.db")
    try:
        got = loop._cross_methods(conn)
        specs = {(lane, spec) for lane, spec, _ in got}
        assert ("code", "best-of:3:q3-4b") in specs
        assert ("code", "plan:q3-4b") in specs
        assert ("svg", "trace:mflux:flux2-klein-4b") in specs
        assert ("svg", "best-of:3:local-large") in specs
        assert ("extract", "plan:q3-1b") in specs
        assert not any(lane in ("agent", "decide", "image") for lane, _, _ in got)
        assert not any(s.startswith("trace-icon:") for _, s, _ in got)
        queued = {r["name"]: r for r in ms.judgeable(conn, limit=1000)}
        assert queued["best-of:3:q3-4b"]["lane"] == "code"
        assert queued["best-of:3:q3-4b"]["kind"] == methods.CROSSING_KIND
    finally:
        conn.close()


def test_crossing_twice_queues_nothing_new_and_adds_no_sighting(monkeypatch, tmp_path):
    from harness.commands import loop
    _lane_defaults(monkeypatch, {"code": "q3-4b"})
    conn = ms.connect(tmp_path / "d.db")
    try:
        first = loop._cross_methods(conn, want="code")
        again = loop._cross_methods(conn, want="code")
        assert [new for _, _, new in first] == [True] * len(first)
        assert [new for _, _, new in again] == [False] * len(again)
        n = conn.execute("SELECT COUNT(*) FROM sightings").fetchone()[0]
        assert n == len(first)
    finally:
        conn.close()


def test_a_crossed_method_reaches_the_screen_as_ready(monkeypatch, tmp_path):
    from harness import rank
    from harness.commands import loop
    _lane_defaults(monkeypatch, {"code": "q3-4b"})
    conn = ms.connect(tmp_path / "d.db")
    try:
        loop._cross_methods(conn, want="code")
        rows = ms.judgeable(conn, limit=1000)
    finally:
        conn.close()
    ranked = rank.rank(rows, ceiling_gib=22.0)
    plan = {r["name"]: r for r in screen.plan(ranked, missing=lambda n: [n])}
    assert plan["best-of:3:q3-4b"]["state"] == screen.READY
    assert plan["plan:q3-4b"]["state"] == screen.READY


def test_the_loop_report_prints_the_crossings(monkeypatch):
    from harness.commands import discover as discover_cmd, loop
    _lane_defaults(monkeypatch, {"code": "q3-4b"})
    monkeypatch.setattr(discover_cmd, "cmd_discover", lambda a: 0)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        loop._report_loop(argparse.Namespace(run=False, lane="code", top=1, json=False))
    text = out.getvalue()
    assert "=== methods ===" in text
    assert "best-of:3:q3-4b" in text and "queued" in text


def test_a_crossing_waiting_for_a_screen_never_holds_back_a_download():
    """The fetch tier waits behind weights already on disk. A method over a served
    incumbent has no weights of its own, so it is not that backlog."""
    from harness.commands import screen as screen_cmd
    plan = [{"name": "best-of:3:q3-4b", "candidate": "best-of:3:q3-4b", "state": screen.READY},
            {"name": "org/fetched", "candidate": "org/fetched", "state": screen.READY}]
    assert screen_cmd.screenable_backlog(plan=plan, room=lambda r: True) == ["org/fetched"]


def test_discover_lists_every_registered_method():
    from harness import discover
    names = {(c.name, c.lane) for c in discover.methods()}
    for m in methods.REGISTRY.values():
        for lane in m.lanes:
            assert (m.name, lane) in names, (m.name, lane)
