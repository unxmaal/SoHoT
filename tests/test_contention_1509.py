"""The contention gate in place of the night rule: GPU work starts on no hold, normal memory and idle served lanes, and a served client pauses it until they are idle again. #1509."""
import json
import sys
import time
import types

import pytest

from harness import cli, contention, pressure, runs, workqueue as wq
from harness import memory_store as ms
from harness import watchdog as wd, watchdog_observe
from tests.test_watchdog import Fake, Hand, P, run


@pytest.fixture
def gate(monkeypatch):
    """The real contention check, with memory pressure as the test sets it."""
    monkeypatch.setattr(wq, "_contended", wq._contended.real)
    level = {"level": pressure.NORMAL}
    monkeypatch.setattr(pressure, "sample", lambda: pressure.Pressure(level=level["level"]))
    return level


def served(at, purpose="unknown", alias="sohot-decide", total=1.0):
    conn = ms.connect()
    conn.execute("INSERT INTO gateway_requests (at, alias, purpose, total_s) VALUES (?, ?, ?, ?)",
                 (at, alias, purpose, total))
    conn.commit()
    conn.close()


def py(code):
    return [sys.executable, "-c", code]


def started(clock) -> list:
    return [j["title"] for j in wq.run_pending(clock=lambda: clock)]


# --- starting -----------------------------------------------------------------------------------------

def test_high_memory_pressure_keeps_a_gpu_job_from_starting(gate):
    wq.add(py("pass"), title="gpu")
    gate["level"] = pressure.WARN
    assert started(time.time()) == [] and [j["title"] for j in wq.pending()] == ["gpu"]
    gate["level"] = pressure.NORMAL
    assert started(time.time()) == ["gpu"]


def test_a_served_client_holds_gpu_jobs_and_deploys_until_the_lanes_are_idle(gate, monkeypatch):
    monkeypatch.setattr("harness.sweep_guard.running", lambda root, **kw: [])
    now = time.time()
    served(now - 60)
    gpu = wq.add(py("pass"), title="gpu")
    assert wq._startable({}, now) is None
    deploy = wq.add(["true"], title="deploy x", kind=wq.DEPLOY, priority=1000, cwd=".")
    assert wq._startable({}, now) is None, "a held deploy lets nothing start ahead of it"
    assert wq._startable({}, now - 60 + contention.IDLE_S + 2)[0]["id"] == deploy["id"]
    wq.cancel(deploy["id"])
    assert wq._startable({}, now - 60 + contention.IDLE_S + 2)[0]["id"] == gpu["id"]


@pytest.mark.parametrize("purpose", ["eval", "smoke", "watchdog", "discover", "internal"])
def test_soh_s_own_traffic_never_holds_the_gate(gate, purpose):
    now = time.time()
    served(now - 5, purpose=purpose)
    wq.add(py("pass"), title="gpu")
    assert wq._startable({}, now)[0]["title"] == "gpu"


def test_a_job_a_client_waits_on_is_serving_and_never_held(gate):
    now = time.time()
    served(now - 5)
    wq.add(py("pass"), title="batch")
    wq.add(py("pass"), title="image", requested_by="mcp")
    assert wq._startable({}, now)[0]["title"] == "image"


def test_the_gate_says_each_change_of_decision_once(gate, monkeypatch):
    monkeypatch.setattr(contention, "_said", "")
    said, conn = [], ms.connect()
    for _ in range(2):
        contention.gate(conn, time.time(), say=said.append)
    gate["level"] = pressure.WARN
    contention.gate(conn, time.time(), say=said.append)
    assert [s.split(" ", 1)[1] for s in said] == [
        f"contention gate open: memory pressure normal, served lanes idle {contention.IDLE_S:.0f} s, no hold",
        "contention gate closed: memory pressure level 2, not normal"]


# --- the owner's hold, in place of soh day clear ---------------------------------------------------------

def test_an_owner_hold_closes_the_gate_until_released_or_its_end(gate, capsys):
    from harness import hold
    assert cli.main(["hold", "gpu"]) != 0, "a hold says who and why"
    assert cli.main(["hold", "gpu", "owner:", "a", "video", "render"]) == 0
    conn = ms.connect()
    v = contention.verdict(conn)
    assert not v["open"] and v["why"] == "held by the owner: owner: a video render (soh hold release gpu)"
    capsys.readouterr()
    assert cli.main(["gate"]) == 0 and "gpu held since" in capsys.readouterr().out
    assert cli.main(["hold", "release", "gpu"]) == 0 and contention.verdict(conn)["open"]
    hold.hold(conn, "owner: lunch", until=time.time() + 60, scope=hold.GPU)
    assert not contention.verdict(conn)["open"] and contention.verdict(conn, time.time() + 61)["open"]
    with pytest.raises(SystemExit):
        cli.main(["day", "clear", "owner: all day"])


# --- pausing and resuming ----------------------------------------------------------------------------------

def _watchdog_sees(job, tmp_path, hand, now):
    """One acting wake, from the job's own thread, that sees its group hold the GPU lock with a progress file to pause through."""
    pid = 4242
    fake = Fake(tmp_path, procs=[P(pid, 1, pid, 60, "uv run soh adopt --lane code"),
                                 P(pid + 1, pid, pid + 1, 60, "uv run python -m evals.run --modality code")],
                jobs={job["id"]: pid}, lock={"kind": "eval", "pid": pid + 1, "pgid": pid + 1},
                progress=[run(pid + 1, now=now, tmp=tmp_path)],
                rows={job["id"]: {"state": "running", "title": job["title"], "requested_by": job["requested_by"]}})
    conn = ms.connect()
    try:
        wd.wake(conn, fake, hand, act=True, now=now, say=lambda *_: None)
    finally:
        conn.close()


