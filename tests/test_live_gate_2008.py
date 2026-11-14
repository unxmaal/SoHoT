"""A shell script run by hand from a scratch home reaches none of the machine's units; the live home and its deploy still do. #2008."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from harness import live_gate, load_log, monitor
from tests import conftest, shells
from tests.test_sweep_guard_1000 import fake_loop, stub_main  # noqa: F401

REPO = Path(__file__).resolve().parents[1]
LAUNCHD = REPO / "scripts" / "launchd.sh"
SERVICES = REPO / "scripts" / "services.sh"
ALERT = REPO / "scripts" / "monit-alert.sh"
GATE = REPO / "harness" / "live_gate.py"
posix = pytest.mark.skipif(sys.platform == "win32", reason="a POSIX script")
RECORDER = '#!/bin/sh\necho "${0##*/} $*" >> "$FAKE_CALLS"\n'


def _recorder(bin_: Path, name: str, tail: str = "exit 0\n") -> None:
    bin_.mkdir(parents=True, exist_ok=True)
    (bin_ / name).write_text(RECORDER + tail, encoding="utf-8")
    (bin_ / name).chmod(0o755)


def _calls(tmp_path: Path) -> list[str]:
    f = tmp_path / "calls"
    return f.read_text(encoding="utf-8").splitlines() if f.exists() else []


def _run(argv, env, **kw):
    return subprocess.run(argv, env=env, capture_output=True, text=True, timeout=120, **kw)


def _scratch(tmp_path, **extra) -> dict:
    """The conftest scratch home and its refusing PATH fakes, as a script run by hand from a branch gets them."""
    return {**os.environ, "LOCALHARNESS_STORE": "sqlite", "FAKE_CALLS": str(tmp_path / "calls"), **extra}


def _effects(effect_log: Path) -> str:
    return effect_log.read_text(encoding="utf-8") if effect_log.exists() else ""


def test_the_gate_is_monitor_live_home_not_a_second_rule(monkeypatch, tmp_path):
    assert live_gate.SERVING_ENV == load_log.SERVING_ENV
    assert "is not the live home" in live_gate.refusal(tmp_path, "x")
    monkeypatch.setattr(monitor, "live_home", lambda home=None: True)
    assert live_gate.refusal(tmp_path, "x") == ""


def test_a_canary_home_serving_through_the_live_router_passes_only_when_asked(tmp_path):
    live = str(monitor.paths.DEFAULT_HOME)
    assert live_gate.refusal(tmp_path, "x", serving=live) == ""
    assert live_gate.refusal(tmp_path, "x", serving=str(tmp_path / "other"))
    assert live_gate.main([str(tmp_path), "x"], {live_gate.SERVING_ENV: live}) == live_gate.OFF
    assert live_gate.main([str(tmp_path), "x", "--serving"], {live_gate.SERVING_ENV: live}) == live_gate.LIVE


@pytest.mark.parametrize("python", [sys.executable, "/usr/bin/python3"])
def test_the_gate_runs_as_a_file_with_no_package_importable(python, tmp_path):
    """launchd.sh runs `python3 -I harness/live_gate.py`; a node's ssh PATH finds the system python3 (3.9). #1910."""
    if not Path(python).exists():
        pytest.skip(f"no {python}")
    flags = ["-I", "-S"] if python == sys.executable else ["-I"]
    user = tmp_path / "user"
    (user / "localharness").mkdir(parents=True)
    env = {"HOME": str(user), "PATH": "/usr/bin:/bin"}
    off = _run([python, *flags, str(GATE), str(tmp_path / "scratch"), "launchd.sh restart"], env, cwd=tmp_path)
    assert off.returncode == live_gate.OFF, off.stderr
    assert "is not the live home" in off.stderr and "launchd.sh restart" in off.stderr
    on = _run([python, *flags, str(GATE), str(user / "localharness"), "launchd.sh restart"], env, cwd=tmp_path)
    assert on.returncode == live_gate.LIVE, on.stderr


@posix
@pytest.mark.parametrize("verb", [["restart", "gateway"], ["install"], ["uninstall"]])
def test_launchd_sh_from_a_scratch_home_is_refused_before_any_launchctl(verb, tmp_path, _no_real_effect_in_children):
    got = _run([shells.BASH, str(LAUNCHD), *verb], _scratch(tmp_path))
    assert got.returncode == 1, got.stdout + got.stderr
    assert "is not the live home" in got.stderr and f"launchd.sh {verb[0]}" in got.stderr, got.stderr
    assert _effects(_no_real_effect_in_children) == "", "not even a launchctl print"


@posix
def test_reinstall_from_a_scratch_home_is_refused(tmp_path, _home, _no_real_effect_in_children):
    (_home / "install.env").write_text(f"PATH=/usr/bin:/bin\nHF_HOME={tmp_path}\n", encoding="utf-8")
    got = _run([shells.BASH, str(LAUNCHD), "reinstall"], _scratch(tmp_path))
    assert got.returncode == 1 and "launchd.sh reinstall" in got.stderr, got.stderr
    assert _effects(_no_real_effect_in_children) == ""


