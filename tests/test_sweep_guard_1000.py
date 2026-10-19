"""#1000: a deploy refuses while a sweep runs, the loop records its commit, and morning and the audit say when code moved under it."""
from __future__ import annotations

import io
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from evals import watch
from harness import heartbeat, live_audit, morning, paths, sweep_guard, watchdog
from tests import shells
from tests.test_morning_867 import NOW, SINCE, _beat, _gh, _git, _store, deploy_dir  # noqa: F401

REPO = Path(__file__).resolve().parents[1]
GEN = REPO / "scripts" / "launchd.sh"
LOOP_CMD = "/opt/lh/deploy/.venv/bin/python3 /opt/lh/deploy/.venv/bin/soh discover --loop --run"
EVAL_CMD = "/opt/lh/deploy/.venv/bin/python3 -m evals.run --modality code --out /x/runs/measure-1"
A, B = "a" * 40, "b" * 40


def _home(tmp_path, beat=None, evals=()):
    root = tmp_path / "lh"
    root.mkdir(exist_ok=True)
    if beat is not None:
        (root / sweep_guard.HEARTBEAT).write_text(json.dumps(beat), encoding="utf-8")
    for name, pid in evals:
        d = root / sweep_guard.RUNS / name
        d.mkdir(parents=True)
        (d / sweep_guard.PROGRESS).write_text(json.dumps({"state": "running", "pid": pid, "started_at": 1.0}),
                                              encoding="utf-8")
    return root


def _loop(pid=4242, commit=A):
    return {"state": "running", "pid": pid, "started": time.mktime((2026, 10, 18, 21, 0, 0, 0, 0, -1)),
            "commit": commit}


def test_the_guard_reads_what_the_harness_writes():
    assert sweep_guard.HEARTBEAT == heartbeat.path().name
    assert sweep_guard.PROGRESS == watch.PROGRESS
    assert sweep_guard.RUNS == paths.runs().name
    assert sweep_guard.EVAL.pattern == watchdog._EVAL.pattern
    assert watchdog._DISCOVER.search(LOOP_CMD) and sweep_guard.LOOP.search(LOOP_CMD)


def test_a_running_loop_and_its_eval_are_found_by_pid(tmp_path):
    root = _home(tmp_path, _loop(), evals=[("measure-1", 5151)])
    cmds = {4242: LOOP_CMD, 5151: EVAL_CMD}
    got = sweep_guard.running(root, alive=lambda p: p in cmds, command_of=cmds.get)
    assert [(r["what"], r["pid"]) for r in got] == [("discover loop", 4242), ("eval measure-1", 5151)]


@pytest.mark.parametrize("alive,command", [(False, LOOP_CMD), (True, "/usr/bin/vim notes.txt"), (True, "")])
def test_a_dead_or_reused_pid_is_not_a_sweep(tmp_path, alive, command):
    root = _home(tmp_path, _loop())
    assert sweep_guard.running(root, alive=lambda p: alive, command_of=lambda p: command) == []


def test_a_finished_loop_is_not_a_sweep(tmp_path):
    root = _home(tmp_path, {**_loop(), "state": "finished"})
    assert sweep_guard.running(root, alive=lambda p: True, command_of=lambda p: LOOP_CMD) == []


def test_the_guard_refuses_naming_the_pid_its_start_and_commit(tmp_path):
    root = _home(tmp_path, _loop())
    err = io.StringIO()
    rc = sweep_guard.check(root, environ={}, err=err, alive=lambda p: True, command_of=lambda p: LOOP_CMD,
                           stopper=lambda found: pytest.fail("refusing stops nothing"))
    said = err.getvalue()
    assert rc == sweep_guard.REFUSED
    assert "REFUSING to deploy: discover loop (pid 4242, started 2026-10-18 21:00 on aaaaaaaaaaaa)" in said
    assert f"{sweep_guard.OVERRIDE}=1" in said