def _popen(steps):
    """A job command that runs `steps` in turn, one per start, each writing to the job's log and returning its rc."""
    def popen(argv, cwd=None, stdout=None, stderr=None, env=None):
        rc = steps.pop(0)()
        stdout.write(f"part rc={rc}\n")
        return types.SimpleNamespace(returncode=rc)
    return popen


def test_served_traffic_during_a_gpu_job_pauses_it_at_a_checkpoint_and_it_resumes_when_idle(gate, tmp_path):
    hand, at = Hand(), {}
    job = wq.add(["soh-batch-job"], title="batch")

    def first():
        at["req"] = time.time()
        served(at["req"])
        _watchdog_sees(wq.get(job["id"]), tmp_path, hand, at["req"] + 1)
        return 75

    popen = _popen([first, lambda: 0])
    assert [j["state"] for j in wq.run_pending(popen=popen, clock=time.time)] == [wq.PENDING]
    assert (wd.PAUSE, "job " + job["id"]) in hand.done
    got = wq.get(job["id"])
    assert got["state"] == wq.PENDING and got["note"].startswith("paused for contention")
    assert wq.run_pending(popen=popen, clock=lambda: at["req"] + 60) == [], "the lanes are not idle yet"
    later = at["req"] + contention.IDLE_S + 2
    assert [j["state"] for j in wq.run_pending(popen=popen, clock=lambda: later)] == [wq.DONE]
    log = open(wq.get(job["id"])["log"], encoding="utf-8").read()
    assert "part rc=75" in log and "part rc=0" in log, "the resumed part keeps the first part's log"


def test_a_job_paused_for_anything_else_stays_paused(gate, tmp_path):
    job = wq.add(["soh-batch-job"], title="batch")

    def first():
        conn = ms.connect()
        conn.execute("INSERT INTO watchdog_actions (at, criterion, subject, action, escalated, dry_run, evidence, "
                     "outcome, result, job_id) VALUES (?, 'long_run', ?, 'pause', 1, 0, '{}', 'paused', 'acted', ?)",
                     (time.time() + 1, "job " + job["id"], int(job["id"])))
        conn.commit()
        return 75

    wq.run_pending(popen=_popen([first]), clock=time.time)
    assert wq.get(job["id"])["state"] == wq.PAUSED


def test_a_command_that_queued_its_own_continuation_is_left_paused(gate, tmp_path):
    job = wq.add(["soh-batch-job"], title="batch")

    def first():
        served(time.time())
        _watchdog_sees(wq.get(job["id"]), tmp_path, Hand(), time.time() + 1)
        wq.add(["soh-batch-job"], title="continuation")
        return 75

    wq.run_pending(popen=_popen([first]), clock=time.time)
    assert wq.get(job["id"])["state"] == wq.PAUSED
    assert [j["title"] for j in wq.pending()] == ["continuation"]


def test_a_paused_bare_eval_resumes_from_its_stored_run(gate, tmp_path, monkeypatch):
    argv = ["uv", "run", "python", "-m", "evals.run", "--modality", "pii", "--candidates", "pii-regex"]
    job = wq.add(argv, title="eval", requested_by="reverify")
    monkeypatch.setattr(runs, "for_job", lambda c, i: {"path": str(tmp_path / "runs" / "x")})

    def first():
        served(time.time())
        _watchdog_sees(wq.get(job["id"]), tmp_path, Hand(), time.time() + 1)
        return 75

    wq.run_pending(popen=_popen([first]), clock=time.time)
    got = wq.get(job["id"])
    assert got["state"] == wq.PENDING
    assert got["argv"] == [*argv, "--out", str(tmp_path / "runs" / "x"), "--resume"]


def test_an_unreadable_contention_reading_skips_the_criterion_and_the_wake_goes_on(tmp_path):
    class Broken(Fake):
        def contention(self, conn, now):
            raise OSError("hold file unreadable")

    fake = Broken(tmp_path, procs=[P(500, 1, 500, 60, "uv run soh adopt --lane code")], jobs={"0007": 500},
                  lock={"kind": "eval", "pid": 500, "pgid": 500})
    world = watchdog_observe.observe(fake, None, time.time())
    found, skipped = wd.judge(world)
    assert "hold file unreadable" in skipped[contention.CRITERION] and world.contention is None
    assert not [f for f in found if f.criterion == contention.CRITERION]


def test_the_watchdog_never_pauses_a_job_a_client_waits_on(tmp_path):
    now = time.time()
    fake = Fake(tmp_path, procs=[P(500, 1, 500, 60, "uv run soh image x")], jobs={"0007": 500},
                lock={"kind": "image", "pid": 500, "pgid": 500},
                rows={"0007": {"state": "running", "title": "image", "requested_by": "mcp"}},
                contention={"hold": {"said": "owner"}, "requests": [("sohot-decide", now - 5)]})
    found, _ = wd.judge(watchdog_observe.observe(fake, None, now))
    assert [f for f in found if f.criterion == contention.CRITERION] == []
    fake.rows["0007"]["requested_by"] = "cli"
    found, _ = wd.judge(watchdog_observe.observe(fake, None, now))
    got = [f for f in found if f.criterion == contention.CRITERION]
    assert [f.subject.key for f in got] == ["job 0007"]
    assert got[0].evidence["hold"] == "owner" and got[0].evidence["served"] == 1
    assert json.dumps(got[0].evidence)
