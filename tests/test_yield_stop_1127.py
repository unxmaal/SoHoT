"""A task stops once the tasks still running at its generated-token count rarely pass: a stop point per lane-model (#1127)."""
import json
import time

import pytest

from evals import core
from evals import run as R
from evals.core import Case
from evals.runners.text import CompletionRunner
from harness import completion, reasons, runs, yield_stop
from harness import memory_store as ms
from harness.commands import common
from tests.test_morning_867 import deploy_dir  # noqa: F401

LANE = "repo"
BUDGET = completion.budget(LANE)
_SEQ = iter(range(1, 10_000))


@pytest.fixture
def conn(tmp_path, monkeypatch):
    c = ms.connect(tmp_path / "d.db")
    yield c
    c.close()


def _row(spec, i, tokens, passed, seconds=1.0, cut=False):
    return {"candidate": spec, "case_id": f"c{i}", "passed": passed, "seconds": seconds,
            "failure_class": reasons.TOKEN_BUDGET_EXHAUSTED if cut else ("" if passed else reasons.CONTENT_FAILED),
            "limit": f"max_tokens.{LANE}>{BUDGET}" if cut else "",
            "metrics": {} if cut else {"completion_tokens": tokens}}


def record(conn, spec, rows, top=BUDGET):
    receipt = {"modality": LANE, "max_tokens": top, "budget_ladder": []}
    return runs.record(conn, f"runs/r{next(_SEQ)}-{LANE}",
                       {"receipt": receipt, "specs": {spec: spec}, "rows": rows}, at=1_000.0)


def tail_never_passes(spec, seconds=1.0):
    """Ten quick passes at 100 tokens, ten replies that run on to 5000 and fail, five cut at the budget."""
    return ([_row(spec, i, 100, True, seconds) for i in range(10)]
            + [_row(spec, 10 + i, 5000, False, seconds) for i in range(10)]
            + [_row(spec, 20 + i, BUDGET, False, seconds, cut=True) for i in range(5)])


def test_a_curve_whose_tail_never_passes_stops_at_the_tail():
    pts = [(100, True)] * 10 + [(5000, False)] * 10
    got = yield_stop.stop_point(pts, 0.25)
    assert got["tokens"] == 100 and got["running"] == 10 and got["running_passed"] == 0


def test_a_curve_that_keeps_passing_has_no_stop():
    assert yield_stop.stop_point([(100 * i, True) for i in range(1, 20)], 0.25)["tokens"] is None
    assert yield_stop.stop_point([(100, False)] * 5, 0.25)["tokens"] is None


def test_the_stop_falls_where_the_running_rate_first_drops_under_ratio_times_base():
    pts = [(100, True)] * 4 + [(200, False)] * 4 + [(300, True)] + [(400, False)] * 7
    got = yield_stop.stop_point(pts, 0.5)
    assert got["base"] == round(5 / 16, 4)
    assert got["tokens"] == 100 and (got["running_passed"], got["running"]) == (1, 12)


def test_a_model_with_no_history_uses_the_lanes_pooled_curve(conn):
    record(conn, "ornith", tail_never_passes("ornith"))
    own = yield_stop.point(conn, LANE, "ornith,temperature=1.0")
    new = yield_stop.point(conn, LANE, "newcomer")
    assert own["from"] == "model" and own["tokens"] == 100
    assert new["from"] == "lane" and new["tokens"] == 100 and new["model"] == "newcomer"


def test_runs_that_gave_less_room_than_the_budget_are_left_out(conn):
    record(conn, "ornith", [_row("ornith", i, 900, False, cut=True) for i in range(20)], top=1000)
    assert yield_stop.point(conn, LANE, "ornith")["rows"] == 0


def test_the_stop_point_is_the_same_at_concurrency_1_and_4_for_the_same_tokens(conn, tmp_path):
    record(conn, "alone", tail_never_passes("alone", seconds=10.0))
    record(conn, "shared", tail_never_passes("shared", seconds=22.0))
    a, b = yield_stop.point(conn, LANE, "alone"), yield_stop.point(conn, LANE, "shared")
    assert a["tokens"] == b["tokens"] == 100


