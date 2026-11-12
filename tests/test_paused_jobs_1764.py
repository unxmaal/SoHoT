"""A paused queue job leaves paused by a named move: resumed when its cause clears, superseded, expired with one alert, or failed as needing a person. #1764."""
import time
import types

import pytest

from evals import watch
from harness import job_state as js
from harness import memory_store as ms
from harness import monitor, paused_jobs, pressure, runs
from harness import workqueue as wq

EVAL = ["uv", "run", "python", "-m", "evals.run", "--modality", "pii", "--candidates", "pii-regex"]
WARN, NORMAL = pressure.Pressure(level=pressure.NORMAL + 1), pressure.Pressure(level=pressure.NORMAL)


@pytest.fixture
def run_dir(tmp_path, monkeypatch):
    """Every job stored its partial run here."""
    where = tmp_path / "runs" / "x"
    where.mkdir(parents=True)
    monkeypatch.setattr(runs, "for_job", lambda c, i: {"path": str(where)})
    return where


@pytest.fixture
def alerts(monkeypatch):
    got = []
    monkeypatch.setattr(monitor, "alert", lambda kind, env, **k: got.append((kind, env["MONIT_DESCRIPTION"])))
    return got


def _pauses(job: dict, criterion: str = ""):
    """A child the watchdog pauses for `criterion` (none: a bare pause file or SIGUSR1), exiting PAUSED."""
    def popen(argv, cwd=None, stdout=None, stderr=None, env=None):
        if criterion:
            conn = ms.connect()
            conn.execute("INSERT INTO watchdog_actions (at, criterion, subject, action, escalated, dry_run, evidence, "
                         "outcome) VALUES (?, ?, ?, 'pause', 0, 0, '{}', 'paused')",
                         (time.time() + 1, criterion, "job " + job["id"]))
            conn.commit()
            conn.close()
        return types.SimpleNamespace(returncode=watch.PAUSED)
    return popen


def _paused(argv, criterion: str = "") -> dict:
    job = wq.add(argv, title="batch")
    wq.run_one(wq.get(job["id"]), popen=_pauses(job, criterion))
    got = wq.get(job["id"])
    assert got["state"] == wq.PAUSED
    return got


def _settle(now, sample, alert=None) -> list[dict]:
    conn = ms.connect()
    try:
        return paused_jobs.settle(conn, now, pressure=lambda: sample, alert=alert)
    finally:
        conn.close()


def test_a_memory_stuck_pause_resumes_where_it_stopped_once_pressure_is_back_to_normal(run_dir):
    job = _paused(EVAL, "memory_stuck")
    assert job["reason"] == js.MEMORY_PAUSE and "memory pressure is back to normal" in job["note"]
    assert _settle(time.time(), WARN) == [] and wq.get(job["id"])["state"] == wq.PAUSED
    assert [g["reason"] for g in _settle(time.time(), NORMAL)] == [js.RESUMED]
    got = wq.get(job["id"])
    assert (got["state"], got["reason"]) == (wq.PENDING, js.RESUMED)
    assert got["argv"] == [*EVAL, "--out", str(run_dir), "--resume"] and not got["finished"]


def test_the_worker_turn_resumes_a_memory_pause(run_dir, monkeypatch):
    job = _paused(EVAL, "memory_stuck")
    monkeypatch.setattr(pressure, "sample", lambda: NORMAL)
    assert [g["id"] for g in paused_jobs.turn(time.time())] == [job["id"]]
    assert wq.get(job["id"])["state"] == wq.PENDING


def test_the_worker_service_loop_takes_the_paused_turn(run_dir, monkeypatch):
    job = _paused(EVAL, "memory_stuck")
    monkeypatch.setattr(pressure, "sample", lambda: NORMAL)
    wq.serve(forever=False, gate_fn=lambda: (False, "held by the test"))
    assert wq.get(job["id"])["state"] == wq.PENDING


def test_an_evals_own_memory_deferral_is_a_memory_pause(run_dir):
    watch.ask_pause(run_dir, watch.MEMORY_HEADROOM)
    assert _paused(EVAL)["reason"] == js.MEMORY_PAUSE


