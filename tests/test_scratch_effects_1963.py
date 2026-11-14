"""SE-4's non-test side: a scratch home reaches no machine-wide effect, reads stay open, the live home still acts. #1963."""
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from harness import (engine_trials, gateway_switch, github, gguf, heartbeat, monitor, node_deploy, paths, privacy,
                     publish, queue_pause, review, store_service, sweep_check, volume, watchdog_hands)
from harness import nodes as nodes_mod
from harness import watchdog as wd
from tests import conftest
from tests.gauntlet import registry

NOT_LIVE = "is not the live home"
#: conftest's _no_real_services stubs it for every test; this file tests the real one.
REFRESH_ROUTER = gguf.refresh_router
posix = pytest.mark.skipif(sys.platform == "win32", reason="the PATH fakes are sh scripts")


def _reached(log: Path) -> str:
    """What the suite's refusing PATH fakes were asked to run, cleared once read."""
    got = log.read_text(encoding="utf-8") if log.exists() else ""
    log.unlink(missing_ok=True)
    return got


@pytest.fixture
def scratch(tmp_path, monkeypatch, _no_real_effect_in_children):
    """paths.eval_home(scratch) as a hand run makes it, with nothing the suite or the effect fakes recorded yet."""
    monkeypatch.delenv(paths.ENV_VAR)
    home = paths.eval_home(tmp_path / "scratch")
    assert not monitor.live_home()
    subprocess.Popen.refused.clear()
    yield home
    assert _reached(_no_real_effect_in_children) == ""


@pytest.fixture
def log(_no_real_effect_in_children):
    return _no_real_effect_in_children


def _nothing_spawned(log: Path | None = None):
    assert subprocess.Popen.refused == [], subprocess.Popen.refused
    assert log is None or _reached(log) == ""


def _finding(service: str = "none"):
    """A finding each act refuses on its own merits too, so a broken gate fails the test and touches nothing."""
    return wd.Finding("memory_warn", wd.Subject("service", f"service {service}", "test",
                                                detail={"service": service}), {"idle": []})


@pytest.mark.parametrize("action", sorted(watchdog_hands.MACHINE_ACTS))
def test_the_watchdog_acts_on_nothing_from_a_scratch_home(action, scratch, log, monkeypatch):
    monkeypatch.setenv(wd.FILE_ENV, "1")
    got = watchdog_hands.Hands(platform="darwin").do(action, _finding())
    assert got.result == wd.REFUSED and NOT_LIVE in got and f"the watchdog's {action}" in got, got
    _nothing_spawned(log)


def test_the_watchdog_only_notes_from_a_scratch_home(scratch):
    assert watchdog_hands.Hands().do("note", _finding()) == "noted"


def test_the_live_home_s_watchdog_still_restarts(shown_live):
    seen = []
    got = watchdog_hands.Hands(run=lambda argv, **kw: seen.append(argv) or subprocess.CompletedProcess(argv, 0),
                               platform="darwin").do("restart", _finding("mlx"))
    assert got == "restarted mlx" and seen[0][:3] == ["launchctl", "kickstart", "-k"]


def test_volume_stop_and_start_refuse_from_a_scratch_home(scratch, log, tmp_path):
    with pytest.raises(volume.VolumeError, match=NOT_LIVE):
        volume.stop(str(tmp_path), volume.Ops())
    with pytest.raises(volume.VolumeError, match=NOT_LIVE):
        volume.start(volume.Ops())
    assert not volume.state_path().exists()
    _nothing_spawned(log)


def test_monitor_install_refuses_from_a_scratch_home(scratch, log):
    with pytest.raises(monitor.InstallError, match=NOT_LIVE):
        monitor.install(platform="darwin", which=lambda name: None)
    _nothing_spawned(log)


def test_a_router_refresh_from_a_scratch_home_restarts_nothing(scratch, log, capsys):
    why = REFRESH_ROUTER(expect=("stem",))
    assert NOT_LIVE in why and "eval router" in why and NOT_LIVE in capsys.readouterr().err
    _nothing_spawned(log)


