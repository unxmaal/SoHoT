"""A deploy works without the owner: a bound on memory pressure, measurement paused for it, a failed sha retried, one alert. #1672."""
import os
import sys
import time
import types

import pytest

from harness import cli, contention, deploy, morning, paths, pressure, workqueue as wq
from harness import memory_store as ms
from harness.commands import morning as morning_cmd
from tests.test_deploy_1506 import _commit, _green, posix, world  # noqa: F401 - world is a fixture

WARN = pressure.Pressure(level=pressure.WARN)
NORMAL = pressure.Pressure(level=pressure.NORMAL)


@pytest.fixture
def warn(monkeypatch):
    """The real contention gate with memory pressure stuck at warn, the served lanes idle, no hold and no sweep."""
    monkeypatch.setattr(wq, "_contended", wq._contended.real)
    monkeypatch.setattr("harness.sweep_guard.running", lambda root, **kw: [])
    monkeypatch.setattr(contention, "_said", "")
    level = {"p": WARN}
    monkeypatch.setattr(pressure, "sample", lambda: level["p"])
    return level


def _deploy(queued_at: float, sha: str = "a" * 40) -> dict:
    job = wq.add([*deploy.SOH, "deploy", "run", sha], title=f"deploy {sha[:12]}", kind=deploy.KIND, output=sha,
                 priority=deploy.PRIORITY, requested_by="deploy", cwd=str(paths.home()))
    _set(job, created_at=queued_at)
    return job


def _set(job: dict, **cols) -> None:
    conn = ms.connect()
    conn.execute(f"UPDATE jobs SET {', '.join(f'{k} = ?' for k in cols)} WHERE id = ?", (*cols.values(), int(job["id"])))
    conn.commit()
    conn.close()


def _gpu() -> dict:
    return wq.add(["uv", "run", "python", "-m", "evals.run", "--modality", "code"], title="gpu", cwd=str(paths.home()))


def _starts(now: float):
    """What the worker would start now: the worker gate, then the first startable job."""
    ok, why = wq.gate(now=now)
    got = wq._startable({}, now) if ok else None
    return (got[0]["title"] if got else None), why


# --- the gate ---------------------------------------------------------------------------------------------------

def test_a_deploy_starts_past_its_bound_on_stuck_pressure_and_a_gpu_job_does_not(warn):
    now = time.time()
    gpu = _gpu()
    assert wq.needs(gpu) == wq.GPU
    assert _starts(now) == (None, "memory pressure level 2")
    job = _deploy(now - contention.DEPLOY_PRESSURE_S + 60)
    title, why = _starts(now)
    assert title is None and why.startswith("memory pressure level 2; the deploy waits on it until ")
    title, why = _starts(now + 61)
    assert title == job["title"] and "only the deploy starts" in why
    wq.cancel(job["id"])
    assert _starts(now + 61) == (None, "memory pressure level 2"), "a GPU job never rides the deploy's bound"


def test_the_gate_s_log_says_the_deploy_went_past_pressure(warn):
    now = time.time()
    said = []
    conn = ms.connect()
    try:
        contention.gate(conn, now, since=now - contention.DEPLOY_PRESSURE_S - 1, say=said.append)
        contention.gate(conn, now, say=said.append)
    finally:
        conn.close()
    assert "contention gate open: memory pressure level 2, but the deploy has waited past its" in said[0]
    assert said[1].endswith("contention gate closed: memory pressure level 2, not normal")
    assert _cuts("deploy_pressure_wait") == [(contention.DEPLOY_PRESSURE_S, 1)]


def _cuts(knob: str) -> list:
    conn = ms.connect()
    try:
        return [(r[0], r[1]) for r in conn.execute("SELECT value, dropped FROM limit_cuts WHERE knob = ?", (knob,))]
    finally:
        conn.close()


def test_a_deploy_still_waits_for_served_lanes_and_the_owner_hold(warn):
    from harness import hold
    now = time.time()
    job = _deploy(now - contention.DEPLOY_PRESSURE_S - 60)
    conn = ms.connect()
    conn.execute("INSERT INTO gateway_requests (at, alias, purpose, total_s) VALUES (?, ?, ?, ?)",
                 (now - 30, "sohot-decide", "work", 1.0))
    conn.commit()
    assert _starts(now)[0] is None
    assert _starts(now + contention.IDLE_S)[0] == job["title"]
    hold.hold(conn, "owner: a render", scope=hold.GPU)
    conn.close()
    assert _starts(now + contention.IDLE_S)[0] is None