def test_the_override_stops_the_loop_and_settles_its_heartbeat(tmp_path):
    root = _home(tmp_path, _loop())
    gone = set()

    def stopper(found):
        gone.update(r["pid"] for r in found)
        return []
    rc = sweep_guard.check(root, environ={sweep_guard.OVERRIDE: "1"}, err=io.StringIO(),
                           alive=lambda p: p not in gone, command_of=lambda p: LOOP_CMD, stopper=stopper)
    assert rc == sweep_guard.OK and gone == {4242}
    beat = json.loads((root / sweep_guard.HEARTBEAT).read_text(encoding="utf-8"))
    assert beat["state"] == "finished" and beat["finished_commit"] == A and "stopped for a deploy" in beat["error"]
    assert heartbeat.code_moved(beat, B) == ""


def test_the_override_refuses_when_a_pid_outlives_the_kill(tmp_path):
    root = _home(tmp_path, _loop())
    err = io.StringIO()
    rc = sweep_guard.check(root, environ={sweep_guard.OVERRIDE: "1"}, err=err, alive=lambda p: True,
                           command_of=lambda p: LOOP_CMD, stopper=lambda found: [4242])
    assert rc == sweep_guard.REFUSED and "pid(s) 4242 outlived SIGKILL" in err.getvalue()
    assert json.loads((root / sweep_guard.HEARTBEAT).read_text(encoding="utf-8"))["state"] == "running"


def test_the_override_must_be_exactly_one(tmp_path):
    root = _home(tmp_path, _loop())
    assert sweep_guard.check(root, environ={sweep_guard.OVERRIDE: "yes"}, err=io.StringIO(), alive=lambda p: True,
                             command_of=lambda p: LOOP_CMD, stopper=lambda f: []) == sweep_guard.REFUSED


def test_stop_terms_then_kills_what_outlives_the_grace():
    live, sent = {7}, []

    def kill(pid, sig):
        sent.append(sig)
        if sig != signal.SIGTERM:
            live.discard(pid)
    now = iter(range(100))
    left = sweep_guard.stop([{"pid": 7}], grace=3, alive=lambda p: p in live, kill=kill, sleep=lambda s: None,
                            clock=lambda: next(now))
    assert sent == [signal.SIGTERM, getattr(signal, "SIGKILL", signal.SIGTERM)] and left == []


def test_nothing_running_lets_the_deploy_go_ahead_quietly(tmp_path):
    err = io.StringIO()
    assert sweep_guard.check(_home(tmp_path), environ={}, err=err) == sweep_guard.OK and err.getvalue() == ""


# --- the loop records the commit it started on ---------------------------------

