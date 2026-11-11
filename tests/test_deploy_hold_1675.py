"""A deploy never waits on benchmark work: the override holds the queue and stops whole jobs, the sweep yields, a confirm resumes. #1675."""
import json
import os
import signal
import subprocess
import sys
import time
import types
from pathlib import Path

import pytest

import shells
from evals import watch
from harness import deploy, exclusive, heartbeat, paths, workqueue as wq
from harness.commands import loop as loop_cmd
from harness.commands import measure as measure_cmd
from tests.test_confirm_resume_1357 import CELLS, _fake_eval, _held, _in_process, conn  # noqa: F401 - conn is a fixture
from tests.test_deploy_wait_1672 import _deploy, _measuring, _running

REPO = Path(__file__).resolve().parents[1]
posix = pytest.mark.skipif(sys.platform == "win32" or shells.BASH is None, reason="POSIX process groups and bash")

# A job like 1622's `adopt --confirm`: whenever its eval (in a session of its own) exits, it starts another.
RELAUNCHER = """
import subprocess, sys, time
while True:
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(300)"], start_new_session=True)
    with open(sys.argv[1], "a") as f:
        f.write(f"{p.pid}\\n")
    p.wait()
"""


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _children(path: Path, n: int = 1, within: float = 10.0) -> list[int]:
    deadline = time.monotonic() + within
    while time.monotonic() < deadline:
        got = [int(x) for x in path.read_text(encoding="utf-8").split()] if path.exists() else []
        if len(got) >= n:
            return got
        time.sleep(0.05)
    raise AssertionError(f"no child written to {path}")


# --- the override holds the queue and stops whole jobs ---------------------------------------------------------

@posix
def test_the_override_stops_a_relaunching_job_with_its_child_and_nothing_starts_until_release(tmp_path):
    job = wq.add([sys.executable, "-c", RELAUNCHER], title="confirm web", cwd=str(paths.home()))
    assert wq._claim(job, wq.log_dir() / f"{job['id']}.log")
    pids = tmp_path / "kids"
    leader = wq.spawn_group([sys.executable, "-c", RELAUNCHER, str(pids)], None, subprocess.DEVNULL, None)
    wq._pid_file(job["id"]).write_text(str(leader.pid), encoding="utf-8")
    try:
        [child] = _children(pids)
        os.kill(child, signal.SIGTERM)
        relaunched = _children(pids, 2)[-1]
        assert relaunched != child, "the fake relaunches its child as job 1622 did"
        said = wq.hold_for_deploy(grace=5.0)
        leader.wait(timeout=10)
        time.sleep(0.5)
        assert not _alive(relaunched), "the child in its own session outlived the stop"
        assert len(_children(pids, 2)) == 2, "nothing was relaunched after the stop"
        assert said[0] == "queue held for the deploy; it is released when the install ends"
        assert said[1].startswith(f"job {job['id']} stopped for the deploy (")
        got = wq.get(job["id"])
        assert got["state"] == wq.PENDING and got["note"].startswith("stopped for a deploy at ")
        assert wq.gate() == (False, "paused (soh jobs resume)"), "no job starts until the install ends"
        assert wq.release_for_deploy() == "queue released after the deploy"
        assert not wq.paused() and not wq._held_flag().exists()
    finally:
        for p in _children(pids, 1):
            if _alive(p):
                os.kill(p, getattr(signal, "SIGKILL", signal.SIGTERM))
        if leader.poll() is None:
            leader.kill()


def test_a_pause_the_owner_set_before_the_deploy_is_left_alone():
    wq.pause()
    assert wq.hold_for_deploy() == ["queue was already paused by its owner and stays paused after the deploy "
                                    "(soh jobs resume)"]
    assert wq.release_for_deploy() == "queue not held for a deploy; left as it was"
    assert wq.paused()


def test_a_second_hold_keeps_the_first_and_one_release_lifts_it():
    wq.hold_for_deploy()
    assert wq.hold_for_deploy() == ["queue already held for a deploy; it is released when the install ends"]
    assert wq.release_for_deploy() == "queue released after the deploy" and not wq.paused()


def test_a_pause_set_while_the_deploy_held_the_queue_stays():
    wq.hold_for_deploy()
    wq._pause_flag().write_text("2026-11-09T19:05:00 the owner", encoding="utf-8")
    assert wq.release_for_deploy() == "queue left as it is: it was paused again during the deploy (soh jobs resume)"
    assert wq.paused() and not wq._held_flag().exists()


