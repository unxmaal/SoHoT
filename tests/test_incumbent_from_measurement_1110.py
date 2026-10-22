"""A lane whose typed incumbent never passes takes its incumbent from measurement, never from one gained case. #1110."""
from __future__ import annotations

import argparse
import subprocess

from harness import adopt, baseline, morning, runs
from harness import memory_store as ms
from harness.commands import measure as measure_cmd
from harness.commands import morning as morning_cmd

INC = "mlx-community/Qwen3-4B-Instruct-2507-4bit"
CH = "llamacpp:Ornith-1.5-35B-Q4_K_M"
EXAM = frozenset(f"sohot-{i:03d}-spec" for i in range(30))
DIGEST = "exam1110"


def _rows(key, ids, passes, cut=0):
    ids = sorted(ids)
    return [{"case_id": c, "candidate": key, "passed": i < passes, "seconds": 1.0, "peak_kb": 0,
             "detail": "", "output": None, "artifact_path": None, "warnings": [],
             "metrics": {} if i >= len(ids) - cut else {"resolved": int(i < passes)}}
            for i, c in enumerate(ids)]


def _zero_incumbent(store_run, conn, cases=30):
    store_run("inc-old", "repo", rows=_rows(INC, [f"old-{i}" for i in range(cases)], 0),
              specs={INC: INC}, cases_digest="old-exam", conn=conn)


def _exam(lane):
    return EXAM, DIGEST


def _conn():
    conn = ms.connect()
    ms.remember_machine(conn)
    return conn


def test_a_typed_incumbent_that_passed_none_of_enough_stored_cases_is_zero_pass(store_run):
    conn = _conn()
    _zero_incumbent(store_run, conn)
    got = baseline.zero_pass(conn, "repo", INC)
    assert got == {"spec": INC, "cases": 30, "draws": 30}


def test_too_few_stored_cases_or_one_pass_is_not_zero_pass(store_run, monkeypatch):
    conn = _conn()
    _zero_incumbent(store_run, conn, cases=29)
    assert baseline.zero_pass(conn, "repo", INC) is None
    monkeypatch.setattr(baseline, "MIN_CASES", 29)
    assert baseline.zero_pass(conn, "repo", INC) is not None
    store_run("inc-pass", "repo", rows=_rows(INC, ["old-0"], 1), specs={INC: INC}, cases_digest="x", conn=conn)
    assert baseline.zero_pass(conn, "repo", INC) is None


def test_one_gained_case_over_a_zero_pass_incumbent_is_not_adopted(store_run):
    conn = _conn()
    _zero_incumbent(store_run, conn)
    zero = baseline.zero_pass(conn, "repo", INC)
    store_run("ch-exam", "repo", rows=_rows(CH, EXAM, 1), specs={CH: CH}, cases_digest=DIGEST, conn=conn)
    got = baseline.take(conn, "repo", INC, zero, exam_of=_exam)
    assert got is not None and got.challenger == CH
    assert not got.adopt, got.why
    assert "1 gained" in got.why and "passed 1 of 30" in got.why


def test_enough_gained_cases_take_the_incumbent_from_measurement(store_run):
    conn = _conn()
    _zero_incumbent(store_run, conn)
    zero = baseline.zero_pass(conn, "repo", INC)
    store_run("ch-exam", "repo", rows=_rows(CH, EXAM, 7), specs={CH: CH}, cases_digest=DIGEST, conn=conn)
    got = baseline.take(conn, "repo", INC, zero, exam_of=_exam)
    assert got.adopt, got.why
    assert got.why.startswith(baseline.SOURCE) and got.evidence["cases_digest"] == DIGEST


def test_a_cut_reply_is_no_loss_against_the_zero_pass_incumbent(store_run):
    conn = _conn()
    _zero_incumbent(store_run, conn)
    zero = baseline.zero_pass(conn, "repo", INC)
    store_run("ch-exam", "repo", rows=_rows(CH, EXAM, 7, cut=20), specs={CH: CH}, cases_digest=DIGEST, conn=conn)
    got = baseline.take(conn, "repo", INC, zero, exam_of=_exam)
    assert got.adopt and "0 lost" in got.why, got.why


def test_only_a_run_of_every_case_of_the_current_exam_counts(store_run):
    conn = _conn()
    _zero_incumbent(store_run, conn)
    zero = baseline.zero_pass(conn, "repo", INC)
    store_run("ch-short", "repo", rows=_rows(CH, sorted(EXAM)[:-1], 7), specs={CH: CH}, cases_digest=DIGEST, conn=conn)
    store_run("ch-other", "repo", rows=_rows(CH, EXAM, 7), specs={CH: CH}, cases_digest="older", conn=conn)
    assert baseline.take(conn, "repo", INC, zero, exam_of=_exam) is None


