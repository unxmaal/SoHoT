"""#955: a reply cut at the token budget that loops or collapses is the candidate's failure, not a limit."""
import json
import zlib

import httpx
import pytest
import respx

from evals import core
from evals import run as R
from evals.core import Case
from evals.runners.text import CompletionRunner
from harness import cli, degenerate as dg, reasons, screen
from harness import memory_store as ms
from harness.commands import degenerate as cmd

GW = "http://gw.test"
URL = f"{GW}/v1/chat/completions"
CODE = Case("add-two", "code", "write add", assertions={"checks": ["add(1, 2) == 3"]})
ROWS = dg.load()
#: The three screens the #918 audit labelled the model's, by run directory.
#: A stored budget-cut reply that is one character repeated.
LOOP = next(r["tail"] for r in ROWS if r["run"] == "screen-1791854855-code" and r["case_id"] == "evaluate-expr")
LABELLED_MODEL = ("screen-1791806973-code", "screen-1791854855-code", "screen-1791940053-code")


def _row(run, case_id):
    return next(r for r in ROWS if r["run"] == run and r["case_id"] == case_id)


def _reply(text, finish="length", tokens=32768):
    return httpx.Response(200, json={"choices": [{"message": {"content": text}, "finish_reason": finish}],
                                     "usage": {"completion_tokens": tokens}},
                          request=httpx.Request("POST", URL))


def _ran(text, case=CODE, candidate="org/x", max_tokens=32768):
    with respx.mock:
        respx.post(URL).mock(return_value=_reply(text, tokens=max_tokens))
        row = CompletionRunner(GW, "org/x", max_tokens=max_tokens).run(case)
    row.candidate = candidate
    return row


def _replay(r, **kw):
    # The fixture keeps the measured tail; the stored reply began with text before it, as this head does.
    return _ran("```python\n" + r["tail"], **kw)


def _content_failure(candidate, case_id):
    return core.Result(case_id, candidate, False, 1.0, 0, "wrong", failure_class=reasons.CONTENT_FAILED)


def test_the_constants_are_the_fit_and_every_label_agrees():
    fitted = dg.fit(ROWS)
    assert fitted["counts"][dg.DEGENERATE] == 16 and fitted["counts"][dg.CUT_OFF] == 4
    assert fitted["counts"][dg.NATURAL] >= 30
    assert dg.REPEAT_SHARE == pytest.approx(fitted["repeat"], abs=0.001)
    assert dg.ENTROPY_BITS == pytest.approx(fitted["entropy"], abs=0.001)
    assert fitted["repeat_margin"] > 0.1 and fitted["entropy_margin"] > 0.5
    assert dg.agreement(ROWS) == []


def test_the_hand_labelled_cut_offs_sit_far_from_both_thresholds():
    cut = [dg.measure(r["tail"]) for r in ROWS if r["label"] == dg.CUT_OFF]
    measured = [m for m in cut if m]
    assert len(measured) == 3
    assert max(m["tail_repeat"] for m in measured) < dg.REPEAT_SHARE - 0.5
    assert min(m["tail_entropy"] for m in measured) > dg.ENTROPY_BITS + 1.0


def test_one_compression_ratio_would_call_a_passing_reply_degenerate():
    def ratio(t):
        return len(zlib.compress(t.encode(), 9)) / len(t.encode())
    worst_bad = max(ratio(r["tail"]) for r in ROWS if r["label"] == dg.DEGENERATE)
    best_good = min(ratio(r["tail"]) for r in ROWS if r["label"] == dg.NATURAL)
    assert best_good < worst_bad


def test_no_passing_reply_in_the_control_reads_as_degenerate():
    natural = [r for r in ROWS if r["label"] == dg.NATURAL]
    assert natural and not any(dg.is_degenerate(dg.measure(r["tail"])) for r in natural)


@pytest.mark.parametrize("run", LABELLED_MODEL)
def test_the_audited_budget_screens_are_the_models_failure_with_no_limit(run):
    mine = [r for r in ROWS if r["run"] == run]
    rows = [_replay(r, candidate=r["candidate"]) for r in mine]
    assert {r.failure_class for r in rows} == {reasons.DEGENERATE}
    assert not any(r.limit for r in rows)
    assert all("tail_repeat" in r.metrics and "tail_entropy" in r.metrics for r in rows)
    if run == "screen-1791806973-code":
        rows += [_content_failure(mine[0]["candidate"], c) for c in ("chunk-bytes", "glob-match", "hevalpro-0")]
    got = screen.outcome(0, core.summarize(rows))
    assert (got.outcome, got.reason, got.until) == ("broken", reasons.CANDIDATE, "")
    assert not got.until.startswith("limit:")


@pytest.mark.parametrize("case_id", ["lc3197", "lc3017", "lc3382", "lc3235"])
def test_an_answer_cut_mid_work_stays_a_limit(case_id):
    r = next(r for r in ROWS if r["case_id"] == case_id)
    row = _replay(r)
    assert row.failure_class == reasons.TOKEN_BUDGET_EXHAUSTED
    assert row.limit == "max_tokens.code>32768"
    got = screen.outcome(0, core.summarize([row, _content_failure("org/x", "other")]))
    assert (got.outcome, got.reason, got.until) == ("declined", reasons.LIMIT, "limit:max_tokens.code>32768")