def test_a_deploy_job_and_a_job_with_no_process_here_are_not_stopped():
    d = _running(_deploy(time.time()))
    gone = wq.add(["true"], title="gone", cwd=str(paths.home()))
    assert wq._claim(gone, wq.log_dir() / "x.log")
    stopped = []
    said = wq.hold_for_deploy(stop=lambda pid, grace: stopped.append(pid) or "term", tree=lambda pid: [])
    assert stopped == [] and len(said) == 1
    assert wq.get(d["id"])["state"] == wq.RUNNING and wq.get(gone["id"])["state"] == wq.RUNNING


def test_a_stopped_bare_eval_resumes_from_the_run_its_process_was_writing(monkeypatch):
    job = _running(_measuring())
    monkeypatch.setattr(wq, "alive", lambda pid: pid in (os.getpid(), 4343))
    out = paths.runs() / "20261109-184554-code"
    out.mkdir(parents=True)
    (out / watch.PROGRESS).write_text(json.dumps({"state": "running", "pid": 4343}), encoding="utf-8")
    other = paths.runs() / "20261109-000000-code"
    other.mkdir()
    (other / watch.PROGRESS).write_text(json.dumps({"state": "running", "pid": 9999}), encoding="utf-8")
    left = []
    said = wq.hold_for_deploy(stop=lambda pid, grace: "term", tree=lambda pid: [(pid, "uv"), (4343, "evals.run")],
                              stop_rest=lambda rest, **kw: left.extend(r["pid"] for r in rest) or [])
    got = wq.get(job["id"])
    assert got["argv"][-3:] == ["--out", str(out), "--resume"], got["argv"]
    assert left == [4343] and said[-1].endswith("it resumes after it")


def test_the_worker_re_pends_a_job_the_deploy_stopped_rather_than_failing_it():
    job = _measuring()

    def popen(argv, cwd=None, stdout=None, stderr=None, env=None):
        wq._stop_flag(job["id"]).write_text(json.dumps({"at": "x", "argv": ["resumed"]}), encoding="utf-8")
        return types.SimpleNamespace(returncode=-15)
    got = wq.run_one(job, popen=popen)
    assert got["state"] == wq.PENDING and got["argv"] == ["resumed"], got
    assert got["note"].startswith("stopped for a deploy at ")


def test_a_job_the_deploy_stopped_whose_worker_went_away_waits_again():
    job = _measuring()
    assert wq._claim(job, wq.log_dir() / "x.log")
    wq._stop_flag(job["id"]).write_text("{}", encoding="utf-8")
    assert wq._recover() == []
    assert wq.get(job["id"])["state"] == wq.PENDING


def test_hold_and_release_run_from_the_command_line():
    env = {**os.environ, paths.ENV_VAR: str(paths.home())}
    held = subprocess.run([sys.executable, "-m", "harness.workqueue", "hold-for-deploy"], cwd=REPO, env=env,
                          capture_output=True, text=True, timeout=120)
    assert held.returncode == 0 and "queue held for the deploy" in held.stdout, held.stderr[-800:]
    freed = subprocess.run([sys.executable, "-m", "harness.workqueue", "release-for-deploy"], cwd=REPO, env=env,
                           capture_output=True, text=True, timeout=120)
    assert freed.returncode == 0 and freed.stdout.strip() == "queue released after the deploy", freed.stderr[-800:]


# --- launchd.sh: hold before the guard, release whatever install did -------------------------------------------

def _locked(tmp_path, override: bool, lock_rc: int = 0):
    scripts, bin_ = tmp_path / "scripts", tmp_path / "bin"
    scripts.mkdir()
    bin_.mkdir()
    log = tmp_path / "log"
    text = (REPO / "scripts" / "launchd.sh").read_text(encoding="utf-8")
    (scripts / "lib.sh").write_text(text[:text.index('case "${1:-}" in')], encoding="utf-8")
    (scripts / "run.sh").write_text('source "$(dirname "$0")/lib.sh"\nsweep_guard() { echo guard >> "$LOG"; }\n'
                                    '_locked_install reinstall\nexit\n', encoding="utf-8")
    for path, body in ((bin_ / "uv", 'echo "uv $*" >> "$LOG"\n'),
                       (scripts / "with-gpu-lock", f'echo "lock $*" >> "$LOG"\nexit {lock_rc}\n')):
        path.write_text(f"#!/bin/sh\n{body}", encoding="utf-8")
        path.chmod(0o755)
    (tmp_path / "lh").mkdir()
    (tmp_path / "lh" / "install.env").write_text("HF_HOME=/\n", encoding="utf-8")
    env = {**os.environ, "PATH": f"{bin_}{os.pathsep}{os.environ['PATH']}", "HOME": str(tmp_path / "home"),
           "LOCALHARNESS_HOME": str(tmp_path / "lh"), "LOG": str(log), "LH_ROLE": "scheduler"}
    env.pop("LH_GPU_LOCK_HELD", None)
    env.pop("LH_DEPLOY_DURING_SWEEP", None)
    if override:
        env["LH_DEPLOY_DURING_SWEEP"] = "1"
    got = subprocess.run([shells.BASH, str(scripts / "run.sh")], env=env, capture_output=True, text=True, timeout=60)
    return got, [ln.split(" -m ")[-1] if ln.startswith("uv ") else ln.split(" ")[0]
                 for ln in log.read_text(encoding="utf-8").splitlines()]


