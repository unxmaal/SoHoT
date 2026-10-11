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


@darwin
def test_when_env_sh_refuses_the_weights_root_the_probe_says_so_and_probes_nothing(tmp_path):
    got = _probe(tmp_path, {"HF_ROOT": str(tmp_path / "no-such-parent" / "hf")})
    assert got.returncode != 0
    assert "scripts/env.sh" in got.stderr, got.stderr
    assert "a launchd agent cannot read" not in got.stderr
    assert "did not finish" not in got.stderr


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


def test_a_loop_waiting_behind_a_holder_with_a_deadline_is_running_until_it_passes(clock):
    hb.start(lane="code", total=9)
    hb.beat("measure", step=9, candidate="org/model")
    hb.expect(6 * 3600, waiting="waiting for eval for 10s (pid 7) to finish")
    clock.t += 4 * 3600
    assert hb.status(hb.read()) == "running"
    clock.t += 3 * 3600
    assert hb.status(hb.read()) == "stalled"
    assert "waiting for eval" in hb.summary()["line"]


def test_a_loop_waiting_behind_a_wedged_holder_still_reads_stalled(clock):
    hb.start(lane="code", total=9)
    hb.beat("measure", step=9, candidate="org/model")
    hb.expect(None, waiting="waiting for a queued job to finish")
    clock.t += hb.STALL_S * 3
    assert hb.status(hb.read(), alive=lambda pid: True) == "stalled"
    assert "waiting for a queued job" in hb.summary(alive=lambda pid: True)["line"]


def test_the_lock_holder_record_carries_its_deadline():
    from harness import exclusive
    with exclusive.held("eval", deadline_s=600.0):
        assert exclusive.holder()["deadline_s"] == 600.0


def test_measure_waits_behind_the_holders_deadline_and_declares_its_own(clock, monkeypatch):
    import contextlib
    from harness import exclusive
    from harness.commands import measure
    seen, calls = {}, []

    @contextlib.contextmanager
    def held(kind, announce=None, **kw):
        seen.update(kw)
        announce("waiting for eval for 5s (pid 7) to finish")
        calls.append(dict(hb.read()))
        yield True

    monkeypatch.setattr(exclusive, "held", held)
    monkeypatch.setattr(exclusive, "holder", lambda: {"kind": "eval", "pid": 7, "deadline_s": 7200.0})
    hb.start(lane="code", total=9)
    measure._launch([sys.executable, "-c", "pass"], deadline_s=600.0, lock="eval")
    assert seen.get("deadline_s") == 600.0
    assert calls[0]["deadline_s"] == 7200.0 and calls[0]["waiting"].startswith("waiting for eval")
    assert hb.read()["deadline_s"] == 600.0 and hb.read()["waiting"] == ""


def test_a_video_screen_declares_its_engines_deadline(monkeypatch, tmp_path):
    import argparse
    from harness import cli, memory, screen
    from harness import memory_store as ms
    from harness.commands import measure as measure_cmd
    from harness.commands import screen as screen_cmd
    from evals.run import SCREEN_CASES
    real = ms.connect
    monkeypatch.setattr(ms, "connect", lambda *a, **k: real(tmp_path / "d.db"))
    conn = ms.connect()
    ms.record(conn, ms.Seen(name="org/clip", source="t", kind="weights", lane="video", why="seeded"))
    conn.close()
    spec = "diffusers-video:org/clip"
    monkeypatch.setattr(screen_cmd, "_screen_plan", lambda want: [
        {"name": "org/clip", "state": screen.READY, "candidate": spec, "modality": "video", "why_not": ""}])
    monkeypatch.setattr(memory, "check_model", lambda *a, **k: (True, ""))
    monkeypatch.setattr(screen, "argv", lambda r, **k: ["screen", r["name"]])
    beats = []

    class Done:
        returncode = 0
        stderr = ""

    monkeypatch.setattr(subprocess, "run", lambda argv, **kw: beats.append(dict(hb.read())) or Done())
    monkeypatch.setattr(measure_cmd, "_receipt_at", lambda out: None)
    hb.start(lane="video", total=9)
    cli._report_screen(argparse.Namespace(lane="", top=5, limit=5, run=True, json=False))
    assert screen.deadline_s(spec) == SCREEN_CASES * 6 * 3600.0
    assert beats and beats[0]["deadline_s"] == SCREEN_CASES * 6 * 3600.0


def test_a_screen_of_a_candidate_no_engine_bounds_keeps_the_default_threshold():
    from harness import screen
    assert screen.deadline_s("org/text-model") is None
    assert screen.deadline_s("diffusers-video:") is None


def test_measure_records_its_deadline_on_the_heartbeat(clock):
    from harness.commands import measure
    hb.start(lane="code", total=9)
    measure._launch([sys.executable, "-c", "pass"], deadline_s=6 * 3600.0, lock="none")
    assert hb.read()["deadline_s"] == 6 * 3600.0


