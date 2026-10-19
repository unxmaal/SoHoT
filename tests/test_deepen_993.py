"""Prompt-transform templates (deepen, the neutral control) and the lane-too-small verdict. #993."""
from __future__ import annotations

import contextlib
import io
import json
import math
from dataclasses import replace

import httpx
import pytest
import yaml

from evals import run as er
from harness import adopt, completion, delegate, gateway, holdout, methods, paired, power, reasons
from harness import memory_store as ms
from harness.memory_store import revisit

SERVER = "http://127.0.0.1:9"
QUESTIONS = ("What would a top professional do here that the task doesn't ask for?",
             "What raw material would they start from?",
             "Which specific methods and tools would they use?",
             "What, other than the author, would show the result is right?")


# ---- the templates are data the registry loads ------------------------------------

def test_deepen_and_its_control_are_read_from_the_template_file():
    names = {m.name for m in methods.load_templates()}
    assert {"deepen", "neutral"} <= names
    deepen, neutral = methods.REGISTRY["deepen"], methods.REGISTRY["neutral"]
    assert deepen.grammar == "deepen:<base>" and set(deepen.lanes) == {"code", "extract", "web"}
    assert set(neutral.lanes) == set(deepen.lanes)
    assert methods.calls("deepen:q3-4b") == 2 and methods.calls("neutral:q3-4b") == 1
    assert methods.is_control("neutral:q3-4b") and not methods.is_control("deepen:q3-4b")
    assert not methods.is_control("plan:q3-4b") and not methods.is_control("q3-4b")
    assert methods.text_method("deepen:q3-4b") and methods.base_of("deepen:q3-4b") == "q3-4b"
    rewrite = methods.steps_of("deepen:q3-4b")[0].prompt
    assert all(q in rewrite for q in QUESTIONS)


def test_a_new_template_is_a_method_with_no_code(tmp_path):
    path = tmp_path / "t.yaml"
    path.write_text(yaml.safe_dump({"templates": [{
        "name": "critique", "lanes": ["code"], "steps": [
            {"as": "draft", "answers": True, "prompt": "{task}"},
            {"as": "notes", "prompt": "Critique this answer to {task}:\n{draft}"},
            {"prompt": "{task}\nRevise this answer:\n{draft}\nwith these notes:\n{notes}"}]}]}),
        encoding="utf-8")
    (m,) = methods.load_templates(path)
    steps = m.extra["steps"]
    assert [s.name for s in steps] == ["draft", "notes", ""]
    assert [s.answers for s in steps] == [True, False, True]
    asked = []

    def ask(prompt, modality):
        asked.append((prompt, modality))
        return f"reply {len(asked)}"
    parsed = methods.Parsed(m, (), "q3-4b", "critique:q3-4b")
    text, cost = m.serve(parsed, "code", "add two numbers", ask)
    assert text == "reply 3" and cost["calls"] == 3 and cost["template"] == m.extra["digest"]
    assert [mod for _, mod in asked] == ["code", "", "code"]
    assert "reply 1" in asked[1][0] and "reply 2" in asked[2][0] and "add two numbers" in asked[2][0]


@pytest.mark.parametrize("row, said", [
    ({"name": "Bad Name", "steps": [{"prompt": "{task}"}]}, "lower-case"),
    ({"name": "x", "steps": []}, "at least one step"),
    ({"name": "x", "lanes": ["image"], "steps": [{"prompt": "{task}"}]}, "not text lanes"),
    ({"name": "x", "steps": [{"prompt": "{task} {nope}"}]}, "reads {nope}"),
    ({"name": "x", "steps": [{"prompt": "{task}"}, {"prompt": "{task}"}]}, "needs an `as`"),
    ({"name": "x", "steps": [{"as": "a", "prompt": "{task}"}, {"prompt": "{task}"}]}, "reads step 1"),
    ({"name": "x", "steps": [{"as": "task", "prompt": "{task}"}, {"prompt": "{task}"}]}, "taken"),
    ({"name": "x", "steps": [{"prompt": " "}]}, "no prompt"),
])
def test_a_template_that_would_not_run_is_refused_when_it_is_loaded(row, said):
    with pytest.raises(ValueError, match=said):
        methods.from_template(row)