def test_a_pause_whose_cause_never_clears_expires_at_the_knob_with_one_alert(run_dir, alerts):
    job = _paused(EVAL, "memory_stuck")
    at = wq._epoch(job["finished"])
    assert _settle(at + paused_jobs.EXPIRY_S - 1, WARN) == [] and alerts == []
    assert [g["reason"] for g in _settle(at + paused_jobs.EXPIRY_S, WARN)] == [js.EXPIRED]
    assert _settle(at + 2 * paused_jobs.EXPIRY_S, WARN) == []
    got = wq.get(job["id"])
    assert (got["state"], got["reason"]) == (wq.FAILED, js.EXPIRED)
    assert len(alerts) == 1 and f"job {job['id']}" in alerts[0][1] and js.EXPIRED in alerts[0][1]


def test_a_job_with_no_resume_path_ends_named_as_needing_a_person_with_one_alert(alerts):
    job = _paused(["soh-batch-job"], "memory_stuck")
    assert paused_jobs.resume_argv(ms.connect(), job) is None
    _settle(time.time(), NORMAL)
    _settle(time.time() + paused_jobs.EXPIRY_S, NORMAL)
    got = wq.get(job["id"])
    assert (got["state"], got["reason"]) == (wq.FAILED, js.NEEDS_OWNER) and "needs a person" in got["note"]
    assert len(alerts) == 1 and js.NEEDS_OWNER in alerts[0][1]
    assert got["argv"] == ["soh-batch-job"], "no resume argv is invented"


def test_a_pause_with_no_known_cause_waits_for_the_knob_then_expires(run_dir, alerts):
    job = _paused(EVAL)
    assert job["reason"] == js.CHECKPOINTED
    at = wq._epoch(job["finished"])
    assert _settle(at + 60, NORMAL) == [], "nothing says its cause cleared"
    assert [g["reason"] for g in _settle(at + paused_jobs.EXPIRY_S, NORMAL)] == [js.EXPIRED]
    assert len(alerts) == 1


def test_a_pause_while_the_queue_is_paused_resumes_when_the_owner_resumes_the_queue(run_dir):
    wq.pause("disk")
    job = _paused(EVAL)
    assert job["reason"] == js.QUEUE_PAUSE
    assert _settle(time.time(), NORMAL) == []
    wq.resume()
    assert [g["reason"] for g in _settle(time.time(), NORMAL)] == [js.RESUMED]


def test_a_paused_job_a_later_job_carries_on_is_superseded_not_resumed(run_dir, alerts):
    job = _paused(EVAL, "memory_stuck")
    twin = wq.add([*EVAL, "--out", str(run_dir), "--resume"], title="continuation")
    _settle(time.time(), NORMAL)
    got = wq.get(job["id"])
    assert (got["state"], got["reason"]) == (wq.CANCELLED, js.SUPERSEDED) and twin["id"] in got["note"]
    assert alerts == [] and [j["id"] for j in wq.pending()] == [twin["id"]]


def test_a_paused_job_an_open_reverification_owns_is_left_for_it_to_resume(run_dir):
    job = _paused(EVAL, "memory_stuck")
    conn = ms.connect()
    conn.execute("INSERT INTO reverifications (lane, spec, queued_at, job_id) VALUES ('pii', 'pii-regex', ?, ?)",
                 (time.time(), int(job["id"])))
    conn.commit()
    conn.close()
    assert _settle(time.time() + paused_jobs.EXPIRY_S, NORMAL) == []
    assert wq.get(job["id"])["state"] == wq.PAUSED


def test_a_paired_adopt_resumes_with_its_own_argv():
    argv = ["soh", "adopt", "--lane", "repo", "--challenger", "X", "--unscreened"]
    job = _paused(argv, "memory_stuck")
    _settle(time.time(), NORMAL)
    assert wq.get(job["id"])["argv"] == argv and wq.get(job["id"])["state"] == wq.PENDING


def test_the_owner_can_cancel_a_paused_job():
    job = _paused(["soh-batch-job"])
    got = wq.cancel(job["id"])
    assert (got["state"], got["reason"]) == (wq.CANCELLED, js.CANCEL) and "paused" in got["note"]


def test_every_move_out_of_paused_is_one_of_the_named_ends():
    out = {to: why for (frm, to), why in js.MOVES.items() if frm == js.PAUSED}
    assert out == {js.PENDING: {js.RESUMED}, js.FAILED: {js.EXPIRED, js.NEEDS_OWNER},
                   js.CANCELLED: {js.CANCEL, js.SUPERSEDED}}