def test_a_superseded_deploy_keeps_the_wait_of_the_one_it_replaced(warn):
    now = time.time()
    old = _deploy(now - contention.DEPLOY_PRESSURE_S - 60, sha="b" * 40)
    _set(old, state=wq.CANCELLED, note=f"{deploy.SUPERSEDED}{'c' * 12}")
    new = _deploy(now - 10, sha="c" * 40)
    conn = ms.connect()
    try:
        since, first = deploy.waiting_since(conn, new["id"])
    finally:
        conn.close()
    assert (round(since), first) == (round(now - contention.DEPLOY_PRESSURE_S - 60), int(old["id"]))
    assert _starts(now)[0] == new["title"]
    other = _deploy(now - 5, sha="d" * 40)
    _set(new, state=wq.DONE)
    conn = ms.connect()
    try:
        assert deploy.waiting_since(conn, other["id"])[1] == int(other["id"]), "a deploy that ran ends the wait"
    finally:
        conn.close()


# --- the alert --------------------------------------------------------------------------------------------------

def test_a_stuck_deploy_alerts_once_past_the_wait_knob_naming_why(warn, monkeypatch):
    monkeypatch.setattr(contention, "DEPLOY_PRESSURE_S", contention.DEPLOY_ALERT_S * 2)
    now = time.time()
    job = _deploy(now - contention.DEPLOY_ALERT_S + 60)
    sent = []
    assert deploy.watch_wait(now, alert=sent.append) is None and sent == []
    got = deploy.watch_wait(now + 61, alert=sent.append)
    assert got["job"] == job["id"] and len(sent) == 1
    assert f"deploy job {job['id']} of {'a' * 12}" in sent[0] and "memory pressure level 2" in sent[0]
    assert deploy.watch_wait(now + 3600, alert=sent.append) is None and len(sent) == 1
    assert _cuts("deploy_wait_alert") == [(contention.DEPLOY_ALERT_S, 1)]
    _set(job, state=wq.DONE)
    _deploy(now - contention.DEPLOY_ALERT_S - 1, sha="e" * 40)
    assert deploy.watch_wait(now, alert=sent.append) is not None and len(sent) == 2, "the next wait alerts again"


def test_a_paused_or_sweep_held_deploy_does_not_alert(warn, monkeypatch):
    monkeypatch.setattr(contention, "DEPLOY_PRESSURE_S", contention.DEPLOY_ALERT_S * 2)
    now = time.time()
    _deploy(now - contention.DEPLOY_ALERT_S - 60)
    monkeypatch.setattr("harness.sweep_guard.running", lambda root, **kw: [
        {"what": "discover loop", "pid": 4242, "started": None, "commit": "", "command": "discover --loop"}])
    sent = []
    assert deploy.watch_wait(now, alert=sent.append) is None and sent == []
    monkeypatch.setattr("harness.sweep_guard.running", lambda root, **kw: [])
    deploy.pause()
    assert deploy.watch_wait(now, alert=sent.append) is None and sent == []
    deploy.resume()
    assert deploy.watch_wait(now, alert=sent.append) is not None and len(sent) == 1


def test_a_deploy_that_starts_next_poll_does_not_alert(warn):
    warn["p"] = NORMAL
    now = time.time()
    _deploy(now - contention.DEPLOY_ALERT_S - 60)
    sent = []
    assert deploy.watch_wait(now, alert=sent.append) is None and sent == []


def test_the_worker_checks_the_wait_each_poll(monkeypatch):
    seen = []
    monkeypatch.setattr(deploy, "watch_wait", lambda now=None, alert=None: seen.append(now))
    monkeypatch.setattr(wq, "ready", lambda now=None: [])
    wq.serve(forever=False, clock=lambda: 123.0)
    assert seen == [123.0]


def test_the_alert_runs_monit_alert_sh_with_the_reason(monkeypatch):
    ran = []
    monkeypatch.setattr("subprocess.run", lambda argv, **kw: ran.append((argv, kw)))
    deploy._alert_script("deploy job 0001 waits")
    (argv, kw), = ran
    assert argv == ["bash", "scripts/monit-alert.sh", "deploy"]
    assert (kw["cwd"] / "scripts" / "monit-alert.sh").exists()
    assert kw["env"]["MONIT_SERVICE"] == "deploy" and kw["env"]["MONIT_DESCRIPTION"] == "deploy job 0001 waits"


# --- showing why ------------------------------------------------------------------------------------------------

