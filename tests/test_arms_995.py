"""Prompts and skills measured as claude-code arms: context, repeats, power, cost, frozen split, controls. #995."""
from __future__ import annotations

import json
import random
from types import SimpleNamespace

import pytest

from evals import arms_report as A, repo_report as R, run
from evals.core import Case, Receipt
from evals.importers import history
from evals.runners.claude_code import ClaudeCodeRunner
from harness import arms, holdout, methods

MODEL = "claude-opus-5-5"
NONE, NOCHANGE = f"claude-code:{MODEL}", f"claude-code:{MODEL},context=skill:no-change"
PLACEBO = f"claude-code:{MODEL},context=placebo:skill:no-change"


class Proc:
    def __init__(self, result, turns=1, out=10, inp=100):
        self.stdout = json.dumps({"type": "result", "result": result, "is_error": False, "num_turns": turns,
                                  "usage": {"input_tokens": inp, "output_tokens": out,
                                            "cache_read_input_tokens": 5}})
        self.returncode, self.stderr = 0, ""


def fake(reply, seen: list):
    def run_(argv, **kw):
        seen.append(kw["input"])
        return Proc(reply(kw["input"]) if callable(reply) else reply)
    return run_


def _case(prompt="Fix the bug."):
    return Case(id="t", modality="code", prompt=prompt, assertions={"checks": []})


# ---- the context an arm carries --------------------------------------------------

def test_none_is_the_plain_model_key_and_sends_the_task_untouched():
    seen = []
    r = ClaudeCodeRunner(MODEL, execute=fake("ok", seen))
    r.generate(_case())
    assert r.candidate == NONE and seen == ["Fix the bug."]


def test_a_planted_skill_goes_before_the_task_in_the_frame_and_names_itself_in_the_key():
    seen = []
    r = ClaudeCodeRunner(MODEL, execute=fake("NO CHANGE", seen), context="skill:no-change")
    r.generate(_case())
    text = arms.planted()["no-change"]["text"].strip()
    assert r.candidate == NOCHANGE
    assert seen == [arms.FRAME.format(text=text, task="Fix the bug.")]
    assert r.context.digest and r.context.source.startswith("planted:")


def test_a_home_skill_is_its_body_without_frontmatter(tmp_path, monkeypatch):
    (tmp_path / "deep").mkdir()
    (tmp_path / "deep" / "SKILL.md").write_text("---\nname: deep\ndescription: d\n---\n\n# Deep\n\nThink.\n",
                                                encoding="utf-8")
    monkeypatch.setattr(arms, "skills_root", lambda: tmp_path)
    ctx = arms.parse("skill:deep")
    assert ctx.text == "# Deep\n\nThink." and ctx.chars == len(ctx.text)
    with pytest.raises(ValueError, match="no planted skill"):
        arms.parse("skill:absent")


def test_a_placebo_is_as_long_as_what_it_controls_for_and_says_something_else():
    real, fake_ = arms.parse("skill:no-change"), arms.parse("placebo:skill:no-change")
    assert len(fake_.text) == real.chars and fake_.digest != real.digest
    assert "change" not in fake_.text.lower() and "diff" not in fake_.text.lower()
    assert arms.placebo(5000) == arms.placebo(5000) and len(arms.placebo(5000)) == 5000
    for bad in ("placebo:none", "placebo:placebo:skill:no-change", "deepen", "none:x", "skill:"):
        with pytest.raises(ValueError):
            arms.parse(bad)


def test_a_prompt_template_runs_its_steps_as_calls_and_adds_up_their_tokens():
    seen = []
    r = ClaudeCodeRunner(MODEL, execute=fake(lambda s: "REWRITTEN" if "Do not answer" in s else "done", seen),
                         context="prompt:deepen")
    got, _ = r.generate(_case())
    assert got == "done" and len(seen) == 2 and seen[1] == "REWRITTEN"
    assert r.context.digest == methods.REGISTRY["deepen"].extra["digest"]
    assert r.last_metrics["completion_tokens"] == 20 and r.last_metrics["turns"] == 2
    assert r.last_metrics["method_calls"] == 2