@posix
def test_the_override_holds_the_queue_before_the_guard_and_releases_it_after_install(tmp_path):
    got, calls = _locked(tmp_path, override=True)
    assert got.returncode == 0, got.stderr
    assert calls == ["harness.workqueue hold-for-deploy", "guard", "lock", "harness.workqueue release-for-deploy"]


@posix
def test_a_failed_install_still_releases_the_queue_and_keeps_its_exit(tmp_path):
    got, calls = _locked(tmp_path, override=True, lock_rc=3)
    assert got.returncode == 3, got.stderr
    assert calls[-1] == "harness.workqueue release-for-deploy"


@posix
def test_without_the_override_the_queue_is_not_touched(tmp_path):
    got, calls = _locked(tmp_path, override=False)
    assert got.returncode == 0 and calls == ["guard", "lock"], (got.stderr, calls)


def test_an_install_waiting_on_a_queued_job_names_how_to_stop_it():
    hint = exclusive._stop_hint([{"job_id": 1622}, {"job_id": None}])
    assert "LH_DEPLOY_DURING_SWEEP=1 scripts/launchd.sh install" in hint and "soh jobs cancel 1622)" in hint
    assert exclusive._stop_hint([{"job_id": None}]) == ""


@pytest.fixture(autouse=True)
def _leads(monkeypatch):
    """This process stands in for a job's process, which as a real job's would lead its own group. #1728."""
    monkeypatch.setattr(wq, "_leads", lambda pid: True)


# --- the scheduled sweep yields to a due deploy -----------------------------------------------------------------

@pytest.fixture
def loop_beat(monkeypatch):
    """This process as a running discover loop that offers to yield, as the sweep guard sees it."""
    monkeypatch.setattr("harness.env.unmounted", lambda *a: "")
    heartbeat.start(total=loop_cmd.LOOP_TOTAL)
    restore = loop_cmd._yield_on_signal()
    monkeypatch.setattr("harness.sweep_guard.running", lambda root, **kw: [
        {"what": "discover loop", "pid": os.getpid(), "started": None, "commit": "", "command": "discover --loop"}])
    yield
    restore()
    loop_cmd._ASKED.clear()


@pytest.mark.skipif(not hasattr(signal, "SIGUSR1"), reason="SIGUSR1 is POSIX")
def test_a_due_deploy_asks_the_sweep_and_its_evals_and_the_sweep_yields_at_its_checkpoint(loop_beat):
    assert heartbeat.read()[heartbeat.YIELDS] is True
    loop_cmd._beat("fetch")
    _deploy(time.time())
    asked = []
    said = wq.preempt_for_deploy(evals=lambda pid: asked.append(pid) or [], signal_=signal.SIGUSR1)
    assert said == [f"discover loop {os.getpid()} asked to yield at its next checkpoint for the pending deploy"]
    assert asked == [os.getpid()], "the loop's evals, in their own sessions, are found under it"
    assert wq.preempt_for_deploy(evals=lambda pid: [], signal_=signal.SIGUSR1) == [], "said once"
    with pytest.raises(loop_cmd.DeployDue) as due:
        loop_cmd._beat("screen")
    assert due.value.tier == "screen"


def test_a_loop_that_does_not_offer_to_yield_is_never_signalled(monkeypatch):
    heartbeat.start(total=loop_cmd.LOOP_TOTAL)
    monkeypatch.setattr("harness.sweep_guard.running", lambda root, **kw: [
        {"what": "discover loop", "pid": os.getpid(), "started": None, "commit": "", "command": "discover --loop"}])
    killed = []
    monkeypatch.setattr(wq.os, "kill", lambda pid, sig: killed.append(pid))
    _deploy(time.time())
    assert wq.preempt_for_deploy(evals=lambda pid: [], signal_=10) == [] and killed == []