@posix
def test_generate_into_launch_agents_from_a_scratch_home_is_refused_and_elsewhere_is_not(tmp_path):
    user = tmp_path / "user"
    agents = user / "Library" / "LaunchAgents"
    agents.mkdir(parents=True)
    env = _scratch(tmp_path, HOME=str(user))
    got = _run([shells.BASH, str(LAUNCHD), "generate", str(agents)], env)
    assert got.returncode == 1 and "generate into" in got.stderr, got.stderr
    assert list(agents.iterdir()) == []
    own = tmp_path / "plists"
    own.mkdir()
    got = _run([shells.BASH, str(LAUNCHD), "generate", str(own)], env)
    assert got.returncode == 0, got.stderr
    assert list(own.glob("com.unxmaal.localharness.*.plist"))


@posix
def test_restart_from_the_live_home_with_no_localharness_home_set_reaches_launchctl(tmp_path):
    """The deploy's and a node's shape: LOCALHARNESS_HOME unset, the home is $HOME/localharness."""
    bin_ = tmp_path / "bin"
    _recorder(bin_, "launchctl", "exit 1\n")
    env = conftest.live_child(_scratch(tmp_path, PATH=f"{bin_}{os.pathsep}{os.environ['PATH']}"), tmp_path / "user")
    env.pop("LOCALHARNESS_HOME")
    got = _run([shells.BASH, str(LAUNCHD), "restart", "gateway"], env)
    assert got.returncode == 0, got.stderr
    assert _calls(tmp_path) == [f"launchctl print gui/{os.getuid()}/com.unxmaal.localharness.gateway"]


@posix
def test_restart_from_a_canary_home_that_serves_through_the_live_router_still_restarts_it(tmp_path):
    bin_ = tmp_path / "bin"
    _recorder(bin_, "launchctl", "exit 1\n")
    user = tmp_path / "user"
    (user / "localharness").mkdir(parents=True)
    env = _scratch(tmp_path, PATH=f"{bin_}{os.pathsep}{os.environ['PATH']}", HOME=str(user),
                   **{load_log.SERVING_ENV: str(user / "localharness")})
    got = _run([shells.BASH, str(LAUNCHD), "restart", "eval"], env)
    assert got.returncode == 0, got.stderr
    assert [c.split()[:2] for c in _calls(tmp_path)] == [["launchctl", "print"]]


@posix
@pytest.mark.parametrize("verb, held", [("install", "1"), ("reinstall", None)])
def test_install_and_reinstall_on_the_live_home_pass_the_gate(verb, held, stub_main, fake_loop, tmp_path):  # noqa: F811
    """They go on to the sweep guard, which a running loop stops, so nothing past the gate acts here."""
    (work, bin_), (pid, home) = stub_main, fake_loop
    (home / "install.env").write_text(f"PATH={os.environ['PATH']}\nHF_HOME={tmp_path}\n", encoding="utf-8")
    env = {**os.environ, "PATH": f"{bin_}{os.pathsep}{os.environ['PATH']}", "LOCALHARNESS_HOME": str(home),
           "LH_REPO": str(work), "LH_DEPLOY": str(tmp_path / "deploy"), "LH_ROLE": "scheduler"}
    env = conftest.live_child(env, tmp_path / "user")
    env.pop("LOCALHARNESS_HOME")
    for k in ("LH_REEXECED", "LH_DEPLOY_UNCHECKED", "LH_DEPLOY_DURING_SWEEP", "LH_GPU_LOCK_HELD"):
        env.pop(k, None)
    if held:
        env["LH_GPU_LOCK_HELD"] = held
    got = _run([shells.BASH, str(LAUNCHD), verb], env)
    assert "is not the live home" not in got.stderr, got.stderr
    assert f"REFUSING to deploy: discover loop (pid {pid}" in got.stderr, got.stderr


@posix
def test_probe_from_a_scratch_home_touches_only_its_own_per_run_label(tmp_path):
    bin_ = tmp_path / "bin"
    _recorder(bin_, "launchctl")
    env = _scratch(tmp_path, PATH=f"{bin_}{os.pathsep}{os.environ['PATH']}", PREFLIGHT_WAIT_S="0")
    _run([shells.BASH, str(LAUNCHD), "probe"], env)
    labels = {c.split()[-1] for c in _calls(tmp_path)}
    own = r"(com\.unxmaal\.localharness\.preflight|localharness-preflight)\.\d+(\.plist)?$"
    assert labels and all(re.search(own, x) for x in labels), labels


