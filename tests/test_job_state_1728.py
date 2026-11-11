"""A queue job's state moves only by job_state's table, each move a compare-and-swap on the state it leaves. #1728."""
import json
import subprocess
import sys
import threading
import time
import types

import pytest

from evals import watch
from harness import contention, deploy, executors, job_state as js
from harness import memory_store as ms
from harness import workqueue as wq

BATCH = ["soh-batch-job"]


def _claimed(argv=BATCH, kind="command") -> dict:
    job = wq.add(argv, title="batch", kind=kind)
    assert wq._claim(job, wq.log_dir() / f"{job['id']}.log")
    return job


def _exits(rc: int, *flags: str):
    """A worker's child that sets `flags` beside its pid file and exits rc."""
    def popen(argv, cwd=None, stdout=None, stderr=None, env=None):
        key = env[wq.JOB_ENV]
        for name, f in wq._flag_files(key).items():
            if name in flags:
                f.write_text(json.dumps({"at": "now"}), encoding="utf-8")
        return types.SimpleNamespace(returncode=rc)
    return popen


# --- the table ---------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("frm,to,reason", [
    (js.DONE, js.CANCELLED, js.CANCEL),
    (js.FAILED, js.PENDING, js.WORKER_GONE),
    (js.PAUSED, js.PENDING, js.CONTENTION_PAUSE),
    (js.CANCELLED, js.RUNNING, js.CLAIMED),
    (js.PENDING, js.DONE, js.EXITED),
    (js.RUNNING, js.RUNNING, js.HANDED_OFF),
    (js.RUNNING, js.CANCELLED, js.SUPERSEDED),
    (js.PENDING, js.CANCELLED, js.EXITED),
])
def test_an_illegal_move_is_refused_and_writes_nothing(frm, to, reason):
    job = wq.add(BATCH, title="batch")
    conn = ms.connect()
    conn.execute("UPDATE jobs SET state = ? WHERE id = ?", (frm, int(job["id"])))
    conn.commit()
    with pytest.raises(js.IllegalMove):
        js.move(conn, job["id"], frm, to, reason, "never")
    conn.rollback()
    assert wq.get(job["id"], conn=conn)["state"] == frm and wq.get(job["id"], conn=conn)["note"] != "never"
    conn.close()


def test_no_terminal_state_has_a_move_out():
    assert not [k for k in js.MOVES if k[0] in (js.DONE, js.FAILED, js.CANCELLED, js.PAUSED)]


def test_a_move_names_no_column_outside_its_own():
    job = wq.add(BATCH, title="batch")
    conn = ms.connect()
    with pytest.raises(js.IllegalMove, match="priority"):
        js.move(conn, job["id"], js.PENDING, js.CANCELLED, js.CANCEL, priority=9)
    conn.close()


def test_a_second_writer_of_the_same_move_loses():
    job = _claimed()
    first, second = ms.connect(), ms.connect()
    assert js.move(first, job["id"], js.RUNNING, js.DONE, js.EXITED, rc=0)
    first.commit()
    assert not js.move(second, job["id"], js.RUNNING, js.FAILED, js.EXITED, "late", rc=1)
    second.commit()
    got = wq.get(job["id"])
    assert (got["state"], got["reason"], got["rc"]) == (js.DONE, js.EXITED, 0)


# --- exit precedence ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("rc,flags,handed,contended,want", [
    (0, {js.CANCEL_FLAG, js.STOP_FLAG}, False, False, (js.CANCELLED, js.CANCEL)),
    (watch.PAUSED, {js.CANCEL_FLAG, js.ITEM_FLAG, js.DEPLOY_FLAG}, False, True, (js.CANCELLED, js.CANCEL)),
    (deploy.HANDED_OFF, {js.STOP_FLAG}, True, False, (js.PENDING, js.DEPLOY_STOP)),
    (1, {js.STOP_FLAG, js.ITEM_FLAG}, False, False, (js.PENDING, js.DEPLOY_STOP)),
    (deploy.HANDED_OFF, set(), True, False, (js.RUNNING, js.HANDED_OFF)),
    (0, {js.ITEM_FLAG, js.DEPLOY_FLAG}, False, True, (js.DONE, js.EXITED)),
    (1, {js.ITEM_FLAG, js.DEPLOY_FLAG}, False, True, (js.FAILED, js.EXITED)),
    (watch.PAUSED, {js.ITEM_FLAG, js.DEPLOY_FLAG}, False, True, (js.PENDING, js.NEXT_ITEM)),
    (watch.PAUSED, {js.DEPLOY_FLAG}, False, True, (js.PENDING, js.DEPLOY_PAUSE)),
    (watch.PAUSED, set(), False, True, (js.PENDING, js.CONTENTION_PAUSE)),
    (watch.PAUSED, set(), False, False, (js.PAUSED, js.CHECKPOINTED)),
])
def test_an_exit_moves_by_flag_precedence_then_rc(rc, flags, handed, contended, want):
    assert js.exit_move(rc, frozenset(flags), handed, contended) == want


