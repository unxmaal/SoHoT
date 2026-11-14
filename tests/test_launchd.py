"""launchd units for the services.

The point is that the machine comes back up serving after a reboot or a crash
without anyone remembering four script names. The units are generated from one
template rather than hand-written, because near-identical plists drift:
the last time this repo had three near-identical things, the copies disagreed
about which port they used.
"""
import os
import plistlib
import re
import shutil
import shlex
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

import shells
from tests import conftest

REPO = Path(__file__).resolve().parents[1]
GEN = REPO / "scripts" / "launchd.sh"
#: READ FROM THE SCRIPT, not restated here. A hardcoded copy is a second
#: answer to the same question, and it went stale the moment `discover` was
#: added: the suite failed with `assert 5 == 4` for a change that was correct.
SERVICES = tuple(
    re.search(r'^SERVICES="([^"]+)"', GEN.read_text(encoding="utf-8"), re.M)
    .group(1).split())

#: launchd IS macOS. There is no Windows equivalent to generate plists for, and
#: Windows service supervision (Task Scheduler) is not implemented -- so these
#: skip rather than fail, which keeps "not built yet" distinct from "broken".
pytestmark = pytest.mark.skipif(
    sys.platform != "darwin",
    reason="launchd is macOS-only. The desktop registers nothing with either "
           "of its operating systems on purpose; scripts/services.sh is that "
           "machine's answer and starts on demand")


