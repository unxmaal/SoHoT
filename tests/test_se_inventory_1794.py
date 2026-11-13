"""Gauntlet SE (#1748) mediums and lows: no notice, effect binary or signal leaves a test or a scratch home. #1794."""
import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path

import pytest

from harness import claude_news, monitor, morning, paths, sweep_check, watchdog_hands, workqueue
from harness import watchdog as wd
from tests import conftest, shells

REPO = Path(__file__).resolve().parents[1]
posix = pytest.mark.skipif(sys.platform == "win32", reason="the PATH fakes are sh scripts")


def _finding():
    return wd.Finding("overrun", wd.Subject("eval", "eval pgid 1", "test"), {"x": 1})


NOTICES = {
    "watchdog": lambda: watchdog_hands.Hands(platform="darwin").do(wd.NOTIFY, _finding()),
    "morning": lambda: morning.notify({"needs": ["watchdog stop: overrun on eval pgid 2"]}, "brief",
                                      platform="darwin"),
    "claude-news": lambda: claude_news.notify({"relevant": [{"text": "Added a hook"}], "latest": "2.1.302"}),
}


def _scratch(tmp_path, monkeypatch) -> Path:
    """A scratch home as paths.eval_home makes one when no home was named."""
    monkeypatch.delenv(paths.ENV_VAR)
    return paths.eval_home(tmp_path / "scratch")


@pytest.fixture(params=["test home", "scratch home"])
def not_live(request, tmp_path, monkeypatch):
    if request.param == "scratch home":
        _scratch(tmp_path, monkeypatch)
    assert not monitor.live_home()
    return paths.home()


@pytest.mark.parametrize("who", sorted(NOTICES))
def test_a_desktop_notice_from_a_test_or_scratch_home_is_not_shown(who, not_live, _no_real_notifier):
    got = NOTICES[who]()
    assert _no_real_notifier == []
    assert got.startswith("notify not sent: ") and str(not_live) in got and got.result == wd.UNAVAILABLE


@pytest.mark.parametrize("who", sorted(NOTICES))
def test_the_same_notice_from_the_live_home_is_shown_once(who, shown_live, _no_real_notifier):
    NOTICES[who]()
    assert [s[0] for s in _no_real_notifier] == ["desktop"]


@posix
def test_a_child_finds_a_refusing_fake_first_for_every_effect_binary(tmp_path_factory):
    fakes = conftest.effect_fakes(tmp_path_factory.getbasetemp())
    for name in conftest.EFFECT_BINARIES:
        found = subprocess.run([shells.resolve("bash"), "-c", f"type -P {name}"], capture_output=True, text=True,
                               timeout=30).stdout.strip()
        assert Path(found).parent.resolve() == fakes.resolve(), (name, found)


@posix
def test_a_scratch_release_whose_soh_fails_reaches_only_the_fake_osascript(tmp_path, _no_real_effect_in_children):
    release = tmp_path / "release"
    (release / "scripts").mkdir(parents=True)
    shutil.copy(REPO / "scripts" / "monit-alert.sh", release / "scripts" / "monit-alert.sh")
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    (bin_ / "uv").write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    (bin_ / "uv").chmod(0o755)
    env = {**os.environ, "PATH": f"{bin_}{os.pathsep}{os.environ['PATH']}", "MONIT_SERVICE": "system_data"}
    got = subprocess.run([shells.resolve("bash"), str(release / "scripts" / "monit-alert.sh"), "disk"], env=env,
                         capture_output=True, text=True, timeout=60)
    log = _no_real_effect_in_children
    reached = log.read_text(encoding="utf-8") if log.exists() else ""
    log.unlink(missing_ok=True)
    assert got.returncode == 1
    assert reached.startswith("osascript -e on run argv") and "system_data" in reached


def _real_path(monkeypatch, tmp_path_factory):
    """PATH as the developer has it, without the suite's refusing fakes, so only the Popen guard stands in the way."""
    fakes = str(conftest.effect_fakes(tmp_path_factory.getbasetemp()))
    monkeypatch.setenv("PATH", os.pathsep.join(p for p in os.environ["PATH"].split(os.pathsep) if p != fakes))


HARMLESS = {"launchctl": ["version"], "ssh": ["-V"], "gh": ["--version"], "docker": ["--version"], "kill": ["-l"],
            "osascript": ["-e", "return 1"], "terminal-notifier": ["-help"]}


@pytest.mark.parametrize("name", conftest.EFFECT_BINARIES)
def test_the_suite_refuses_each_effect_binary_a_test_runs_itself(name, monkeypatch, tmp_path_factory):
    _real_path(monkeypatch, tmp_path_factory)
    if not shutil.which(name):
        pytest.skip(f"no {name} here, so nothing real could run")
    refused = subprocess.Popen.refused
    with pytest.raises(FileNotFoundError, match="effect binary refused under test"):
        subprocess.run([name, *HARMLESS[name]], capture_output=True, timeout=30)
    assert refused == [[name, *HARMLESS[name]][:4]]
    refused.clear()


def test_a_hook_bound_at_import_still_meets_the_refusal(monkeypatch, tmp_path_factory):
    _real_path(monkeypatch, tmp_path_factory)
    got = sweep_check.launchd(platform="darwin", uid=501)
    assert got["loaded"] is None and "refused under test" in got["why"]
    assert subprocess.Popen.refused[0][:2] == ["launchctl", "print"]
    subprocess.Popen.refused.clear()


#: SIGCONT to a running process does nothing, so a broken guard here harms no one.
OLDER = {"kill": lambda: 1, "killpg": lambda: os.getpgrp()}


@pytest.mark.skipif(sys.platform == "win32", reason="SIGCONT and process groups are POSIX")
@pytest.mark.parametrize("how", sorted(OLDER))
def test_a_signal_to_a_process_the_test_did_not_start_is_refused(how, _no_real_signal):
    pid = OLDER[how]()
    with pytest.raises(PermissionError):
        getattr(os, how)(pid, signal.SIGCONT)
    assert _no_real_signal == [(how, pid, signal.SIGCONT)]
    _no_real_signal.clear()


@pytest.mark.skipif(sys.platform == "win32", reason="SIGTERM delivery is POSIX")
def test_a_test_signals_its_own_child_and_probes_any_pid(_no_real_signal):
    os.kill(os.getppid(), 0)
    mine = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"], start_new_session=True)
    os.killpg(mine.pid, signal.SIGTERM)
    assert mine.wait(timeout=30) == -signal.SIGTERM and _no_real_signal == []


def test_a_disk_pause_from_a_scratch_home_pauses_only_the_scratch_queue(tmp_path, monkeypatch, _no_real_notifier):
    live = tmp_path / "live"
    monkeypatch.setattr(paths, "DEFAULT_HOME", live)
    _scratch(tmp_path, monkeypatch)
    got = monitor.alert("disk-pause", {"MONIT_SERVICE": "system_data"}, measure=lambda: [])
    assert got["paused"]["queue"] == "paused" and workqueue.paused()
    assert workqueue.root().is_relative_to(tmp_path / "scratch")
    assert not (live / "queue").exists() and _no_real_notifier == []