def test_the_heartbeat_carries_the_commit_the_loop_started_and_finished_on(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALHARNESS_HOME", str(tmp_path))
    commits = iter([A, B])
    monkeypatch.setattr(heartbeat, "code_commit", lambda: next(commits))
    heartbeat.start("code")
    assert heartbeat.read()["commit"] == A
    heartbeat.finish(0)
    got = heartbeat.read()
    assert got["finished_commit"] == B
    assert heartbeat.code_moved(got).startswith("the sweep started on aaaaaaaa and finished on bbbbbbbb")


def test_code_commit_reads_this_checkout():
    got = subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"], capture_output=True, text=True)
    assert heartbeat.code_commit() == got.stdout.strip()


def test_code_commit_reads_a_detached_deploy_worktree_and_packed_refs(tmp_path):
    src = tmp_path / "src"
    subprocess.run(["git", "init", "-q", "-b", "main", str(src)], check=True)
    _git_c(src, "config", "user.email", "t@example.invalid")
    _git_c(src, "config", "user.name", "t")
    (src / "f").write_text("x\n", encoding="utf-8")
    _git_c(src, "add", "f")
    _git_c(src, "commit", "-q", "-m", "one")
    sha = _git_c(src, "rev-parse", "HEAD")
    _git_c(src, "worktree", "add", "-q", "--detach", str(tmp_path / "deploy"), sha)
    assert heartbeat.code_commit(tmp_path / "deploy") == sha
    _git_c(src, "pack-refs", "--all")
    assert not (src / ".git" / "refs" / "heads" / "main").exists()
    assert heartbeat.code_commit(src) == sha
    assert heartbeat.code_commit(tmp_path / "not-a-repo") == ""


@pytest.mark.parametrize("beat,head,moved", [
    ({"state": "finished", "commit": A, "finished_commit": A}, B, False),
    ({"state": "finished", "commit": A, "finished_commit": B}, A, True),
    ({"state": "running", "pid": 1, "commit": A}, B, True),
    ({"state": "running", "pid": 1, "commit": A}, A, False),
    ({"state": "running", "pid": -1, "commit": A}, B, False),
    ({"state": "finished", "finished_commit": B}, A, False),
])
def test_code_moved_only_when_the_loops_own_code_changed(beat, head, moved):
    assert bool(heartbeat.code_moved(beat, head, alive=lambda p: p > 0)) is moved


# --- soh morning and soh audit say so ------------------------------------------

def test_morning_says_a_sweep_ran_on_code_a_deploy_replaced(deploy_dir):  # noqa: F811
    beat = {**_beat(), "commit": B, "finished_commit": A}
    r = morning.gather(_store(), NOW, SINCE, beat=beat, gh=_gh(), git=_git(), where=deploy_dir, lanes=lambda c: [])
    assert r["needs"] == ["the sweep started on bbbbbbbb and finished on aaaaaaaa: a deploy landed under it, "
                          "so it ran bbbbbbbb's code"]


def test_morning_is_quiet_when_the_sweep_ran_on_one_commit(deploy_dir):  # noqa: F811
    beat = {**_beat(), "commit": A, "finished_commit": A}
    r = morning.gather(_store(), NOW, SINCE, beat=beat, gh=_gh(), git=_git(behind=1), where=deploy_dir,
                       lanes=lambda c: [])
    assert r["needs"] == ["deploy is 1 commit(s) behind origin/main"]


def test_morning_names_a_running_sweep_under_a_newer_deploy(deploy_dir):  # noqa: F811
    beat = {"state": "running", "status": "running", "pid": os.getpid(), "started": NOW - 3600, "commit": B,
            "line": "discovery loop running"}
    r = morning.gather(_store(), NOW, SINCE, beat=beat, gh=_gh(), git=_git(), where=deploy_dir, lanes=lambda c: [])
    assert "the sweep started on bbbbbbbb and is still running under aaaaaaaa" in r["needs"][0]


def test_the_audit_warns_about_a_sweep_on_moved_code(tmp_path, monkeypatch):
    from harness import memory_store as ms
    monkeypatch.setenv("LOCALHARNESS_HOME", str(tmp_path))
    ms.connect(tmp_path / "discovery.db").close()
    (tmp_path / "loop-heartbeat.json").write_text(json.dumps(
        {"state": "finished", "started": time.time(), "commit": A, "finished_commit": B}), encoding="utf-8")
    check = {c["name"]: c for c in live_audit.audit(tmp_path / "discovery.db")["checks"]}["sweep_on_deployed_code"]
    assert check["ok"] and check["warn"] and "a deploy landed under it" in check["detail"]


# --- launchd.sh: install refuses while a loop runs, and the override stops it ---

def _git_c(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def stub_main(tmp_path):
    """origin/main whose launchd.sh is a stub, so an install that gets past deploy re-runs only that."""
    origin, work = tmp_path / "origin.git", tmp_path / "work"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    subprocess.run(["git", "clone", "-q", str(origin), str(work)], check=True)
    _git_c(work, "config", "user.email", "t@example.invalid")
    _git_c(work, "config", "user.name", "t")
    (work / "scripts").mkdir()
    (work / "scripts" / "launchd.sh").write_text('echo "deployed copy ran: $1"\n', encoding="utf-8")
    _git_c(work, "add", "scripts")
    _git_c(work, "commit", "-q", "-m", "stub")
    _git_c(work, "push", "-q", "origin", "HEAD:main")
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    (bin_ / "launchctl").write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    (bin_ / "gh").write_text('#!/bin/sh\nif [ "$1 $2" = "run list" ]; then\n'
                             '  while [ $# -gt 0 ]; do [ "$1" = --commit ] && sha="$2"; shift; done\n'
                             '  printf \'[{"databaseId":7,"status":"completed","conclusion":"success",'
                             '"headSha":"%s","url":"u"}]\' "$sha"\nelse\n'
                             '  printf \'{"jobs":[{"name":"check-macos","status":"completed",'
                             '"conclusion":"success"}]}\'\nfi\n', encoding="utf-8")
    for f in bin_.iterdir():
        f.chmod(0o755)
    return work, bin_


@pytest.fixture
def fake_loop(tmp_path):
    """A `discover --loop` process launchd would own: detached, so init reaps it rather than this test."""
    pidfile = tmp_path / "loop.pid"
    subprocess.run([shells.BASH, "-c", f'"{sys.executable}" -c "import time; time.sleep(120)" discover --loop '
                    f'>/dev/null 2>&1 & echo $! > "{pidfile}"'], check=True)
    pid = int(pidfile.read_text(encoding="utf-8"))
    home = tmp_path / "lh"
    home.mkdir()
    (home / "loop-heartbeat.json").write_text(json.dumps(_loop(pid)), encoding="utf-8")
    yield pid, home
    if sweep_guard.alive(pid):
        os.kill(pid, getattr(signal, "SIGKILL", signal.SIGTERM))


def _gone(pid, within=10.0):
    deadline = time.monotonic() + within
    while time.monotonic() < deadline:
        if not sweep_guard.alive(pid):
            return True
        time.sleep(0.1)
    return False


def _install(work, bin_, home, deploy, **extra):
    env = {**os.environ, "PATH": f"{bin_}{os.pathsep}{os.environ['PATH']}", "HOME": str(home.parent / "home"),
           "LOCALHARNESS_HOME": str(home), "LH_REPO": str(work), "LH_DEPLOY": str(deploy),
           "LH_GPU_LOCK_HELD": "1", "LH_ROLE": "scheduler", **extra}
    for k in ("LH_REEXECED", "LH_DEPLOY_UNCHECKED", *(() if sweep_guard.OVERRIDE in extra else (sweep_guard.OVERRIDE,))):
        env.pop(k, None)
    return subprocess.run([shells.BASH, str(GEN), "install"], env=env, capture_output=True, text=True, timeout=90)


@pytest.mark.skipif(sys.platform == "win32", reason="launchd.sh and ps are POSIX")
def test_install_refuses_while_a_loop_runs_and_names_its_pid(stub_main, fake_loop, tmp_path):
    (work, bin_), (pid, home) = stub_main, fake_loop
    got = _install(work, bin_, home, tmp_path / "deploy")
    assert got.returncode != 0
    assert f"REFUSING to deploy: discover loop (pid {pid}" in got.stderr, got.stderr
    assert not (tmp_path / "deploy").exists(), "nothing is checked out under a running loop"
    assert sweep_guard.alive(pid), "refusing stops nothing"


@pytest.mark.skipif(sys.platform == "win32", reason="launchd.sh and ps are POSIX")
def test_install_with_the_override_stops_the_loop_then_deploys(stub_main, fake_loop, tmp_path):
    (work, bin_), (pid, home) = stub_main, fake_loop
    got = _install(work, bin_, home, tmp_path / "deploy", **{sweep_guard.OVERRIDE: "1"})
    assert got.returncode == 0, got.stderr
    assert _gone(pid)
    assert "deployed copy ran: install" in got.stdout and (tmp_path / "deploy" / "scripts").is_dir()
    beat = json.loads((home / "loop-heartbeat.json").read_text(encoding="utf-8"))
    assert beat["state"] == "finished" and "stopped for a deploy" in beat["error"]


def test_install_asks_before_it_waits_on_the_gpu_lock_and_deploy_asks_before_checkout():
    text = GEN.read_text(encoding="utf-8")
    case = text[text.index('  install)\n'):]
    assert case.index("sweep_guard") < case.index("with-gpu-lock")
    body = text[text.index("deploy() {"):]
    assert body.index("sweep_guard") < body.index("checkout")
