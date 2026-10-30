"""A paused confirmation run resumes where it stopped, and a paused job is not a failed one. #1357."""
import argparse
import json
import time
import types
from datetime import datetime
from pathlib import Path

import pytest

from evals import watch
from harness import adopt, cli, heartbeat, holdout, paths, screen, watchdog, workqueue
from harness import memory_store as ms
from harness.commands import adopt as adopt_cmd
from harness.commands import measure as measure_cmd

FAKE_MACHINE = {"fingerprint": "test/rig", "hw_model": "", "os": "", "arch": "",
                "memory_gb": 0.0, "accelerator": "", "runtimes": "", "ceiling_gb": 0.0}
SPLIT = holdout.Split("code", dev=tuple(f"d{i}" for i in range(10)), holdout=("h1", "h2", "h3"), too_small=False)
CELLS = {**{f"d{i}": (False, True) for i in range(9)}, "d9": (True, True)}


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv(paths.ENV_VAR, str(tmp_path))
    monkeypatch.delenv(workqueue.JOB_ENV, raising=False)
    monkeypatch.setattr(ms.machines, "_THIS_MACHINE", FAKE_MACHINE)
    real = ms.connect
    monkeypatch.setattr(ms, "connect", lambda *a, **k: real(tmp_path / "d.db"))
    c = ms.connect()
    yield c
    c.close()


def _rows(cells, inc, ch):
    out = []
    for case, (i, c) in cells.items():
        out.append({"candidate": inc, "case_id": case, "passed": i, "seconds": 1.0, "metrics": {}})
        out.append({"candidate": ch, "case_id": case, "passed": c, "seconds": 1.0, "metrics": {}})
    return out


def _held(conn, tmp_path, monkeypatch):
    """A held holdout win whose _record queued the night confirmation job."""
    rows = _rows({"h1": (False, True), "h2": (False, True), "h3": (False, True)}, "inc", "ch")
    won = adopt.Verdict("code", "inc", "ch", True, "beats inc", evidence={"split": SPLIT.as_dict()})
    held = adopt.confirm(won, rows, SPLIT, frozenset({"z0"}))
    held = adopt.Verdict(held.lane, held.incumbent, held.challenger, False, held.why, held.how, held.failure_class,
                         {**held.evidence, "confirm": {**held.evidence["confirm"], "incumbent": "inc-spec",
                                                        "challenger": "org/x", "repeat": 1}})
    ms.record(conn, ms.Seen(name="org/x", source="test", lane="code"))
    measure_cmd._record(held, "org/x", None, tmp_path / "no-run")
    monkeypatch.setattr(holdout, "for_lane", lambda lane, root=None: SPLIT)
    monkeypatch.setattr(adopt, "default_for", lambda lane, fallback, conn=None: "inc-spec")
    monkeypatch.setattr(screen, "candidate_for", lambda lane, name: name)
    return conn.execute("SELECT MAX(id) FROM verdicts").fetchone()[0]