def test_jobs_list_and_morning_say_why_a_pending_deploy_waits(warn, capsys, monkeypatch):
    monkeypatch.setattr(contention, "DEPLOY_PRESSURE_S", contention.DEPLOY_ALERT_S * 2)
    now = time.time()
    job = _deploy(now - contention.DEPLOY_ALERT_S - 60)
    assert cli.main(["jobs", "list"]) == 0
    out = capsys.readouterr().out
    assert f"deploy job {job['id']} of {'a' * 12} pending since" in out and "memory pressure level 2" in out
    conn = ms.connect()
    try:
        w = morning.deploy_wait(conn, now)
    finally:
        conn.close()
    r = {"deploys": [], "sweep": {"loop": None}, "deploy": {}, "stale": [], "ci": {}, "watchdog": [], "incidents": [],
         "deploy_wait": w}
    assert [n for n in morning.needs(r) if n.startswith(f"deploy job {job['id']}")] == [deploy.wait_line(w)]
    assert "memory pressure level 2" in deploy.wait_line(w)
    w["waited"] = contention.DEPLOY_ALERT_S - 1
    assert not [n for n in morning.needs(r) if n.startswith("deploy job")], "a short wait needs no person"


def test_morning_s_deploy_section_shows_a_pending_deploy_however_short_its_wait():
    from tests.test_morning_867 import _gh, _git
    now = time.time()
    w = {"job": "0007", "sha": "f" * 40, "since": now - 60, "first": 7, "waited": 60.0,
         "why": "the contention gate is closed: served lanes in use", "held": False}
    conn = ms.connect()
    try:
        r = morning.gather(conn, now, now - 86400, gh=_gh(), git=_git(), lanes=lambda c: [],
                           waiting=lambda c, at: w)
    finally:
        conn.close()
    assert r["deploy_wait"] is w
    assert f"          {deploy.wait_line(w)}" in morning_cmd.render(r)
    assert deploy.wait_line(w).endswith("(0.0 h): the contention gate is closed: served lanes in use")


# --- a pending deploy preempts measurement ----------------------------------------------------------------------

def _measuring(title: str = "measure") -> dict:
    return wq.add(["uv", "run", "python", "-m", "evals.run", "--modality", "code"], title=title,
                  cwd=str(paths.home()))


def _running(job: dict) -> dict:
    assert wq._claim(job, wq.log_dir() / f"{job['id']}.log")
    wq._pid_file(job["id"]).write_text(str(os.getpid()), encoding="utf-8")
    return job


def _kills(monkeypatch) -> list:
    got = []
    monkeypatch.setattr(wq.os, "kill", lambda pid, sig: got.append((pid, sig)) if sig else None)
    return got


def test_a_due_deploy_asks_a_running_measurement_job_s_evals_to_pause_once(monkeypatch):
    killed = _kills(monkeypatch)
    job = _running(_measuring())
    other = _running(wq.add(["true"], title="fetch", cwd=str(paths.home())))
    asked = []

    def evals(pid):
        asked.append(pid)
        return [111, 222]
    assert wq.preempt_for_deploy(evals=evals, signal_=10) == [], "no deploy pending, nothing paused"
    _deploy(time.time())
    said = wq.preempt_for_deploy(evals=evals, signal_=10)
    assert killed == [(111, 10), (222, 10)] and len(said) == 2 and all(f"job {job['id']}" in s for s in said)
    assert asked == [os.getpid()], f"only the measurement job's group is read, not job {other['id']}'s"
    assert wq.preempt_for_deploy(evals=evals, signal_=10) == [] and len(killed) == 2, "each eval is asked once"
    assert wq.preempt_for_deploy(evals=lambda pid: [111, 333], signal_=10)[0].endswith("for the pending deploy")
    assert killed[-1] == (333, 10), "an eval the job starts after the ask is asked too"


def test_a_paused_or_not_yet_due_deploy_preempts_nothing(monkeypatch):
    killed = _kills(monkeypatch)
    _running(_measuring())
    job = _deploy(time.time())
    deploy.pause()
    assert wq.preempt_for_deploy(evals=lambda pid: [111], signal_=10) == [] and killed == []
    deploy.resume()
    _set(job, not_before=time.time() + 3600)
    assert wq.preempt_for_deploy(evals=lambda pid: [111], signal_=10) == [] and killed == []


