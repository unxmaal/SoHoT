"""The disk sweep removes cached uv environments no process uses, older than a knob, outside uv's lock. #2050."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time

import pytest

from harness import disk, uv_cache

needs_lsof = pytest.mark.skipif(not shutil.which("lsof"), reason="no lsof on PATH")
OLD = time.time() - 30 * 86400
HOLD = "import os, sys; f = open(os.environ['HOLD']); print('ready', flush=True); sys.stdin.read()"


def _env(archive, name, old=True, venv=True):
    entry = archive / name
    (entry / "lib").mkdir(parents=True)
    (entry / "lib" / "mod.py").write_bytes(b"x" * 4096)
    if venv:
        (entry / "pyvenv.cfg").write_text("home = /usr/bin\n")
    if old:
        os.utime(entry, (OLD, OLD))
    return entry


@pytest.fixture
def cache(tmp_path):
    root = tmp_path / "cache"
    (root / "archive-v0").mkdir(parents=True)
    return root


@pytest.fixture
def holder(cache):
    """A child holding a file open in archive-v0/HELDenv, its path only in its environment, never its args."""
    held = _env(cache / "archive-v0", "HELDenv")
    proc = subprocess.Popen([sys.executable, "-c", HOLD], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
                            env={**os.environ, "HOLD": str(held / "lib" / "mod.py")})
    try:
        assert proc.stdout.readline().strip() == "ready"
        yield held
    finally:
        proc.kill()
        proc.wait()


@needs_lsof
def test_an_env_held_open_or_fresh_is_kept_an_old_unused_one_removed_a_non_venv_never_touched(cache, holder):
    archive = cache / "archive-v0"
    fresh = _env(archive, "FRESHenv", old=False)
    old = _env(archive, "OLDenv")
    wheel = _env(archive, "WHEELentry", venv=False)
    got = uv_cache.prune_envs_at(cache)
    assert "skipped" not in got, got
    assert holder.is_dir() and "HELDenv" in got["in_use"]
    assert fresh.is_dir() and got["fresh"] == 1
    assert not old.exists() and got["removed"] == ["OLDenv"] and got["bytes"] >= 4096
    assert (wheel / "lib" / "mod.py").exists()


def test_an_env_named_in_a_process_args_or_through_its_environments_v2_link_is_kept(cache):
    archive = cache / "archive-v0"
    for name in ("ARGenv", "LINKEDenv", "GONEenv"):
        _env(archive, name)
    group = cache / "environments-v2" / "grp"
    group.mkdir(parents=True)
    (group / "used").symlink_to("../../archive-v0/LINKEDenv")
    (group / "stale").symlink_to("../../archive-v0/GONEenv")
    os.utime(group / "stale", (OLD, OLD), follow_symlinks=False)
    said = {"lsof": "python 1 u txt REG /x/archive-v0/ARGenv/lib/mod.py\n",
            "ps": f"{cache}/environments-v2/grp/used/bin/python -m x\n"}

    def run(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 0, said[cmd[0]], "")
    got = uv_cache.prune_envs_at(cache, run=run)
    assert sorted(got["in_use"]) == ["ARGenv", "LINKEDenv"]
    assert got["removed"] == ["GONEenv"] and not (group / "stale").is_symlink()
    assert (archive / "LINKEDenv").is_dir() and (group / "used").is_symlink()


def test_a_recent_environments_v2_link_keeps_an_old_entry(cache):
    entry = _env(cache / "archive-v0", "RELINKEDenv")
    group = cache / "environments-v2" / "grp"
    group.mkdir(parents=True)
    (group / "new").symlink_to("../../archive-v0/RELINKEDenv")
    got = uv_cache.prune_envs_at(cache, run=lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, "nothing\n", ""))
    assert got["removed"] == [] and got["fresh"] == 1 and entry.is_dir()


@pytest.mark.parametrize("how", ["missing", "timeout", "empty"])
def test_nothing_is_removed_when_the_processes_cannot_be_listed(cache, how):
    entry = _env(cache / "archive-v0", "OLDenv")

    def run(cmd, **kw):
        if how == "missing":
            raise FileNotFoundError(cmd[0])
        if how == "timeout":
            raise subprocess.TimeoutExpired(cmd, 1)
        return subprocess.CompletedProcess(cmd, 1, "", "")
    assert "skipped" in uv_cache.prune_envs_at(cache, run=run)
    assert entry.is_dir()


def test_the_knob_turns_it_off_and_the_sweep_says_so(cache, monkeypatch):
    entry = _env(cache / "archive-v0", "OLDenv")
    monkeypatch.setattr(uv_cache, "cache_dir", lambda run=None: cache)
    monkeypatch.setattr(uv_cache, "ENV_PRUNE", False)
    said = []
    got = disk.uv_env_prune(said.append)
    assert "skipped" in got and entry.is_dir()
    assert any("ENV_PRUNE" in line for line in said)


def test_the_sweep_logs_the_in_use_set_and_bytes_freed(cache, monkeypatch):
    _env(cache / "archive-v0", "OLDenv")
    _env(cache / "archive-v0", "HELDenv")
    monkeypatch.setattr(uv_cache, "cache_dir", lambda run=None: cache)
    monkeypatch.setattr(uv_cache, "in_use", lambda c, run=None: {"HELDenv"})
    said = []
    got = disk.uv_env_prune(said.append)
    assert got["removed"] == ["OLDenv"]
    assert any("removed 1" in line and "GiB" in line for line in said)
    assert any("in use: HELDenv" in line for line in said)
