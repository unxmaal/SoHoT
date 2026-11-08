"""A deploy never flips to a release a launchd agent cannot read the weights from, and the switch runs under /bin/bash. #1516."""
from __future__ import annotations

import os
import plistlib
import stat
import subprocess
import sys
from pathlib import Path

import pytest
from test_deploy_1506 import (BASH, _deploys, _git, _queue, _schema, _worker_runs, alerts,  # noqa: F401 - fixtures
                              posix, world)

from harness import deploy, deploy_switch, paths
from harness import memory_store as ms
from harness import workqueue as wq

REPO = Path(__file__).resolve().parents[1]
LAUNCHD = REPO / "scripts" / "launchd.sh"
WRAPPER = REPO / "scripts" / "deploy-switch.sh"
darwin = pytest.mark.skipif(sys.platform != "darwin", reason="launchd is macOS-only")


def _exe(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


def _fake_launchctl(bin_dir: Path, *, hang: bool = False) -> Path:
    """Starts the probe's /bin/bash script as launchd would; with hang, every `ls` it runs blocks like a held open()."""
    pids = bin_dir / "probe.pid"
    path = ""
    if hang:
        held = bin_dir / "held"
        held.mkdir(exist_ok=True)
        _exe(held / "ls", "#!/bin/bash\nexec sleep 3600\n")
        path = f'PATH="{held}:$PATH" '
    _exe(bin_dir / "launchctl", f"""#!/bin/bash
case "$1" in
  bootstrap)
    prog="$(sed -n 's:.*<array><string>/bin/bash</string><string>\\(.*\\)</string></array>.*:\\1:p' "$3")"
    [ -n "$prog" ] || exit 0
    {path}/bin/bash "$prog" &
    echo $! > "{pids}" ;;
  bootout)
    if [ -f "{pids}" ]; then pkill -P "$(cat "{pids}")"; kill "$(cat "{pids}")"; rm -f "{pids}"; fi ;;
esac
exit 0
""")
    return pids


def _probe(tmp_path, env_extra, *, hang=False, timeout=60):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    _fake_launchctl(bin_dir, hang=hang)
    env = {k: v for k, v in os.environ.items() if k not in ("HF_ROOT", "HF_HOME")}
    env.update(PATH=f"{bin_dir}{os.pathsep}{env['PATH']}", HF_MIN_FREE_GB="0", **env_extra)
    return subprocess.run([BASH, str(LAUNCHD), "probe"], cwd=tmp_path, env=env, capture_output=True, text=True,
                          timeout=timeout)


@darwin
def test_a_probe_that_starts_and_never_returns_reads_as_consent_pending_within_its_wait(tmp_path):
    weights = tmp_path / "weights"
    weights.mkdir()
    got = _probe(tmp_path, {"HF_HOME": str(weights), "PREFLIGHT_WAIT_S": "2"}, hang=True)
    assert got.returncode != 0
    assert "consent pending" in got.stderr and str(weights) in got.stderr, got.stderr
    assert "Full Disk Access" in got.stderr and "/bin/bash" in got.stderr
    assert "says nothing about permissions" not in got.stderr
    assert "still blocked after 2 s" in got.stderr, "the probe waited past PREFLIGHT_WAIT_S"
    assert not (tmp_path / "bin" / "probe.pid").exists(), "the blocked probe agent was never booted out"


@darwin
def test_the_probe_reads_a_home_link_onto_a_volume_as_well_as_the_weights(tmp_path):
    """Deploy 1 blocked in machine.versions reading ~/localharness/acestep, a link onto the weights volume."""
    weights = tmp_path / "weights"
    weights.mkdir()
    (paths.home() / "acestep").symlink_to("/Volumes/MISSING/src")
    got = _probe(tmp_path, {"HF_HOME": str(weights)})
    assert got.returncode != 0
    assert "cannot read" in got.stderr and "acestep" in got.stderr, got.stderr


@darwin
def test_the_probe_asks_about_the_weights_reinstall_will_render_not_the_callers(tmp_path):
    recorded, callers = tmp_path / "recorded", tmp_path / "callers"
    recorded.mkdir()
    callers.mkdir()
    bin_dir = tmp_path / "bin"
    (paths.home() / deploy_switch.INSTALL_ENV).write_text(
        f"HF_HOME={recorded}\nPATH={bin_dir}{os.pathsep}/usr/bin:/bin:/usr/sbin:/sbin\n", encoding="utf-8")
    got = _probe(tmp_path, {"HF_HOME": str(callers)})
    assert got.returncode == 0, got.stderr
    assert f"can read {recorded}" in got.stdout


@darwin
def test_the_switch_unit_runs_under_bin_bash_through_its_own_releases_wrapper(tmp_path, monkeypatch):
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    _exe(bin_ / "launchctl", "#!/bin/sh\nexit 0\n")
    monkeypatch.setenv("PATH", f"{bin_}{os.pathsep}{os.environ['PATH']}")
    deploy.spawn_switch(tmp_path / "1.json", tmp_path)
    plist = plistlib.loads((paths.home() / "launchd" / f"{deploy.SWITCH_LABEL}.plist").read_bytes())
    argv = plist["ProgramArguments"]
    assert argv[0] == "/bin/bash", argv
    assert Path(argv[1]) == Path(deploy_switch.__file__).resolve().parents[1] / "scripts" / "deploy-switch.sh"
    assert Path(argv[1]).is_file()
    assert argv[2:] == deploy.switch_argv(tmp_path / "1.json")


@posix
def test_the_switch_wrapper_keeps_bash_as_the_parent_and_passes_the_exit_code():
    """A grant to /bin/bash covers its children only while bash stays their parent; an exec would drop it."""
    child = subprocess.Popen([BASH, str(WRAPPER), sys.executable, "-c", "import os; print(os.getppid())"],
                             stdout=subprocess.PIPE, text=True)
    out, _ = child.communicate(timeout=60)
    assert int(out.strip()) == child.pid, "the wrapper exec'd its command instead of running it as a child"
    rc = subprocess.run([BASH, str(WRAPPER), sys.executable, "-c", "raise SystemExit(3)"], timeout=60).returncode
    assert rc == 3


@posix
def test_a_deploy_whose_launchd_probe_never_returns_is_refused_before_the_flip(world, alerts, monkeypatch):
    monkeypatch.setattr(deploy, "PROBE_TIMEOUT_S", 1.0)
    world["steps"].probe = [BASH, "-c", "sleep 600"]
    job = _queue(world, {"f": "two\n", "harness/memory_store/schema.py": f"SCHEMA_VERSION = {ms.SCHEMA_VERSION + 1}\n"})
    ran = _worker_runs(job, world, spawn=lambda path, release: pytest.fail("the switch was handed off"))
    assert ran["state"] == wq.FAILED and ran["rc"] == 1
    d = _deploys()[0]
    assert d["outcome"] == deploy.FAILED
    assert "launchd probe of the new release before the switch" in d["detail"] and "timed out" in d["detail"]
    assert _git(world["link"], "rev-parse", "HEAD") == world["first"]
    assert d["backup"] == "" and _schema() == ms.SCHEMA_VERSION
    steps = world["log"].read_text(encoding="utf-8")
    assert "smoke" not in steps and "reinstall" not in steps
    assert f"alert deploy of {job['output'][:12]} failed before the switch: launchd probe" in steps
    assert not wq.paused()


@posix
def test_a_consent_pending_probe_says_so_in_the_deploy_record_and_the_alert(world, alerts, tmp_path):
    # A file, not -c: the step's argv lands in the record too, and must not be what carries the words.
    probe = _exe(tmp_path / "probe.sh", "echo 'FATAL: consent pending: the launchd probe was still blocked' >&2\n"
                                        "exit 1\n")
    world["steps"].probe = [BASH, str(probe)]
    job = _queue(world, {"f": "two\n"})
    _worker_runs(job, world, spawn=lambda path, release: pytest.fail("the switch was handed off"))
    d = _deploys()[0]
    assert d["outcome"] == deploy.FAILED and "consent pending" in d["detail"], d["detail"]
    assert "consent pending" in world["log"].read_text(encoding="utf-8").split("alert ", 1)[1]


def test_the_probe_runs_by_default_only_where_launchd_does(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    assert deploy.Steps().probe == ["bash", "scripts/launchd.sh", "probe"]
    monkeypatch.setattr(sys, "platform", "linux")
    assert deploy.Steps().probe == []
