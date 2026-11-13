"""A pid, an argv or a file name keyed by pid is never taken for the process or job that held it before. #1774."""
import json
import os
import time

from harness import ds4, job_settle, paused_jobs, proc_identity, serve_lease, sweep_check
from harness import heartbeat as hb
from harness import job_state as js
from harness import memory_store as ms
from harness import workqueue as wq
from tests.test_paused_jobs_1764 import EVAL, NORMAL, _paused, _settle, alerts, run_dir  # noqa: F401

#: A start time no live process has.
OTHER = "1.000001"


def _rewrite(path, **fields) -> None:
    got = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(json.dumps({**got, **fields}), encoding="utf-8")


# ID-3: eval yielder files keyed by pid.

def test_a_dead_evals_cut_request_and_beside_lines_are_not_the_next_eval_with_its_pid():
    me = os.getpid()
    serve_lease._write(serve_lease._cut_path(me), {"at": time.time(), "why": "a dead eval's", "case": "c1"})
    serve_lease._beside_path(me).write_text(json.dumps({"at": time.time(), "lane": "decide"}) + "\n",
                                            encoding="utf-8")
    y = serve_lease.Yielder("runs/x")
    try:
        assert not y.cut_asked(), "the new eval would cut its first case for a delegation that asked the dead one"
        assert y.contended() == [], "the new eval read the dead run's beside lines as its own contention"
    finally:
        y.close()


def test_a_yielder_record_whose_pid_another_process_now_holds_is_dropped():
    path = serve_lease._dir("yielders") / f"{os.getpid()}.json"
    serve_lease._write(path, {"pid": os.getpid(), "started": OTHER, "state": serve_lease.CASE, "node": ""})
    assert serve_lease.yielders() == [] and not path.exists()


def test_a_live_yielder_and_an_old_record_without_a_start_time_still_count():
    y = serve_lease.Yielder("runs/x")
    try:
        assert [r["started"] for r in serve_lease.yielders()] == [proc_identity.started(os.getpid())]
        _rewrite(y.path, started="", pgid=None)
        assert [r["pid"] for r in serve_lease.yielders()] == [os.getpid()]
    finally:
        y.close()


def test_a_serving_lease_whose_pid_another_process_now_holds_is_released():
    lease = serve_lease.Lease("decide", "a delegation")
    assert [h["pid"] for h in serve_lease.holders()] == [os.getpid()]
    conn = ms.connect()
    try:
        conn.execute("UPDATE leases SET started = ? WHERE id = ?", (OTHER, lease.id))
        conn.commit()
    finally:
        conn.close()
    assert serve_lease.holders() == [], "evals would keep yielding to a delegation that is gone"


# ID-4: job identity by argv.

def _running(conn, argv) -> dict:
    job = wq.add(argv, conn=conn)
    assert js.move(conn, job["id"], wq.PENDING, wq.RUNNING, js.CLAIMED, machine_id=ms.machine_row(conn))
    conn.commit()
    return wq.get(job["id"], conn=conn)


def test_a_contention_paused_eval_is_not_continued_by_a_fresh_eval_with_its_argv(run_dir):  # noqa: F811
    conn = ms.connect()
    try:
        job = _running(conn, EVAL)
        fresh = wq.add(EVAL, title="next night's eval", conn=conn)
        assert job_settle._repend(conn, job, js.CONTENTION_PAUSE)
        got = wq.get(job["id"], conn=conn)
    finally:
        conn.close()
    assert got["state"] == wq.PENDING, f"job {fresh['id']} starts a new run dir, so it carries nothing on: {got['note']}"
    assert got["argv"] == [*EVAL, "--out", str(run_dir), "--resume"]


def test_a_contention_paused_eval_is_continued_by_a_job_resuming_its_run(run_dir):  # noqa: F811
    conn = ms.connect()
    try:
        job = _running(conn, EVAL)
        twin = wq.add([*EVAL, "--out", str(run_dir), "--resume"], title="continuation", conn=conn)
        assert job_settle._repend(conn, job, js.CONTENTION_PAUSE)
        got = wq.get(job["id"], conn=conn)
    finally:
        conn.close()
    assert (got["state"], got["reason"]) == (wq.PAUSED, js.CONTINUED) and wq.label(twin["id"]) in got["note"]


def test_a_paused_eval_is_not_superseded_by_a_later_fresh_eval_with_its_argv(run_dir, alerts):  # noqa: F811
    job = _paused(EVAL, "memory_stuck")
    wq.add(EVAL, title="next night's eval")
    _settle(time.time(), NORMAL)
    got = wq.get(job["id"])
    assert (got["state"], got["reason"]) == (wq.PENDING, js.RESUMED), got["note"]


def test_a_paused_command_with_no_resume_path_is_still_carried_on_by_the_same_command():
    job = _paused(["true", "reverify"], "memory_stuck")
    twin = wq.add(["true", "reverify"], title="the next one")
    conn = ms.connect()
    try:
        assert paused_jobs._twin(conn, wq.get(job["id"], conn=conn), None) == int(twin["id"])
    finally:
        conn.close()


# ID-6: the discover loop heartbeat's pid.

def test_a_heartbeat_whose_pid_another_process_now_holds_reads_stalled_not_running():
    hb.start(lane="code", total=3)
    assert hb.read()["pid_started"] == proc_identity.started(os.getpid())
    assert hb.status(hb.read()) == "running"
    _rewrite(hb.path(), **{"pid_started": OTHER})
    beat = hb.read()
    assert hb.status(beat) == "stalled" and "is gone" in hb.summary()["line"]
    assert hb.code_moved({**beat, "commit": "a" * 40}, "b" * 40) == ""
    unit = {"loaded": True, "state": "running", "pid": os.getpid()}
    assert sweep_check.verdict(unit, beat, time.time(), 0.0)["verdict"] == sweep_check.EXITED


def test_a_process_given_a_dead_loops_pid_does_not_write_its_heartbeat():
    hb.start(lane="code", total=3)
    _rewrite(hb.path(), **{"pid_started": OTHER})
    hb.finish(rc=0)
    assert hb.read()["state"] == hb.RUNNING


def test_a_heartbeat_written_before_start_times_is_judged_by_its_pid():
    hb.start(lane="code", total=3)
    _rewrite(hb.path(), **{"pid_started": ""})
    assert hb.status(hb.read()) == "running"
    hb.finish(rc=0)
    assert hb.read()["state"] == hb.FINISHED


# ID-7: the ds4 server's pid.

def test_a_ds4_state_whose_pid_another_process_now_holds_is_not_the_launch_answering(monkeypatch):
    monkeypatch.setattr(ds4, "_models", lambda base: {"data": [{"id": "x"}]})
    spec = "ds4:Qwen3.8-Flash-Next-Q2"
    ds4.write_state(spec, 18999, os.getpid())
    got = ds4.live(18999)
    assert got["key"] == ds4.key(spec) and got["started"] == proc_identity.started(os.getpid())
    _rewrite(ds4.state_path(18999), started=OTHER)
    assert "launch" not in ds4.live(18999), "a reused pid made an unknown server read as this harness's launch"


def test_a_ds4_state_written_before_start_times_is_judged_by_its_pid(monkeypatch):
    monkeypatch.setattr(ds4, "_models", lambda base: {"data": []})
    ds4.write_state("ds4:Qwen3.8-Flash-Next-Q2", 18998, os.getpid())
    _rewrite(ds4.state_path(18998), started="", pgid=None)
    assert "launch" in ds4.live(18998)
