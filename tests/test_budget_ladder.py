"""A budget ladder retries a reply cut off at its budget at the next larger one. #668."""
import argparse
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from evals import core, environment
from evals import run as R
from evals.core import Case, Receipt, Result, comparable, summarize
from evals.runners.base import BaseRunner
from harness import completion, context, delegate, paired, reasons, runs
from harness import memory_store as ms

ROOT = Path(__file__).resolve().parents[1]
GW = "http://gw.test"
CODE = Case("add-two", "code", "write add", assertions={"checks": ["add(1, 2) == 3"]})
LADDER = (4000, 16000, 32000, 65536)


def _receipt(**kw):
    base = dict(modality="code", case_ids=("a",), repeat=1, sampling={}, gateway=GW)
    return Receipt(**{**base, **kw})


class Scripted(BaseRunner):
    """Answers each budget as scripted: "pass", "wrong" or "cut"."""

    def __init__(self, script, default="cut"):
        self.candidate = self.spec = "org/x"
        self.script, self.default = dict(script), default
        self.max_tokens = 0
        self.asked = []

    def run(self, case):
        self.asked.append(self.max_tokens)
        how = self.script.get(self.max_tokens, self.default)
        if how == "pass":
            return Result(case.id, self.candidate, True, 2.0, 0, "",
                          metrics={"completion_tokens": self.max_tokens // 2})
        if how == "wrong":
            return Result(case.id, self.candidate, False, 3.0, 0, "0/1 checks passed",
                          failure_class=reasons.CONTENT_FAILED,
                          metrics={"completion_tokens": 100})
        return Result(case.id, self.candidate, False, 5.0, 0,
                      f"spent the whole {self.max_tokens}-token budget",
                      failure_class=reasons.TOKEN_BUDGET_EXHAUSTED,
                      limit=f"max_tokens.code>{self.max_tokens}")


def test_each_lane_has_a_default_ladder_beside_its_budget():
    assert set(completion.LADDER) == set(completion.BUDGET)
    assert completion.ladder("code") == LADDER
    assert completion.ladder("image") == ()
    for lane, rungs in completion.LADDER.items():
        assert list(rungs) == sorted(set(rungs)) and len(rungs) > 1, lane


def test_the_run_ladder_is_none_unless_asked_and_the_lanes_when_asked_bare():
    assert R.run_ladder("code", None) == ()
    assert R.run_ladder("code", "default") == LADDER
    assert R.run_ladder("code", "4000, 16000") == (4000, 16000)
    assert R.run_ladder("image", "4000,16000") == ()
    for bad in ("16000,4000", "4000,4000", "0,4000", "4k", "4000"):
        with pytest.raises(SystemExit):
            R.run_ladder("code", bad)


def test_budget_ladder_is_a_flag_of_the_eval_command():
    seen = []
    real = R._execute
    R._execute = lambda args: seen.append(args.budget_ladder) or 0
    try:
        R.main(["--modality", "code", "--candidates", "org/x", "--budget-ladder", "4000,16000"])
        R.main(["--modality", "code", "--candidates", "org/x", "--budget-ladder"])
        R.main(["--modality", "code", "--candidates", "org/x"])
    finally:
        R._execute = real
    assert seen == ["4000,16000", "default", None]


def test_an_exhausted_reply_escalates_to_the_next_rung():
    runner = Scripted({4000: "cut", 16000: "pass"})
    row = R.climb(runner, CODE, LADDER)
    assert runner.asked == [4000, 16000]
    assert row.passed
    assert [a["max_tokens"] for a in row.attempts] == [4000, 16000]


def test_a_pass_does_not_escalate():
    runner = Scripted({4000: "pass"})
    row = R.climb(runner, CODE, LADDER)
    assert runner.asked == [4000] and row.passed and len(row.attempts) == 1


def test_a_wrong_answer_does_not_escalate():
    runner = Scripted({4000: "cut", 16000: "wrong"})
    row = R.climb(runner, CODE, LADDER)
    assert runner.asked == [4000, 16000]
    assert row.failure_class == reasons.CONTENT_FAILED


def test_the_ladder_stops_at_its_top_rung():
    runner = Scripted({})
    row = R.climb(runner, CODE, LADDER)
    assert runner.asked == list(LADDER)
    assert row.failure_class == reasons.TOKEN_BUDGET_EXHAUSTED
    assert row.limit == "max_tokens.code>65536"


def test_the_attempts_are_on_the_row_and_its_seconds_are_their_sum():
    row = R.climb(Scripted({16000: "pass"}), CODE, LADDER)
    assert row.attempts == [
        {"max_tokens": 4000, "tokens": 4000, "seconds": 5.0,
         "passed": False, "failure_class": reasons.TOKEN_BUDGET_EXHAUSTED},
        {"max_tokens": 16000, "tokens": 8000, "seconds": 2.0,
         "passed": True, "failure_class": ""}]
    assert row.seconds == 7.0


def test_the_rungs_are_capped_by_the_served_context_less_the_prompt():
    assert R.rungs_for(LADDER, None) == LADDER
    assert R.rungs_for(LADDER, 262144) == LADDER
    assert R.rungs_for(LADDER, 40000) == (4000, 16000, 32000, 40000)
    prompt = "x" * (delegate.CHARS_PER_TOKEN * 1000)
    assert R.rungs_for(LADDER, 40000, prompt) == (4000, 16000, 32000, 39000)
    assert R.rungs_for(LADDER, 32000) == (4000, 16000, 32000)
    assert R.rungs_for(LADDER, 3000) == (3000,)


def test_the_ladder_stops_at_the_served_context_cap():
    runner = Scripted({})
    row = R.climb(runner, CODE, R.rungs_for(LADDER, 20000, CODE.prompt))
    cap = delegate.cap(20000, CODE.prompt)
    assert runner.asked == [4000, 16000, cap]
    assert row.limit == f"max_tokens.code>{cap}"


def test_the_ladder_sets_a_method_runners_base_budget():
    runner = R.build_runner("best-of:3:local-large", "", None, max_tokens=4000)
    R.set_budget(runner, 16000)
    assert runner.max_tokens == 16000 and runner.base.max_tokens == 16000


def test_the_receipt_carries_the_ladder():
    got = _receipt(max_tokens=65536, budget_ladder=LADDER).as_dict()
    assert got["budget_ladder"] == list(LADDER)
    assert Receipt.from_dict(got).budget_ladder == LADDER
    old = _receipt(max_tokens=32768).as_dict()
    old.pop("budget_ladder")
    assert Receipt.from_dict(old).budget_ladder == ()


def test_comparable_refuses_a_ladder_against_a_single_budget():
    ladder = _receipt(max_tokens=65536, budget_ladder=LADDER)
    ok, why = comparable(ladder, _receipt(max_tokens=65536))
    assert not ok and "budget ladder" in why
    ok, why = comparable(ladder, _receipt(max_tokens=65536, budget_ladder=(16000, 65536)))
    assert not ok and "budget ladder" in why
    assert comparable(ladder, _receipt(max_tokens=65536, budget_ladder=LADDER))[0]


def test_a_ladder_is_an_axis_the_across_comparison_names():
    assert "budget_ladder" in paired.AXES
    got = paired.differences(_receipt(max_tokens=65536, budget_ladder=LADDER),
                             _receipt(max_tokens=65536))
    assert got == ["budget_ladder"]


def _laddered(cid, passed, rungs, secs=1.0):
    attempts = [{"max_tokens": m, "tokens": m, "seconds": secs,
                 "passed": passed and i == len(rungs) - 1,
                 "failure_class": "" if passed and i == len(rungs) - 1
                 else reasons.TOKEN_BUDGET_EXHAUSTED}
                for i, m in enumerate(rungs)]
    return Result(cid, "m", passed, secs * len(rungs), 0, "" if passed else "cut",
                  failure_class="" if passed else reasons.TOKEN_BUDGET_EXHAUSTED,
                  attempts=attempts)


def test_the_summary_shows_pass_rate_by_rung():
    rows = [_laddered("a", True, (4000,)), _laddered("b", True, (4000, 16000)),
            _laddered("c", False, (4000, 16000))]
    got = summarize(rows)["m"]["by_rung"]
    assert got == {"4000": {"tried": 3, "passed": 1, "seconds": 3.0},
                   "16000": {"tried": 2, "passed": 1, "seconds": 2.0}}
    assert "by_rung" not in summarize([Result("a", "n", True, 1.0, 0, "")])["n"]


def test_the_report_prints_pass_by_rung(capsys):
    rows = [_laddered("a", True, (4000,)), _laddered("b", True, (4000, 16000))]
    R.report(summarize(rows))
    out = capsys.readouterr().out
    assert "pass by rung" in out
    line = next(line for line in out.splitlines() if line.strip().startswith("m: 4000"))
    assert "4000 1/2" in line and "16000 1/1" in line


@pytest.fixture
def quiet_receipt(monkeypatch):
    for name, value in (("accelerator_id", "unified:test"), ("where_id", "test"),
                        ("swap_used_mb", 0), ("instruments", {}), ("engines", {})):
        monkeypatch.setattr(R, name, lambda *a, _v=value, **k: _v)
    monkeypatch.setattr(ms.machines, "_THIS_MACHINE", None)
    monkeypatch.setattr(environment, "capture", lambda: {})
    monkeypatch.setattr(R, "warn_if_pressed", lambda *a, **k: SimpleNamespace(
        as_dict=lambda: {}))


def _args(tmp_path, **kw):
    base = dict(screen=False, repeat=1, adherence="", cases=str(ROOT / "evals" / "cases"),
                modality="code", candidates="org/x", from_winners=False, gateway=GW,
                out=str(tmp_path / "out"), split="all", max_tokens=None,
                budget_ladder="4000,16000")
    return argparse.Namespace(**{**base, **kw})


def test_a_laddered_run_records_the_ladder_and_each_rows_attempts(tmp_path, monkeypatch,
                                                                   quiet_receipt):
    monkeypatch.setattr(R, "build_runner", lambda *a, **k: Scripted({16000: "pass"}))
    monkeypatch.setattr(context, "served_ctx", lambda spec, *a, **k: None)
    R._execute(_args(tmp_path))
    data = json.loads((tmp_path / "out" / "results.json").read_text(encoding="utf-8"))
    assert data["receipt"]["budget_ladder"] == [4000, 16000]
    assert data["receipt"]["max_tokens"] == 16000
    row = data["rows"][0]
    assert [a["max_tokens"] for a in row["attempts"]] == [4000, 16000]
    conn = ms.connect()
    try:
        run = runs.at(conn, tmp_path / "out")
        stored = runs.rows(conn, run["id"])
    finally:
        conn.close()
    assert [a["max_tokens"] for a in stored[0]["attempts"]] == [4000, 16000]


def test_a_laddered_run_caps_its_rungs_at_the_candidates_served_context(
        tmp_path, monkeypatch, quiet_receipt):
    runner = Scripted({})
    monkeypatch.setattr(R, "build_runner", lambda *a, **k: runner)
    monkeypatch.setattr(context, "served_ctx", lambda spec, *a, **k: 10000)
    R._execute(_args(tmp_path, budget_ladder="4000,16000,32000"))
    tops = set(runner.asked) - {4000}
    assert 4000 in runner.asked and tops and all(4000 < t < 10000 for t in tops)


def test_a_ladder_and_a_single_budget_are_refused_together(tmp_path, monkeypatch, quiet_receipt):
    monkeypatch.setattr(R, "build_runner", lambda *a, **k: Scripted({}))
    with pytest.raises(SystemExit, match="budget-ladder"):
        R._execute(_args(tmp_path, max_tokens=16000))


def test_a_run_with_no_ladder_has_no_attempts(tmp_path, monkeypatch, quiet_receipt):
    monkeypatch.setattr(R, "build_runner", lambda *a, **k: Scripted({0: "pass"}))
    R._execute(_args(tmp_path, budget_ladder=None))
    data = json.loads((tmp_path / "out" / "results.json").read_text(encoding="utf-8"))
    assert data["receipt"]["budget_ladder"] == []
    assert data["rows"][0]["attempts"] == []


@pytest.mark.gauntlet("a-closed-table-fronting-an-open-set", site="harness/completion.py:LADDER")
def test_every_lane_that_generates_text_has_a_ladder():
    for lane in sorted(core.TEXT_MODALITIES | core.AGENT_MODALITIES):
        assert completion.ladder(lane), lane
