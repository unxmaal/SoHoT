"""The switch a deploy hands off is the release it installs, so an orchestration change takes effect on the deploy that ships it. #1786."""
from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from harness import deploy, deploy_switch, paths

REPO = Path(__file__).resolve().parents[1]
posix = pytest.mark.skipif(sys.platform == "win32", reason="the deploy link is a symlink, as on launchd hosts")
darwin = pytest.mark.skipif(sys.platform != "darwin", reason="the switch is a launchd one-shot on macOS only")
BASE = os.path.realpath(sys.executable)
OK = [BASE, "-c", ""]
#: An orchestration change the new release ships: a step its forward() takes before it calls the release verified.
NEW_STEP = '    rec["new_step"] = "ran"\n    _keep(rec, ds.VERIFIED, path)\n'


def _release_with_new_switch(release: Path) -> Path:
    shutil.copytree(REPO / "harness", release / "harness", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(REPO / "scripts", release / "scripts", ignore=shutil.ignore_patterns("__pycache__"))
    f = release / "harness" / "deploy_switch.py"
    text = f.read_text(encoding="utf-8")
    old = "    _keep(rec, ds.VERIFIED, path)\n"
    assert text.count(old) == 1
    f.write_text(text.replace(old, NEW_STEP), encoding="utf-8")
    return f


def _record(tmp_path: Path, release: Path) -> Path:
    previous = tmp_path / "releases" / "13-old"
    previous.mkdir(parents=True)
    release.mkdir(parents=True, exist_ok=True)
    link = tmp_path / "deploy"
    os.symlink(previous, link)
    rec = {"id": 16, "sha": "a" * 40, "job_id": "260", "link": str(link), "release": str(release),
           "previous": str(previous), "previous_sha": "b" * 40, "db": str(tmp_path / "discovery.db"), "backup": "",
           "migrated": False, "queue_was_paused": False, "queue_flag": str(tmp_path / "paused"), "install": OK,
           "rollback_install": OK, "verify": [OK], "alert": OK, "log": str(tmp_path / "logs" / "deploy.log"),
           "stage": "handed_off", "outcome": ""}
    path = tmp_path / "16.json"
    deploy_switch.save(path, rec)
    return path


@posix
def test_the_switch_that_runs_is_the_one_the_new_release_ships(tmp_path):
    release = tmp_path / "releases" / "16-new"
    new_switch = _release_with_new_switch(release)
    path = _record(tmp_path, release)
    argv = deploy.switch_argv(path)
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "VIRTUAL_ENV")}
    got = subprocess.run(argv, cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120)
    rec = deploy_switch.load(path)
    assert rec["outcome"] == deploy_switch.DEPLOYED, (rec, got.stderr)
    assert rec.get("new_step") == "ran", f"the old release's switch ran: {argv}"
    assert Path(argv[2]) == new_switch.resolve()


@darwin
def test_the_switch_unit_runs_the_new_releases_wrapper(tmp_path, monkeypatch):
    release = tmp_path / "releases" / "16-new"
    _release_with_new_switch(release)
    path = _record(tmp_path, release)
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    (bin_ / "launchctl").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    (bin_ / "launchctl").chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_}{os.pathsep}{os.environ['PATH']}")
    deploy.spawn_switch(path, release)
    plist = plistlib.loads((paths.home() / "launchd" / f"{deploy.SWITCH_LABEL}.plist").read_bytes())
    argv = plist["ProgramArguments"]
    assert Path(argv[1]) == (release / "scripts" / "deploy-switch.sh").resolve()
    assert Path(argv[4]) == (release / "harness" / "deploy_switch.py").resolve()


def test_a_release_without_a_switch_or_no_record_falls_back_to_this_ones(tmp_path):
    own = Path(deploy_switch.__file__).resolve()
    assert Path(deploy.switch_argv(tmp_path / "missing.json")[2]) == own
    bare = tmp_path / "releases" / "16-bare"
    path = _record(tmp_path, bare)
    assert Path(deploy.switch_argv(path)[2]) == own


@posix
def test_the_switch_runs_under_the_new_releases_base_interpreter(tmp_path):
    release = tmp_path / "releases" / "16-new"
    _release_with_new_switch(release)
    base = tmp_path / "uv" / "python3.99"
    base.parent.mkdir()
    base.write_text("", encoding="utf-8")
    py = release / ".venv" / "bin" / "python"
    py.parent.mkdir(parents=True)
    os.symlink(base, py)
    argv = deploy.switch_argv(_record(tmp_path, release))
    assert argv[:2] == [os.path.realpath(base), "-I"]