@pytest.mark.parametrize("serving, restarts", [("live", True), ("other", False)])
def test_the_canary_s_isolated_home_restarts_the_router_it_screens_through(serving, restarts, scratch, monkeypatch):
    from harness import load_log
    monkeypatch.setenv(load_log.SERVING_ENV, str(paths.DEFAULT_HOME if serving == "live" else scratch))
    ran = []
    why = REFRESH_ROUTER(expect=("stem",), run=lambda argv, **kw: ran.append(argv), wait=lambda expect: "")
    assert bool(ran) is restarts and (why == "") is restarts
    assert not ran or ran[0] == gguf.router_restart_argv(sys.platform)


def test_a_gateway_switch_from_a_scratch_home_starts_nothing(scratch, log, monkeypatch, capsys):
    monkeypatch.setattr(gateway_switch, "RESTARTERS", {sys.platform: lambda: pytest.fail("restarted the gateway")})
    assert gateway_switch.spawn(popen=lambda *a, **k: pytest.fail("started a switch")) is None
    assert NOT_LIVE in capsys.readouterr().err
    with pytest.raises(RuntimeError, match=NOT_LIVE):
        gateway_switch.restart_service()
    _nothing_spawned(log)


def _node():
    return nodes_mod.Node("n1", "http://node.invalid:8083/v1", "llamacpp", ("m",), ssh="someone@node.invalid")


@posix
def test_a_node_install_over_ssh_refuses_from_a_scratch_home_and_a_read_still_goes(scratch, log):
    rc, why = node_deploy._ssh(node_deploy.ssh_argv(_node(), "install", "", "a" * 40, "scheduler"),
                               node_deploy.SCRIPT, 5)
    assert rc is None and NOT_LIVE in why
    _nothing_spawned(log)
    rc, said = node_deploy._ssh(node_deploy.ssh_argv(_node(), "state", ""), node_deploy.SCRIPT, 5)
    assert rc == 127 and "refused under test" in said
    assert _reached(log).startswith("ssh -o BatchMode=yes")


def test_a_node_deploy_from_a_scratch_home_deploys_no_node(scratch, log, monkeypatch):
    monkeypatch.setattr(node_deploy, "target", lambda conn=None: {"id": 7, "sha": "a" * 40})
    got = node_deploy.follow(load=lambda: [_node()])
    assert got["nodes"] == {} and NOT_LIVE in got["why"] and "node deploy" in got["why"]
    _nothing_spawned(log)


class _Secret:
    def get(self):
        return "pw"

    def set(self, value):
        raise AssertionError("a scratch home stores no store password")


def test_the_store_container_is_not_started_stopped_or_restored_from_a_scratch_home(scratch, log, tmp_path):
    for action in (["up", "-d", "--wait"], ["stop"], ["down"]):
        got = store_service.compose(action, secret=_Secret())
        assert got.returncode == 1 and NOT_LIVE in got.stderr and store_service.CONTAINER in got.stderr
    dump = tmp_path / "x.dump"
    dump.write_bytes(store_service.DUMP_MAGIC)
    with pytest.raises(RuntimeError, match=NOT_LIVE):
        store_service.restore(dump)
    with pytest.raises(RuntimeError, match=NOT_LIVE):
        store_service.ensure_volume()
    _nothing_spawned(log)


@posix
def test_the_store_container_s_status_is_still_read_from_a_scratch_home(scratch, log):
    assert store_service.compose(["ps", "--format", "json"], secret=_Secret()).returncode == 127
    assert _reached(log).startswith("docker compose -f")


@pytest.mark.parametrize("argv, writes", [
    (["issue", "create", "--title", "t"], True), (["pr", "comment", "7", "--body", "b"], True),
    (["run", "rerun", "1"], True), (["label", "create", "x"], True), (["workflow", "run", "ci.yml"], True),
    (["issue", "list", "--state", "open"], False), (["run", "list"], False), (["pr", "view", "7"], False),
    (["api", "repos/o/r/contents/x"], False), (["api", "repos/o/r/git/blobs", "-X", "POST"], True),
    (["api", "repos/o/r", "--method=PATCH"], True), (["api", "repos/o/r/issues", "-f", "title=x"], True),
    (["api", "search/issues", "-X", "GET", "-f", "q=x"], False), (["api", "repos/o/r", "--input", "-"], True),
    (["api", "graphql", "-f", "query={ viewer { login } }"], False),
    (["api", "graphql", "-f", "query=mutation { addStar }"], True),
])
def test_a_gh_argv_is_a_write_when_it_would_change_github(argv, writes):
    assert github.writes(argv) is writes


