"""Overrun is judged on paired evidence against an honest plan; a run the watchdog stopped is resumed, its rows kept. #864."""
import json
import os
import shutil
import sys
from pathlib import Path

import pytest

from evals import watch
from harness import power
from harness import watchdog as wd
from harness.commands import measure as measure_cmd
from harness.commands.measure import Launched
from tests.test_resume_813 import CH, INC, Eval, _measure, _pauses, _rows, world  # noqa: F401
from tests.test_watchdog import ids, judged, owned_eval

FIXTURES = Path(__file__).parent / "fixtures" / "watchdog_864"
ORNITH = "llamacpp:Ornith-1.5-35B-Q4_K_M"
#: Mean metrics.tokens_per_s of each model's stored code rows on the Studio, discovery.db 2026-10-15.
DECODE = {ORNITH: 135.29, "LiquidAI/LFM2.5-8B-A1B": 164.5, "WeiboAI/VibeThinker-3B": 118.0,
          "LiquidAI/LFM2.5-2.6B": 140.48}
RUNS = sorted(p.name for p in FIXTURES.iterdir())


def _load(name):
    ident, rows = watch.read(FIXTURES / name)
    return ident, rows, json.loads((FIXTURES / name / watch.PROGRESS).read_text(encoding="utf-8"))


def _honest(progress):
    """The plan the #864 measure step prices: the challenger at the incumbent's s/case times the decode ratio."""
    inc = progress["planned_s_per_case"][ORNITH]
    return {k: inc if k == ORNITH else inc * DECODE[ORNITH] / DECODE[k] for k in progress["planned_s_per_case"]}