def test_the_measure_step_yields_before_its_next_measurement_once_asked(monkeypatch):
    from harness import ceiling
    monkeypatch.setattr(loop_cmd, "_servable_lanes", lambda rows, want, sweep, refusal=None: list(rows))
    sweep = ceiling.Sweep(3600)
    sweep.halted = "paused on request"  # what the deploy's pause of its eval leaves; it held the rest back
    loop_cmd._ASKED.append(True)
    try:
        with pytest.raises(loop_cmd.DeployDue):
            loop_cmd._measure_all(types.SimpleNamespace(lane=""), [{"name": "a"}], sweep, [])
    finally:
        loop_cmd._ASKED.clear()


def test_a_yielded_sweep_finishes_its_heartbeat_waits_for_the_deploy_and_exits_78(monkeypatch, capsys):
    monkeypatch.setattr("harness.hold.held", lambda *a, **k: "")
    beats = []

    def run_loop(a):
        due = loop_cmd.DeployDue("measure")
        due.left = 1800.0
        raise due

    def after(left):
        beats.append(dict(heartbeat.read()))
        return loop_cmd.YIELDED
    monkeypatch.setattr(loop_cmd, "_run_loop", run_loop)
    monkeypatch.setattr(loop_cmd, "_after_deploy", after)
    assert loop_cmd._report_loop(types.SimpleNamespace(run=True, lane="")) == loop_cmd.YIELDED
    beat = beats[0]
    assert beat["state"] == heartbeat.FINISHED and beat["rc"] == loop_cmd.YIELDED, "the deploy waits on a running beat"
    assert beat[heartbeat.PAUSED]["tier"] == "measure"


def test_the_wait_ends_when_the_deploy_is_done_and_hands_on_the_ceiling_left():
    t = {"now": 0.0}
    busy = iter([True, True, False])
    got = loop_cmd._after_deploy(3600.0, sleep=lambda s: t.update(now=t["now"] + s), clock=lambda: t["now"],
                                 busy=lambda: next(busy))
    assert got == loop_cmd.YIELDED
    left = json.loads((paths.home() / loop_cmd.YIELD_FILE).read_text(encoding="utf-8"))["left_s"]
    assert left == 3600.0 - 2 * loop_cmd.YIELD_POLL_S
    from harness import power
    a = types.SimpleNamespace(ceiling_h=None)
    assert loop_cmd._ceiling_s(a, environ={}) == float(power.SWEEP_CEILING_H) * 3600, "a fresh sweep has it all"
    assert loop_cmd._ceiling_s(a, environ={"LH_SWEEP_RESUMED": "1"}) == left
    assert not (paths.home() / loop_cmd.YIELD_FILE).exists(), "the ceiling left is handed on once"


def test_a_deploy_that_outlasts_the_ceiling_ends_the_sweep():
    t = {"now": 0.0}
    got = loop_cmd._after_deploy(60.0, sleep=lambda s: t.update(now=t["now"] + s), clock=lambda: t["now"],
                                 busy=lambda: True)
    assert got == 0 and not (paths.home() / loop_cmd.YIELD_FILE).exists()


def test_a_deploy_job_pending_or_switching_here_is_in_flight():
    assert not loop_cmd._deploy_in_flight()
    job = _deploy(time.time())
    assert loop_cmd._deploy_in_flight()
    deploy.pause()
    assert not loop_cmd._deploy_in_flight(), "a paused deploy is not waited for"
    deploy.resume()
    _running(job)
    assert loop_cmd._deploy_in_flight()


