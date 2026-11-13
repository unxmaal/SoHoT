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
proc = subprocess.Popen(SLEEPER)
tether.tie(proc)
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
llama_vlm._popen = lambda *a, **k: spawned.append(subprocess.Popen(*a, **k)) or spawned[-1]
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


def test_untie_leaves_the_child_to_its_owner_and_reaps_the_watcher():
    proc = subprocess.Popen(SLEEPER)
    rec = proc_identity.identity(proc.pid)
    try:
        watcher = tether.tie(proc)
        assert watcher is not None
        tether.untie(watcher)
        assert watcher.returncode is not None and proc.poll() is None
    finally:
        proc.kill()
        proc.wait()
    assert proc_identity.same(rec) is False


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
    assert tether.tie(Fake()) is None


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
"$PY" -c 'import time; time.sleep(300)' &
child=$!
tether "$child"
echo "$child"
exec "$PY" -c 'import time; time.sleep(300)'
"""


def test_the_sweep_scripts_server_dies_when_the_script_is_killed(tmp_path):
    assert 'SERVER=$!\n  tether "$SERVER"\n' in (ROOT / "scripts" / "slots-sweep.sh").read_text(encoding="utf-8")
    sh = subprocess.Popen([shells.BASH, "-c", TETHER_SH], cwd=ROOT, stdout=subprocess.PIPE, text=True, encoding="utf-8",
                          env={**os.environ, "PY": sys.executable})
    child = proc_identity.identity(int(sh.stdout.readline()))
    try:
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
    assert "tether.tie(server)" in src and "tether.untie(watcher)" in src


def test_the_interactive_warm_up_is_owned_by_its_units_group():
    unit = (ROOT / "scripts" / "serve-interactive.sh").read_text(encoding="utf-8")
    assert "harness.interactive warm &" in unit and "\nexec scripts/serve-llamacpp.sh" in unit
    assert "AbandonProcessGroup" not in (ROOT / "scripts" / "launchd.sh").read_text(encoding="utf-8")