def test_the_discover_unit_is_named_by_the_one_python_prefix(monkeypatch):
    from harness import volume
    monkeypatch.setattr(volume, "PREFIX", "org.example.other")
    assert hb.discover_unit().name == "org.example.other.discover.plist"
    assert hb.discover_unit().parent == volume.agents_dir()


def test_launchd_generates_the_discover_unit_the_heartbeat_reads(tmp_path):
    out = tmp_path / "gen"
    hf = tmp_path / "hf"
    hf.mkdir()
    env = {**os.environ, "HF_ROOT": str(hf), "HF_MIN_FREE_GB": "0",
           "LOCALHARNESS_HOME": str(tmp_path / "home")}
    got = subprocess.run([shells.BASH, str(LAUNCHD), "generate", str(out)], env=env,
                         capture_output=True, text=True, timeout=120)
    assert got.returncode == 0, got.stderr
    assert (out / hb.discover_unit().name).is_file(), sorted(p.name for p in out.iterdir())


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


def test_a_loop_waiting_behind_a_real_video_job_reads_running_for_the_engines_timeout(clock, monkeypatch, tmp_path):
    from harness import engines, proc
    from harness.commands import lanes
    engine = engines.resolve("diffusers-video:org/clip")
    seen = []

    def run(argv, **kw):
        os.environ.pop("LH_GPU_LOCK_HELD", None)
        hb.waiting("waiting for video for 5s (pid 7) to finish")
        seen.append(dict(hb.read()))
        os.environ["LH_GPU_LOCK_HELD"] = "1"
        return proc.Outcome(1, 0.0, 0, "", "stop")

    monkeypatch.setattr(proc, "run", run)
    hb.start(lane="video", total=9)
    lanes._generate("diffusers-video:org/clip", "a cat", tmp_path / "c.mp4", {})
    assert seen and seen[0]["deadline_s"] == engine.timeout == 6 * 3600.0
    clock.t += 4 * 3600
    assert hb.status(seen[0], alive=lambda pid: True) == "running"


def test_a_screen_waits_for_the_lock_in_the_loop_and_reads_the_holders_deadline(clock, monkeypatch, tmp_path):
    import argparse
    import contextlib
    from harness import cli, exclusive, memory, screen
    from harness import memory_store as ms
    from harness.commands import measure as measure_cmd
    from harness.commands import screen as screen_cmd
    real = ms.connect
    monkeypatch.setattr(ms, "connect", lambda *a, **k: real(tmp_path / "d.db"))
    conn = ms.connect()
    ms.record(conn, ms.Seen(name="org/text", source="t", kind="weights", lane="code", why="seeded"))
    conn.close()
    monkeypatch.setattr(screen_cmd, "_screen_plan", lambda want: [
        {"name": "org/text", "state": screen.READY, "candidate": "org/text", "modality": "code", "why_not": ""}])
    monkeypatch.setattr(memory, "check_model", lambda *a, **k: (True, ""))
    monkeypatch.setattr(screen, "argv", lambda r, **k: ["screen", r["name"]])
    waits, ran = [], []

    @contextlib.contextmanager
    def held(kind, announce=None, **kw):
        announce("waiting for video for 5s (pid 7) to finish")
        waits.append((kind, dict(hb.read())))
        os.environ[exclusive.HELD_ENV] = "1"
        try:
            yield True
        finally:
            os.environ.pop(exclusive.HELD_ENV, None)

    class Done:
        returncode = 0
        stderr = ""

    monkeypatch.setattr(exclusive, "held", held)
    monkeypatch.setattr(exclusive, "holder", lambda: {"kind": "video", "pid": 7, "deadline_s": 6 * 3600.0})
    monkeypatch.setattr(subprocess, "run", lambda argv, **kw: ran.append(os.environ.get(exclusive.HELD_ENV)) or Done())
    monkeypatch.setattr(measure_cmd, "_receipt_at", lambda out: None)
    hb.start(lane="code", total=9)
    cli._report_screen(argparse.Namespace(lane="", top=5, limit=5, run=True, json=False))
    assert waits and waits[0][0] == "eval" and waits[0][1]["deadline_s"] == 6 * 3600.0
    assert ran == ["1"]


def test_a_standalone_video_screen_declares_its_deadline_on_the_lock(monkeypatch):
    import contextlib
    import evals.run as run
    from harness import exclusive
    seen = {}

    @contextlib.contextmanager
    def held(kind, announce=None, **kw):
        seen.update(kw, kind=kind)
        yield False

    monkeypatch.setattr(exclusive, "held", held)
    monkeypatch.setattr(run, "_execute", lambda args: 0)
    monkeypatch.setattr(run.env, "guard", lambda: None)
    run._main(run.parse_args(
        ["--modality", "video", "--screen", "--candidates", "diffusers-video:org/a,diffusers-video:org/b"]))
    assert seen["kind"] == "eval" and seen.get("deadline_s") == 2 * run.SCREEN_CASES * 6 * 3600.0