def test_the_runner_records_turns_and_every_input_token_kind():
    r = ClaudeCodeRunner(MODEL, execute=fake("ok", []))
    r.generate(_case())
    m = r.extra_metrics()
    assert (m["turns"], m["prompt_tokens"], m["cache_read_tokens"], m["completion_tokens"]) == (1, 100, 5, 10)


def test_the_candidate_spec_carries_the_context_option_into_the_repo_lane():
    r = run._repo_runner(NOCHANGE, "", 0)
    assert r.candidate == NOCHANGE and r.context.spec == "skill:no-change"
    assert run._repo_runner(f"{NONE},context=none", "", 0).candidate == NONE
    with pytest.raises(SystemExit, match="allowed: context"):
        run._repo_runner(f"{NONE},temperature=0", "", 0)
    with pytest.raises(SystemExit, match="context"):
        run._repo_runner(f"{NONE},context=skill:absent-995", "", 0)
    with pytest.raises(SystemExit, match="no context yet"):
        run._agent_runner(NOCHANGE, "", 0)
    assert run.split_candidates(f"{NONE},context=none,{NOCHANGE},{PLACEBO}") == [
        f"{NONE},context=none", NOCHANGE, PLACEBO]


def test_arms_default_to_three_repeats_and_a_plain_run_to_one():
    assert run.default_repeat(f"{NONE},context=none,{NOCHANGE}") == run.ARM_REPEAT == 3
    assert run.default_repeat(NONE) == 1 and run.default_repeat("") == 1
    assert run.parse_args(["--modality", "repo"]).repeat is None


def test_the_receipt_keeps_each_arms_context_and_digest():
    r = run._repo_runner(NOCHANGE, "", 0)
    got = run.context_receipts([(NOCHANGE, r, []), (NONE, run._repo_runner(NONE, "", 0), [])])
    assert list(got) == [NOCHANGE] and got[NOCHANGE]["digest"] == r.context.digest
    rec = Receipt(modality="repo", case_ids=(), repeat=3, sampling={}, gateway="", contexts=got)
    assert Receipt.from_dict(rec.as_dict()).contexts == got


def test_two_runs_of_one_arm_spec_with_different_skill_text_are_told_apart():
    runs = [{"receipt": {"contexts": {NOCHANGE: {"spec": "skill:no-change", "digest": d}}}} for d in ("a", "b")]
    assert R.sent(runs[0], NOCHANGE)["context"] != R.sent(runs[1], NOCHANGE)["context"]


# ---- the frozen task split ---------------------------------------------------------

def test_the_manifest_split_is_the_seeded_draw_and_every_task_is_on_one_side():
    m = history.manifest()
    assert m["split"] == history.split(m["tasks"])
    ids = [t["id"] for t in m["tasks"]]
    assert sorted(m["split"]["dev"] + m["split"]["holdout"]) == sorted(ids)
    assert m["split"]["seed"] == history.SPLIT_SEED


def test_a_side_is_the_fix_alone_so_a_new_task_moves_no_old_one():
    m = history.manifest()
    before = history.split(m["tasks"])
    after = history.split(m["tasks"] + [{"id": "sohot-new", "fix": "f" * 40}])
    for side in ("dev", "holdout"):
        assert set(before[side]) <= set(after[side])


def test_both_variants_of_a_task_land_on_the_same_side():
    from evals.core import load_cases
    from evals.importers import CASES
    cases = load_cases(CASES / "repo")
    split = holdout.assign("repo", cases)
    assert not split.too_small and split.version == holdout.version("repo") != holdout.VERSION
    sides: dict = {}
    for c in cases:
        if holdout.task_of(c):
            sides.setdefault(c.params["fix"], set()).add(split.side(c.id))
    assert sides and all(len(s) == 1 for s in sides.values())
    assert {c.id for c in holdout.only(cases, "holdout")} == set(split.holdout)


def test_a_lane_without_tasks_keeps_the_per_case_draw():
    cases = [Case(id=f"c{i}", modality="code", prompt=str(i)) for i in range(20)]
    split = holdout.assign("code", cases)
    assert split.version == holdout.VERSION and len(split.holdout) + len(split.dev) == 20