@pytest.mark.parametrize("flags,resumable,want", [
    ({js.CANCEL_FLAG, js.STOP_FLAG}, True, (js.CANCELLED, js.CANCEL)),
    ({js.STOP_FLAG}, True, (js.PENDING, js.DEPLOY_STOP)),
    ({js.ITEM_FLAG, js.DEPLOY_FLAG}, True, (js.PENDING, js.WORKER_GONE)),
    (set(), False, (js.FAILED, js.INTERRUPTED)),
])
def test_a_job_whose_worker_went_away_moves_by_flag_precedence(flags, resumable, want):
    assert js.gone_move(frozenset(flags), resumable) == want


def test_every_move_exit_and_gone_choose_is_in_the_table():
    froms = {js.CANCELLED: js.RUNNING, js.PENDING: js.RUNNING, js.DONE: js.RUNNING, js.FAILED: js.RUNNING,
             js.PAUSED: js.RUNNING}
    chosen = {js.exit_move(rc, frozenset(f), h, c) for rc in (0, 1, watch.PAUSED) for h in (False, True)
              for c in (False, True) for f in ((), (js.CANCEL_FLAG,), (js.STOP_FLAG,), (js.ITEM_FLAG,), (js.DEPLOY_FLAG,))}
    chosen |= {js.gone_move(frozenset(f), r) for r in (False, True) for f in ((), (js.CANCEL_FLAG,), (js.STOP_FLAG,))}
    for to, why in chosen - {(js.RUNNING, js.HANDED_OFF)}:
        assert not js.refused(froms[to], to, why), (to, why)


def test_cancel_and_stop_both_set_record_the_job_cancelled_and_leave_no_flag():
    job = wq.add(BATCH, title="batch")
    wq.run_one(wq.get(job["id"]), popen=_exits(0, js.CANCEL_FLAG, js.STOP_FLAG))
    got = wq.get(job["id"])
    assert (got["state"], got["reason"]) == (js.CANCELLED, js.CANCEL)
    assert wq._flags(job["id"]) == frozenset()


def test_a_deploy_flag_on_a_job_that_finished_is_cleared_at_its_exit_not_its_next_start():
    job = wq.add(BATCH, title="batch")
    wq.run_one(wq.get(job["id"]), popen=_exits(0, js.DEPLOY_FLAG, js.ITEM_FLAG))
    got = wq.get(job["id"])
    assert (got["state"], got["reason"]) == (js.DONE, js.EXITED) and wq._flags(job["id"]) == frozenset()


def test_a_paused_exit_nothing_repends_is_paused_checkpointed(monkeypatch):
    monkeypatch.setattr(contention, "paused_for", lambda c, job: False)
    job = wq.add(BATCH, title="batch")
    wq.run_one(wq.get(job["id"]), popen=_exits(watch.PAUSED))
    got = wq.get(job["id"])
    assert (got["state"], got["reason"]) == (js.PAUSED, js.CHECKPOINTED)


def test_a_paused_exit_whose_continuation_is_queued_names_it(monkeypatch):
    monkeypatch.setattr(contention, "paused_for", lambda c, job: True)
    job = wq.add(BATCH, title="batch")
    twin = wq.add(BATCH, title="its continuation")
    wq.run_one(wq.get(job["id"]), popen=_exits(watch.PAUSED))
    got = wq.get(job["id"])
    assert (got["state"], got["reason"]) == (js.PAUSED, js.CONTINUED) and twin["id"] in got["note"]


def test_an_item_end_with_no_stored_run_falls_to_the_deploy_pause(monkeypatch):
    from harness import runs
    monkeypatch.setattr(runs, "for_job", lambda c, i: None)
    job = wq.add(["uv", "run", "python", "-m", "evals.run", "--modality", "code"], title="eval")
    wq.run_one(wq.get(job["id"]), popen=_exits(watch.PAUSED, js.ITEM_FLAG, js.DEPLOY_FLAG))
    got = wq.get(job["id"])
    assert (got["state"], got["reason"]) == (js.PENDING, js.DEPLOY_PAUSE)


# --- cancel against a natural exit -------------------------------------------------------------------------------

@pytest.fixture
def leader():
    if sys.platform == "win32":
        pytest.skip("a process group leader is a POSIX notion")
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], start_new_session=True)
    yield p
    p.kill()
    p.wait()


def test_a_cancel_racing_a_natural_exit_cannot_turn_done_into_cancelled(monkeypatch, leader):
    job = _claimed()
    wq._pid_file(job["id"]).write_text(str(leader.pid), encoding="utf-8")

    found = wq._pid_of

    def pid_of(job_id):
        # Cancel found the process; it then finished on its own and the worker recorded that before the cancel flag.
        pid = found(job_id)
        assert not wq._settle_exit({**job, "finished": time.strftime(wq._STAMP)}, 0)
        return pid
    monkeypatch.setattr(wq, "_pid_of", pid_of)
    monkeypatch.setattr(executors, "for_job", lambda j: types.SimpleNamespace(stop=lambda pid, grace=None: "gone"))
    got = wq.cancel(job["id"])
    assert (got["state"], got["reason"], got["rc"]) == (js.DONE, js.EXITED, 0)
    assert "cancelled" not in got["note"]