@pytest.mark.parametrize("run,case_id", [("20261014-232539-adopt-code", "lc3163"),
                                         ("20261014-234502-adopt-code", "lc3163"),
                                         ("screen-1792113135-code", "glob-match")])
def test_a_strong_or_a_small_model_that_loops_is_degenerate(run, case_id):
    assert _replay(_row(run, case_id)).failure_class == reasons.DEGENERATE


def test_a_reply_too_short_to_measure_stays_a_limit_though_its_entropy_reads_low():
    tail = _row("20261014-232539-adopt-code", "lc3235")["tail"]
    assert dg.entropy_bits(tail) <= dg.ENTROPY_BITS
    assert dg.measure(tail) == {}


def test_a_lane_the_threshold_was_not_fitted_on_keeps_every_cut_a_limit():
    loop = LOOP
    web = Case("page", "web", "write a page", assertions={})
    row = _ran(loop, case=web, max_tokens=4000)
    assert row.failure_class == reasons.TOKEN_BUDGET_EXHAUSTED and row.limit == "max_tokens.web>4000"


def test_a_reply_that_finished_is_never_measured():
    loop = LOOP
    with respx.mock:
        respx.post(URL).mock(return_value=_reply(loop, finish="stop", tokens=100))
        row = CompletionRunner(GW, "org/x", max_tokens=32768).run(CODE)
    assert row.failure_class == reasons.CONTENT_FAILED and "tail_repeat" not in row.metrics


def test_the_budget_ladder_does_not_climb_a_degenerate_reply():
    loop = LOOP
    runner = CompletionRunner(GW, "org/x")
    with respx.mock:
        respx.post(URL).mock(return_value=_reply(loop, tokens=4000))
        row = R.climb(runner, CODE, (4000, 16000))
    assert [a["max_tokens"] for a in row.attempts] == [4000]
    assert row.failure_class == reasons.DEGENERATE


def test_the_new_metrics_are_declared_and_never_ranked():
    assert core.direction_of("tail_repeat") == "neutral"
    assert core.direction_of("tail_entropy") == "neutral"


def _results(path, rows, candidate):
    path.mkdir(parents=True)
    summary = core.summarize(rows)
    stored = {"receipt": {"modality": "code"}, "summary": summary,
              "rows": [{**r.__dict__, "candidate": candidate} for r in rows]}
    (path / "results.json").write_text(json.dumps(stored, default=str), encoding="utf-8")


def _seed_screen(conn, name, run_path, until="limit:max_tokens.code>32768"):
    ms.record(conn, ms.Seen(name=name, source="s", kind="candidate", registry=ms.HUGGINGFACE,
                            lane="code", resolved=name))
    ms.decide(conn, name, "queued", tier="inspect", detail="fits")
    rid = conn.execute("INSERT INTO runs (path, lane, tier, recorded_at) VALUES (?, 'code', 'screen', 0)",
                       (run_path,)).lastrowid
    return ms.decide(conn, name, "declined", tier="screen", reason=reasons.LIMIT, until=until, run_id=rid)


def _raw(text, candidate, case_id, cls=reasons.TOKEN_BUDGET_EXHAUSTED):
    return core.Result(case_id, candidate, False, 1.0, 0, "syntax error", output=text,
                       failure_class=cls, limit="max_tokens.code>32768")


def test_redecide_moves_only_the_screens_their_degenerate_rows_decide(tmp_path):
    loop = LOOP
    cut = _row("20261014-234502-adopt-code", "lc3197")["tail"]
    _results(tmp_path / "runs" / "loops", [_raw(loop, "org/loops", c) for c in ("a", "b")], "org/loops")
    _results(tmp_path / "runs" / "cut", [_raw(cut, "org/cut", "a"), _raw(loop, "org/cut", "b")], "org/cut")
    _results(tmp_path / "runs" / "old", [_raw(cut, "org/old", "a")], "org/old")
    conn = ms.connect()
    try:
        _seed_screen(conn, "org/loops", "loops")
        _seed_screen(conn, "org/cut", "cut")
        # Today's rules decide this one differently for reasons that are not #955's.
        _seed_screen(conn, "org/old", "old", until="limit:max_tokens>4000")
        found = cmd.changes(conn, tmp_path / "runs")
        assert [(c["name"], c["now"]) for c in found] == [("org/loops", ["broken", "candidate", ""])]
        cmd.apply(conn, found)
        state = dict(conn.execute("SELECT name, state FROM proposals WHERE name LIKE 'org/%'").fetchall())
        assert state == {"org/loops": "broken", "org/cut": "declined", "org/old": "declined"}
        assert cmd.changes(conn, tmp_path / "runs") == []
    finally:
        conn.close()


def test_fit_flags_an_unlabelled_cut_row_inside_the_margin(tmp_path, capsys):
    loop = _row("screen-1791854855-code", "glob-match")["tail"]
    half = "".join(chr(0x4e00 + (i * 7919) % 2000) for i in range(1600)) + loop[:2400]
    _results(tmp_path / "runs" / "new", [_raw(half, "org/new", "a")], "org/new")
    assert dg.inside_margin(dg.measure(half), dg.fit(ROWS))
    assert cli.main(["degenerate", "fit", "--runs", str(tmp_path / "runs")]) == 1
    assert cli.main(["degenerate", "fit"]) == 0