# ---- the arms report and its controls ----------------------------------------------

def _tasks(n):
    return [SimpleNamespace(id=f"t{t}-{v}", params={"fix": f"{t:040x}", "variant": v})
            for t in range(n) for v in history.VARIANTS]


def _runs(ctx: dict):
    return [{"id": 1, "lane": "repo", "repeat": 3, "cases_digest": "d", "generated_at": None, "environment": {},
             "receipt": {"modality": "repo", "contexts": ctx}}]


def _controls(seed: int, tasks: int = 19, repeat: int = 3, arms_=(NONE, NOCHANGE, PLACEBO)):
    """Rows from the real runner over a fake model that obeys a context and is otherwise a coin of rate p_task."""
    rng = random.Random(seed)
    rate = {t: rng.choice((0.0, 0.2, 0.4, 0.6, 0.8)) for t in range(tasks)}
    rows, ctx = [], {}
    for spec in arms_:
        model, context = run.claude_code_parts(spec)
        sent = []
        r = ClaudeCodeRunner(model, context=context, execute=fake(
            lambda s: "NO CHANGE" if "NO CHANGE" in s else ("FIX" if rng.random() < rate[int(s.split()[-1])] else "x"),
            sent))
        if r.context.kind != "none":
            ctx[r.candidate] = r.context.as_receipt()
        for t in range(tasks):
            for v in history.VARIANTS:
                for i in range(1, repeat + 1):
                    reply, _ = r.generate(_case(f"task {t}"))
                    rows.append({"run_id": 1, "candidate": r.candidate, "case_id": f"t{t}-{v}#{i}",
                                 "repeat_index": i, "passed": reply == "FIX", "failure_class": "",
                                 "seconds": 1.0, "metrics": dict(r.last_metrics)})
    return _runs(ctx), rows, _tasks(tasks)


def test_the_known_answer_skill_scores_below_none_and_the_placebo_does_not_differ():
    runs, rows, cases = _controls(995)
    rep = A.report(runs, rows, cases, resamples=200)
    assert rep["baseline"] == NONE and rep["contexts"][NOCHANGE]["spec"] == "skill:no-change"
    side = rep["sides"]["all"]
    no = side["arms"][NOCHANGE]
    assert no["rate"]["all"] == 0.0 and no["sign"]["p"] <= rep["alpha"]
    assert no["verdict"] == "differs: lower" and no["vs"]["all"]["high"] < 0
    pl = side["arms"][PLACEBO]
    assert pl["sign"]["p"] > rep["alpha"] and not pl["verdict"].startswith("differs")
    assert pl["vs"]["all"]["low"] <= 0 <= pl["vs"]["all"]["high"]
    assert side["arms"][NOCHANGE]["cost"]["turns"] == 1.0 and side["arms"][NONE]["cost"]["tokens_in"] == 105
    text = A.text(rep)
    assert "holdout:" in text and "(held out; quote these)" in text and "differs: lower" in text


def test_a_placebo_rarely_differs_from_none_across_seeds():
    false = 0
    for seed in range(60):
        runs, rows, cases = _controls(seed, tasks=12, repeat=2, arms_=(NONE, PLACEBO))
        rep = A.report(runs, rows, cases, resamples=1)
        false += rep["sides"]["all"]["arms"][PLACEBO]["verdict"].startswith("differs")
    assert false / 60 <= 0.1


def test_an_underpowered_null_is_never_called_no_effect():
    runs, rows, cases = _controls(3, tasks=6, repeat=1, arms_=(NONE, PLACEBO))
    pl = A.report(runs, rows, cases, resamples=20)["sides"]["all"]["arms"][PLACEBO]
    assert not pl["power"]["enough"] and pl["verdict"].startswith("underpowered")
    assert "not evidence of no effect" in pl["verdict"]


def test_repeats_are_replicates_so_a_task_counts_once_however_many_draws():
    runs, rows, cases = _controls(5, tasks=19, repeat=3)
    side = A.report(runs, rows, cases, resamples=20)["sides"]["all"]
    sg = side["arms"][PLACEBO]["sign"]
    assert sg["higher"] + sg["lower"] + sg["tied"] == side["tasks"] == 19
    assert side["arms"][NONE]["draws"] == 19 * 2 * 3