def test_a_template_cannot_take_a_coded_methods_name():
    clash = methods.from_template({"name": "plan", "steps": [{"prompt": "{task}"}]})
    with pytest.raises(ValueError, match="already registered"):
        methods._registry([methods.REGISTRY["plan"]], [clash])


def test_a_task_is_filled_in_once_and_never_read_for_slots():
    assert methods.fill("A {task} B", {"task": "{rewrite} {task}"}) == "A {rewrite} {task} B"


def test_the_template_digest_changes_with_its_prompt():
    a = methods.from_template({"name": "x", "steps": [{"prompt": "{task}"}]})
    b = methods.from_template({"name": "x", "steps": [{"prompt": "{task}."}]})
    assert a.extra["digest"] != b.extra["digest"]


# ---- deepen serves and measures as two calls on its base ---------------------------

def test_deepen_rewrites_with_the_four_questions_then_answers_its_rewrite():
    asked = []

    def ask(prompt, modality):
        asked.append((prompt, modality))
        return "  the better task  " if len(asked) == 1 else "the answer"
    text, cost = methods.run("deepen:q3-4b", "code", "write fizzbuzz", ask)
    assert text == "the answer"
    assert asked[0][1] == "" and "write fizzbuzz" in asked[0][0]
    assert all(q in asked[0][0] for q in QUESTIONS)
    assert asked[1] == ("the better task", "code")
    assert cost == {"method": "deepen", "base": "q3-4b", "calls": 2,
                    "template": methods.REGISTRY["deepen"].extra["digest"]}


def test_each_call_of_a_template_is_named_by_its_step():
    assert delegate._call_label("deepen:q3-4b", 1, "") == "call 1 of deepen:q3-4b (the rewrite)"
    assert delegate._call_label("deepen:q3-4b", 2, "code") == "call 2 of deepen:q3-4b (the answer)"
    assert delegate._call_label("neutral:q3-4b", 1, "code") == "call 1 of neutral:q3-4b (the answer)"