@pytest.mark.skipif(sys.platform != "darwin", reason="lan-probe.sh is macOS only")
def test_lan_probe_from_a_scratch_home_submits_only_its_own_per_run_label(tmp_path):
    bin_ = tmp_path / "bin"
    _recorder(bin_, "launchctl")
    _recorder(bin_, "uv", '[ "$4 $5" = "harness.lanprobe targets" ] && echo "n1 127.0.0.1 9 0 1"\nexit 0\n')
    env = _scratch(tmp_path, PATH=f"{bin_}{os.pathsep}{os.environ['PATH']}", LAN_PROBE_PYTHON=sys.executable,
                   LAN_PROBE_WAIT_EXTRA_S="0")
    _run([shells.BASH, str(REPO / "scripts" / "lan-probe.sh")], env, cwd=REPO)
    acts = [c for c in _calls(tmp_path) if c.startswith("launchctl")]
    assert [c.split()[1] for c in acts] == ["submit", "remove"], acts
    assert all(re.search(r"com\.unxmaal\.localharness\.lanprobe\.\d+\.n1", c) for c in acts), acts


@posix
@pytest.mark.parametrize("verb", ["install-node", "uninstall-node"])
def test_a_windows_node_task_from_a_scratch_home_is_refused(verb, tmp_path):
    bin_ = tmp_path / "bin"
    _recorder(bin_, "powershell")
    env = _scratch(tmp_path, PATH=f"{bin_}{os.pathsep}{os.environ['PATH']}", OS="Windows_NT")
    got = _run([shells.BASH, str(SERVICES), verb], env)
    assert got.returncode == 1 and f"services.sh {verb}" in got.stderr, got.stderr
    assert _calls(tmp_path) == []


@posix
def test_a_windows_node_task_from_the_live_home_passes_the_gate(tmp_path):
    bin_ = tmp_path / "bin"
    _recorder(bin_, "powershell")
    env = conftest.live_child(_scratch(tmp_path, PATH=f"{bin_}{os.pathsep}{os.environ['PATH']}", OS="Windows_NT"),
                              tmp_path / "user")
    env.pop("LLAMACPP_API_KEY_FILE", None)
    got = _run([shells.BASH, str(SERVICES), "install-node"], env)
    assert "set LLAMACPP_API_KEY_FILE first" in got.stderr, got.stderr
    got = _run([shells.BASH, str(SERVICES), "uninstall-node"], env)
    assert [c.split()[0] for c in _calls(tmp_path)] == ["powershell"], got.stderr


@posix
def test_services_sh_stop_from_a_scratch_home_leaves_what_the_live_home_started(tmp_path, _home):
    """Home-scoped: stop reads this home's run/<name>.pid, so another home's servers are out of its reach."""
    live = tmp_path / "user" / "localharness"
    (live / "run").mkdir(parents=True)
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        (live / "run" / "gateway.pid").write_text(f"{child.pid}\n", encoding="utf-8")
        got = _run([shells.BASH, str(SERVICES), "stop", "gateway"], _scratch(tmp_path, HOME=str(tmp_path / "user")))
        assert got.returncode == 0 and "gateway not running" in got.stdout, got.stdout + got.stderr
        assert child.poll() is None
        assert (live / "run" / "gateway.pid").exists()
    finally:
        child.kill()
        child.wait()


def _alert_env(tmp_path, live: bool) -> dict:
    bin_ = tmp_path / "bin"
    _recorder(bin_, "uv", "exit 1\n")
    _recorder(bin_, "osascript")
    env = _scratch(tmp_path, PATH=f"{bin_}{os.pathsep}{os.environ['PATH']}", MONIT_SERVICE="disk")
    return conftest.live_child(env, tmp_path / "user") if live else env


@posix
def test_monit_alert_from_a_scratch_home_puts_no_fallback_notice_on_the_desktop(tmp_path, _home):
    got = _run([shells.BASH, str(ALERT), "disk"], _alert_env(tmp_path, live=False))
    assert got.returncode == 1
    assert [c.split()[0] for c in _calls(tmp_path)] == ["uv"]
    assert "is not the live home" in (_home / "logs" / "monit-alert.log").read_text(encoding="utf-8")


@posix
def test_monit_alert_on_the_live_home_still_falls_back_to_a_notice(tmp_path):
    got = _run([shells.BASH, str(ALERT), "disk"], _alert_env(tmp_path, live=True))
    assert got.returncode == 1
    assert [c.split()[0] for c in _calls(tmp_path)] == ["uv", "osascript"]


@posix
def test_monit_alert_still_notifies_when_the_gate_cannot_run(tmp_path):
    """The fallback exists for when Python fails; only a home known not to be live is kept off the desktop."""
    env = _alert_env(tmp_path, live=False)
    shutil.copytree(REPO / "scripts", tmp_path / "repo" / "scripts")
    (tmp_path / "repo" / "harness").mkdir()
    _run([shells.BASH, str(tmp_path / "repo" / "scripts" / "monit-alert.sh"), "disk"], env)
    assert [c.split()[0] for c in _calls(tmp_path)] == ["uv", "osascript"]