@pytest.fixture(scope="module")
def plists(tmp_path_factory):
    """Generate the units into a scratch directory and parse them."""
    out = tmp_path_factory.mktemp("launchagents")
    proc = subprocess.run([shells.BASH, str(GEN), "generate", str(out)],
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    return {p.stem: plistlib.loads(p.read_bytes()) for p in out.glob("*.plist")}


def test_one_unit_per_service(plists):
    labels = {v["Label"] for v in plists.values()}
    for service in SERVICES:
        assert any(service in label for label in labels), f"no unit for {service}"


@pytest.mark.parametrize("service", SERVICES)
def test_each_unit_runs_the_repo_script(plists, service):
    unit = next(v for k, v in plists.items() if service in k)
    argv = unit["ProgramArguments"]
    assert argv[0] == "/bin/bash", argv
    assert argv[1].endswith(f"serve-{service}.sh"), argv
    assert Path(argv[1]).is_absolute(), "launchd has no working directory"


#: Jobs that RUN AND EXIT, read from the script for the same reason SERVICES
#: is. KeepAlive on one of these restarts a finished sweep at once and the
#: machine discovers in a tight loop.
PERIODIC = tuple(
    re.search(r'^declare -a PERIODIC=\(([^)]*)\)',
              GEN.read_text(encoding="utf-8"), re.M).group(1).split())
SERVERS = tuple(s for s in SERVICES if s not in PERIODIC)


@pytest.mark.parametrize("service", SERVERS)
def test_each_server_restarts_on_crash(plists, service):
    unit = next(v for k, v in plists.items() if service in k)
    # ds4 exits 0 when no lane adopted a ds4 spec; a crash is still restarted. #611.
    assert unit.get("KeepAlive") in (True, {"SuccessfulExit": False})
    assert "StartInterval" not in unit, (
        f"{service} serves; an interval would let it die between runs")


@pytest.mark.parametrize("service", PERIODIC)
def test_each_periodic_job_runs_on_an_interval(plists, service):
    """A sweep finishes. KeepAlive would restart it immediately and the
    machine would discover in a tight loop, which is the opposite failure from
    a sweep that never runs and just as invisible."""
    unit = next(v for k, v in plists.items() if service in k)
    assert unit.get("StartCalendarInterval"), unit
    assert "StartInterval" not in unit, "an interval restarts at every reload (#625)"
    assert unit.get("KeepAlive") is not True


@pytest.mark.parametrize("service", SERVICES)
def test_each_unit_logs_somewhere_you_can_read(plists, service):
    unit = next(v for k, v in plists.items() if service in k)
    for key in ("StandardOutPath", "StandardErrorPath"):
        assert unit.get(key), f"{service} has no {key}"
        assert Path(unit[key]).is_absolute()


@pytest.mark.parametrize("service", SERVICES)
def test_each_unit_writes_its_log_as_it_goes(plists, service):
    """The first scheduled sweep wrote 87 bytes and then nothing for its whole
    run while the store kept being updated. launchd's stdout is a file, so
    Python block-buffers it, and a job that is working reads exactly like a
    job that is wedged -- which defeats the reason for having a log at all."""
    unit = next(v for k, v in plists.items() if service in k)
    assert unit["EnvironmentVariables"].get("PYTHONUNBUFFERED") == "1", unit


@pytest.mark.parametrize("service", SERVICES)
def test_each_unit_carries_a_path_that_includes_homebrew(plists, service):
    """launchd starts jobs with PATH=/usr/bin:/bin:/usr/sbin:/sbin. uv, ffmpeg,
    rsvg-convert and rec all live in /opt/homebrew/bin, so without this every
    service dies on 'command not found' -- the same trap a GUI-spawned wezterm
    set for the voice scripts."""
    unit = next(v for k, v in plists.items() if service in k)
    assert "/opt/homebrew/bin" in unit["EnvironmentVariables"]["PATH"]


def test_labels_are_reverse_dns_and_distinct(plists):
    labels = [v["Label"] for v in plists.values()]
    assert len(set(labels)) == len(labels)
    for label in labels:
        assert label.count(".") >= 2, f"{label} is not a reverse-DNS label"


def test_the_script_refuses_an_unknown_subcommand():
    proc = subprocess.run([shells.BASH, str(GEN), "frobnicate"],
                          capture_output=True, text=True)
    assert proc.returncode != 0
    assert "generate" in proc.stdout + proc.stderr


def test_generate_is_idempotent(tmp_path):
    """Re-running must overwrite rather than accumulate or fail."""
    for _ in range(2):
        proc = subprocess.run([shells.BASH, str(GEN), "generate", str(tmp_path)],
                              capture_output=True, text=True)
        assert proc.returncode == 0, proc.stderr
    assert len(list(tmp_path.glob("*.plist"))) == len(SERVICES)


def test_install_is_a_separate_step_from_generate():
    """Writing into ~/Library/LaunchAgents and loading jobs is not something
    `generate` should do as a side effect."""
    text = GEN.read_text(encoding="utf-8")
    assert "install)" in text and "generate)" in text
    assert "uninstall)" in text, "anything that loads jobs must unload them"


def test_install_checks_the_weights_volume_is_readable_first():
    """macOS TCC blocks a launchd agent from reading /Volumes even though the
    volume stats fine, and mlx_lm turns that into a silent hang. Installing
    units that will wedge on first use is worse than refusing."""
    text = GEN.read_text(encoding="utf-8")
    assert "Full Disk Access" in text
    assert "preflight" in text.lower() or "readable" in text.lower()


def test_the_preflight_runs_in_the_launchd_domain_not_the_shell():
    """Checking readability from the installing terminal proves nothing: that
    terminal already has the access the agent lacks. It has to be tested from
    inside launchd."""
    text = GEN.read_text(encoding="utf-8")
    assert "launchctl" in text and ("probe" in text.lower() or "preflight" in text.lower())


def test_the_mcp_unit_can_find_lh(plists):
    """The MCP server shells out to `lh`, which uv installs into
    ~/.local/bin. launchd starts jobs with PATH=/usr/bin:/bin:/usr/sbin:/sbin
    and nothing else, so without this the unit loads, listens, and fails every
    single tool call with "lh: command not found"."""
    unit = next(v for k, v in plists.items() if "mcp" in k)
    assert ".local/bin" in unit["EnvironmentVariables"]["PATH"]


#: launchctl that runs a bootstrapped plist's program itself, so the probe submits no real launchd job. #1794.
FAKE_LAUNCHCTL = ('#!{py}\nimport plistlib, subprocess, sys\nif sys.argv[1:2] == ["bootstrap"]:\n'
                  '    with open(sys.argv[3], "rb") as f:\n        subprocess.Popen(plistlib.load(f)["ProgramArguments"])\n')


def test_probe_is_available_without_installing_anything(tmp_path):
    """The TCC verdict is the whole question, and finding it out should not
    require committing to an install first."""
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    (bin_ / "launchctl").write_text(FAKE_LAUNCHCTL.format(py=sys.executable), encoding="utf-8")
    (bin_ / "launchctl").chmod(0o755)
    proc = subprocess.run([shells.BASH, str(GEN), "probe"], env={**os.environ, "PATH": f"{bin_}:{os.environ['PATH']}"},
                          capture_output=True, text=True)
    # Either verdict is fine here; what matters is that it ran and said so.
    assert "ok" in proc.stdout.lower() or "denied" in (proc.stdout + proc.stderr).lower()


def test_the_probe_agent_label_is_per_run():
    """Two suites probing at once shared one launchd label in gui/$UID: one
    booted out the other's probe, which then read "unknown" and failed. Same
    class as #426's fixed ports."""
    import re
    gen = GEN.read_text(encoding="utf-8")
    body = gen[gen.index("preflight() {"):gen.index("MSG\n    exit 1")]
    label = re.search(r'local label="([^"]+)"', body).group(1)
    assert "$$" in label, label


def test_install_waits_for_a_teardown_before_loading_again():
    """`install` claims in its own comment to be re-runnable and was not.

    On a machine with all five agents already loaded it printed "loaded
    gateway", then "Bootstrap failed: 5: Input/output error" and stopped --
    naming neither the service nor the cause. `launchctl bootout` returns
    before the job is gone, so the bootstrap that follows hits a label that
    still exists.

    `set -e` then made it worse than either extreme: four agents kept running
    the OLD plists while one ran the new one, and nothing said which.
    """
    gen = GEN.read_text(encoding="utf-8")
    body = gen[gen.index("install_units()"):gen.index("uninstall_units()")]
    assert "_await_unload" in body, (
        "install bootstraps straight after bootout, which fails on a machine "
        "where the agents are already loaded -- the normal case")
    assert "failed=" in body and "FAILED to load" in body, (
        "a failed bootstrap must name the service and let the rest load, "
        "rather than aborting the loop and leaving the machine part old")


# --- the agents run a deploy checkout, never the working one. #290 ----------

def _git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], check=True,
                          capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repos(tmp_path):
    """A bare origin with `main`, and a working clone sitting on a branch."""
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)],
                   check=True)
    work = tmp_path / "work"
    subprocess.run(["git", "clone", "-q", str(origin), str(work)], check=True)
    _git(work, "config", "user.email", "t@example.invalid")
    _git(work, "config", "user.name", "t")
    (work / "f").write_text("main\n", encoding="utf-8")
    _git(work, "add", "f")
    _git(work, "commit", "-q", "-m", "main")
    _git(work, "push", "-q", "origin", "HEAD:main")
    _git(work, "checkout", "-q", "-b", "feature")
    (work / "f").write_text("feature\n", encoding="utf-8")
    _git(work, "commit", "-q", "-am", "feature")
    return origin, work, tmp_path / "deploy"


FAKE_GH = """#!/bin/sh
# run list ... --commit SHA ... | run view ID --json jobs; answers with FAKE_GH_CHECK for check-macos.
if [ "$1 $2" = "run list" ]; then
  while [ $# -gt 0 ]; do [ "$1" = --commit ] && sha="$2"; shift; done
  printf '[{"databaseId":7,"status":"completed","conclusion":"%s","headSha":"%s","url":"https://example.invalid/7"}]' \
    "$FAKE_GH_CHECK" "$sha"
else
  printf '{"jobs":[{"name":"check-macos","status":"completed","conclusion":"%s"}]}' "$FAKE_GH_CHECK"
fi
"""


