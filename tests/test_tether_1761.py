"""A server, browser or scratch file a process starts dies with it, however the process dies (#1761, gauntlet OW-3..OW-8)."""
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from harness import proc_identity, stale_temp, tether
from tests import shells

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX signals end the owner")

SLEEPER = [sys.executable, "-c", "import time; time.sleep(300)"]

OWNERS = {
    "tie": """
import subprocess, sys
from harness import tether
proc = tether.spawn(SLEEPER)
""",
    "needle": """
import sys
from harness import needle
code = "import time; print('needle serving on http://127.0.0.1:1', flush=True); time.sleep(300)"
proc = needle.Server(lambda port: [sys.executable, "-c", code], 1).proc
""",
    "llama_vlm": """
import contextlib, subprocess
from pathlib import Path
from harness import llama_vlm
class Up:
    status_code = 200
llama_vlm._http.get = lambda url, timeout=None: Up()
llama_vlm.argv_for = lambda *a, **k: SLEEPER
spawned = []
class Spy(subprocess.Popen):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        spawned.append(self)
llama_vlm._popen = Spy
stack = contextlib.ExitStack()
stack.enter_context(llama_vlm.serve(Path("m.gguf"), Path("p.gguf")))
proc = spawned[0]
""",
    "render": """
import subprocess, threading, time
from pathlib import Path
from harness.checks import render
spawned = []
real = subprocess.Popen
class Spy(real):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        spawned.append(self)
render.subprocess.Popen = Spy
threading.Thread(target=render._shoot, args=(SLEEPER, Path("never.png"), "."), kwargs={"timeout": 300},
                 daemon=True).start()
while not spawned:
    time.sleep(0.01)
proc = spawned[0]
render.subprocess.Popen = real
""",
}


def _owner(kind, tmp_path):
    code = (f"import json, os, sys, time\nSLEEPER = {SLEEPER!r}\n" + OWNERS[kind]
            + "\nprint(json.dumps(__import__('harness.proc_identity').proc_identity.identity(proc.pid)), flush=True)"
            + "\ntime.sleep(300)\n")
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    owner = subprocess.Popen([sys.executable, "-c", code], cwd=tmp_path, env=env, stdout=subprocess.PIPE,
                             text=True, encoding="utf-8")
    line = owner.stdout.readline()
    assert line, f"the {kind} owner printed nothing (rc {owner.poll()})"
    child = json.loads(line)
    assert proc_identity.same(child) is True
    return owner, child


