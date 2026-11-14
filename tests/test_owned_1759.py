"""A server started in its own session dies with its owner: TERM stops it, a SIGKILLed owner's is reaped, a reused pid is not (#1759)."""
import contextlib
import json
import os
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from harness import memory_store as ms
from harness import owned, proc_identity, vllm
from harness import watchdog as wd
from harness import watchdog_hands, watchdog_observe
from tests.test_tether_1761 import _watchers_of

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="process groups and start times are POSIX")

ROOT = Path(__file__).resolve().parents[1]

OWNER = textwrap.dedent("""
    import sys, time
    from harness import vllm
    vllm._probe = lambda base, listed=None: ""
    out = sys.argv[1]
    with vllm.served(["sleep", "300"], 1, log=out + "/srv.log", timeout=5) as srv:
        open(out + "/child.pid", "w").write(str(srv.proc.pid))
        time.sleep(300)
""")

# A TERM that lands while the child is being started is held until the child is recorded, then honoured. #916.
TERM_IN_POPEN = textwrap.dedent("""
    import os, signal, subprocess, sys, time
    from harness import owned
    class Popen(subprocess.Popen):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            open(sys.argv[1] + "/child.pid", "w").write(str(self.pid))
            os.kill(os.getpid(), signal.SIGTERM)
            time.sleep(0.5)
    owned.subprocess.Popen = Popen
    owned.start(["sleep", "300"])
    time.sleep(300)
""")


# The server leads its own session and has a worker in it, as vllm does.
LEADER = textwrap.dedent("""
    import subprocess, sys, time
    worker = subprocess.Popen(["sleep", "300"])
    open(sys.argv[1], "w").write(str(worker.pid))
    time.sleep(300)
""")

OWNER_OF_LEADER = textwrap.dedent("""
    import sys, time
    from harness import owned
    out = sys.argv[1]
    p = owned.start([sys.executable, "-c", sys.argv[2], out + "/worker.pid"])
    open(out + "/child.pid", "w").write(str(p.pid))
    time.sleep(300)
""")


# The owner dies the moment its child exists, before owned records it: only the child's own tether can stop it. #1967.
DIES_IN_POPEN = textwrap.dedent("""
    import json, os, subprocess, sys, time
    from harness import owned, proc_identity, tether
    SLEEPER = json.loads(sys.argv[3])
    class Dies(subprocess.Popen):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            if tether.command(self.args) == SLEEPER:
                open(sys.argv[1] + "/child.pid", "w").write(str(self.pid))
                os.kill(os.getpid(), int(sys.argv[2]))
                time.sleep(5)
    owned.subprocess.Popen = Dies
    owned.start(SLEEPER)
    time.sleep(300)
""")

SLEEPER = [sys.executable, "-c", "import time; time.sleep(300)"]

# A server that ignores TERM: its tether must outlive its own TERM to the server's group and send KILL.
TERM_DEAF = textwrap.dedent("""
    import os, sys, time
    from harness import owned, tether
    tether.GRACE_S = 1.0
    ready = sys.argv[1] + "/ready"
    code = "import signal, sys, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); open(sys.argv[1], 'w').close(); time.sleep(300)"
    p = owned.start([sys.executable, "-c", code, ready])
    while not os.path.exists(ready):
        time.sleep(0.05)
    open(sys.argv[1] + "/child.pid", "w").write(str(p.pid))
    time.sleep(300)
""")