def _fake_gh(bin_):
    bin_.mkdir(exist_ok=True)
    (bin_ / "gh").write_text(FAKE_GH, encoding="utf-8")
    (bin_ / "gh").chmod(0o755)
    return bin_


def _deploy(work, deploy, check="success", **extra):
    bin_ = _fake_gh(work.parent / "ghbin")
    # The sweep guard reads this home's heartbeat; never the real one, where a sweep may be running. #1000.
    env = {**os.environ, "PATH": f"{bin_}{os.pathsep}{os.environ['PATH']}", "LH_REPO": str(work),
           "LH_DEPLOY": str(deploy), "FAKE_GH_CHECK": check, "LOCALHARNESS_HOME": str(work.parent / "lh"), **extra}
    env = {k: v for k, v in env.items() if k != "LH_DEPLOY_UNCHECKED" or k in extra}
    return subprocess.run([shells.BASH, str(GEN), "deploy"], env=env,
                          capture_output=True, text=True)


def test_deploy_runs_origin_main_whatever_the_working_branch_is(repos):
    origin, work, deploy = repos
    proc = _deploy(work, deploy)
    assert proc.returncode == 0, proc.stderr
    assert _git(deploy, "rev-parse", "HEAD") == _git(origin, "rev-parse", "main")
    assert (deploy / "f").read_text(encoding="utf-8") == "main\n"
    assert _git(work, "rev-parse", "--abbrev-ref", "HEAD") == "feature"


def test_deploy_follows_main_when_it_moves(repos):
    origin, work, deploy = repos
    assert _deploy(work, deploy).returncode == 0
    other = work.parent / "other"
    subprocess.run(["git", "clone", "-q", str(origin), str(other)], check=True)
    _git(other, "config", "user.email", "t@example.invalid")
    _git(other, "config", "user.name", "t")
    (other / "f").write_text("main 2\n", encoding="utf-8")
    _git(other, "commit", "-q", "-am", "main 2")
    _git(other, "push", "-q", "origin", "HEAD:main")
    assert _deploy(work, deploy).returncode == 0
    assert (deploy / "f").read_text(encoding="utf-8") == "main 2\n"


def test_deploy_refuses_a_main_whose_check_failed(repos):
    origin, work, deploy = repos
    proc = _deploy(work, deploy, check="failure")
    assert proc.returncode != 0
    assert "REFUSING to deploy" in proc.stderr and "LH_DEPLOY_UNCHECKED=1" in proc.stderr
    assert not deploy.exists()


def test_deploy_unchecked_goes_ahead_with_a_warning(repos):
    origin, work, deploy = repos
    proc = _deploy(work, deploy, check="failure", LH_DEPLOY_UNCHECKED="1")
    assert proc.returncode == 0, proc.stderr
    assert "WARNING: LH_DEPLOY_UNCHECKED=1" in proc.stderr
    assert _git(deploy, "rev-parse", "HEAD") == _git(origin, "rev-parse", "main")


def test_deploy_refuses_to_overwrite_edits_in_the_deploy_checkout(repos):
    _, work, deploy = repos
    assert _deploy(work, deploy).returncode == 0
    (deploy / "f").write_text("hand edit\n", encoding="utf-8")
    proc = _deploy(work, deploy)
    assert proc.returncode != 0
    assert (deploy / "f").read_text(encoding="utf-8") == "hand edit\n"