def test_the_held_out_side_is_reported_on_its_own_tasks():
    runs, rows, cases = _controls(7)
    rep = A.report(runs, rows, cases, resamples=20)
    hold = {t for t in range(19) if history.side_of(f"{t:040x}") == "holdout"}
    assert rep["sides"]["holdout"]["tasks"] == len(hold) and rep["sides"]["dev"]["tasks"] == 19 - len(hold)


def test_the_symptom_hypothesis_is_a_paired_interaction_over_tasks():
    tasks = 19
    rows, cases = [], _tasks(tasks)
    for t in range(tasks):
        for v in history.VARIANTS:
            rows += [{"run_id": 1, "candidate": NONE, "case_id": f"t{t}-{v}", "passed": v == "spec",
                      "failure_class": "", "metrics": {}, "seconds": 0},
                     {"run_id": 1, "candidate": NOCHANGE, "case_id": f"t{t}-{v}", "passed": True,
                      "failure_class": "", "metrics": {}, "seconds": 0}]
    g = A.report(_runs({}), rows, cases, resamples=50)["sides"]["all"]["arms"][NOCHANGE][
        "symptom_gain_minus_spec_gain"]
    assert g["higher"] == tasks and g["p"] < 0.001 and g["difference"] == 1.0


def test_a_baseline_can_be_named_by_context_spec():
    runs, rows, cases = _controls(1, tasks=6, repeat=1)
    assert A.report(runs, rows, cases, baseline="placebo:skill:no-change", resamples=5)["baseline"] == PLACEBO
    with pytest.raises(R.Refused, match="matches 0 arms"):
        A.report(runs, rows, cases, baseline="skill:other", resamples=5)


# ---- the plan ----------------------------------------------------------------------

def test_the_plan_is_power_on_the_baselines_task_rates_per_side():
    from harness import power
    cases = _tasks(19)
    runs, rows, _ = _controls(11, tasks=19, repeat=1, arms_=(NONE,))
    p = A.plan(cases, runs, rows, effect=0.2)
    assert p["baseline"] == NONE and not p["unseen"] and p["rho"] is None
    hold = sorted(f"{t:040x}" for t in range(19) if history.side_of(f"{t:040x}") == "holdout")
    by = {}
    for r in rows:
        by.setdefault(f"{int(r['case_id'].split('-')[0][1:]):040x}", []).append(int(r["passed"]))
    rates = [sum(by[t]) / len(by[t]) for t in hold]
    want = power.plan(rates, 0.2, rho=None, observed=len(hold) * 2)
    got = p["sides"]["holdout"]
    assert (got["tasks"], got["repeat"], got["tasks_needed"]) == (len(hold), want.repeat, want.cases_needed)
    assert got["too_small"] == power.too_small(want)
    assert "tasks needed" in A.plan_text(p)


def test_the_plan_with_no_runs_assumes_unseen_rates_and_counts_a_spec_only_task():
    cases = _tasks(10) + [SimpleNamespace(id="lone", params={"fix": "e" * 40, "variant": "spec"})]
    p = A.plan(cases)
    assert p["unseen"] and p["sides"]["all"]["tasks"] == 11


