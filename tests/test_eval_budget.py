"""The eval reply budget is a recorded run setting, and running out of it is not a wrong answer. #628."""
import argparse
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
import respx

from evals import core, environment
from evals import run as R
from evals.core import Case, Receipt, Result, comparable, summarize
from evals.runners.base import BaseRunner
from evals.runners.text import CompletionRunner
from harness import completion, paired, reasons
from harness import memory_store as ms

ROOT = Path(__file__).resolve().parents[1]
GW = "http://gw.test"
URL = f"{GW}/v1/chat/completions"
CODE = Case("add-two", "code", "write add", assertions={"checks": ["add(1, 2) == 3"]})


def _reply(text, reasoning=None, finish="stop", tokens=3):
    msg = {"content": text}
    if reasoning:
        msg["reasoning_content"] = reasoning
    return httpx.Response(200, json={"choices": [{"message": msg, "finish_reason": finish}],
                                     "usage": {"completion_tokens": tokens}},
                          request=httpx.Request("POST", URL))


def _receipt(**kw):
    base = dict(modality="code", case_ids=("a",), repeat=1, sampling={}, gateway=GW)
    return Receipt(**{**base, **kw})


def test_the_code_lane_is_budgeted_for_a_reasoning_model_and_the_rest_keep_theirs():
    assert completion.budget("code") == 32768
    assert completion.budget("agent") == 8000
    for lane in ("svg", "web", "extract", "decide"):
        assert completion.budget(lane) == completion.MAX_TOKENS
    assert completion.budget("image") == 0


def test_a_bigger_budget_gets_a_request_timeout_it_can_finish_in():
    assert completion.timeout_for(completion.MAX_TOKENS) == completion.TIMEOUT_S
    assert completion.timeout_for(32768) >= 32768 / completion.MIN_DECODE_TOK_S


@respx.mock
def test_the_runner_asks_with_its_budget_and_a_timeout_sized_for_it(monkeypatch):
    route = respx.post(URL).mock(return_value=_reply("def add(a, b): return a + b"))
    runner = CompletionRunner(GW, "org/x", max_tokens=16000)
    runner.generate(CODE)
    assert json.loads(route.calls[0].request.content)["max_tokens"] == 16000
    seen = []
    monkeypatch.setattr(completion, "_post",
                        lambda gw, payload, timeout: seen.append(timeout) or _reply("x"))
    runner.generate(CODE)
    assert seen == [completion.timeout_for(16000)]


@respx.mock
def test_a_runner_with_no_budget_named_takes_its_lanes():
    route = respx.post(URL).mock(return_value=_reply("def add(a, b): return a + b"))
    CompletionRunner(GW, "org/x").generate(CODE)
    assert json.loads(route.calls[0].request.content)["max_tokens"] == completion.budget("code")


@respx.mock
def test_null_content_at_the_budget_names_the_lanes_limit():
    respx.post(URL).mock(return_value=_reply(None, reasoning="x" * 99, finish="length"))
    row = CompletionRunner(GW, "org/x", max_tokens=16000).run(CODE)
    assert row.failure_class == reasons.TOKEN_BUDGET_EXHAUSTED
    assert row.limit == "max_tokens.code>16000"


@respx.mock
def test_an_answer_cut_off_at_the_budget_is_a_limit_not_a_wrong_answer():
    respx.post(URL).mock(return_value=_reply("def add(a, b):\n    return a -", finish="length",
                                             tokens=16000))
    row = CompletionRunner(GW, "org/x", max_tokens=16000).run(CODE)
    assert not row.passed
    assert row.failure_class == reasons.TOKEN_BUDGET_EXHAUSTED
    assert row.limit == "max_tokens.code>16000"


@respx.mock
def test_a_cut_off_answer_that_still_passes_is_a_pass():
    respx.post(URL).mock(return_value=_reply("def add(a, b):\n    return a + b\n", finish="length"))
    row = CompletionRunner(GW, "org/x", max_tokens=16000).run(CODE)
    assert row.passed and not row.failure_class and not row.limit


@respx.mock
def test_a_wrong_answer_that_finished_is_still_wrong():
    respx.post(URL).mock(return_value=_reply("def add(a, b):\n    return a - b\n"))
    row = CompletionRunner(GW, "org/x", max_tokens=16000).run(CODE)
    assert row.failure_class == reasons.CONTENT_FAILED and not row.limit


def test_the_lane_budgets_are_limits_a_retest_can_read():
    got = reasons.limits()
    assert got["max_tokens.code"] == completion.budget("code")
    assert got["max_tokens.svg"] == completion.MAX_TOKENS
    assert got["max_tokens"] == completion.MAX_TOKENS
    assert ms.until_met("limit:max_tokens.code>4000", {"limits": got})
    assert not ms.until_met("limit:max_tokens.svg>4000", {"limits": got})


def test_the_budget_is_on_the_receipt():
    assert _receipt(max_tokens=32768).as_dict()["max_tokens"] == 32768


def test_a_receipt_from_before_the_budget_was_recorded_ran_at_the_old_constant():
    raw = _receipt(max_tokens=1).as_dict()
    raw.pop("max_tokens")
    assert Receipt.from_dict(raw).max_tokens == 4000
    assert Receipt.from_dict({**raw, "modality": "agent"}).max_tokens == 8000
    assert Receipt.from_dict({**raw, "modality": "image"}).max_tokens == 0
    assert Receipt.from_dict({**raw, "max_tokens": 16000}).max_tokens == 16000


def test_runs_at_different_budgets_are_not_ranked_together():
    ok, why = comparable(_receipt(max_tokens=4000), _receipt(max_tokens=32768))
    assert not ok and "reply budget" in why
    assert comparable(_receipt(max_tokens=32768), _receipt(max_tokens=32768))[0]


