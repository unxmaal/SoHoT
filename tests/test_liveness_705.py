"""Operational scripts and liveness that misdiagnosed a slow or healthy machine as a broken one. #705."""
import os
import plistlib
import re
import stat
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

import shells
from harness import gateway, serving
from harness import heartbeat as hb

REPO = Path(__file__).resolve().parents[1]
LAUNCHD = REPO / "scripts" / "launchd.sh"
darwin = pytest.mark.skipif(sys.platform != "darwin", reason="launchd is macOS-only")


class Clock:
    def __init__(self, t=1_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


@pytest.fixture
def clock(monkeypatch):
    c = Clock()
    monkeypatch.setattr(hb, "clock", c)
    return c


def _exe(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


def _fake_launchctl(bin_dir: Path, runs: bool) -> None:
    run = '"$prog"' if runs else ":"
    _exe(bin_dir / "launchctl", f"""#!/bin/bash
if [ "$1" = bootstrap ]; then
  prog="$(sed -n 's:.*<array><string>\\(.*\\)</string></array>.*:\\1:p' "$3")"
  {run}
fi
exit 0
""")


def _probe(tmp_path, env_extra, runs=True):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    _fake_launchctl(bin_dir, runs)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir(exist_ok=True)
    env = {k: v for k, v in os.environ.items() if k not in ("HF_ROOT", "HF_HOME")}
    env.update(PATH=f"{bin_dir}{os.pathsep}{env['PATH']}", HF_MIN_FREE_GB="0", **env_extra)
    return subprocess.run([shells.BASH, str(LAUNCHD), "probe"], cwd=elsewhere, env=env,
                          capture_output=True, text=True, timeout=60)


@darwin
def test_the_probe_reads_the_hf_home_the_agents_are_given(tmp_path):
    weights = tmp_path / "weights"
    weights.mkdir()
    got = _probe(tmp_path, {"HF_HOME": str(weights)})
    assert got.returncode == 0, got.stderr
    assert f"can read {weights}" in got.stdout


@darwin
def test_a_probe_that_never_reports_is_not_called_a_permission_problem(tmp_path):
    weights = tmp_path / "weights"
    weights.mkdir()
    got = _probe(tmp_path, {"HF_ROOT": str(weights), "PREFLIGHT_WAIT_S": "1"}, runs=False)
    assert got.returncode != 0
    assert "did not finish in 1 s" in got.stderr
    assert "Full Disk Access" not in got.stderr


def test_a_failed_gateway_generator_says_so(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _exe(bin_dir / "uv", """#!/bin/bash
case "$*" in
  *harness.gateway_key*) echo key ;;
  *harness.gateway*) echo "store locked" >&2; exit 1 ;;
  *harness.nodes*) ;;
  *litellm*) echo "served $*" ;;
esac
""")
    hf = tmp_path / "hf"
    hf.mkdir()
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
           "HF_ROOT": str(hf), "HF_MIN_FREE_GB": "0", "ANTHROPIC_API_KEY": "x",
           "LOCALHARNESS_HOME": str(tmp_path / "home")}
    got = subprocess.run([shells.BASH, str(REPO / "scripts" / "serve-gateway.sh")],
                         env=env, capture_output=True, text=True, timeout=60)
    assert "WARN" in got.stderr and "gateway/config.yaml" in got.stderr, got.stderr


def test_the_static_gateway_config_caps_every_mlx_entry():
    body = yaml.safe_load((REPO / "gateway" / "config.yaml").read_text(encoding="utf-8"))
    mlx = [e for e in body["model_list"]
           if serving.bare(str(e["litellm_params"].get("api_base", ""))) == serving.MLX_URL]
    assert mlx
    for e in mlx:
        assert e["litellm_params"].get("max_parallel_requests") == serving.MLX_MAX_PARALLEL, e["model_name"]


def test_a_declared_mlx_cap_is_a_ceiling_the_sized_cap_can_lower(monkeypatch):
    monkeypatch.setattr(serving, "mlx_parallel", lambda repo: 4)
    entry = {"model_name": "m", "litellm_params": {
        "model": "openai/m", "api_base": f"{serving.MLX_URL}/v1", "max_parallel_requests": 16}}
    assert gateway._capped(entry, {"model_list": [entry]})["litellm_params"]["max_parallel_requests"] == 4


def test_a_step_with_a_six_hour_deadline_four_hours_in_is_running(clock):
    hb.start(lane="video", total=9)
    hb.beat("measure", step=9, candidate="org/video")
    hb.expect(6 * 3600)
    clock.t += 4 * 3600
    assert hb.status(hb.read()) == "running"
    clock.t += 3 * 3600
    assert hb.status(hb.read()) == "stalled"


def test_a_new_step_forgets_the_last_steps_deadline(clock):
    hb.start(lane="video", total=9)
    hb.expect(6 * 3600)
    hb.beat("measure", step=9, candidate="org/next")
    clock.t += hb.STALL_S + 1
    assert hb.status(hb.read()) == "stalled"


def test_a_loop_waiting_on_the_machine_lock_is_not_stalled(clock):
    hb.start(lane="code", total=9)
    hb.beat("measure", step=9, candidate="org/model")
    hb.expect(None, waiting="waiting for a queued job to finish")
    clock.t += hb.STALL_S * 3
    assert hb.status(hb.read()) == "running"
    assert "waiting for a queued job" in hb.summary()["line"]


def test_measure_records_its_deadline_on_the_heartbeat(clock):
    from harness.commands import measure
    hb.start(lane="code", total=9)
    measure._launch([sys.executable, "-c", "pass"], deadline_s=6 * 3600.0, lock="none")
    assert hb.read()["deadline_s"] == 6 * 3600.0


def test_two_sweeps_a_day_expect_one_every_twelve_hours():
    assert hb.sweep_every_s([9, 21]) == 12 * 3600
    assert hb.sweep_every_s([21]) == 24 * 3600
    assert hb.sweep_every_s([3, 9, 21]) == 12 * 3600


def test_the_overdue_check_reads_the_installed_schedule(clock, tmp_path, monkeypatch):
    unit = tmp_path / "com.unxmaal.localharness.discover.plist"
    unit.write_bytes(plistlib.dumps({"StartCalendarInterval": [
        {"Hour": 9, "Minute": 0}, {"Hour": 21, "Minute": 0}]}))
    monkeypatch.setattr(hb, "discover_unit", lambda: unit)
    assert hb.discover_hours() == [9, 21]
    hb.start()
    hb.finish(0)
    clock.t += 14 * 3600
    assert "every 12h" in hb.overdue()


def test_with_no_installed_unit_the_schedule_is_the_launchd_default(tmp_path, monkeypatch):
    monkeypatch.setattr(hb, "discover_unit", lambda: tmp_path / "absent.plist")
    monkeypatch.delenv("DISCOVER_HOURS", raising=False)
    default = re.search(r'^DISCOVER_HOURS="\$\{DISCOVER_HOURS:-([^}]+)\}"',
                        LAUNCHD.read_text(encoding="utf-8"), re.M).group(1)
    assert hb.discover_hours() == [int(h) for h in default.split()]


@pytest.mark.gauntlet("each-half-verified-against-its-own-spec-the-seam-against-nothing",
                      site="env:DISCOVER_HOURS")
def test_with_no_installed_unit_the_overdue_check_reads_the_hours_launchd_was_given(tmp_path, monkeypatch):
    monkeypatch.setattr(hb, "discover_unit", lambda: tmp_path / "absent.plist")
    monkeypatch.setenv("DISCOVER_HOURS", "9 21")
    assert hb.discover_hours() == [9, 21]


def _make_n(cwd: Path) -> str:
    return subprocess.run(["make", "-n", "-f", str(REPO / "Makefile"), "test-postgres"],
                          cwd=cwd, capture_output=True, text=True, timeout=60).stdout


@pytest.mark.skipif(sys.platform == "win32", reason="make test-postgres is docker on a unix host")
def test_two_worktrees_run_test_postgres_under_distinct_names_and_no_fixed_port(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    names = [set(re.findall(r"--name (\S+)", _make_n(d))) for d in (a, b)]
    assert all(len(n) == 1 for n in names) and names[0] != names[1]
    assert not re.search(r"-p \d+:5432", _make_n(a))