def test_a_job_paused_for_the_deploy_waits_again_to_resume(monkeypatch):
    killed = _kills(monkeypatch)
    job = _measuring()
    _deploy(time.time())

    def popen(argv, cwd=None, stdout=None, stderr=None, env=None):
        wq._pid_file(job["id"]).write_text(str(os.getpid()), encoding="utf-8")
        wq.preempt_for_deploy(evals=lambda pid: [4242], signal_=10)
        return types.SimpleNamespace(returncode=75)
    wq.run_one(job, popen=popen)
    got = wq.get(job["id"])
    assert killed == [(4242, 10)]
    assert got["state"] == wq.PENDING and got["note"].startswith("paused for a deploy at ")
    assert not wq._deploy_flag(job["id"]).exists()


def test_a_job_that_pauses_on_its_own_is_not_repended_as_the_deploy_s():
    job = _measuring()
    wq.run_one(job, popen=lambda argv, **kw: types.SimpleNamespace(returncode=75))
    assert wq.get(job["id"])["state"] == wq.PAUSED


def test_measurement_waits_while_a_deploy_waits_for_a_running_eval(monkeypatch):
    measure, fetch = _measuring(), wq.add(["true"], title="fetch", cwd=str(paths.home()))
    job = _deploy(time.time())
    monkeypatch.setattr("harness.sweep_guard.running", lambda root, **kw: [
        {"what": "eval x", "pid": 4242, "started": None, "commit": "", "command": "evals.run"}])
    assert [j["title"] for j in wq.ready()] == ["fetch"]
    deploy.pause()
    assert [j["title"] for j in wq.ready()] == ["measure", "fetch"], "a paused deploy holds nothing back"
    deploy.resume()
    monkeypatch.setattr("harness.sweep_guard.running", lambda root, **kw: [])
    assert [j["id"] for j in wq.ready()] == [job["id"], measure["id"], fetch["id"]]


def test_evals_in_a_group_are_read_from_ps(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    out = ("  101  100 uv run soh adopt --confirm 7\n  102  100 python -m evals.run --out runs/x\n"
           "  103  999 python -m evals.run --out runs/y\n  104  100 llama-server -m x.gguf\n")
    monkeypatch.setattr(wq.subprocess, "run", lambda *a, **k: types.SimpleNamespace(stdout=out, returncode=0))
    assert wq._evals_in(100) == [102]
    monkeypatch.setattr(sys, "platform", "win32")
    assert wq._evals_in(100) == []


def test_each_worker_turn_preempts_for_the_deploy(monkeypatch, capsys):
    seen = []
    monkeypatch.setattr(wq, "preempt_for_deploy", lambda now=None: seen.append(now) or ["job 0001: asked"])
    wq.add(["true"], title="t", cwd=str(paths.home()))
    wq.run_pending(popen=lambda argv, **kw: types.SimpleNamespace(returncode=0), clock=lambda: 5.0)
    assert seen and set(seen) == {5.0} and "job 0001: asked" in capsys.readouterr().out


# --- a failed deploy is tried again -----------------------------------------------------------------------------

@posix
def test_a_failed_sha_is_queued_again_after_its_wait_up_to_its_retries(world):
    head = _commit(world["work"], {"f": "two\n"}, "two")
    now = time.time()
    job = deploy.poll(src=world["link"], green=_green, environ={}, now=now)["queued"]
    _set(job, state=wq.FAILED, finished_at=now)
    got = deploy.poll(src=world["link"], green=_green, environ={}, now=now + 60)
    assert got["queued"] is None and f"failed as job {job['id']}; retry 1 of {deploy.RETRIES} at " in got["why"]
    for _ in range(deploy.RETRIES):
        job = deploy.poll(src=world["link"], green=_green, environ={}, now=now + deploy.RETRY_S + 1)["queued"]
        assert job["output"] == head
        _set(job, state=wq.FAILED, finished_at=now)
    got = deploy.poll(src=world["link"], green=_green, environ={}, now=now + deploy.RETRY_S * 9)
    assert got["queued"] is None and f"past its {deploy.RETRIES} retries" in got["why"]
    assert len(_cuts("deploy_retry_after")) == deploy.RETRIES and len(_cuts("deploy_retries")) == 1


@posix
def test_a_cancelled_deploy_is_not_retried(world):
    _commit(world["work"], {"f": "two\n"}, "two")
    now = time.time()
    job = deploy.poll(src=world["link"], green=_green, environ={}, now=now)["queued"]
    _set(job, state=wq.CANCELLED, finished_at=now)
    got = deploy.poll(src=world["link"], green=_green, environ={}, now=now + deploy.RETRY_S * 9)
    assert got["queued"] is None and got["why"].endswith(f"is already queued as job {job['id']} (cancelled)")