def test_cut_rows_without_usage_count_at_the_budget_they_were_cut_at():
    row = _row("m", 0, 0, False, cut=True)
    assert yield_stop.tokens_of(row) == BUDGET
    assert yield_stop.tokens_of({"metrics": "{}", "attempts": "[]", "failure_class": ""}) is None


def _streamed(tokens: int, answer: str):
    """SSE lines of a reply that reasons for tokens - 1 tokens, then answers in one more."""
    for _ in range(tokens - 1):
        yield "data: " + json.dumps({"choices": [{"delta": {"reasoning_content": "x"}}]})
    yield "data: " + json.dumps({"choices": [{"delta": {"content": answer}, "finish_reason": "stop"}],
                                 "usage": {"completion_tokens": tokens}})
    yield "data: [DONE]"


def _ran(tokens: int, stop) -> bool:
    """Whether a reply of `tokens` tokens finished under a stop at `stop`."""
    with completion.stopping_after(stop):
        body, _ = completion.assemble(_streamed(tokens, "ok"), time.perf_counter(), 60.0)
    return body["choices"][0]["finish_reason"] != reasons.STOPPED_LOW_YIELD


def test_rescoring_a_stored_run_equals_a_new_run_with_the_stop_on_the_same_rows():
    rows = tail_never_passes("m") + [_row("m", 40, 300, True), _row("m", 41, 301, True), _row("m", 42, 299, False)]
    for stop in (100, 300, 5000):
        got = yield_stop.rescore(rows, stop)
        fresh = [bool(r["passed"]) and _ran(yield_stop.tokens_of(r), stop) for r in rows]
        assert [r["passed"] for r in got["rows"]] == fresh, stop
    got = yield_stop.rescore(rows, 300)
    assert (got["kept"], got["lost"]) == (11, 1)
    stopped = [r for r in got["rows"] if r["failure_class"] == reasons.STOPPED_LOW_YIELD]
    assert len(stopped) == got["stopped"] == 16 and stopped[0]["limit"] == "yield_stop>300"


def test_no_stop_point_rescoring_changes_nothing():
    rows = tail_never_passes("m")
    got = yield_stop.rescore(rows, None)
    assert [r["passed"] for r in got["rows"]] == [r["passed"] for r in rows] and got["saved_s"] == 0


def _runner(monkeypatch, tokens, stop):
    sent = []

    def send(gateway, payload, timeout):
        sent.append(payload)
        body, timing = completion.assemble(_streamed(tokens, "{}"), time.perf_counter(), timeout)
        return completion.Streamed(body, timing)
    monkeypatch.setattr(completion, "_send", send)
    runner = CompletionRunner("http://gw.test", "m", max_tokens=BUDGET)
    runner.answered = True
    runner.stop_tokens = stop
    return runner, sent


def test_a_reply_past_the_stop_point_is_stopped_low_yield_and_the_request_is_unchanged(monkeypatch):
    case = Case("e1", "extract", "pull the fields", assertions={})
    runner, sent = _runner(monkeypatch, 500, 200)
    row = runner.run(case)
    assert row.failure_class == reasons.STOPPED_LOW_YIELD and not row.passed
    assert row.limit == "yield_stop>200"
    plain, plain_sent = _runner(monkeypatch, 500, None)
    plain.run(case)
    assert completion.request_of(sent[0]) == completion.request_of(plain_sent[0])
    assert sent[0]["max_tokens"] == BUDGET


def test_a_reply_at_the_stop_point_finishes(monkeypatch):
    runner, _ = _runner(monkeypatch, 200, 200)
    row = runner.run(Case("e1", "extract", "pull the fields", assertions={}))
    assert row.failure_class != reasons.STOPPED_LOW_YIELD


def test_a_ladder_rung_past_the_stop_point_is_never_sent():
    assert R.rungs_for((4000, 16000, 32000), None, stop=10000) == (4000, 10000)
    assert R.rungs_for((4000, 16000), 262144, stop=None) == (4000, 16000)
    assert R.rungs_for((4000, 16000), 12000, stop=50000) == (4000, 12000)