@posix
def test_serve_discover_goes_on_from_the_deployed_release_after_a_yield(tmp_path):
    old, new, bin_ = tmp_path / "old", tmp_path / "new", tmp_path / "bin"
    for d in (old / "scripts", new / "scripts", bin_):
        d.mkdir(parents=True)
    (old / "scripts" / "serve-discover.sh").write_text(
        (REPO / "scripts" / "serve-discover.sh").read_text(encoding="utf-8"), encoding="utf-8")
    (old / "scripts" / "env.sh").write_text("", encoding="utf-8")
    (old / "scripts" / "launchd.sh").write_text(f'[ "$1" = deploy-path ] && echo "{new}"\n', encoding="utf-8")
    (new / "scripts" / "serve-discover.sh").write_text('echo "new release resumed=$LH_SWEEP_RESUMED"\n',
                                                       encoding="utf-8")
    uv = bin_ / "uv"
    uv.write_text("#!/bin/sh\nexit ${UV_RC}\n", encoding="utf-8")
    uv.chmod(0o755)
    env = {**os.environ, "PATH": f"{bin_}{os.pathsep}{os.environ['PATH']}", "LOCALHARNESS_HOME": str(tmp_path / "h")}
    got = subprocess.run([shells.BASH, str(old / "scripts" / "serve-discover.sh")], env={**env, "UV_RC": "78"},
                         capture_output=True, text=True, timeout=60)
    assert got.returncode == 0 and "new release resumed=1" in got.stdout, (got.stdout, got.stderr)
    got = subprocess.run([shells.BASH, str(old / "scripts" / "serve-discover.sh")], env={**env, "UV_RC": "3"},
                         capture_output=True, text=True, timeout=60)
    assert got.returncode == 3 and "new release" not in got.stdout


# --- a preempted confirm resumes its run ------------------------------------------------------------------------

def _with_flag(monkeypatch, flag):
    """_in_process, with the queue's flag for this job written as the job starts, as a deploy writes it."""
    inner = _in_process(monkeypatch)

    def popen(argv, cwd=None, stdout=None, stderr=None, env=None):
        flag(env[wq.JOB_ENV]).write_text("4242", encoding="utf-8")
        return inner(argv, cwd=cwd, stdout=stdout, stderr=stderr, env=env)
    return popen


def test_a_confirmation_paused_for_a_deploy_is_the_same_job_and_resumes_its_run(conn, tmp_path, monkeypatch):
    vid = _held(conn, tmp_path, monkeypatch)
    [job] = wq.pending(conn)
    seen = {}
    _fake_eval(monkeypatch, seen, pause_after=8)
    got = wq.run_one(job, popen=_with_flag(monkeypatch, wq._deploy_flag))
    assert got["state"] == wq.PENDING and got["note"].startswith("paused for a deploy at "), got
    assert [j["id"] for j in wq.pending(conn)] == [job["id"]], "no second job: the queue re-pends this one"
    assert got["argv"][-2:] == ["--confirm", str(vid)]
    got = wq.run_one(wq.get(job["id"]), popen=_in_process(monkeypatch))
    assert got["state"] == wq.DONE
    assert seen["calls"][1]["resume"] and seen["calls"][1]["out"] == seen["calls"][0]["out"]
    assert seen["calls"][1]["ran"] == len(CELLS) * 2 - 8, "it went on from its 8 cells, not from the start"


def test_a_confirmation_whose_eval_a_signal_stopped_resumes_rather_than_fails(conn, tmp_path, monkeypatch):
    vid = _held(conn, tmp_path, monkeypatch)
    conn.execute("DELETE FROM jobs")
    conn.commit()
    seen = {}
    _fake_eval(monkeypatch, seen, pause_after=8)
    real = measure_cmd._launch

    def term(argv, **kw):
        got = real(argv, **kw)
        return types.SimpleNamespace(returncode=128 + signal.SIGTERM, stderr="") if len(seen["calls"]) == 1 else got
    monkeypatch.setattr(measure_cmd, "_launch", term)
    assert measure_cmd.confirm_job(vid) == watch.PAUSED
    [later] = wq.pending(conn)
    assert later["argv"][-2:] == ["--confirm", str(vid)]


def test_an_overrun_stop_still_ends_a_confirmation(conn, tmp_path, monkeypatch):
    vid = _held(conn, tmp_path, monkeypatch)
    conn.execute("DELETE FROM jobs")
    conn.commit()

    def launch(argv, **kw):
        out = Path(argv[argv.index("--out") + 1])
        out.mkdir(parents=True, exist_ok=True)
        watch.mark_stop(out, watch.OVERRUN)
        return types.SimpleNamespace(returncode=-signal.SIGTERM, stderr="stopped")
    monkeypatch.setattr(measure_cmd, "_launch", launch)
    assert measure_cmd.confirm_job(vid) == 1 and wq.pending(conn) == []


def test_a_confirmation_whose_worker_went_away_waits_to_resume_its_run():
    job = wq.add(["uv", "run", "soh", "adopt", "--confirm", "20271"], title="confirm", cwd=str(paths.home()))
    assert wq._claim(job, wq.log_dir() / "x.log")
    wq._recover()
    got = wq.get(job["id"])
    assert got["state"] == wq.PENDING and got["argv"] == job["argv"]
    assert got["note"] == "its worker went away; resumes from its stored run"
