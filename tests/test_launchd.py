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
import subprocess
import sys
from pathlib import Path

import pytest

import shells

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


def test_probe_is_available_without_installing_anything():
    """The TCC verdict is the whole question, and finding it out should not
    require committing to an install first."""
    proc = subprocess.run([shells.BASH, str(GEN), "probe"],
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


def _deploy(work, deploy):
    env = {**os.environ, "LH_REPO": str(work), "LH_DEPLOY": str(deploy)}
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


def test_the_sweep_schedule_and_the_overdue_check_agree(plists):
    from harness import heartbeat
    unit = next(v for k, v in plists.items() if k.endswith(".discover"))
    hours = [t["Hour"] for t in unit["StartCalendarInterval"]]
    gaps = {(b - a) % 24 or 24 for a, b in zip(hours, hours[1:] + hours[:1])}
    assert gaps == {heartbeat.SWEEP_EVERY_S // 3600}


def test_install_audits_what_it_just_deployed():
    body = GEN.read_text(encoding="utf-8").split("install_units() {", 1)[1].split("\n}\n", 1)[0]
    assert "serve-audit.sh" in body, "a deploy is checked by `soh audit` once its units are loaded"
    assert body.index("serve-audit.sh") > body.index("launchctl bootstrap")


def test_the_audit_script_runs_soh_audit_from_its_checkout():
    text = (REPO / "scripts" / "serve-audit.sh").read_text(encoding="utf-8")
    assert "set -euo pipefail" in text and "uv run soh audit" in text


def test_install_lets_a_running_job_finish_before_reloading_the_worker():
    """#577: a reload under a running job killed it and recorded it as failed."""
    body = GEN.read_text(encoding="utf-8").split("install_units() {", 1)[1].split("\n}\n", 1)[0]
    assert "harness.workqueue quiesce" in body
    assert body.index("harness.workqueue quiesce") < body.index("launchctl bootout")
    assert "was-running" in body and "jobs resume" in body, (
        "the queue is resumed after the reload only if the owner had not paused it")