def test_a_stopped_reply_is_a_cut_fail_the_grader_never_saw():
    assert reasons.STOPPED_LOW_YIELD in reasons.CUT
    assert reasons.CLASSES[reasons.STOPPED_LOW_YIELD] == ("declined", reasons.LIMIT)


def test_the_receipt_records_the_stop_point_and_is_not_an_axis():
    base = dict(modality=LANE, case_ids=("a",), repeat=1, sampling={}, gateway="gw", max_tokens=BUDGET)
    a = core.Receipt(**base, yield_stop={"m": {"tokens": 100, "from": "model", "runs": [1]}})
    assert core.Receipt.from_dict(a.as_dict()).yield_stop["m"]["tokens"] == 100
    assert core.comparable(a, core.Receipt(**base))[0]


def test_reused_draws_are_rescored_at_the_runs_stop_point(tmp_path):
    from harness.commands import measure
    (tmp_path / "results.json").write_text(json.dumps({"receipt": {"yield_stop": {"inc": {"tokens": 100}}}}),
                                           encoding="utf-8")
    assert measure._stopped_at(tmp_path, "inc") == 100
    assert measure._stopped_at(tmp_path, "other") is None
    assert measure._stopped_at(tmp_path / "missing", "inc") is None


def test_the_dry_run_rescores_a_checkpoint(conn, tmp_path, capsys):
    record(conn, "ornith", tail_never_passes("ornith"))
    conn.commit()
    ck = tmp_path / "checkpoint.jsonl"
    ck.write_text("\n".join(json.dumps({"row": r}) for r in tail_never_passes("ornith")), encoding="utf-8")
    a = common.parsed("yield-stop", LANE, "ornith", "--store", str(tmp_path / "d.db"), "--checkpoint", str(ck))
    assert a.func(a) == 0
    out = capsys.readouterr().out
    assert "stops at 100 tokens" in out and "10 passes kept, 0 lost, 15 stopped" in out


def test_morning_names_each_served_lane_models_stop_point(conn, deploy_dir):
    from harness.commands import morning as morning_cmd
    from tests import test_morning_867 as M
    record(conn, "ornith", tail_never_passes("ornith"))
    got = yield_stop.report(conn, served={LANE: {"spec": "ornith"}, "image": {"spec": "flux"}})
    assert [g["lane"] for g in got] == [LANE] and got[0]["tokens"] == 100 and got[0]["saved_share"] > 0
    line = yield_stop.line(got[0])
    assert "stops at 100 tokens" in line and "10 passes kept, 0 lost" in line
    r = M._report(M._store(), deploy_dir)
    assert "yield" in r
    r["yield"] = got
    assert any(line in ln for ln in morning_cmd.render(r))


def test_a_measured_run_stops_at_its_models_point_and_records_it(tmp_path, monkeypatch):
    from tests.test_budget_ladder import CODE, Scripted, _args, quiet_receipt  # noqa: F401
    from tests import test_budget_ladder as B
    for name, value in (("accelerator_id", "unified:test"), ("where_id", "test"), ("swap_used_mb", 0),
                        ("instruments", {}), ("engines", {})):
        monkeypatch.setattr(R, name, lambda *a, _v=value, **k: _v)
    monkeypatch.setattr(ms.machines, "_THIS_MACHINE", None)
    monkeypatch.setattr(R.environment, "capture", lambda: {})
    monkeypatch.setattr(R, "warn_if_pressed", lambda *a, **k: type("P", (), {"as_dict": lambda self: {}})())
    c = ms.connect()
    budget = completion.budget("code")
    rows = ([_row("org/x", i, 100, True) for i in range(10)] + [_row("org/x", 10 + i, 5000, False) for i in range(10)])
    runs.record(c, "runs/seed-code", {"receipt": {"modality": "code", "max_tokens": budget, "budget_ladder": []},
                                      "specs": {"org/x": "org/x"}, "rows": rows}, at=1_000.0)
    c.execute("UPDATE runs SET lane = 'code', tier = 'measure'")
    c.commit()
    c.close()

    class Streams(B.Scripted):
        def __init__(self):
            super().__init__({}, default="pass")
            self.trajectories, self.sent, self.stop_tokens = [], [], None
    runner = Streams()
    monkeypatch.setattr(R, "build_runner", lambda *a, **k: runner)
    monkeypatch.setattr(R, "cases_for", lambda candidate, cases: [CODE])
    R._execute(_args(tmp_path, budget_ladder=None))
    data = json.loads((tmp_path / "out" / "results.json").read_text(encoding="utf-8"))
    assert runner.stop_tokens == 100
    assert data["receipt"]["yield_stop"]["org/x"]["tokens"] == 100
    assert data["receipt"]["yield_stop"]["org/x"]["from"] == "model"
    assert data["receipt"]["budget_ladder"] == [] and data["receipt"]["max_tokens"] == budget


