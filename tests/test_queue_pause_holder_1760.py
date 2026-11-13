"""A queue pause a process holds ends with it: the deploy marker goes down before the pause, and a dead holder's flags are lifted. #1754, #1760."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

import shells
from harness import paths, pressure, proc_identity, queue_hold, workqueue as wq
from harness import queue_pause

REPO = Path(__file__).resolve().parents[1]
posix = pytest.mark.skipif(sys.platform == "win32" or shells.BASH is None, reason="POSIX pids and bash")
CALM = pressure.Pressure(level=pressure.NORMAL)

# Holds the queue for a deploy as launchd.sh does, and is SIGKILLed right after its Nth write of a queue flag.
KILLED_MID_HOLD = """
import os, pathlib, runpy, signal, sys
os.environ["LH_QUEUE_HOLDER"] = str(os.getpid())
after, real, n = int(sys.argv[1]), pathlib.Path.write_text, [0]
def write(self, *a, **k):
    got = real(self, *a, **k)
    if self.name in ("paused", "paused.deploy"):
        n[0] += 1
        if n[0] == after:
            os.kill(os.getpid(), signal.SIGKILL)
    return got
pathlib.Path.write_text = write
sys.argv = ["workqueue", "hold-for-deploy"]
runpy.run_module("harness.workqueue", run_name="__main__")
"""


def _env() -> dict:
    return {**os.environ, paths.ENV_VAR: str(paths.home())}


def _gate():
    return wq.gate(sample=lambda: CALM)


def _flags() -> set[str]:
    return {p.name for p in (queue_pause._pause_flag(), queue_pause._held_flag()) if p.exists()}


@posix
@pytest.mark.parametrize("after", [1, 2])
def test_a_hold_killed_between_or_after_its_flag_writes_does_not_strand_the_queue(after):
    got = subprocess.run([sys.executable, "-c", KILLED_MID_HOLD, str(after)], cwd=REPO, env=_env(),
                         capture_output=True, text=True, timeout=120)
    assert got.returncode == -9, got.stderr[-800:]
    ok, why = _gate()
    assert ok, f"a dead holder's flags {_flags()} still hold the queue: {why}"
    assert not _flags()


@posix
@pytest.mark.parametrize("step", ["hold-for-deploy", "quiesce"])
def test_a_script_killed_before_it_lifts_its_pause_does_not_strand_the_queue(step):
    # launchd.sh SIGKILLed after it paused the queue: its EXIT trap or resume never runs.
    script = f'LH_QUEUE_HOLDER=$$ "{sys.executable}" -m harness.workqueue {step} >/dev/null; kill -9 $$'
    got = subprocess.run([shells.BASH, "-c", script], cwd=REPO, env=_env(), capture_output=True, text=True,
                         timeout=120)
    assert got.returncode == -9, got.stderr[-800:]
    assert wq.paused(), "the script paused the queue"
    ok, why = _gate()
    assert ok, f"a dead holder's pause still holds the queue: {why}"
    assert not _flags()


def test_a_live_holder_keeps_its_pause_and_the_gate_names_it():
    wq.pause("held for a test", holder=os.getpid())
    ok, why = _gate()
    assert not ok and why.startswith(f"held by pid {os.getpid()} ") and why.endswith("lifted when it ends")
    assert wq.paused()


@posix
def test_an_owner_pause_is_never_lifted():
    wq.pause("owner")
    script = f'LH_QUEUE_HOLDER=$$ "{sys.executable}" -m harness.workqueue quiesce'
    got = subprocess.run([shells.BASH, "-c", script], cwd=REPO, env=_env(), capture_output=True, text=True,
                         timeout=120)
    assert got.stdout.strip() == "was-paused", got.stderr[-800:]
    assert _gate() == (False, "paused (soh jobs resume)"), "quiesce never turns an owner's pause into its own"
    assert queue_hold.holder_of(queue_pause._pause_flag().read_text(encoding="utf-8")) is None


@posix
def test_a_holder_that_cannot_be_read_keeps_its_pause(monkeypatch):
    script = f'LH_QUEUE_HOLDER=$$ "{sys.executable}" -m harness.workqueue hold-for-deploy'
    subprocess.run([shells.BASH, "-c", script], cwd=REPO, env=_env(), capture_output=True, timeout=120, check=True)
    monkeypatch.setattr(proc_identity, "same", lambda rec: None)
    assert not _gate()[0] and _flags() == {"paused", "paused.deploy"}, "None is 'cannot say', never dead"


def test_a_marker_alone_whose_holder_died_is_lifted_and_the_next_hold_takes_the_queue():
    queue_pause._held_flag().write_text(queue_hold.text("held for a deploy", os.getpid()), encoding="utf-8")
    rec = queue_hold.holder_of(queue_pause._held_flag().read_text(encoding="utf-8"))
    queue_pause._held_flag().write_text(queue_pause._held_flag().read_text(encoding="utf-8").replace(rec["started"], "1.000000"),
                               encoding="utf-8")
    said = wq.hold_for_deploy(holder=os.getpid())
    assert said[0].startswith("paused.deploy lifted: its holder pid")
    assert "queue held for the deploy; it is released when the install ends" in said
    assert wq.release_for_deploy() == "queue released after the deploy" and not _flags()


@posix
def test_launchd_hands_its_own_pid_to_the_queue_as_the_holder(tmp_path):
    bin_, log = tmp_path / "bin", tmp_path / "log"
    bin_.mkdir()
    text = (REPO / "scripts" / "launchd.sh").read_text(encoding="utf-8")
    (tmp_path / "lib.sh").write_text(text[:text.index('case "${1:-}" in')], encoding="utf-8")
    (tmp_path / "run.sh").write_text('source "$(dirname "$0")/lib.sh"\necho "shell $$" >> "$LOG"\n'
                                     '_queue_for_deploy hold\n', encoding="utf-8")
    (bin_ / "uv").write_text('#!/bin/sh\necho "holder $LH_QUEUE_HOLDER" >> "$LOG"\n', encoding="utf-8")
    (bin_ / "uv").chmod(0o755)
    (tmp_path / "lh").mkdir()
    (tmp_path / "lh" / "install.env").write_text("HF_HOME=/\n", encoding="utf-8")
    env = {**os.environ, "PATH": f"{bin_}{os.pathsep}{os.environ['PATH']}", "HOME": str(tmp_path / "home"),
           "LOCALHARNESS_HOME": str(tmp_path / "lh"), "LOG": str(log), "LH_ROLE": "scheduler"}
    got = subprocess.run([shells.BASH, str(tmp_path / "run.sh")], env=env, capture_output=True, text=True, timeout=60)
    assert got.returncode == 0, got.stderr
    shell, holder = log.read_text(encoding="utf-8").split()[1::2]
    assert holder == shell
    assert 'LH_QUEUE_HOLDER=$$ "$UV" run python -m harness.workqueue quiesce' in text
