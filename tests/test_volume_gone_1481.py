"""A weights volume that is not mounted is named as such, a preflight refusal logs under its own header, and the sweep and the queue pause (#1481)."""
import argparse
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

import shells
from harness import env, heartbeat, morning, workqueue
from harness import memory_store as ms
from harness.commands import loop
from test_env_sh import REPO, run_env

NIGHT = time.mktime((2026, 10, 17, 1, 30, 0, 0, 0, -1))


@pytest.fixture
def volume(tmp_path, monkeypatch):
    """A fake volume VOL holding the weights root VOL/hf; remove VOL to unmount it."""
    vol = tmp_path / "VOL"
    (vol / "hf").mkdir(parents=True)
    monkeypatch.setenv("HF_ROOT", str(vol / "hf"))
    monkeypatch.delenv("HF_HOME", raising=False)
    return vol


def _unmount(vol: Path) -> None:
    shutil.rmtree(vol, ignore_errors=True)


# --- the preflight's message ----------------------------------------------------

def test_env_sh_says_not_mounted_and_names_the_volume(tmp_path):
    code, _, err = run_env(hf_root=str(tmp_path / "VOL" / "hf"))
    assert code == 1
    assert "not mounted" in err and str(tmp_path / "VOL") in err, err
    assert "not writable" not in err and "TCC" not in err and "GB free" not in err.split("\n")[0], err


def test_env_sh_names_the_topmost_missing_directory_as_the_volume(tmp_path):
    code, _, err = run_env(hf_root=str(tmp_path / "VOL" / "deep" / "hf"))
    assert code == 1
    assert f"{tmp_path / 'VOL'} is not mounted" in err, err


def test_env_sh_keeps_low_space_apart_from_not_mounted(tmp_path):
    code, _, err = run_env(hf_root=str(tmp_path / "hf"), min_free_gb="999999")
    assert code == 1
    first = err.splitlines()[0]
    assert "not mounted" not in err and "GB free" in first and "not writable" not in first, err


@pytest.mark.skipif(sys.platform == "win32", reason="chmod 500 does not remove write access on Windows")
def test_env_sh_keeps_not_writable_apart_from_not_mounted(tmp_path):
    locked = tmp_path / "locked"
    locked.mkdir()
    subprocess.run(["chmod", "500", str(locked)], check=True)
    try:
        code, _, err = run_env(hf_root=str(locked / "hf"))
    finally:
        subprocess.run(["chmod", "700", str(locked)], check=True)
    assert code == 1
    assert "not writable" in err.splitlines()[0] and "not mounted" not in err, err


def test_env_py_agrees_with_env_sh_on_not_mounted(tmp_path, capsys):
    root = str(tmp_path / "VOL" / "deep" / "hf")
    assert env.unmounted(root) == str(tmp_path / "VOL")
    assert env.unmounted(str(tmp_path / "hf")) == ""
    assert env.usable(root, min_free_gb=0) is False
    assert env.problem(root, 0) == f"{tmp_path / 'VOL'} is not mounted"
    assert env.guard(root=root, environ={}, min_free_gb=0) is None
    assert "not mounted" in capsys.readouterr().err


# --- a run that fails its preflight still says when -------------------------------

def _wrapper(tmp_path, name):
    (tmp_path / "scripts").mkdir()
    shutil.copy(REPO / "scripts" / f"serve-{name}.sh", tmp_path / "scripts" / f"serve-{name}.sh")
    (tmp_path / "scripts" / "env.sh").write_text('echo "FATAL: HF_ROOT=/x is not mounted" >&2\nreturn 1\n',
                                                 encoding="utf-8")
    (tmp_path / "bin").mkdir()
    uv = tmp_path / "bin" / "uv"
    uv.write_text('#!/bin/sh\necho "uv ran: $*"\n', encoding="utf-8")
    uv.chmod(0o755)
    env_ = {**os.environ, "PATH": f"{tmp_path / 'bin'}{os.pathsep}{os.environ['PATH']}",
            "LOCALHARNESS_HOME": str(tmp_path / "home")}
    return subprocess.run([shells.BASH, str(tmp_path / "scripts" / f"serve-{name}.sh")], env=env_,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=60)


HEADED = sorted(p.stem.removeprefix("serve-") for p in (REPO / "scripts").glob("serve-*.sh")
                if 'echo "=== ' in p.read_text(encoding="utf-8"))


def test_every_periodic_wrapper_with_a_header_is_covered():
    assert {"watchdog", "morning", "discover", "audit"} <= set(HEADED)


@pytest.mark.parametrize("name", HEADED)
def test_a_run_that_fails_its_preflight_logs_a_timestamped_header_first(tmp_path, name):
    before = time.time()
    got = _wrapper(tmp_path, name)
    log = got.stdout
    header = re.search(r"^=== [\w -]+? (\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ)", log, re.M)
    assert header and header.start() < log.index("FATAL"), log
    stamp = datetime.strptime(header.group(1), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
    assert before - 2 <= stamp <= time.time() + 2, log
    assert "uv ran" not in log and got.returncode != 0, log


# --- the sweep and the queue pause, saying why -----------------------------------------

def test_the_sweep_heartbeat_records_a_pause_when_the_volume_goes_between_steps(volume, monkeypatch):
    ran = []

    def step(sub):
        ran.append(next(k for k in ("sweep", "inspect", "queue") if getattr(sub, k, False)))
        _unmount(volume)
        return 0
    monkeypatch.setattr(loop.discover_cmd, "cmd_discover", step)
    rc = loop._report_loop(argparse.Namespace(run=False, lane=""))
    assert ran == ["sweep"]
    beat = heartbeat.read()
    assert rc == loop.PAUSED and beat["state"] == heartbeat.FINISHED and beat["rc"] == loop.PAUSED
    assert "not mounted" in beat["paused"]["reason"] and str(volume) in beat["paused"]["reason"]
    assert beat["paused"]["tier"] == "queue"
    assert "paused" in heartbeat.summary()["line"] and "not mounted" in heartbeat.summary()["line"]


def test_the_queue_waits_while_the_volume_is_gone_and_says_why(volume):
    calm = lambda: type("S", (), {"alarming": False, "level": 1})()  # noqa: E731
    assert workqueue.gate(calm)[0] is True
    _unmount(volume)
    ok, why = workqueue.gate(calm)
    assert ok is False and "not mounted" in why and str(volume) in why


def test_the_morning_brief_says_why_the_sweep_paused_rather_than_its_exit_code():
    why = "the weights volume /x/VOL is not mounted"
    beat = {"status": heartbeat.FINISHED, "rc": loop.PAUSED, "started": NIGHT, "line": "",
            heartbeat.PAUSED: {"tier": "queue", "reason": why}}
    r = morning.gather(ms.connect(), NIGHT + 6 * 3600, NIGHT - 6 * 3600, beat=beat, gh=lambda argv: "[]",
                       git=lambda argv: "", where=None, lanes=lambda c: [])
    assert f"the sweep paused before queue: {why}" in r["needs"], r["needs"]
    assert not any("exited" in n for n in r["needs"]), r["needs"]