def _gone_within(rec, seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if proc_identity.same(rec) is False:
            return True
        time.sleep(0.1)
    return False


def _kill(rec):
    if proc_identity.same(rec) is True:
        os.kill(rec["pid"], signal.SIGKILL)


@pytest.mark.parametrize("kind", sorted(OWNERS))
@pytest.mark.parametrize("sig", [signal.SIGKILL, signal.SIGTERM])
def test_a_child_dies_with_its_owner_however_the_owner_dies(kind, sig, tmp_path):
    owner, child = _owner(kind, tmp_path)
    try:
        owner.send_signal(sig)
        owner.wait(30)
        assert _gone_within(child, 15), f"{kind}: the child outlived an owner ended by {sig.name}"
    finally:
        owner.kill()
        owner.wait()
        _kill(child)


DIES_IN_POPEN = """
import json, os, subprocess, sys, time
from harness import proc_identity, tether
SLEEPER = json.loads(sys.argv[2])
class Dies(subprocess.Popen):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        print(json.dumps(proc_identity.identity(self.pid)), flush=True)
        os.kill(os.getpid(), int(sys.argv[1]))
tether.spawn(SLEEPER, Dies)
time.sleep(300)
"""


@pytest.mark.parametrize("sig", [signal.SIGKILL, signal.SIGTERM])
def test_an_owner_killed_the_moment_its_child_exists_still_takes_the_child_with_it(sig, tmp_path):
    owner = subprocess.Popen([sys.executable, "-c", DIES_IN_POPEN, str(int(sig)), json.dumps(SLEEPER)], cwd=tmp_path,
                             env={**os.environ, "PYTHONPATH": str(ROOT)}, stdout=subprocess.PIPE, text=True,
                             encoding="utf-8")
    child = json.loads(owner.stdout.readline())
    try:
        assert owner.wait(30) == -sig and child["started"]
        assert _gone_within(child, 15), f"the child outlived an owner ended by {sig.name} inside Popen"
    finally:
        owner.kill()
        owner.wait()
        _kill(child)


def _watchers_of(pid):
    out = subprocess.run(["ps", "-axww", "-o", "pid=,ppid=,command="], capture_output=True, text=True,
                         encoding="utf-8", check=True).stdout
    return [(int(p), int(pp)) for p, pp, cmd in (line.split(None, 2) for line in out.splitlines() if line.strip())
            if "spec_from_file_location" in cmd and "while pi.same(owner)" in cmd and f'"pid": {pid},' in cmd]


def test_a_child_its_owner_stops_leaves_no_watcher_and_was_never_the_watchers_parent():
    proc = tether.spawn(SLEEPER)
    try:
        end = time.monotonic() + 15
        while not (found := _watchers_of(proc.pid)) and time.monotonic() < end:
            time.sleep(0.05)
        assert len(found) == 1 and found[0][1] != proc.pid
        assert tether.command(proc.args) == SLEEPER
    finally:
        proc.kill()
        proc.wait()
    end = time.monotonic() + 15
    while _watchers_of(proc.pid) and time.monotonic() < end:
        time.sleep(0.1)
    assert _watchers_of(proc.pid) == []


def _watch(owner, child):
    return subprocess.Popen(tether.watch_argv(owner, child), stdin=subprocess.DEVNULL)


def test_a_pid_that_is_no_longer_the_child_is_never_signalled():
    gone = subprocess.Popen([sys.executable, "-c", "pass"])
    owner = proc_identity.identity(gone.pid)
    gone.wait()
    proc = subprocess.Popen(SLEEPER)
    try:
        watcher = _watch(owner, {**proc_identity.identity(proc.pid), "started": "1.000000"})
        assert watcher.wait(30) is not None
        assert proc.poll() is None
    finally:
        proc.kill()
        proc.wait()


def test_an_owner_whose_start_cannot_be_read_is_not_taken_for_gone():
    proc = subprocess.Popen(SLEEPER)
    try:
        watcher = _watch({"pid": os.getpid(), "pgid": None, "started": ""}, proc_identity.identity(proc.pid))
        time.sleep(tether.POLL_S * 4)
        assert proc.poll() is None and watcher.poll() is None
        proc.kill()
        proc.wait()
        assert watcher.wait(30) == 0
    finally:
        proc.kill()
        proc.wait()


def test_a_fake_process_is_not_tied():
    class Fake:
        pid = 0
    assert tether._tie(Fake()) is None


def test_a_stand_in_popen_gets_the_argv_as_given():
    assert tether.spawn([sys.executable, "-V"], lambda argv, **kw: argv) == [sys.executable, "-V"]


def test_a_program_that_is_not_there_raises_as_popen_does(tmp_path):
    with pytest.raises(FileNotFoundError):
        tether.spawn([str(tmp_path / "absent")])
    assert tether.tied([str(tmp_path / "absent")]) == [str(tmp_path / "absent")]


def test_the_suites_runtime_guard_sees_the_program_behind_the_tether(tmp_path):
    from tests.conftest import runtime_binary
    server = tmp_path / "llama-server"
    server.write_text("#!/bin/sh\n", encoding="utf-8")
    server.chmod(0o755)
    wrapped = tether.tied([server, "--version"])
    assert wrapped[0] == sys.executable and tether.command(wrapped) == [str(server), "--version"]
    assert runtime_binary(wrapped) == "llama-server"


def test_a_dead_renders_scratch_dir_is_swept_by_the_next_render(tmp_path, monkeypatch):
    from harness.checks import render
    monkeypatch.setattr(render.tempfile, "tempdir", str(tmp_path))
    gone = subprocess.Popen([sys.executable, "-c", "pass"])
    gone.wait()
    left = tmp_path / f"sohot-render-{gone.pid}-abcd1234"
    (left / "chrome-profile").mkdir(parents=True)
    old = time.time() - stale_temp.FLOOR_S - 5
    os.utime(left, (old, old))
    mine = render._scratch()
    assert not left.exists() and Path(mine).is_dir()
    assert stale_temp._pattern("sohot-render", "{name}-{pid}-{hex}").match(Path(mine).name)


def test_a_job_claim_temp_a_dead_writer_left_is_swept(tmp_path, monkeypatch):
    from harness import job_claim
    monkeypatch.setattr(job_claim, "path", lambda job_id: tmp_path / "0001.claim")
    gone = subprocess.Popen([sys.executable, "-c", "pass"])
    gone.wait()
    left = tmp_path / f"0001.claim.{gone.pid}.123"
    left.write_text("{}", encoding="utf-8")
    old = time.time() - stale_temp.FLOOR_S - 5
    os.utime(left, (old, old))
    job_claim.mark(1)
    assert not left.exists() and sorted(p.name for p in tmp_path.iterdir()) == ["0001.claim"]


TETHER_SH = r"""
set -euo pipefail
eval "$(sed -n '/^tether() {/,/^}/p' scripts/slots-sweep.sh)"
tether "$PY" -c 'import time; time.sleep(300)' &
echo "$!"
[ "$DIE_AT_ONCE" = 1 ] && kill -KILL $$
exec "$PY" -c 'import time; time.sleep(300)'
"""


@pytest.mark.parametrize("at_once", [False, True])
def test_the_sweep_scripts_server_dies_when_the_script_is_killed(at_once, tmp_path):
    src = (ROOT / "scripts" / "slots-sweep.sh").read_text(encoding="utf-8")
    assert "  tether llama-server --jinja" in src and '>"$log" 2>&1 &\n  SERVER=$!\n' in src
    sh = subprocess.Popen([shells.BASH, "-c", TETHER_SH], cwd=ROOT, stdout=subprocess.PIPE, text=True, encoding="utf-8",
                          env={**os.environ, "PY": sys.executable, "DIE_AT_ONCE": str(int(at_once))})
    child = proc_identity.identity(int(sh.stdout.readline()))
    try:
        assert child["started"]
        if not at_once:
            assert proc_identity.same(child) is True
            sh.send_signal(signal.SIGKILL)
        sh.wait(30)
        assert _gone_within(child, 15), "the server outlived its SIGKILLed script"
    finally:
        sh.kill()
        sh.wait()
        _kill(child)


def test_the_pool_probe_ties_its_server():
    src = (ROOT / "scripts" / "pool-full-probe.py").read_text(encoding="utf-8")
    assert 'server = tether.spawn(["llama-server"' in src and "subprocess.Popen" not in src


def test_the_interactive_warm_up_is_owned_by_its_units_group():
    unit = (ROOT / "scripts" / "serve-interactive.sh").read_text(encoding="utf-8")
    assert "harness.interactive warm &" in unit and "\nexec scripts/serve-llamacpp.sh" in unit
    assert "AbandonProcessGroup" not in (ROOT / "scripts" / "launchd.sh").read_text(encoding="utf-8")