def _eval_at(tmp_path, ident, rows, progress, planned=None):
    """An owned evals.run whose run directory holds these checkpoint rows and this progress."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    ck = watch.Checkpoint(tmp_path, ident)
    walls = {}
    for r in rows:
        ck.add(r, r["wall_s"])
        walls.setdefault(r["candidate"], []).append(r["wall_s"])
    got = {**progress, "state": "running", "pid": 511, "done": len(rows), "_dir": str(tmp_path),
           "planned_s_per_case": planned or progress["planned_s_per_case"],
           "observed_s_per_case": {k: sum(v) / len(v) for k, v in walls.items()}}
    return owned_eval(tmp_path, progress=[got])


def _pairs(rows, inc=ORNITH):
    ch = {r["case_id"] for r in rows if r["candidate"] != inc}
    return len(ch & {r["case_id"] for r in rows if r["candidate"] == inc})


@pytest.mark.parametrize("name", RUNS)
def test_the_three_stopped_runs_replayed_case_by_case_are_never_an_overrun(tmp_path, name):
    ident, rows, progress = _load(name)
    planned = _honest(progress)
    judged_at = 0
    for k in range(wd.OVERRUN_MIN_CASES, len(rows) + 1):
        fake = _eval_at(tmp_path / str(k), ident, rows[:k], progress, planned)
        assert ids(judged(fake)[1], "overrun") == [], f"{name} at {k} rows"
        judged_at += _pairs(rows[:k]) >= wd.OVERRUN_MIN_PAIRS
    assert judged_at, "the replay reached enough paired cases to be judged at all"


@pytest.mark.parametrize("name", RUNS)
def test_the_plan_they_ran_under_was_what_stopped_them(tmp_path, name):
    ident, rows, progress = _load(name)
    seen = progress["observed_s_per_case"]
    planned = progress["planned_s_per_case"]
    challenger = next(k for k in planned if k != ORNITH)
    assert seen[challenger] > wd.OVERRUN_FACTOR * planned[challenger], "the unpaired rule tripped on these"
    assert planned[challenger] < _honest(progress)[challenger], "a screen mean priced it under its decode speed"


def _scaled(rows, factor_s=1.0, factor_tok=1.0, inc=ORNITH):
    out = []
    for r in rows:
        if r["candidate"] == inc:
            out.append(r)
            continue
        m = dict(r.get("metrics") or {})
        if m.get("completion_tokens"):
            m["completion_tokens"] = int(m["completion_tokens"] * factor_tok)
        out.append({**r, "metrics": m, "wall_s": r["wall_s"] * factor_s, "seconds": r["seconds"] * factor_s})
    return out


def test_a_challenger_three_times_slower_per_token_on_the_same_cases_is_an_overrun(tmp_path):
    ident, rows, progress = _load("20261014-234502-adopt-code")
    fake = _eval_at(tmp_path, ident, _scaled(rows, factor_s=3.0), progress, _honest(progress))
    found = [f for f in judged(fake)[1] if f.criterion == "overrun"]
    assert [f.evidence["candidate"] for f in found] == ["LiquidAI/LFM2.5-2.6B"]
    ev = found[0].evidence
    assert ev["basis"] == "seconds per reply token" and ev["paired"] == 10
    assert ev["observed_ratio"] > wd.OVERRUN_FACTOR * ev["planned_ratio"]


def test_a_challenger_that_writes_three_times_the_tokens_at_the_same_speed_is_not(tmp_path):
    ident, rows, progress = _load("20261014-234502-adopt-code")
    fake = _eval_at(tmp_path, ident, _scaled(rows, factor_s=3.0, factor_tok=3.0), progress, _honest(progress))
    assert ids(judged(fake)[1], "overrun") == []


def _bare(rows):
    """The same rows with no token counts, as a lane that reports none writes them."""
    return [{**r, "metrics": {}, "failure_class": ""} for r in rows]


def test_without_token_counts_the_paired_seconds_are_compared(tmp_path):
    ident, rows, progress = _load("20261014-232539-adopt-code")
    planned = {ORNITH: 50.0, "WeiboAI/VibeThinker-3B": 50.0}
    fine = _eval_at(tmp_path / "a", ident, _bare(rows), progress, planned)
    assert ids(judged(fine)[1], "overrun") == []
    slow = _eval_at(tmp_path / "b", ident, _scaled(_bare(rows), factor_s=3.0), progress, planned)
    (f,) = [f for f in judged(slow)[1] if f.criterion == "overrun"]
    assert f.evidence["basis"] == "seconds" and f.evidence["paired"] == 9


def test_a_challenger_is_not_judged_before_enough_cases_are_paired(tmp_path):
    ident, rows, progress = _load("20261014-232539-adopt-code")
    head = rows[:2 * (wd.OVERRUN_MIN_PAIRS - 1)]
    assert _pairs(head) == wd.OVERRUN_MIN_PAIRS - 1
    fake = _eval_at(tmp_path, ident, _scaled(head, factor_s=50.0), progress, _honest(progress))
    assert ids(judged(fake)[1], "overrun") == []


def test_the_incumbent_of_a_paired_run_is_still_judged_against_its_own_plan(tmp_path):
    ident, rows, progress = _load("20261014-232539-adopt-code")
    planned = {**_honest(progress), ORNITH: 10.0}
    found = [f for f in judged(_eval_at(tmp_path, ident, rows, progress, planned))[1] if f.criterion == "overrun"]
    assert [f.evidence["candidate"] for f in found] == [ORNITH]


def test_an_unpaired_single_candidate_run_keeps_the_mean_over_plan_rule(tmp_path):
    ident = {"modality": "code", "candidates": ["a"], "repeat": 1, "max_tokens": 32768}
    rows = [{"case_id": f"c{i}", "candidate": "a", "wall_s": 30.0, "seconds": 30.0,
             "metrics": {"completion_tokens": 100}} for i in range(10)]
    progress = {"total": 100, "specs": {"a": "a"}}
    slow = _eval_at(tmp_path / "a", ident, rows, progress, {"a": 10.0})
    assert ids(judged(slow)[1], "overrun") == ["eval pgid 510"]
    fine = _eval_at(tmp_path / "b", ident, rows, progress, {"a": 20.0})
    assert ids(judged(fine)[1], "overrun") == []


def test_the_min_pairs_knob_is_registered():
    from harness import knobs
    assert knobs.KNOBS["watchdog_overrun_min_pairs"].default() == wd.OVERRUN_MIN_PAIRS


# --- the plan at its source ------------------------------------------------------

def _decode_rows(lane, spec, seconds, tok_s, cases=("c1", "c2", "c3")):
    return [{"case_id": c, "candidate": spec, "passed": True, "seconds": seconds, "peak_kb": 0, "detail": "",
             "metrics": {"tokens_per_s": tok_s, "completion_tokens": int(seconds * tok_s)}} for c in cases]


def test_a_screened_challenger_is_priced_at_the_incumbents_seconds_times_the_decode_ratio(store_run):
    from harness import completion, runs
    from harness import memory_store as ms
    budget = {"max_tokens": completion.budget("code")}
    store_run("inc-1", "code", rows=_decode_rows("code", "inc", 57.0, 135.0), receipt=budget)
    # Screened at another reply budget: decode speed does not depend on it (VibeThinker's screen, 2026-10-14).
    store_run("ch-1", "code", rows=_decode_rows("code", "ch", 7.0, 165.0), tier="screen", receipt={"max_tokens": 4000})
    conn = ms.connect()
    try:
        s, source = power.challenger_seconds(conn, "code", "ch", incumbent="inc", incumbent_s=57.0,
                                             settings=(completion.budget("code"), ()), machines=runs.here(conn))
    finally:
        conn.close()
    assert source == "decode ratio"
    assert s == pytest.approx(57.0 * 135.0 / 165.0)


def test_a_resumed_run_is_priced_afresh_and_keeps_its_exam(monkeypatch, world):  # noqa: F811
    fake = Eval(rows=_rows(10))
    monkeypatch.setattr(measure_cmd, "_launch", fake)
    _measure()
    conn = world()
    try:
        stored = json.loads(conn.execute("SELECT plan FROM paused_runs").fetchone()[0])
        stored["estimate"] = {**stored["estimate"], "challenger_s": 0.01, "challenger_calls": 1}
        conn.execute("UPDATE paused_runs SET plan = ?", (json.dumps(stored),))
        conn.commit()
    finally:
        conn.close()
    _measure()
    first, second = fake.argvs
    assert "--resume" in second
    plan_s = lambda argv: [argv[i + 1] for i, a in enumerate(argv) if a == "--plan-s"]  # noqa: E731
    assert plan_s(second) == plan_s(first), "the stale stored price is not what the resumed run is judged by"
    assert second[second.index("--repeat") + 1] == first[first.index("--repeat") + 1]


# --- a stopped run is resumed, not restarted ------------------------------------

@pytest.mark.parametrize("rc", [-15, -9, 143])
def test_a_run_stopped_by_a_signal_is_kept_as_a_pause_and_resumed(monkeypatch, world, rc):  # noqa: F811
    fake = Eval(rc=rc, rows=_rows(10))
    monkeypatch.setattr(measure_cmd, "_launch", fake)
    assert _measure() == 0
    conn = world()
    try:
        (p,) = _pauses(conn)
    finally:
        conn.close()
    assert p["state"] == "paused" and p["done"] == 20
    fake.rc, fake.rows = watch.PAUSED, _rows(30)
    _measure()
    first, second = fake.argvs
    assert "--resume" in second and second[second.index("--out") + 1] == first[first.index("--out") + 1]


def test_a_crashed_run_is_still_an_error_not_a_pause(monkeypatch, world):  # noqa: F811
    monkeypatch.setattr(measure_cmd, "_launch", Eval(rc=1, rows=_rows(10)))
    assert _measure() == 1
    conn = world()
    try:
        assert _pauses(conn) == []
    finally:
        conn.close()


def _abandon(home, name, candidates, *, pid=None, rows=None, state="running", repeat=1, split="holdout"):
    """A run directory a stopped run left: its checkpoint and a progress file naming a pid."""
    out = home / "runs" / name
    out.mkdir(parents=True)
    ck = watch.Checkpoint(out, {"modality": "code", "candidates": candidates, "repeat": repeat, "split": split})
    for r in rows if rows is not None else _rows(4):
        ck.add(r, r["wall_s"])
    (out / watch.PROGRESS).write_text(json.dumps({
        "state": state, "done": 8, "total": 40, "pid": pid or _dead_pid(), "pgid": pid or 1,
        "specs": {INC: INC, CH: CH}}), encoding="utf-8")
    return out


def _dead_pid():
    import subprocess
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    return proc.pid


def test_a_run_stopped_before_this_fix_is_found_by_its_checkpoint_and_resumed(monkeypatch, world, tmp_path):  # noqa: F811
    out = _abandon(tmp_path, "20261014-232539-adopt-code", [INC, CH], repeat=3)
    fake = Eval(rows=_rows(10))
    monkeypatch.setattr(measure_cmd, "_launch", fake)
    assert _measure() == 0
    (argv,) = fake.argvs
    assert "--resume" in argv and argv[argv.index("--out") + 1] == str(out)
    assert argv[argv.index("--repeat") + 1] == "3" and argv[argv.index("--split") + 1] == "holdout"
    conn = world()
    try:
        (p,) = _pauses(conn)
    finally:
        conn.close()
    assert p["out"] == str(out) and p["state"] == "paused"


@pytest.mark.parametrize("why", ["another pairing", "still running", "already settled", "finished"])
def test_a_run_directory_that_is_not_an_abandoned_run_of_this_pairing_is_left(monkeypatch, world, tmp_path, why):  # noqa: F811
    from harness import paused
    from harness import memory_store as ms
    if why == "another pairing":
        out = _abandon(tmp_path, "20261014-000000-adopt-code", [INC, "llamacpp:Other"])
    elif why == "still running":
        if sys.platform == "win32":
            pytest.skip("a live run is told by its process group, which Windows does not have")
        out = _abandon(tmp_path, "20261014-000000-adopt-code", [INC, CH], pid=os.getpid())
        prog = json.loads((out / watch.PROGRESS).read_text(encoding="utf-8"))
        prog["pgid"] = os.getpgid(0) if sys.platform != "win32" else os.getpid()
        (out / watch.PROGRESS).write_text(json.dumps(prog), encoding="utf-8")
    elif why == "already settled":
        out = _abandon(tmp_path, "20261014-000000-adopt-code", [INC, CH])
        conn = ms.connect()
        try:
            pid = paused.save(conn, lane="code", inc_spec=INC, spec=CH, proposal=CH, out=str(out), ident={},
                              plan={}, done=8, total=40, looks=[])
            paused.settle(conn, pid, "stale", "test")
        finally:
            conn.close()
    else:
        out = _abandon(tmp_path, "20261014-000000-adopt-code", [INC, CH], state="done")
    fake = Eval(rows=_rows(10))
    monkeypatch.setattr(measure_cmd, "_launch", fake)
    _measure()
    (argv,) = fake.argvs
    assert "--resume" not in argv and argv[argv.index("--out") + 1] != str(out)
    shutil.rmtree(out)