def test_units_point_at_the_deploy_checkout(tmp_path):
    deploy = tmp_path / "deploy"
    out = tmp_path / "units"
    env = {**os.environ, "LH_DEPLOY": str(deploy)}
    proc = subprocess.run([shells.BASH, str(GEN), "generate", str(out)],
                          env=env, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    for p in out.glob("*.plist"):
        unit = plistlib.loads(p.read_bytes())
        assert unit["ProgramArguments"][1].startswith(f"{deploy}/scripts/"), p
        assert unit["WorkingDirectory"] == str(deploy), p


def test_the_default_deploy_checkout_is_not_the_working_one(plists):
    for unit in plists.values():
        assert not unit["ProgramArguments"][1].startswith(f"{REPO}/"), (
            "an agent runs the working checkout, so branch work goes live")


@pytest.mark.parametrize("service", PERIODIC)
def test_installing_does_not_start_a_periodic_job(plists, service):
    """Every install started a sweep that hit HuggingFace and took the
    machine lock (#328). An install is not a schedule tick."""
    unit = next(v for k, v in plists.items() if service in k)
    assert unit.get("RunAtLoad") is not True


@pytest.mark.parametrize("service", SERVERS)
def test_a_server_still_starts_when_loaded(plists, service):
    unit = next(v for k, v in plists.items() if service in k)
    assert unit.get("RunAtLoad") is True


def test_the_live_store_is_audited_nightly(plists):
    """`soh audit` reads the live store read-only; once a day it says whether it still holds. #492."""
    unit = next(v for k, v in plists.items() if k.endswith(".audit"))
    assert unit["ProgramArguments"][1].endswith("serve-audit.sh")
    assert unit["StartCalendarInterval"] == [{"Hour": 3, "Minute": 0}]
    assert unit.get("RunAtLoad") is not True


def test_the_discover_sweep_runs_at_fixed_local_times(plists):
    """StartInterval counts from load, so a day of deploys never let it fire (#625); once a day after 21:00 (#646)."""
    unit = next(v for k, v in plists.items() if k.endswith(".discover"))
    assert unit["StartCalendarInterval"] == [{"Hour": 21, "Minute": 0}]
    assert "StartInterval" not in unit and unit.get("RunAtLoad") is not True


def test_the_sweep_schedule_and_the_overdue_check_agree(tmp_path, monkeypatch):
    from harness import heartbeat
    out = tmp_path / "agents"
    env = {**os.environ, "DISCOVER_HOURS": "9 21"}
    proc = subprocess.run([shells.BASH, str(GEN), "generate", str(out)],
                          capture_output=True, text=True, env=env)
    assert proc.returncode == 0, proc.stderr
    monkeypatch.setattr(heartbeat, "discover_unit", lambda: next(out.glob("*.discover.plist")))
    assert heartbeat.discover_hours() == [9, 21]
    assert heartbeat.sweep_every_s(heartbeat.discover_hours()) == 12 * 3600


def test_install_audits_what_it_just_deployed():
    body = GEN.read_text(encoding="utf-8").split("install_units() {", 1)[1].split("\n}\n", 1)[0]
    assert "serve-audit.sh" in body, "a deploy is checked by `soh audit` once its units are loaded"
    assert body.index("serve-audit.sh") > body.index('_reload "$service"')


def test_the_audit_script_runs_soh_audit_from_its_checkout():
    text = (REPO / "scripts" / "serve-audit.sh").read_text(encoding="utf-8")
    assert "set -euo pipefail" in text and "uv run soh audit" in text


def test_install_lets_a_running_job_finish_before_reloading_the_worker():
    """#577: a reload under a running job killed it and recorded it as failed."""
    body = GEN.read_text(encoding="utf-8").split("install_units() {", 1)[1].split("\n}\n", 1)[0]
    assert "harness.workqueue quiesce" in body
    assert body.index("harness.workqueue quiesce") < body.index('_reload "$service"')
    assert "was-running" in body and "jobs resume" in body, (
        "the queue is resumed after the reload only if the owner had not paused it")


def test_the_sweep_downloads_up_to_80_gib_by_default_and_the_knob_agrees(monkeypatch):
    # The old default bound most nights (#1288); this is the next registered rung. #678, #1526.
    from harness import fetching, knobs
    for var in ("DISCOVER_BUDGET_GIB", "DAY_FETCH_GIB"):
        monkeypatch.delenv(var, raising=False)
    text = (REPO / "scripts" / "serve-discover.sh").read_text(encoding="utf-8")
    script = float(re.search(r'BUDGET="\$\{DISCOVER_BUDGET_GIB:-(\d+)\}"', text).group(1))
    knob = knobs.KNOBS["download_budget"]
    assert (script, float(knob.default()), knobs.limits()["download_budget_gib"], fetching.budget_gib(None)) \
        == (80, 80, 80, 80)
    assert 80 in knob.values and knobs.KNOBS["day_fetch_budget"].default() == 40


# --- install leaves a live periodic run alone. #794 ---------------------------

FAKE_LAUNCHCTL_794 = r"""#!/usr/bin/env bash
echo "$*" >> "$FAKE_STATE/log"
case "$1" in
  print) l="${2##*/}"; [ -f "$FAKE_STATE/$l" ] || exit 113
         r="$FAKE_STATE/$l.running"
         if [ -s "$r" ]; then n="$(cat "$r")"; [ "$n" -gt 0 ] && echo $((n - 1)) > "$r" || rm -f "$r"; fi
         printf '%s = {\n\tstate = %s\n' "$2" "$([ -f "$FAKE_STATE/$l.running" ] && echo running || echo waiting)"
         [ -f "$FAKE_STATE/$l.running" ] && printf '\tpid = 4242\n'
         printf '}\n' ;;
  print-disabled) for f in "$FAKE_STATE"/*.disabled; do
                    [ -e "$f" ] && printf '\t\t"%s" => disabled\n' "$(basename "$f" .disabled)"
                  done ;;
  bootout) rm -f "$FAKE_STATE/${2##*/}" ;;
  bootstrap) l="$(basename "$3" .plist)"
             if [ -f "$FAKE_STATE/$l.disabled" ] || [ "$l" = "${FAKE_FAIL_ALWAYS:-}" ]; then
               echo "Bootstrap failed: 5: Input/output error" >&2; exit 5
             fi
             if [ "$l" = "${FAKE_FAIL_ONCE:-}" ] && [ ! -f "$FAKE_STATE/$l.failed" ]; then
               touch "$FAKE_STATE/$l.failed"; echo "Bootstrap failed: 5: Input/output error" >&2; exit 5
             fi
             touch "$FAKE_STATE/$l"
             if [ "$l" = "${FAKE_FAIL_ONCE:-}" ]; then : > "$FAKE_STATE/$l.running"; fi ;;
esac
exit 0
"""


def _install(tmp_path, role="scheduler", running=(), defer_wait=0, mode="", then="", uv="#!/bin/sh\nexit 0\n",
             extra_env=None, run=True, prelude="", env_sh=""):
    """install_units against a fake launchctl, with deploy and preflight stubbed out; rerunnable on one tmp_path."""
    scripts, bin_, state, deploy = (tmp_path / d for d in ("scripts", "bin", "state", "deploy"))
    for d in (scripts, bin_, state, deploy / "scripts"):
        d.mkdir(parents=True, exist_ok=True)
    (state / "log").write_text("", encoding="utf-8")
    text = GEN.read_text(encoding="utf-8")
    (scripts / "lib.sh").write_text(text[:text.index('case "${1:-}" in')], encoding="utf-8")
    (scripts / "env.sh").write_text(env_sh, encoding="utf-8")
    (scripts / "run.sh").write_text(
        'source "$(dirname "$0")/lib.sh"\ndeploy() { :; }\n_run_deployed() { :; }\npreflight() { :; }\n'
        f'{prelude}\ninstall_units {mode}\n', encoding="utf-8")
    for name, body in (("launchctl", FAKE_LAUNCHCTL_794), ("uv", uv)):
        if body is None:
            continue
        (bin_ / name).write_text(body, encoding="utf-8")
        (bin_ / name).chmod(0o755)
    for name in ("lan-probe.sh", "serve-audit.sh"):
        (deploy / "scripts" / name).write_text("exit 0\n", encoding="utf-8")
    for service in SERVICES:
        (state / f"com.unxmaal.localharness.{service}").touch()
    # A name runs for good; a (name, n) pair stays live for its next n prints, then ends. #1058.
    for service in running:
        name, prints = service if isinstance(service, tuple) else (service, None)
        live = state / f"com.unxmaal.localharness.{name}.running"
        live.write_text("" if prints is None else str(prints), encoding="utf-8")
    env = {**os.environ, "PATH": f"{bin_}{os.pathsep}{os.environ['PATH']}", "HOME": str(tmp_path / "home"),
           "LOCALHARNESS_HOME": str(tmp_path / "lh"), "LH_DEPLOY": str(deploy), "LH_ROLE": role,
           "FAKE_STATE": str(state), "LH_DEFER_WAIT_S": str(defer_wait), **(extra_env or {})}
    env = {k: v for k, v in env.items() if v is not None}
    argv = [shells.BASH, str(scripts / "run.sh")]
    if then:
        argv = [shells.BASH, "-c", f'"{shells.BASH}" "{scripts / "run.sh"}" && {then}']
    if not run:
        return argv, env
    got = subprocess.run(argv, env=env, capture_output=True, text=True, timeout=120)
    return got, (state / "log").read_text(encoding="utf-8").splitlines()


def test_install_does_not_kill_a_sweep_that_is_running(tmp_path):
    got, calls = _install(tmp_path, running=("discover",))
    assert not [c for c in calls if c.startswith("bootout") and c.endswith(".discover")], calls
    assert "pid 4242" in got.stderr and "deferred: discover" in got.stderr, got.stderr
    assert "Re-run install after it finishes" in got.stderr
    assert got.returncode == 0, "a deferral is not a failure: the unit starts the deployed code next run (#1521)"
    for service in ("gateway", "audit", "worker"):
        assert f"loaded com.unxmaal.localharness.{service}" in got.stdout, (service, got.stdout)


def test_install_reloads_an_idle_periodic_unit(tmp_path):
    got, calls = _install(tmp_path)
    assert got.returncode == 0, got.stderr
    assert any(c.startswith("bootout") and c.endswith(".discover") for c in calls)
    assert "deferred" not in got.stderr


def test_install_reloads_a_deferred_unit_once_its_run_ends(tmp_path):
    got, calls = _install(tmp_path, running=(("energy", 2),), defer_wait=30)
    assert got.returncode == 0, got.stderr
    assert "NOT reloading com.unxmaal.localharness.energy" in got.stderr
    assert "loaded com.unxmaal.localharness.energy" in got.stdout, got.stdout
    assert "deferred:" not in got.stderr, got.stderr
    assert any(c.startswith("bootstrap") and c.endswith(".energy.plist") for c in calls)


def test_install_defers_a_unit_still_live_at_the_deadline(tmp_path):
    got, calls = _install(tmp_path, running=("energy",), defer_wait=1)
    assert got.returncode == 0, got.stderr
    assert "deferred: energy" in got.stderr, got.stderr
    assert not [c for c in calls if c.startswith("bootout") and c.endswith(".energy")], calls


def test_a_live_day_fetch_lets_the_deploy_chain_run_smoke(tmp_path):
    # `install && smoke.sh && soh coherence` skipped both checks on every daytime install. #1521.
    got, calls = _install(tmp_path, running=("fetch",), defer_wait=1, then="echo smoke-ran")
    assert "deferred: fetch" in got.stderr, got.stderr
    assert got.returncode == 0 and "smoke-ran" in got.stdout, (got.returncode, got.stderr[-800:])
    assert not [c for c in calls if c.startswith("bootout") and c.endswith(".fetch")], calls


@pytest.mark.skipif(sys.platform == "win32", reason="the switch runs its steps in their own POSIX session")
def test_a_queue_deploy_during_a_day_fetch_deploys_and_does_not_roll_back(tmp_path):
    from harness import deploy_switch
    argv, env = _install(tmp_path / "w", running=("fetch",), defer_wait=1, mode="reinstall", run=False)
    # The switch drops LH_DEPLOY and friends from its own environment, so the step names them itself.
    keys = ("PATH", "HOME", "LOCALHARNESS_HOME", "LH_DEPLOY", "LH_ROLE", "FAKE_STATE", "LH_DEFER_WAIT_S")
    step = "env " + " ".join(shlex.quote(f"{k}={env[k]}") for k in keys) + " " + shlex.join(argv)
    for d in ("release", "previous"):
        (tmp_path / d).mkdir()
    rec = {"link": str(tmp_path / "deploy"), "release": str(tmp_path / "release"), "sha": "a" * 40,
           "previous": str(tmp_path / "previous"), "previous_sha": "b" * 40,
           "install": [shells.BASH, "-c", step], "verify": [[shells.BASH, "-c", "echo smoke-ran"]],
           "rollback_install": [shells.BASH, "-c", "echo ROLLED-BACK"], "alert": [shells.BASH, "-c", "echo ALERT"],
           "log": str(tmp_path / "deploy.log"), "queue_flag": str(tmp_path / "flag")}
    deploy_switch.save(tmp_path / "1.json", rec)
    got = deploy_switch.switch(tmp_path / "1.json")
    log = (tmp_path / "deploy.log").read_text(encoding="utf-8")
    assert "deferred: fetch" in log, log[-1500:]
    assert got["outcome"] == deploy_switch.DEPLOYED, got.get("detail")
    assert "smoke-ran" in log and "ROLLED-BACK" not in log and "ALERT" not in log


def test_a_deferred_unit_whose_definition_did_not_change_needs_no_rerun(tmp_path):
    first, _ = _install(tmp_path)
    assert first.returncode == 0, first.stderr
    got, _ = _install(tmp_path, running=("fetch",), defer_wait=1)
    assert got.returncode == 0, got.stderr
    assert "deferred: fetch -- mid-run; its unit is unchanged" in got.stderr, got.stderr
    assert "Re-run install" not in got.stderr, got.stderr


def test_a_deferred_unit_whose_definition_changed_says_to_rerun(tmp_path):
    first, _ = _install(tmp_path)
    assert first.returncode == 0, first.stderr
    got, _ = _install(tmp_path, running=("fetch",), defer_wait=1, extra_env={"FETCH_HOURS": "5"})
    assert got.returncode == 0, got.stderr
    assert "deferred: fetch -- mid-run, and its unit changed" in got.stderr, got.stderr
    assert "Re-run install after it finishes" in got.stderr


MONIT = "com.unxmaal.localharness.monit"
FAKE_UV_SOH = '#!/bin/sh\n[ "$1 $2 $3" = "run --quiet soh" ] || exit 0\nshift 3\nexec "$FAKE_PY" -m harness.cli "$@"\n'


def _monit_set_up(tmp_path):
    """A machine where soh monitor install ran once: its plist, a live monit, and a monit binary that checks fine."""
    for d in ("bin", "state", "home/Library/LaunchAgents"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    (tmp_path / "bin" / "monit").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    (tmp_path / "bin" / "monit").chmod(0o755)
    (tmp_path / "home" / "Library" / "LaunchAgents" / f"{MONIT}.plist").write_text("old", encoding="utf-8")
    (tmp_path / "state" / MONIT).touch()
    (tmp_path / "state" / f"{MONIT}.running").write_text("", encoding="utf-8")
    # The live home is $HOME/localharness, as on the machine, so soh monitor install passes its live-home gate. #1963.
    (tmp_path / "home" / "localharness").symlink_to(tmp_path / "lh", target_is_directory=True)


@pytest.mark.skipif(sys.platform != "darwin", reason="soh monitor install loads a launchd agent")
def test_install_leaves_monit_loaded_when_its_first_bootstrap_fails(tmp_path):
    # Monit was left unloaded after the ba38b746 install; a deploy must leave it loaded or fail. #1521.
    _monit_set_up(tmp_path)
    env = {"FAKE_FAIL_ONCE": MONIT, "FAKE_PY": sys.executable, "PYTHONPATH": str(REPO)}
    got, calls = _install(tmp_path, uv=FAKE_UV_SOH, extra_env=env)
    assert shutil.which("launchctl", path=f"{tmp_path / 'bin'}") == str(tmp_path / "bin" / "launchctl")
    monit = [c for c in calls if c.endswith(MONIT) or c.endswith(f"{MONIT}.plist")]
    assert [c.split()[0] for c in monit if not c.startswith("print")] == ["bootout", "bootstrap", "bootout",
                                                                          "bootstrap"], monit
    assert (tmp_path / "state" / MONIT).exists() and (tmp_path / "state" / f"{MONIT}.running").exists()
    assert got.returncode == 0, got.stderr[-1500:]


@pytest.mark.skipif(sys.platform != "darwin", reason="soh monitor install loads a launchd agent")
def test_install_fails_when_monit_cannot_be_loaded(tmp_path):
    _monit_set_up(tmp_path)
    (tmp_path / "bin" / "monit").write_text("#!/bin/sh\necho 'syntax error' >&2\nexit 1\n", encoding="utf-8")
    env = {"FAKE_PY": sys.executable, "PYTHONPATH": str(REPO)}
    got, _ = _install(tmp_path, uv=FAKE_UV_SOH, extra_env=env)
    assert got.returncode != 0 and "not loaded: monit" in got.stderr, got.stderr[-1500:]


# An ssh shell's PATH, without Homebrew; the units' PATH is cut to the tmp home so a real uv cannot answer. #1616.
SSH_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"
JOB_PATH_HOME_ONLY = 'JOB_PATH="$HOME/.local/bin:/usr/bin:/bin:/usr/sbin:/sbin"'


@pytest.mark.skipif(sys.platform == "win32", reason="launchd.sh install is macOS")
def test_install_without_uv_fails_before_touching_any_unit(tmp_path):
    got, calls = _install(tmp_path, role="interactive", uv=None, prelude=JOB_PATH_HOME_ONLY,
                          extra_env={"PATH": f"{tmp_path / 'bin'}{os.pathsep}{SSH_PATH}"})
    assert got.returncode != 0 and "uv not found" in got.stderr, (got.returncode, got.stderr[-800:])
    assert "pinned set" not in got.stderr and "refused" not in got.stderr, got.stderr[-800:]
    assert not [c for c in calls if c.split()[0] in ("bootout", "bootstrap")], calls
    assert "removed" not in got.stdout, got.stdout
    assert all((tmp_path / "state" / f"com.unxmaal.localharness.{s}").exists() for s in SERVICES)


@pytest.mark.skipif(sys.platform == "win32", reason="launchd.sh install is macOS")
def test_install_finds_uv_on_the_units_path_when_the_shell_has_none(tmp_path):
    local_bin = tmp_path / "home" / ".local" / "bin"
    local_bin.mkdir(parents=True)
    (local_bin / "uv").write_text('#!/bin/sh\necho "$*" >> "$FAKE_STATE/uv"\n', encoding="utf-8")
    (local_bin / "uv").chmod(0o755)
    got, _ = _install(tmp_path, role="interactive", uv=None, prelude=JOB_PATH_HOME_ONLY,
                      extra_env={"PATH": f"{tmp_path / 'bin'}{os.pathsep}{SSH_PATH}"})
    assert got.returncode == 0, got.stderr[-800:]
    assert "loaded com.unxmaal.localharness.interactive" in got.stdout, got.stdout
    ran = (tmp_path / "state" / "uv").read_text(encoding="utf-8")
    assert "run python -m harness.interactive check" in ran and "run python -m harness.nodes check" in ran, ran


FAKE_UV_GGUF_DIR = ('#!/bin/sh\n[ "$*" = "run python -m harness.interactive check" ] || exit 0\n'
                    'exec "$FAKE_PY" -c "from harness import gguf; print(gguf.models_dir())" > "$FAKE_STATE/gguf-dir"\n')


@pytest.mark.skipif(sys.platform == "win32", reason="launchd.sh install is macOS")
def test_the_fit_check_reads_the_gguf_dir_the_unit_serves_from(tmp_path):
    import plistlib
    weights = tmp_path / "hf"
    env_sh = f'HF_ROOT="${{HF_ROOT:-{tmp_path / "hf_root"}}}"\nexport HF_HOME="$HF_ROOT"\n'
    env = {"HF_ROOT": str(weights), "HF_HOME": None, "LLAMACPP_MODELS_DIR": str(tmp_path / "elsewhere"),
           "FAKE_PY": sys.executable, "PYTHONPATH": str(REPO)}
    got, _ = _install(tmp_path, role="interactive", uv=FAKE_UV_GGUF_DIR, env_sh=env_sh, extra_env=env)
    assert got.returncode == 0, got.stderr[-800:]
    unit = tmp_path / "home" / "Library" / "LaunchAgents" / "com.unxmaal.localharness.interactive.plist"
    unit_env = plistlib.loads(unit.read_bytes())["EnvironmentVariables"]
    assert unit_env["HF_HOME"] == unit_env["HF_ROOT"] == str(weights), unit_env
    checked = (tmp_path / "state" / "gguf-dir").read_text(encoding="utf-8").strip()
    assert checked == str(weights / "gguf"), (checked, unit_env)


def test_a_node_still_drops_the_periodic_units(tmp_path):
    got, calls = _install(tmp_path, role="node")
    assert got.returncode == 0, got.stderr
    assert "removed com.unxmaal.localharness.discover (LH_ROLE=node)" in got.stdout
    assert not [c for c in calls if c.startswith("bootstrap") and c.endswith(".discover.plist")]


def test_a_killed_sweep_says_which_signal_killed_it(tmp_path):
    (tmp_path / "scripts").mkdir()
    shutil.copy(REPO / "scripts" / "serve-discover.sh", tmp_path / "scripts" / "serve-discover.sh")
    (tmp_path / "scripts" / "env.sh").write_text("", encoding="utf-8")
    (tmp_path / "bin").mkdir()
    uv = tmp_path / "bin" / "uv"
    uv.write_text("#!/bin/sh\nexec sleep 60\n", encoding="utf-8")
    uv.chmod(0o755)
    env = {**os.environ, "PATH": f"{tmp_path / 'bin'}{os.pathsep}{os.environ['PATH']}",
           "LOCALHARNESS_HOME": str(tmp_path / "home")}
    proc = subprocess.Popen([shells.BASH, str(tmp_path / "scripts" / "serve-discover.sh")], env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    assert proc.stdout.readline().startswith("=== sweep")
    time.sleep(0.5)
    proc.send_signal(signal.SIGTERM)
    out, err = proc.communicate(timeout=30)
    assert "sweep killed by SIGTERM" in err, err
    assert proc.returncode == 143


def _gone(pid, within=10.0):
    deadline = time.monotonic() + within
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        time.sleep(0.1)
    return False


@pytest.mark.skipif(sys.platform == "win32", reason="launchd and process groups are POSIX")
def test_a_killed_sweep_leaves_no_descendant_running(tmp_path):
    """#805: TERM reached uv only; the eval under it kept the GPU."""
    (tmp_path / "scripts").mkdir()
    shutil.copy(REPO / "scripts" / "serve-discover.sh", tmp_path / "scripts" / "serve-discover.sh")
    (tmp_path / "scripts" / "env.sh").write_text("", encoding="utf-8")
    (tmp_path / "bin").mkdir()
    pids = tmp_path / "pids"
    uv = tmp_path / "bin" / "uv"
    uv.write_text(f"#!/bin/sh\nsleep 300 &\necho $! > {pids}\nwait\n", encoding="utf-8")
    uv.chmod(0o755)
    env = {**os.environ, "PATH": f"{tmp_path / 'bin'}{os.pathsep}{os.environ['PATH']}",
           "LOCALHARNESS_HOME": str(tmp_path / "home")}
    proc = subprocess.Popen([shells.BASH, str(tmp_path / "scripts" / "serve-discover.sh")], env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    deadline = time.monotonic() + 10
    while not (pids.exists() and pids.read_text(encoding="utf-8").strip()) and time.monotonic() < deadline:
        time.sleep(0.05)
    grandchild = int(pids.read_text(encoding="utf-8"))
    proc.send_signal(signal.SIGTERM)
    _, err = proc.communicate(timeout=30)
    assert "sweep killed by SIGTERM" in err and proc.returncode == 143, err
    assert _gone(grandchild), "the sweep's grandchild outlived the TERM"


@pytest.mark.skipif(sys.platform == "win32", reason="SIGTERM to a POSIX process")
def test_a_terminated_measure_stops_the_eval_in_its_own_session(tmp_path):
    """#805: the eval runs in its own session, so only the measure step can stop it."""
    pids = tmp_path / "pid"
    child = f"import os, time; open({str(pids)!r}, 'w').write(str(os.getpid())); time.sleep(300)"
    script = ("import sys\nfrom harness.commands import measure\n"
              f"measure._run_group([sys.executable, '-c', {child!r}], None, None, 5.0)\n")
    proc = subprocess.Popen([sys.executable, "-c", script], cwd=REPO,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    deadline = time.monotonic() + 30
    while not (pids.exists() and pids.read_text(encoding="utf-8").strip()) and time.monotonic() < deadline:
        time.sleep(0.05)
    eval_pid = int(pids.read_text(encoding="utf-8"))
    proc.send_signal(signal.SIGTERM)
    _, err = proc.communicate(timeout=30)
    assert proc.returncode == 128 + signal.SIGTERM, err
    assert _gone(eval_pid), "the eval outlived its terminated measure step"


@pytest.mark.skipif(sys.platform == "win32", reason="SIGTERM to a POSIX process")
def test_a_term_that_lands_while_the_eval_spawns_still_stops_it(monkeypatch):
    """#1073: a TERM inside Popen, once the child exists, left the eval running in its own session."""
    from harness.commands import measure
    real, spawned = subprocess.Popen, []

    def popen(*a, **kw):
        spawned.append(real(*a, **kw))
        os.kill(os.getpid(), signal.SIGTERM)
        return spawned[-1]
    monkeypatch.setattr(subprocess, "Popen", popen)
    try:
        with pytest.raises(SystemExit) as got:
            measure._run_group([sys.executable, "-c", "import time; time.sleep(60)"], None, None, 5.0)
        assert got.value.code == 128 + signal.SIGTERM
        assert spawned[0].poll() is not None, "the eval outlived a TERM that landed while it spawned"
    finally:
        for proc in spawned:
            if proc.poll() is None:
                proc.kill()
                proc.wait()


@pytest.mark.skipif(sys.platform == "win32", reason="SIGTERM to a POSIX process")
def test_a_term_held_while_the_spawn_fails_is_still_a_term(monkeypatch):
    from harness.commands import measure

    def popen(*a, **kw):
        os.kill(os.getpid(), signal.SIGTERM)
        raise OSError("no such interpreter")
    monkeypatch.setattr(subprocess, "Popen", popen)
    with pytest.raises(SystemExit) as got:
        measure._run_group(["/nonexistent"], None, None, 5.0)
    assert got.value.code == 128 + signal.SIGTERM


# --- the watchdog: every role, every few minutes, dry run until enabled. #814 -------

def _generate(out, **extra):
    env = {k: v for k, v in os.environ.items() if not k.startswith("LH_WATCHDOG_") and k != "LH_ROLE"}
    proc = subprocess.run([shells.BASH, str(GEN), "generate", str(out)], capture_output=True, text=True,
                          env={**env, **extra})
    assert proc.returncode == 0, proc.stderr
    return {p.stem.rsplit(".", 1)[-1]: plistlib.loads(p.read_bytes()) for p in out.glob("*.plist")}


def test_the_watchdog_wakes_every_few_minutes_on_a_calendar(plists):
    unit = next(v for k, v in plists.items() if k.endswith(".watchdog"))
    assert unit["ProgramArguments"][1].endswith("serve-watchdog.sh")
    cal = unit["StartCalendarInterval"]
    assert [c["Minute"] for c in cal] == list(range(0, 60, 5)) and not any("Hour" in c for c in cal)
    assert "StartInterval" not in unit and unit.get("RunAtLoad") is not True


def test_a_node_keeps_the_watchdog_because_it_watches_this_machine(tmp_path):
    units = _generate(tmp_path, LH_ROLE="node", LOCALHARNESS_HOME=str(tmp_path / "home"))
    assert "watchdog" in units and "discover" not in units and "audit" not in units


def test_the_watchdog_acts_only_once_enabled_and_keeps_the_switch(tmp_path):
    home = str(tmp_path / "home")
    off = _generate(tmp_path / "off", LOCALHARNESS_HOME=home)["watchdog"]["EnvironmentVariables"]
    assert "LH_WATCHDOG_ACT" not in off and "LH_WATCHDOG_FILE" not in off
    on = _generate(tmp_path / "on", LOCALHARNESS_HOME=home, LH_WATCHDOG_ACT="1")["watchdog"]
    assert on["EnvironmentVariables"]["LH_WATCHDOG_ACT"] == "1"
    again = _generate(tmp_path / "again", LOCALHARNESS_HOME=home)
    assert again["watchdog"]["EnvironmentVariables"]["LH_WATCHDOG_ACT"] == "1"
    assert "LH_WATCHDOG_ACT" not in again["gateway"]["EnvironmentVariables"]


def test_install_does_not_kill_a_watchdog_wake_that_is_running(tmp_path):
    got, calls = _install(tmp_path, running=("watchdog",))
    assert not [c for c in calls if c.startswith("bootout") and c.endswith(".watchdog")], calls
    assert "deferred: watchdog" in got.stderr


def test_a_node_drops_the_scheduler_units_and_keeps_the_watchdog(tmp_path):
    got, calls = _install(tmp_path, role="node")
    assert got.returncode == 0, got.stderr
    assert "removed com.unxmaal.localharness.watchdog" not in got.stdout
    assert any(c.startswith("bootstrap") and c.endswith(".watchdog.plist") for c in calls)


def test_the_watchdog_script_runs_one_wake_from_its_checkout():
    text = (REPO / "scripts" / "serve-watchdog.sh").read_text(encoding="utf-8")
    assert "set -euo pipefail" in text and "uv run soh watchdog" in text


# --- install runs the copy it deployed, not the one that started. #821 -------

def test_install_reruns_as_the_deployed_script(repos):
    origin, work, deploy = repos
    _git(work, "checkout", "-q", "main")
    (work / "scripts").mkdir()
    (work / "scripts" / "launchd.sh").write_text(
        'echo "deployed copy ran: $1 reexec=$LH_REEXECED"\n', encoding="utf-8")
    _git(work, "add", "scripts")
    _git(work, "commit", "-q", "-m", "a launchd.sh that differs from this one")
    _git(work, "push", "-q", "origin", "HEAD:main")
    # Without the fix this runs a real install, so it must only ever reach fakes.
    bin_ = work.parent / "bin"
    bin_.mkdir()
    (bin_ / "launchctl").write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    (bin_ / "launchctl").chmod(0o755)
    _fake_gh(bin_)
    env = {**os.environ, "PATH": f"{bin_}{os.pathsep}{os.environ['PATH']}",
           "HOME": str(work.parent / "home"), "LOCALHARNESS_HOME": str(work.parent / "lh"),
           "LH_REPO": str(work), "LH_DEPLOY": str(deploy), "FAKE_GH_CHECK": "success",
           "LH_GPU_LOCK_HELD": "1", "LH_ROLE": "scheduler"}
    env.pop("LH_REEXECED", None)
    proc = subprocess.run([shells.BASH, str(GEN), "install"], env=conftest.live_child(env),
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    assert "deployed copy ran: install reexec=1" in proc.stdout


def test_the_rerun_cannot_loop():
    body = GEN.read_text(encoding="utf-8")
    assert 'LH_REEXECED:-}" = 1 ] && return 0' in body