@posix
@pytest.mark.parametrize("gh_run", [review.gh_run, engine_trials.gh_run], ids=["review", "engine_trials"])
def test_a_filing_from_a_scratch_home_writes_no_issue_and_reads_still_go(gh_run, scratch, log):
    got = gh_run(["issue", "create", "--title", "t", "--body", "b"])
    assert got.returncode == 1 and NOT_LIVE in got.stderr
    _nothing_spawned(log)
    got = gh_run(["issue", "list", "--label", "x"])
    assert got.returncode == 127 and "refused under test" in got.stderr
    assert _reached(log).startswith("gh issue list --label x")


@posix
def test_a_publish_from_a_scratch_home_pushes_nothing(scratch, log):
    with pytest.raises(publish.GhError, match=NOT_LIVE):
        publish._gh(["repos/o/r/git/blobs", "-X", "POST"], {"content": "x"})
    with pytest.raises(publish.GhError, match=NOT_LIVE):
        publish._gh(["repos/o/r/contents/x"], {"message": "m"})
    _nothing_spawned(log)
    with pytest.raises(publish.GhError, match="refused under test"):
        publish._gh(["repos/o/r/contents/x"])
    assert _reached(log).startswith("gh api repos/o/r/contents/x")


def test_a_scanned_post_from_a_scratch_home_sends_nothing(scratch, log, capsys):
    assert privacy.post(["issue", "create", "--title", "t", "--body", "clean text"]) == 1
    err = capsys.readouterr().err
    assert NOT_LIVE in err and str(scratch / privacy.HOME_NAMES_FILE) in err and "nothing was sent" in err
    _nothing_spawned(log)


@posix
def test_a_read_only_launchctl_print_still_runs_from_a_scratch_home(scratch, log):
    sweep_check.launchd(platform="darwin", uid=501)
    assert _reached(log).startswith("launchctl print gui/501/")


@pytest.mark.skipif(sys.platform == "win32", reason="SIGCONT and the loop's process are POSIX")
def test_a_deploy_hold_from_a_scratch_home_signals_only_its_own_loop(tmp_path, monkeypatch):
    live = tmp_path / "live"
    live.mkdir()
    monkeypatch.setattr(paths, "DEFAULT_HOME", live)
    monkeypatch.setenv(paths.ENV_VAR, str(live))
    loop = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)", "discover", "--loop"],
                            start_new_session=True)
    sent = []
    real = os.kill
    monkeypatch.setattr(os, "kill", lambda pid, sig: sent.append((pid, sig)) if sig else real(pid, sig))
    try:
        beat = {"state": heartbeat.RUNNING, "pid": loop.pid, "started": time.time(), heartbeat.YIELDS: True}
        heartbeat.path().write_text(json.dumps(beat), encoding="utf-8")
        assert heartbeat.path().is_relative_to(live)
        monkeypatch.delenv(paths.ENV_VAR)
        paths.eval_home(tmp_path / "scratch")
        assert queue_pause._ask_loop(signal.SIGCONT, lambda pid: []) == [] and sent == []
        monkeypatch.setenv(paths.ENV_VAR, str(live))
        queue_pause._ask_loop(signal.SIGCONT, lambda pid: [])
        assert sent == [(loop.pid, signal.SIGCONT)]
    finally:
        real(loop.pid, signal.SIGKILL)
        loop.wait(timeout=30)


def test_the_gauntlet_counts_every_binary_the_test_guard_refuses_as_guarded():
    guarded = registry.DETECTOR_CONFIG["effect_reachable"]["guarded"]
    assert sorted(guarded) == sorted(conftest.EFFECT_BINARIES)


def test_a_scratch_home_s_refusal_names_the_home_and_the_live_one(scratch):
    said = monitor.off_live("restarting x")
    assert said.startswith(f"refused: {scratch} {NOT_LIVE} {paths.DEFAULT_HOME}") and "restarting x" in said