def test_a_budget_sweep_is_an_axis_the_across_comparison_names():
    assert "max_tokens" in paired.AXES
    assert paired.differences(_receipt(max_tokens=4000), _receipt(max_tokens=16000)) == [
        "max_tokens"]


def test_the_run_budget_is_the_lanes_unless_the_run_names_one():
    assert R.run_budget("code", None) == 32768
    assert R.run_budget("code", 16000) == 16000
    assert R.run_budget("agent", None) == 8000
    assert R.run_budget("image", 16000) == 0
    with pytest.raises(SystemExit, match="at least 1"):
        R.run_budget("code", 0)


def test_max_tokens_is_a_flag_of_the_eval_command():
    seen = {}
    real = R._execute

    def capture(args):
        seen["max_tokens"] = args.max_tokens
        return 0

    R._execute = capture
    try:
        R.main(["--modality", "code", "--candidates", "org/x", "--max-tokens", "16000"])
    finally:
        R._execute = real
    assert seen["max_tokens"] == 16000


def test_build_runner_hands_the_budget_to_a_text_runner():
    runner = R.build_runner("local-large", "", None, max_tokens=16000)
    assert runner.max_tokens == 16000


def test_a_method_runner_passes_the_budget_to_its_base():
    runner = R.build_runner("best-of:3:local-large", "", None, max_tokens=16000)
    assert runner.base.max_tokens == 16000


def _row(cid, passed, cls="", limit="", detail="x"):
    return Result(cid, "m", passed, 1.0, 0, "" if passed else detail,
                  failure_class=cls, limit=limit)


def test_the_summary_counts_budget_apart_from_wrong():
    rows = [_row("a", True),
            _row("b", False, reasons.CONTENT_FAILED, detail="0/3 checks passed"),
            _row("c", False, reasons.TOKEN_BUDGET_EXHAUSTED, "max_tokens.code>4000",
                 detail="m returned no answer: it spent the whole 4000-token budget"),
            _row("d", False, reasons.TOKEN_BUDGET_EXHAUSTED, "max_tokens.code>4000",
                 detail="2/3 checks passed")]
    got = summarize(rows)["m"]
    assert (got["budget"], got["wrong"], got["empty"], got["errored"]) == (2, 1, 0, 0)


def test_the_comparison_table_shows_budget_and_wrong_as_columns(capsys):
    rows = [_row("a", True),
            _row("b", False, reasons.CONTENT_FAILED, detail="0/3 checks passed"),
            _row("c", False, reasons.TOKEN_BUDGET_EXHAUSTED, "max_tokens.code>4000")]
    R.report(summarize(rows))
    out = capsys.readouterr().out
    header = next(line for line in out.splitlines() if line.startswith("candidate"))
    assert "budget" in header and "wrong" in header
    line = next(line for line in out.splitlines() if line.startswith("m "))
    cells = line.split()
    at = header.split()
    assert cells[at.index("budget") - len(at)] == "1"
    assert cells[at.index("wrong") - len(at)] == "1"


@pytest.fixture
def quiet_receipt(monkeypatch):
    for name, value in (("accelerator_id", "unified:test"), ("where_id", "test"),
                        ("swap_used_mb", 0), ("instruments", {}), ("engines", {})):
        monkeypatch.setattr(R, name, lambda *a, _v=value, **k: _v)
    monkeypatch.setattr(ms.machines, "_THIS_MACHINE", None)
    monkeypatch.setattr(environment, "capture", lambda: {})
    monkeypatch.setattr(R, "warn_if_pressed", lambda *a, **k: SimpleNamespace(
        as_dict=lambda: {}))


class Answers(BaseRunner):
    def __init__(self):
        self.candidate = self.spec = "org/x"

    def generate(self, case):
        return "", 0


def test_a_run_records_the_budget_it_ran_at(tmp_path, monkeypatch, quiet_receipt):
    seen = {}

    def build(candidate, gateway, outdir, adherence=None, modality="", max_tokens=0):
        seen["max_tokens"] = max_tokens
        return Answers()

    monkeypatch.setattr(R, "build_runner", build)
    args = argparse.Namespace(
        screen=False, repeat=1, adherence="", cases=str(ROOT / "evals" / "cases"),
        modality="code", candidates="org/x", from_winners=False, gateway=GW,
        out=str(tmp_path / "out"), split="all", max_tokens=16000)
    R._execute(args)
    data = json.loads((tmp_path / "out" / "results.json").read_text(encoding="utf-8"))
    assert data["receipt"]["max_tokens"] == 16000
    assert seen["max_tokens"] == 16000


def test_compare_refuses_two_stored_runs_at_different_budgets(tmp_path, capsys):
    files = []
    for n, budget in ((1, 4000), (2, 32768)):
        f = tmp_path / f"r{n}" / "results.json"
        f.parent.mkdir()
        f.write_text(json.dumps({"receipt": _receipt(max_tokens=budget).as_dict(),
                                 "summary": {}, "rows": []}), encoding="utf-8")
        files.append(str(f))
    assert R.compare_runs(files) == 1
    assert "reply budget" in capsys.readouterr().out



@pytest.mark.gauntlet("a-closed-table-fronting-an-open-set", site="harness/completion.py:BUDGET")
def test_every_lane_that_generates_text_has_a_budget():
    for lane in sorted(core.TEXT_MODALITIES | core.AGENT_MODALITIES):
        assert completion.budget(lane) > 0, lane
    assert set(completion.BUDGET) == core.TEXT_MODALITIES | core.AGENT_MODALITIES