def _fake_eval(monkeypatch, seen, pause_after=None, stale=False):
    """evals.run as far as a confirmation sees it: checkpoint per cell, pause file, --resume, PAUSED and STALE exits."""
    want = _rows(CELLS, "inc-key", "ch-key")

    def launch(argv, **kw):
        out = Path(argv[argv.index("--out") + 1])
        out.mkdir(parents=True, exist_ok=True)
        seen.setdefault("calls", []).append({"out": out, "resume": "--resume" in argv, "ran": 0})
        ident = {"modality": "code", "candidates": argv[argv.index("--candidates") + 1].split(","),
                 "repeat": int(argv[argv.index("--repeat") + 1]),
                 "split": argv[argv.index("--split") + 1] if "--split" in argv else "all"}
        had = watch.read(out) if "--resume" in argv else None
        if had and stale:
            return types.SimpleNamespace(returncode=watch.STALE, stderr="stale")
        done = {(r["candidate"], r["case_id"]) for r in (had or ({}, []))[1]}
        ckpt = watch.Checkpoint(out, ident, keep=bool(had))
        (out / watch.PAUSE_FILE).unlink(missing_ok=True)
        for row in want:
            if (row["candidate"], row["case_id"]) in done:
                continue
            if (out / watch.PAUSE_FILE).exists():
                (out / watch.PROGRESS).write_text(json.dumps({"state": "paused"}), encoding="utf-8")
                return types.SimpleNamespace(returncode=watch.PAUSED, stderr="paused on request")
            ckpt.add(row, 1.0)
            seen["calls"][-1]["ran"] += 1
            if len(seen["calls"]) == 1 and seen["calls"][0]["ran"] == pause_after:
                watch.ask_pause(out, "watchdog long_run")
        (out / watch.PROGRESS).write_text(json.dumps({"state": "done"}), encoding="utf-8")
        return types.SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(measure_cmd, "_launch", launch)
    monkeypatch.setattr(measure_cmd, "_receipt_at", lambda out: {
        "specs": {"inc-key": "inc-spec", "ch-key": "org/x"}, "rows": watch.read(out)[1]})


def _in_process(monkeypatch):
    """A popen for workqueue.run_one that runs `soh adopt --confirm` here, with the job's id in its environment."""
    def popen(argv, cwd=None, stdout=None, stderr=None, env=None):
        monkeypatch.setenv(workqueue.JOB_ENV, env[workqueue.JOB_ENV])
        try:
            rc = adopt_cmd.cmd_adopt(argparse.Namespace(power=False, from_measurement=False, confirm=int(argv[-1])))
        finally:
            monkeypatch.delenv(workqueue.JOB_ENV, raising=False)
        return types.SimpleNamespace(returncode=rc)
    return popen


def test_a_paused_confirmation_is_paused_queues_its_continuation_and_the_next_job_resumes_it(
        conn, tmp_path, monkeypatch):
    vid = _held(conn, tmp_path, monkeypatch)
    first = workqueue.pending(conn)
    assert len(first) == 1
    seen = {}
    _fake_eval(monkeypatch, seen, pause_after=8)
    before = conn.execute("SELECT COUNT(*) FROM verdicts").fetchone()[0]
    got = workqueue.run_one(first[0], popen=_in_process(monkeypatch))
    assert (got["state"], got["rc"]) == (workqueue.PAUSED, watch.PAUSED)
    assert conn.execute("SELECT COUNT(*) FROM verdicts").fetchone()[0] == before
    out = seen["calls"][0]["out"]
    assert out.parent == paths.home() / "runs" and out.name.endswith("-confirm-code")
    assert len(watch.read(out)[1]) == 8
    later = workqueue.pending(conn)
    assert len(later) == 1 and later[0]["id"] != first[0]["id"]
    assert later[0]["argv"][-2:] == ["--confirm", str(vid)]
    assert conn.execute("SELECT not_before FROM jobs WHERE id = ?", (int(later[0]["id"]),)).fetchone()[0] > time.time()

    got = workqueue.run_one(later[0], popen=_in_process(monkeypatch))
    assert (got["state"], got["rc"]) == (workqueue.DONE, 0)
    second = seen["calls"][1]
    assert second["resume"] and second["out"] == out
    assert second["ran"] == len(CELLS) * 2 - 8
    assert len(watch.read(out)[1]) == len(CELLS) * 2
    row = conn.execute("SELECT outcome, detail FROM verdicts ORDER BY id DESC LIMIT 1").fetchone()
    assert row["outcome"] == "measured", row["detail"]
    assert "confirmed on 10 dev case(s): 9 gained against 0 lost" in row["detail"]
    assert workqueue.pending(conn) == []


def _dir(name, candidates, state, split="dev"):
    out = paths.home() / "runs" / name
    out.mkdir(parents=True)
    watch.Checkpoint(out, {"modality": "code", "candidates": candidates, "repeat": 1, "split": split})
    (out / watch.PROGRESS).write_text(json.dumps({"state": state}), encoding="utf-8")
    return out