def _wait(pred, timeout=15.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return True
        time.sleep(0.05)
    return pred()


@pytest.fixture
def strays():
    """pids a test may leave running; each one's group is killed at teardown."""
    pids = []
    yield pids
    for pid in pids:
        with contextlib.suppress(OSError):
            os.killpg(pid, signal.SIGKILL)


def _owner(tmp_path, script, *args):
    path = tmp_path / "owner.py"
    path.write_text(script, encoding="utf-8")
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    proc = subprocess.Popen([sys.executable, str(path), str(tmp_path), *args], cwd=ROOT, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, start_new_session=True)
    pidfile = tmp_path / "child.pid"
    assert _wait(lambda: pidfile.exists() and pidfile.read_text(encoding="utf-8").strip()), proc.stderr.read().decode()
    return proc, int(pidfile.read_text(encoding="utf-8"))


def _records():
    return sorted(owned.root().glob("*.json"))


def test_sigterm_to_the_owner_stops_the_server_it_started(tmp_path, strays):
    proc, child = _owner(tmp_path, OWNER)
    strays.append(child)
    rec = proc_identity.identity(child)
    assert proc_identity.same(rec) is True
    assert _wait(lambda: len(_records()) == 1)
    proc.send_signal(signal.SIGTERM)
    assert proc.wait(timeout=30) == -signal.SIGTERM
    assert _wait(lambda: proc_identity.same(rec) is False), "the server outlived its TERMed owner"
    assert _records() == []


def test_a_term_inside_popen_still_stops_the_child(tmp_path, strays):
    proc, child = _owner(tmp_path, TERM_IN_POPEN)
    strays.append(child)
    rec = proc_identity.identity(child)
    assert proc.wait(timeout=30) == -signal.SIGTERM
    assert _wait(lambda: proc_identity.same(rec) is False), "a TERM during Popen orphaned the child"


def test_a_sigkilled_owner_s_server_and_its_workers_are_stopped_by_its_tether(tmp_path, strays):
    proc, child = _owner(tmp_path, OWNER_OF_LEADER, LEADER)
    strays.append(child)
    wpid = tmp_path / "worker.pid"
    assert _wait(lambda: wpid.exists() and wpid.read_text(encoding="utf-8"))
    worker = proc_identity.identity(int(wpid.read_text(encoding="utf-8")))
    rec = proc_identity.identity(child)
    assert proc_identity.same(worker) is True and worker["pgid"] == child
    proc.kill()
    proc.wait(timeout=10)
    assert _wait(lambda: proc_identity.same(rec) is False, timeout=20), "the server outlived its SIGKILLed owner"
    assert _wait(lambda: proc_identity.same(worker) is False, timeout=20), "the server's worker outlived its owner"


def test_a_server_whose_owner_s_whole_group_was_killed_is_stopped_by_its_tether_and_its_record_cleared(tmp_path, strays):
    proc, child = _owner(tmp_path, OWNER)
    strays.append(child)
    rec = proc_identity.identity(child)
    assert _wait(lambda: len(_records()) == 1)
    assert _wait(lambda: len(_watchers_of(child)) == 1)
    watcher = _watchers_of(child)[0][0]
    assert os.getpgid(watcher) not in (proc.pid, child), "the tether sits in a group a kill meant for another takes"
    os.killpg(proc.pid, signal.SIGKILL)
    proc.wait(timeout=10)
    assert _wait(lambda: proc_identity.same(rec) is False, timeout=20), "a group SIGKILL of the owner left its server running"
    assert not any("stopped" in line for line in owned.reap())
    assert _records() == []


def test_a_server_deaf_to_term_is_killed_by_its_tether_once_the_owner_is_gone(tmp_path, strays):
    proc, child = _owner(tmp_path, TERM_DEAF)
    strays.append(child)
    rec = proc_identity.identity(child)
    proc.kill()
    proc.wait(timeout=10)
    assert _wait(lambda: proc_identity.same(rec) is False, timeout=20), "the tether died of its own TERM and never sent KILL"


@pytest.mark.parametrize("sig", [signal.SIGKILL, signal.SIGTERM])
def test_an_owner_killed_the_moment_its_child_exists_still_takes_the_child_with_it(sig, tmp_path, strays):
    proc, child = _owner(tmp_path, DIES_IN_POPEN, str(int(sig)), json.dumps(SLEEPER))
    strays.append(child)
    rec = proc_identity.identity(child)
    assert proc.wait(timeout=30) == -sig
    assert _wait(lambda: proc_identity.same(rec) is False, timeout=20), f"the child outlived an owner ended by {sig.name} in Popen"


def _dead_owner() -> dict:
    gone = subprocess.Popen(["true"])
    gone.wait()
    return {"pid": gone.pid, "pgid": gone.pid, "started": "1.000000"}


def _plant(children):
    owned.root().mkdir(parents=True, exist_ok=True)
    owner = _dead_owner()
    (owned.root() / f"{owner['pid']}-x.json").write_text(
        json.dumps({"owner": owner, "children": children}), encoding="utf-8")


def test_a_recorded_pid_now_naming_another_process_is_not_killed(strays):
    stranger = subprocess.Popen(["sleep", "300"], start_new_session=True)
    strays.append(stranger.pid)
    real = proc_identity.identity(stranger.pid)
    _plant([{**real, "started": "2.000000", "cmd": "vllm serve"},
            {**real, "pgid": real["pgid"] + 1, "cmd": "vllm serve"}])
    lines = owned.reap(grace=1)
    assert not any("stopped" in line for line in lines), lines
    time.sleep(0.3)
    assert stranger.poll() is None, "the reaper killed a process that only reuses a recorded pid"
    assert _records() == []


def test_reap_removes_a_dead_owner_s_temp_and_keeps_a_live_one_s():
    owned.root().mkdir(parents=True, exist_ok=True)
    dead, me = _dead_owner(), proc_identity.identity(os.getpid())
    gone = owned.root() / f"{dead['pid']}-unknown.tmp"
    mine = owned.root() / f"{me['pid']}-{me['started']}.tmp"
    unsure = owned.root() / f"{me['pid']}-unknown.tmp"
    for t in (gone, mine, unsure):
        t.write_text("{}", encoding="utf-8")
    owned.reap(act=False)
    assert gone.exists(), "a dry run removed a file"
    owned.reap()
    assert not gone.exists(), "a dead owner's temp was left behind"
    assert mine.exists(), "a live owner's temp was removed"
    assert unsure.exists(), "a temp whose owner cannot be judged was removed"


def test_a_live_owner_whose_start_time_cannot_be_read_is_not_taken_for_gone(monkeypatch, strays):
    child = subprocess.Popen(["sleep", "300"], start_new_session=True)
    strays.append(child.pid)
    owned.root().mkdir(parents=True, exist_ok=True)
    owner = proc_identity.identity(os.getpid())
    record = owned.root() / f"{owner['pid']}-live.json"
    record.write_text(json.dumps({"owner": owner, "children": [{**proc_identity.identity(child.pid), "cmd": "sleep 300"}]}),
                      encoding="utf-8")
    monkeypatch.setattr(proc_identity, "_proc", lambda pid: None)
    assert owned.reap(grace=1) == []
    assert child.poll() is None, "an unread start time took a live owner for gone and its server was stopped"
    assert record.exists()


def test_the_watchdog_wake_reaps_a_dead_owner_s_server(tmp_path, strays):
    child = subprocess.Popen(["sleep", "300"], start_new_session=True)
    strays.append(child.pid)
    _plant([{**proc_identity.identity(child.pid), "cmd": "sleep 300"}])
    said = []
    wd.wake(ms.connect(), Quiet(tmp_path), watchdog_hands.Hands(), act=False, say=said.append)
    assert any("would stop" in s for s in said) and child.poll() is None
    wd.wake(ms.connect(), Quiet(tmp_path), watchdog_hands.Hands(), act=True, say=said.append)
    assert child.wait(timeout=15) == -signal.SIGTERM
    assert _records() == []


def test_served_records_its_child_and_forgets_it_and_its_handlers_on_exit(tmp_path, monkeypatch):
    monkeypatch.setattr(vllm, "_probe", lambda base, listed=None: "")
    before = signal.getsignal(signal.SIGTERM)
    with vllm.served(["sleep", "300"], 1, log=tmp_path / "s.log", timeout=5) as srv:
        got = json.loads(_records()[0].read_text(encoding="utf-8"))
        assert [c["pid"] for c in got["children"]] == [srv.proc.pid]
        assert got["owner"]["pid"] == os.getpid()
        assert signal.getsignal(signal.SIGTERM) is owned._on_signal
        assert len(owned._children[srv.proc.pid]) == 2, "owned keeps a handle on the child's own watcher"
        assert _wait(lambda: len(_watchers_of(srv.proc.pid)) == 1), "the server runs with no watcher"
    assert srv.proc.poll() is not None
    assert _wait(lambda: _watchers_of(srv.proc.pid) == []), "the tether outlived the server it watched"
    assert _records() == []
    assert signal.getsignal(signal.SIGTERM) is before


def _no_room(*a, **kw):
    raise OSError(28, "No space left on device")


@pytest.mark.parametrize("fails", ["spawn", "record"])
def test_a_server_that_fails_to_start_leaves_the_owner_s_handlers_and_no_child(fails, monkeypatch, strays):
    before = {s: signal.getsignal(s) for s in (signal.SIGTERM, signal.SIGINT)}
    spawned = []
    if fails == "spawn":
        monkeypatch.setattr(owned.tether, "spawn", _no_room)
    else:
        real = owned.tether.spawn
        monkeypatch.setattr(owned.tether, "spawn", lambda *a, **kw: spawned.append(real(*a, **kw)) or spawned[-1])
        monkeypatch.setattr(owned, "_write", _no_room)
    with pytest.raises(OSError, match="No space"):
        owned.start(["sleep", "300"])
    strays.extend(p.pid for p in spawned)
    assert {s: signal.getsignal(s) for s in before} == before
    assert owned._children == {} and owned._previous == {}
    assert all(p.poll() is not None for p in spawned), "a child the caller never got a handle on still runs"


def test_stopping_a_server_already_on_its_way_out_returns_and_forgets_it(monkeypatch, strays):
    proc = owned.start(["sleep", "300"])
    strays.append(proc.pid)

    def exiting(pid, sig):
        proc.kill()
        raise PermissionError(1, "Operation not permitted")
    monkeypatch.setattr(os, "killpg", exiting)
    owned.stop(proc, grace=5)
    assert proc.poll() is not None and owned._children == {}


class Quiet(watchdog_observe.Probes):
    """A machine with nothing running, so a wake judges nothing and only reaps."""

    def __init__(self, tmp_path):
        self.tmp = tmp_path

    def processes(self):
        return []

    def launchd_loaded(self, service):
        return False

    def launchd_pid(self, service):
        return None

    def heartbeat(self):
        return None

    def job_pids(self):
        return {}

    def progress(self, evals):
        return []

    def lock(self):
        return {}

    def resident(self):
        return []

    def pressure(self):
        return None

    def gateway_up(self):
        return None

    def fallbacks(self, conn):
        return []

    def state(self):
        d = self.tmp / "wd"
        d.mkdir(exist_ok=True)
        return d