def _receipt(passes):
    return {"summary": {INC: {"passed": 0, "total": 30, "pass_rate": 0.0, "median_s": 1.0, "metrics": {"resolved": 0.0}},
                        CH: {"passed": passes, "total": 30, "pass_rate": passes / 30, "median_s": 1.0,
                             "metrics": {"resolved": passes / 30}}},
            "rows": _rows(INC, EXAM, 0) + _rows(CH, EXAM, passes)}


class _Done:
    returncode, stdout, stderr = 0, "", ""


def test_a_paired_run_against_a_zero_pass_incumbent_is_a_screen_and_adopts_nothing(
        store_run, tmp_path, monkeypatch, capsys):
    real = ms.connect
    monkeypatch.setattr(ms, "connect", lambda *a, **k: real(tmp_path / "d.db"))
    conn = _conn()
    _zero_incumbent(store_run, conn)
    store_run("ch-exam", "repo", rows=_rows(CH, EXAM, 1), specs={CH: CH}, cases_digest=DIGEST, conn=conn)
    monkeypatch.setattr(baseline, "exam", _exam)
    monkeypatch.setattr(measure_cmd, "_launch", lambda argv, **kw: _Done())
    monkeypatch.setattr(adopt, "default_for", lambda lane, fallback, conn=None: INC)
    monkeypatch.setattr("harness.screen.routed_gateway", lambda model, config=None: "")
    monkeypatch.setattr(measure_cmd, "_receipt_at", lambda out: _receipt(1))

    rc = measure_cmd._measure_and_adopt(argparse.Namespace(repeat=1, power_budget_min=1e9),
                                        {"name": CH, "lane": "repo"})
    out = capsys.readouterr()
    assert rc == 0, out.err
    assert "no working control" not in out.err
    assert "repo" not in adopt.current(conn)
    got = conn.execute("SELECT outcome, detail FROM verdicts WHERE tier = 'adopt' ORDER BY id DESC").fetchone()
    assert got["outcome"] == "declined" and got["detail"].startswith("repo: screen only"), dict(got)


def test_soh_morning_names_the_repo_incumbent_and_its_source(store_run, monkeypatch):
    conn = _conn()
    _zero_incumbent(store_run, conn)
    store_run("ch-exam", "repo", rows=_rows(CH, EXAM, 7), specs={CH: CH}, cases_digest=DIGEST, conn=conn)
    before = baseline.source(conn, "repo", INC, exam_of=_exam)
    assert before["spec"] == INC and "passed 0 of 30" in before["source"]
    assert before["detail"].startswith("next sweep takes")
    monkeypatch.setattr(baseline, "exam", _exam)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Done())
    got = measure_cmd.take_incumbents("repo")
    assert [v.challenger for v in got] == [CH]
    assert adopt.current(conn)["repo"]["spec"] == CH
    monkeypatch.setattr("harness.winners.typed", lambda: {"repo": INC})
    r = {"incumbent": morning.repo_incumbent(conn)}
    assert r["incumbent"]["spec"] == CH and r["incumbent"]["source"].startswith("adopted, measured")
    assert r["incumbent"]["detail"].startswith(baseline.SOURCE)
    line = morning_cmd.render({**_quiet(), **r})
    assert any(x.startswith(f"incumbent repo: {CH} (adopted, measured") for x in line), line


def _quiet() -> dict:
    return {"since": 0, "lane": {}, "incidents": [], "checks": [], "watchdog": [], "stale": [],
            "ci": {"available": False, "why": "x"}, "ledger": None, "deploy": {"available": False, "why": "x"},
            "sweep": {"loop": None, "screened": {}, "measured": {"runs": [], "verdicts": {}}, "paused": [],
                      "stopped": [], "settled": {"verdicts": {}, "adopted": []}}}


def test_the_knob_is_registered_with_its_range():
    from harness import knobs
    k = knobs.KNOBS["zero_pass_min_cases"]
    assert k.sites == ("harness/baseline.py:MIN_CASES",) and k.default() == baseline.MIN_CASES
    assert baseline.MIN_CASES in k.values and "#1110" in k.note


def test_runs_here_finds_the_stored_runs(store_run):
    conn = _conn()
    _zero_incumbent(store_run, conn)
    mid = conn.execute("SELECT machine_id FROM runs").fetchone()[0]
    assert runs.here(conn) == [mid]