def test_only_an_unfinished_confirm_dir_for_the_same_pair_and_exam_is_resumed(conn, tmp_path, monkeypatch):
    vid = _held(conn, tmp_path, monkeypatch)
    pair = ["inc-spec", "org/x"]
    _dir("20261001-000000-confirm-code", ["inc-spec", "org/other"], "paused")
    _dir("20261002-000000-confirm-code", pair, "done")
    _dir("20261003-000000-confirm-code", pair, "paused", split="all")
    _dir("20261004-000000-confirm-svg", pair, "paused")
    seen = {}
    _fake_eval(monkeypatch, seen)
    assert measure_cmd.confirm_job(vid) == 0
    assert not seen["calls"][0]["resume"]
    assert seen["calls"][0]["out"].name.startswith(time.strftime("%Y"))
    older = _dir("20261005-000000-confirm-code", pair, "paused")
    newer = _dir("20261006-000000-confirm-code", pair, "paused")
    assert measure_cmd._confirm_dir("code", pair, 1, "dev") == newer
    assert measure_cmd._confirm_dir("code", pair, 2, "dev") is None
    assert older != newer


def test_a_resume_refused_as_another_exam_starts_fresh(conn, tmp_path, monkeypatch, capsys):
    vid = _held(conn, tmp_path, monkeypatch)
    old = _dir("20261005-000000-confirm-code", ["inc-spec", "org/x"], "paused")
    seen = {}
    _fake_eval(monkeypatch, seen, stale=True)
    assert measure_cmd.confirm_job(vid) == 0
    assert [(c["out"] == old, c["resume"]) for c in seen["calls"]] == [(True, True), (False, False)]
    assert "starting fresh" in capsys.readouterr().out
    assert conn.execute("SELECT outcome FROM verdicts ORDER BY id DESC LIMIT 1").fetchone()[0] == "measured"


def test_a_crashed_confirmation_still_fails_and_queues_nothing(conn, tmp_path, monkeypatch):
    vid = _held(conn, tmp_path, monkeypatch)
    conn.execute("DELETE FROM jobs")
    conn.commit()
    monkeypatch.setattr(measure_cmd, "_launch", lambda argv, **kw: types.SimpleNamespace(returncode=1, stderr="boom"))
    assert measure_cmd.confirm_job(vid) == 1
    assert workqueue.pending(conn) == []


def test_the_queue_records_exit_75_as_paused_and_lists_it(conn, monkeypatch, capsys):
    jobs = [workqueue.add(["true"], title=f"t{rc}", conn=conn) for rc in (75, 1, 0)]
    for job, rc in zip(jobs, (75, 1, 0)):
        workqueue.run_one(job, popen=lambda *a, rc=rc, **k: types.SimpleNamespace(returncode=rc))
    assert [workqueue.get(j["id"])["state"] for j in jobs] == [workqueue.PAUSED, workqueue.FAILED, workqueue.DONE]
    assert cli.main(["jobs", "list"]) == 0
    assert f"{jobs[0]['id']}  paused" in capsys.readouterr().out


def at(day, hour, minute=0):
    return datetime(2026, 10, day, hour, minute).timestamp()


@pytest.mark.parametrize("now, want", [
    (at(16, 15), at(16, 21)),
    (at(16, 23), at(17, 21)),
    (at(17, 5), at(17, 21)),
    (at(17, 8), at(17, 21)),
])
def test_the_next_night_is_tonight_by_day_and_tomorrow_night_at_night(monkeypatch, now, want):
    monkeypatch.setattr(heartbeat, "discover_hours", lambda: [21])
    monkeypatch.setattr(watchdog, "DAY_START_HOUR", 8)
    monkeypatch.setattr(watchdog, "DAY_END_HOUR", 21)
    assert workqueue.next_night(now) == want