def test_a_worker_exit_after_a_recorded_cancel_leaves_it_cancelled(monkeypatch, leader):
    job = _claimed()
    wq._pid_file(job["id"]).write_text(str(leader.pid), encoding="utf-8")
    monkeypatch.setattr(executors, "for_job", lambda j: types.SimpleNamespace(stop=lambda pid, grace=None: "term"))
    assert wq.cancel(job["id"])["state"] == js.CANCELLED
    said = wq.get(job["id"])["note"]
    assert not wq._settle_exit({**job, "finished": time.strftime(wq._STAMP)}, 0)
    got = wq.get(job["id"])
    assert (got["state"], got["note"]) == (js.CANCELLED, said)


# --- the pid a job's row points at ------------------------------------------------------------------------------

def test_a_live_pid_that_leads_no_group_is_not_the_jobs_process(leader):
    job = _claimed()
    stranger = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        wq._pid_file(job["id"]).write_text(str(stranger.pid), encoding="utf-8")
        assert wq._pid_of(job["id"]) is None
        wq._pid_file(job["id"]).write_text(str(leader.pid), encoding="utf-8")
        assert wq._pid_of(job["id"]) == leader.pid
    finally:
        stranger.kill()
        stranger.wait()


# --- reasons -----------------------------------------------------------------------------------------------------

def test_an_added_job_is_pending_added_and_a_superseded_deploy_says_so_in_its_reason():
    job = wq.add(BATCH, title="batch")
    assert (job["state"], job["reason"]) == (js.PENDING, js.ADDED)
    conn = ms.connect()
    old = wq.add([*deploy.SOH, "deploy", "run", "b" * 40], kind=deploy.KIND, output="b" * 40, conn=conn)
    assert js.move(conn, old["id"], js.PENDING, js.CANCELLED, js.SUPERSEDED, "replaced by a newer deploy")
    conn.commit()
    new = wq.add([*deploy.SOH, "deploy", "run", "c" * 40], kind=deploy.KIND, output="c" * 40, conn=conn)
    assert deploy.waiting_since(conn, new["id"])[1] == int(old["id"])
    conn.close()


def test_schema_94_names_a_superseded_deploy_from_its_note():
    from harness.memory_store.migrations import v94
    conn = ms.connect()
    old = wq.add([*deploy.SOH, "deploy", "run", "b" * 40], kind=deploy.KIND, output="b" * 40, conn=conn)
    other = wq.add(BATCH, title="batch", conn=conn)
    conn.execute("UPDATE jobs SET state = 'cancelled', reason = '', note = ? WHERE id IN (?, ?)",
                 (f"{deploy.SUPERSEDED}c", int(old["id"]), int(other["id"])))
    v94.data(conn)
    assert [wq.get(j["id"], conn=conn)["reason"] for j in (old, other)] == [js.SUPERSEDED, ""]
    conn.close()


# --- a job whose lease is lost ------------------------------------------------------------------------------------

def _lease_watch(monkeypatch, beat):
    from harness import item_lease
    monkeypatch.setattr(item_lease, "TTL_S", 0.6)
    monkeypatch.setattr(item_lease, "beat", beat)
    stopped = threading.Event()
    monkeypatch.setattr(wq, "_pid_of", lambda job_id: 4242)
    monkeypatch.setattr(executors, "for_job", lambda j: types.SimpleNamespace(
        stop=lambda pid, grace=None: stopped.set() or "term"))
    return wq.add(BATCH, title="batch"), stopped


def test_a_refused_lease_beat_stops_the_job(monkeypatch):
    job, stopped = _lease_watch(monkeypatch, lambda c, i: False)
    with wq.leased(job) as lease:
        assert lease is not None and stopped.wait(10)


def test_a_failing_lease_beat_stops_the_job_only_past_two_thirds_of_its_ttl(monkeypatch):
    def beat(c, i):
        raise OSError("the store will not answer")
    job, stopped = _lease_watch(monkeypatch, beat)
    started = time.monotonic()
    with wq.leased(job):
        assert stopped.wait(10)
    assert time.monotonic() - started >= 0.6 * 2 / 3


def test_a_lease_that_keeps_beating_never_stops_the_job(monkeypatch):
    job, stopped = _lease_watch(monkeypatch, lambda c, i: True)
    with wq.leased(job):
        assert not stopped.wait(1.0)


def test_a_new_gpu_job_waits_behind_a_lapsed_gpu_lease_whose_holder_still_runs():
    from harness import item_lease, resources
    conn = ms.connect()
    gone = item_lease.take(conn, resources.GPU, "render pid here", ttl_s=-1.0)
    conn.close()
    job = wq.add(["uv", "run", "python", "-m", "evals.run", "--modality", "code", "--candidates",
                  "llamacpp:Small-4B"], title="eval")
    assert wq.needs(job) == wq.GPU
    with wq.leased(job) as lease:
        assert lease is None
    assert f"gpu lease {gone['id']}" in job["refused"] and "lapsed" in job["refused"]
    conn = ms.connect()
    item_lease.release(conn, gone["id"])
    conn.close()
    with wq.leased(job) as lease:
        assert lease is not None