@pytest.fixture
def faithful(monkeypatch, tmp_path):
    """A gateway whose model answers each case, and rewrites a deepen task into the case unchanged."""
    config = tmp_path / "config.yaml"
    config.write_text(yaml.safe_dump({"model_list": [
        {"model_name": "q3-4b", "engine": "mlx_lm.server", "litellm_params": {
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
    sent = []

    def post(base, payload, timeout):
        user = payload["messages"][-1]["content"]
        sent.append(user)
        task = next((q for q in answers if q in user), "")
        text = f"REWRITTEN: {task}" if "rewrite it into a better task" in user else answers.get(task, "ok")
        body = {"model": payload["model"], "choices": [{"index": 0, "finish_reason": "stop",
                "message": {"role": "assistant", "content": text}}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 3}}
        if payload.get("stream"):
            return completion.Streamed(body, {"ttft_s": 0.01})
        return httpx.Response(200, json=body,
                              request=httpx.Request("POST", f"{base}/v1/chat/completions"))
    monkeypatch.setattr(completion, "_post", post)
    return tmp_path, sent


def _run(where, candidates):
    out = where / "run"
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        assert er.main(["--modality", "extract", "--cases", str(where / "cases"),
                        "--candidates", candidates, "--out", str(out)]) == 0
    return json.loads((out / "results.json").read_text(encoding="utf-8"))


def _decide(data, inc, ch, spec):
    s = data["summary"]
    return (adopt.decide("extract", {**s[inc], "candidate": inc}, {**s[ch], "candidate": ch},
                         data["rows"], spec=spec),
            paired.head_to_head(data["rows"], inc, ch))


def test_deepen_runs_through_evals_run_with_its_extra_call_counted(faithful):
    where, sent = faithful
    data = _run(where, "q3-4b,deepen:q3-4b")
    s = data["summary"]["deepen/q3-4b"]
    assert s["passed"] == 8 and s["metrics"]["method_calls"] == 2.0
    assert data["receipt"]["methods"]["deepen/q3-4b"]["template"] == methods.REGISTRY["deepen"].extra["digest"]
    assert sum("rewrite it into a better task" in u for u in sent) == 8
    assert sum(u.startswith("REWRITTEN: Say the number") for u in sent) == 8
    verdict, _ = _decide(data, "q3-4b", "deepen/q3-4b", "deepen:q3-4b")
    assert verdict.evidence["cost"]["calls"] == 2.0 and "cost: deepen made 2.0 calls" in verdict.why
    assert verdict.evidence["cost"]["template"] == methods.REGISTRY["deepen"].extra["digest"]


def test_the_neutral_control_shows_no_effect_on_the_same_cases(faithful):
    where, _ = faithful
    data = _run(where, "q3-4b,neutral:q3-4b")
    verdict, cell = _decide(data, "q3-4b", "neutral/q3-4b", "neutral:q3-4b")
    assert (cell.gained, cell.lost) == (0, 0) and cell.p == 1.0
    assert not verdict.adopt
    assert data["summary"]["neutral/q3-4b"]["metrics"]["method_calls"] == 1.0


def test_a_control_that_wins_is_never_adopted(tmp_path):
    conn = ms.connect(tmp_path / "d.db")
    try:
        v = adopt.Verdict("code", "q3-4b", "neutral/q3-4b", True,
                          "beats q3-4b on the lane's metric, 8 gained against 0 lost, p=0.01")
        adopt.record(conn, v, spec="neutral:q3-4b")
        assert "code" not in adopt.current(conn)
        row = conn.execute("SELECT outcome, detail FROM verdicts ORDER BY id DESC").fetchone()
        assert row["outcome"] == "declined" and "negative control won" in row["detail"]
    finally:
        conn.close()


def test_the_loop_crosses_deepen_and_its_control_over_each_text_lanes_incumbent(monkeypatch, tmp_path):
    from harness import winners
    from harness.commands import loop
    monkeypatch.setattr(winners, "typed", lambda: {"code": "q3-4b", "web": "q3-4b", "extract": "q3-1b",
                                                   "svg": "local-large"})
    conn = ms.connect(tmp_path / "d.db")
    try:
        got = {(lane, spec) for lane, spec, _ in loop._cross_methods(conn)}
    finally:
        conn.close()
    for name in ("deepen", "neutral"):
        assert {("code", f"{name}:q3-4b"), ("web", f"{name}:q3-4b"),
                ("extract", f"{name}:q3-1b")} <= got
        assert ("svg", f"{name}:local-large") not in got


# ---- a method's null on a lane too small to see the effect -------------------------

SPLIT = holdout.Split("extract", dev=("d1", "d2", "d3"), holdout=("h1", "h2", "h3", "h4", "h5"),
                      too_small=False)


def _rows(inc, ch):
    out = []
    for case, i, c in zip(SPLIT.holdout, inc, ch):
        out.append({"candidate": "inc", "case_id": case, "passed": i, "seconds": 1.0, "metrics": {}})
        out.append({"candidate": "ch", "case_id": case, "passed": c, "seconds": 1.0,
                    "metrics": {"method_calls": 2}})
    return out


def _plan(rates, **kw):
    got = power.plan(rates, 0.2, stochastic=False, observed=len(rates), rho=1.0, **kw)
    return replace(got, odds=power._cell_odds(rates, 0.2))


def _summary(name, rows):
    mine = [r for r in rows if r["candidate"] == name]
    return {"candidate": name, "pass_rate": sum(r["passed"] for r in mine) / len(mine),
            "median_s": 1.0, "metrics": {}}


def _decide_small(spec, inc, ch, plan):
    rows = _rows(inc, ch)
    return adopt.decide("extract", _summary("inc", rows), _summary("ch", rows), rows,
                        split=SPLIT, plan=plan, spec=spec)


def test_a_methods_null_on_a_lane_too_small_names_the_cases_it_needs():
    plan = _plan([0.6] * 5)
    need = power.too_small(plan)
    assert need is not None and need > 5
    got = _decide_small("deepen:q3-4b", [True, True, True, False, False],
                        [True, True, True, False, False], plan)
    assert not got.adopt and got.failure_class == reasons.LANE_TOO_SMALL
    assert got.why.startswith(f"lane too small, needs {need} holdout cases")
    more = math.ceil(round((need - 5) / holdout.FRACTION, 6))
    assert f"about {more} more extract cases" in got.why
    assert got.until == f"cases:extract>{8 + more - 1}", got.until
    assert adopt.outcome_of(got) == ("declined", reasons.LIMIT)


def test_a_lane_reopens_once_it_has_the_cases_it_needs():
    plan = replace(_plan([0.6] * 5), cases_needed=8)
    got = _decide_small("deepen:q3-4b", [True] * 3 + [False] * 2, [True] * 3 + [False] * 2, plan)
    assert "about 10 more extract cases" in got.why and got.until == "cases:extract>17"


def test_a_methods_null_on_a_saturated_lane_asks_for_cases_the_incumbent_fails():
    plan = _plan([1.0] * 5)
    got = _decide_small("deepen:q3-4b", [True] * 5, [True] * 5, plan)
    assert got.failure_class == reasons.LANE_TOO_SMALL
    assert got.why.startswith("lane too small, needs cases the incumbent fails")
    assert got.until == "cases:extract>8"


def test_a_models_null_on_the_same_lane_is_lane_too_small_too():
    got = _decide_small("org/model", [True, True, True, False, False],
                        [True, True, True, False, False], _plan([0.6] * 5))
    assert got.failure_class == reasons.LANE_TOO_SMALL and got.until.startswith("cases:extract>")


def test_a_method_that_is_significantly_worse_is_a_loss_whatever_the_lane_size():
    plan = _plan([0.9] * 5)
    rows = _rows([True] * 5, [False] * 5)
    got = adopt.decide("extract", _summary("inc", rows), _summary("ch", rows), rows,
                       split=SPLIT, plan=plan, spec="deepen:q3-4b", alpha=0.5)
    assert got.failure_class == "" and "significantly worse" in got.why


@pytest.mark.parametrize("rate", [0.6, 1.0])
def test_a_guessed_plan_is_not_called_lane_too_small(rate):
    plan = replace(_plan([rate] * 5), unmeasured=True)
    assert power.too_small(plan) is None
    got = _decide_small("deepen:q3-4b", [True] * 3 + [rate == 1.0] * 2, [True] * 3 + [rate == 1.0] * 2, plan)
    assert got.failure_class == reasons.UNDERPOWERED


def test_a_lane_with_enough_cases_is_not_too_small_at_a_short_repeat():
    plan = power.plan([0.6] * 40, 0.2, stochastic=True, observed=40, rho=0.0, repeat=1)
    assert not plan.enough and plan.cases_needed is not None and plan.cases_needed <= plan.cases
    assert power.too_small(plan) is None


def test_lane_too_small_is_stored_waiting_on_the_lanes_cases_and_spends_no_comparison(tmp_path):
    conn = ms.connect(tmp_path / "d.db")
    try:
        ms.record(conn, ms.Seen(name="deepen:q3-4b", source=methods.CROSSING_SOURCE,
                                kind=methods.CROSSING_KIND, lane="extract", resolved="deepen:q3-4b"))
        ms.decide(conn, "deepen:q3-4b", "screened", tier=ms.SCREEN, reason=reasons.CANDIDATE)
        got = _decide_small("deepen:q3-4b", [True] * 3 + [False] * 2, [True] * 3 + [False] * 2,
                            _plan([0.6] * 5))
        adopt.record(conn, got, spec="deepen:q3-4b")
        row = conn.execute(
            "SELECT p.state, p.next_retest_at, v.reason, v.until, v.failure_class, v.detail "
            "FROM proposals p JOIN verdicts v ON v.id = p.state_verdict_id "
            "WHERE p.name = 'deepen:q3-4b'").fetchone()
        assert (row["state"], row["reason"], row["failure_class"]) == (
            "declined", reasons.LIMIT, reasons.LANE_TOO_SMALL)
        assert row["detail"].startswith("extract: lane too small, needs")
        assert row["until"] == got.until and row["next_retest_at"] is None
        assert adopt.comparisons(conn, "extract", SPLIT.version) == 0
        floor = int(got.until.rpartition(">")[2])
        assert not revisit.until_met(got.until, {"cases": {"extract": floor}})
        assert revisit.until_met(got.until, {"cases": {"extract": floor + 1}})
        assert [r["name"] for r in revisit.revisitable(conn, {"cases": {"extract": floor + 1}})] == [
            "deepen:q3-4b"]
    finally:
        conn.close()