def test_soh_repo_report_arms_and_plan_read_the_store(store_run, tmp_path, capsys):
    from harness import cli
    from harness import memory_store as ms
    import yaml
    d = tmp_path / "cases"
    d.mkdir()
    cases = _tasks(8)
    for c in cases:
        params = {**c.params, "source_repo": "https://example.invalid/r.git", "base": "0" * 40,
                  "fail_to_pass": ["tests/test_x.py::t"], "context_files": ["x.py"], "context": "oracle"}
        (d / f"{c.id}.yaml").write_text(yaml.safe_dump({"id": c.id, "modality": "repo", "prompt": "p",
                                                        "params": params}), encoding="utf-8")
    from evals.core import cases_digest, load_cases
    runs, rows, _ = _controls(2, tasks=8, repeat=2)
    conn = ms.connect(tmp_path / "s.db")
    rid = store_run("arms", "repo", rows=[{k: r[k] for k in ("candidate", "case_id", "passed", "failure_class",
                                                                "seconds", "metrics")} for r in rows],
                    cases_digest=cases_digest(load_cases(d)), conn=conn,
                    receipt={"contexts": runs[0]["receipt"]["contexts"]})
    conn.close()
    args = ["--store", str(tmp_path / "s.db"), "--cases", str(d), "--resamples", "20", "--json"]
    assert cli.main(["repo-report", str(rid), "--arms", *args]) == 0
    got = json.loads(capsys.readouterr().out)
    assert got["baseline"] == NONE and got["sides"]["all"]["arms"][NOCHANGE]["draws"] == 8 * 2 * 2
    assert cli.main(["repo-report", "--plan", *args]) == 0
    assert json.loads(capsys.readouterr().out)["unseen"]
    assert cli.main(["repo-report", "--store", str(tmp_path / "s.db")]) == 1


def test_the_paired_unit_is_the_task_pass_rate_not_whether_any_draw_passed():
    rows = []
    for t in range(8):
        for v in history.VARIANTS:
            for i in (1, 2, 3):
                rows += [{"run_id": 1, "candidate": NONE, "case_id": f"t{t}-{v}#{i}", "repeat_index": i,
                          "passed": i == 1, "failure_class": "", "metrics": {}, "seconds": 0},
                         {"run_id": 1, "candidate": NOCHANGE, "case_id": f"t{t}-{v}#{i}", "repeat_index": i,
                          "passed": True, "failure_class": "", "metrics": {}, "seconds": 0}]
    sg = A.report(_runs({}), rows, _tasks(8), resamples=20)["sides"]["all"]["arms"][NOCHANGE]["sign"]
    assert (sg["higher"], sg["tied"], sg["p"]) == (8, 0, 0.0078)


def test_a_cost_the_rows_never_recorded_is_unknown_not_zero():
    rows = [{"run_id": 1, "candidate": c, "case_id": f"t{t}-{v}", "passed": False, "failure_class": "",
             "metrics": {"completion_tokens": 7} if c == NONE else {}, "seconds": 2.0}
            for t in range(4) for v in history.VARIANTS for c in (NONE, NOCHANGE)]
    arms_ = A.report(_runs({}), rows, _tasks(4), resamples=5)["sides"]["all"]["arms"]
    assert arms_[NONE]["cost"]["tokens_out"] == 7 and arms_[NOCHANGE]["cost"]["tokens_out"] is None
    assert arms_[NONE]["cost"]["tokens_in"] is None and arms_[NOCHANGE]["cost_vs"]["tokens_out"] is None
    assert "?" in A.text({**A.report(_runs({}), rows, _tasks(4), resamples=5)})


def test_a_spec_only_task_counts_for_the_arm_and_stays_out_of_the_symptom_interaction():
    tasks = 19
    rows, cases = [], _tasks(tasks) + [SimpleNamespace(id=f"s{t}-spec", params={"fix": f"{100 + t:040x}", "variant": "spec"})
                                       for t in range(5)]
    for c in cases:
        v = c.params["variant"]
        rows += [{"run_id": 1, "candidate": NONE, "case_id": c.id, "passed": v == "spec" and not c.id.startswith("s"),
                  "failure_class": "", "metrics": {}, "seconds": 0},
                 {"run_id": 1, "candidate": NOCHANGE, "case_id": c.id, "passed": True,
                  "failure_class": "", "metrics": {}, "seconds": 0}]
    rep = A.report(_runs({}), rows, cases, resamples=50)
    arm = rep["sides"]["all"]["arms"][NOCHANGE]
    assert rep["sides"]["all"]["tasks"] == tasks + 5 and rep["set_aside"]["single_variant"] == []
    g = arm["symptom_gain_minus_spec_gain"]
    assert g["tasks"] == tasks and g["higher"] == tasks and g["lower"] == 0 and g["difference"] == 1.0