def _stopped(spec, i, at):
    return {"candidate": spec, "case_id": f"s{i}", "passed": False, "seconds": 1.0,
            "failure_class": reasons.STOPPED_LOW_YIELD, "limit": f"{yield_stop.LIMIT}>{at}",
            "metrics": {"completion_tokens": at + 1}}


def test_the_stop_point_moves_up_when_explored_rows_pass_past_it(conn):
    record(conn, "ornith", tail_never_passes("ornith"))
    assert yield_stop.point(conn, LANE, "ornith")["tokens"] == 100
    record(conn, "ornith", [_row("ornith", i, 100, True) for i in range(10)]
           + [_stopped("ornith", i, 100) for i in range(16)]
           + [_row("ornith", 40 + i, 3000, True) for i in range(4)])
    got = yield_stop.point(conn, LANE, "ornith")
    assert got["tokens"] == 3000


def test_stopped_rows_are_censored_never_failures_past_the_stop(conn):
    record(conn, "ornith", tail_never_passes("ornith"))
    before = yield_stop.point(conn, LANE, "ornith")
    record(conn, "ornith", [_stopped("ornith", i, 100) for i in range(40)])
    after = yield_stop.point(conn, LANE, "ornith")
    assert (after["tokens"], after["base"], after["rows"]) == (before["tokens"], before["base"], before["rows"])


def test_an_explored_row_stands_for_the_stopped_rows_of_its_run():
    rows = ([dict(_stopped("m", i, 100), run_id=7) for i in range(6)]
            + [dict(_row("m", 10 + i, 900, True), run_id=7) for i in range(2)]
            + [dict(_row("m", 20, 50, True), run_id=7)])
    pts, _ = yield_stop.points(rows)
    assert sorted(w for *_, w in pts) == [1.0, 4.0, 4.0]


def test_the_explored_share_is_reproducible_by_case_and_run():
    cases = [f"c{i}" for i in range(2000)]
    one = [c for c in cases if yield_stop.explored(c, "run-a", 0.1)]
    assert one == [c for c in cases if yield_stop.explored(c, "run-a", 0.1)]
    assert one != [c for c in cases if yield_stop.explored(c, "run-b", 0.1)]
    assert 150 < len(one) < 250
    assert not any(yield_stop.explored(c, "run-a", 0.0) for c in cases)


def test_an_explored_case_runs_to_the_budget_and_the_receipt_names_it(tmp_path, monkeypatch):
    from types import SimpleNamespace
    point = {"tokens": 100}
    out = tmp_path / "run-x"
    monkeypatch.setattr(yield_stop, "explored", lambda case_id, seed, share=None: case_id == "a" and seed == "run-x")
    assert R._case_stop(point, SimpleNamespace(id="a"), out) is None
    assert R._case_stop(point, SimpleNamespace(id="b"), out) == 100
    assert point["explored"] == ["a"] and point["explore"] == yield_stop.EXPLORE_SHARE
    assert R._case_stop({"tokens": None}, SimpleNamespace(id="a"), out) is None
