"""A launchd reinstall renders the units from the owner's recorded install, never from launchd's empty environment. #1518."""
from __future__ import annotations

import plistlib
import subprocess
import sys
from pathlib import Path

import pytest

import shells
from harness import deploy_switch, engine_smoke, install_env, monitor

REPO = Path(__file__).resolve().parents[1]
GEN = REPO / "scripts" / "launchd.sh"
darwin = pytest.mark.skipif(sys.platform != "darwin", reason="launchd is macOS-only")


def _fakes(tmp_path):
    from tests.test_launchd import FAKE_LAUNCHCTL_794
    fakes, marked = tmp_path / "fakes", tmp_path / "marked"
    for d in (fakes, marked):
        d.mkdir()
    (fakes / "launchctl").write_text(FAKE_LAUNCHCTL_794, encoding="utf-8")
    (marked / "uv").write_text(f'#!/bin/sh\necho "$*" >> "{tmp_path}/uv-ran"\nexit 0\n', encoding="utf-8")
    for p in (fakes / "launchctl", marked / "uv"):
        p.chmod(0o755)
    return fakes, marked


def _tree(tmp_path, mode: str):
    """launchd.sh up to its dispatch, sourced with MODE, with deploy, re-exec and the launchd probe stubbed."""
    root, deploy, state = tmp_path / "repo", tmp_path / "deploy", tmp_path / "state"
    for d in (root / "scripts", deploy / "scripts", state):
        d.mkdir(parents=True, exist_ok=True)
    text = GEN.read_text(encoding="utf-8")
    (root / "scripts" / "lib.sh").write_text(text[:text.index('case "${1:-}" in')], encoding="utf-8")
    (root / "scripts" / "env.sh").write_text((REPO / "scripts" / "env.sh").read_text(encoding="utf-8"),
                                             encoding="utf-8")
    (root / "scripts" / "run.sh").write_text(
        f'source "$(dirname "$0")/lib.sh" {mode}\ndeploy() {{ :; }}\n_run_deployed() {{ :; }}\npreflight() {{ :; }}\n'
        f'install_units {mode if mode == "reinstall" else ""}\n', encoding="utf-8")
    for name in ("lan-probe.sh", "serve-audit.sh"):
        (deploy / "scripts" / name).write_text("exit 0\n", encoding="utf-8")
    return root, deploy, state


def _run(tmp_path, mode: str, env: dict):
    root, deploy, state = _tree(tmp_path, mode)
    fakes, _ = _fakes(tmp_path) if not (tmp_path / "fakes").exists() else (tmp_path / "fakes", tmp_path / "marked")
    # Only what a launchd one-shot gets: no profile, so no HF_HOME and no LH_* flags. Fakes first, always (RULE #704).
    base = {"HOME": str(tmp_path / "home"), "LOCALHARNESS_HOME": str(tmp_path / "lh"), "LH_DEPLOY": str(deploy),
            "FAKE_STATE": str(state), "PATH": f"{fakes}:/usr/bin:/bin"}
    got = subprocess.run([shells.BASH, str(root / "scripts" / "run.sh")], env={**base, **env}, capture_output=True,
                         text=True, encoding="utf-8", timeout=120)
    agents = tmp_path / "home" / "Library" / "LaunchAgents"
    units = {p.stem.rsplit(".", 1)[-1]: plistlib.loads(p.read_bytes()) for p in agents.glob("*.plist")}
    return got, units


def _record(tmp_path, **values) -> Path:
    lh = tmp_path / "lh"
    lh.mkdir(exist_ok=True)
    p = lh / deploy_switch.INSTALL_ENV
    p.write_text("# test\n" + "".join(f"{k}={v}\n" for k, v in values.items()), encoding="utf-8")
    return p


@darwin
def test_reinstall_with_an_empty_environment_renders_the_recorded_weights_and_flags(tmp_path):
    fakes, marked = _fakes(tmp_path)
    weights = tmp_path / "weights"
    weights.mkdir()
    _record(tmp_path, HF_HOME=weights, HF_MIN_FREE_GB=0, PATH=f"{fakes}:{marked}:/usr/bin:/bin",
            LH_DAY_FETCH=1, LH_WATCHDOG_ACT=1, FETCH_HOURS=9)
    got, units = _run(tmp_path, "reinstall", {})
    assert got.returncode == 0, got.stdout + got.stderr
    assert units and set(units) == set(install_env.services())
    for name, unit in units.items():
        env = unit["EnvironmentVariables"]
        assert (env.get("HF_HOME"), env.get("HF_ROOT")) == (str(weights), str(weights)), name
    assert units["fetch"]["EnvironmentVariables"]["LH_DAY_FETCH"] == "1"
    assert [d["Hour"] for d in units["fetch"]["StartCalendarInterval"]] == [9]
    assert units["watchdog"]["EnvironmentVariables"]["LH_WATCHDOG_ACT"] == "1"
    assert (tmp_path / "uv-ran").exists(), "uv is found only on the recorded PATH"


@darwin
def test_reinstall_ignores_what_its_caller_says(tmp_path):
    fakes, marked = _fakes(tmp_path)
    weights, wrong = tmp_path / "weights", tmp_path / "release" / "hf_root"
    for d in (weights, wrong):
        d.mkdir(parents=True)
    _record(tmp_path, HF_HOME=weights, HF_MIN_FREE_GB=0, PATH=f"{fakes}:{marked}:/usr/bin:/bin")
    got, units = _run(tmp_path, "reinstall", {"HF_HOME": str(wrong), "HF_ROOT": str(wrong), "LH_DAY_FETCH": "1"})
    assert got.returncode == 0, got.stdout + got.stderr
    assert {u["EnvironmentVariables"]["HF_HOME"] for u in units.values()} == {str(weights)}
    assert "LH_DAY_FETCH" not in units["fetch"]["EnvironmentVariables"]


@darwin
def test_reinstall_refuses_when_nothing_is_recorded(tmp_path):
    got, units = _run(tmp_path, "reinstall", {})
    assert got.returncode == 1
    assert "no recorded install environment" in got.stderr and "launchd.sh install" in got.stderr
    assert units == {} and not (tmp_path / "state" / "log").exists()


@darwin
def test_reinstall_refuses_a_recorded_weights_location_it_cannot_read(tmp_path):
    fakes, marked = _fakes(tmp_path)
    _record(tmp_path, HF_HOME=tmp_path / "unplugged" / "hf", PATH=f"{fakes}:{marked}:/usr/bin:/bin")
    got, units = _run(tmp_path, "reinstall", {})
    assert got.returncode == 1 and "cannot be read" in got.stderr and "will not fall back" in got.stderr
    assert units == {} and not (tmp_path / "state" / "log").exists()


@darwin
def test_a_manual_install_records_what_it_read_and_a_later_one_keeps_it(tmp_path):
    fakes, marked = _fakes(tmp_path)
    weights = tmp_path / "weights"
    weights.mkdir()
    path = f"{fakes}:{marked}:/usr/bin:/bin"
    got, _ = _run(tmp_path, "install", {"HF_HOME": str(weights), "HF_MIN_FREE_GB": "0", "LH_DAY_FETCH": "1",
                                        "PATH": path})
    assert got.returncode == 0, got.stdout + got.stderr
    rec = install_env.read(tmp_path / "lh" / deploy_switch.INSTALL_ENV)
    assert rec == {"HF_HOME": str(weights), "HF_MIN_FREE_GB": "0", "PATH": path, "LH_DAY_FETCH": "1"}
    got, units = _run(tmp_path, "install", {"PATH": path})
    assert got.returncode == 0, got.stdout + got.stderr
    assert install_env.read(tmp_path / "lh" / deploy_switch.INSTALL_ENV) == rec
    assert units["mlx"]["EnvironmentVariables"]["HF_HOME"] == str(weights)


def _plist(agents: Path, name: str, hf: str | None) -> None:
    env = {"PATH": "/usr/bin"} if hf is None else {"PATH": "/usr/bin", "HF_HOME": hf}
    (agents / f"{install_env.PREFIX}.{name}.plist").write_bytes(plistlib.dumps({"EnvironmentVariables": env}))


def test_the_unit_check_names_each_unit_off_the_recorded_weights(tmp_path):
    agents = tmp_path / "agents"
    agents.mkdir()
    _plist(agents, "gateway", "/w")
    _plist(agents, "mlx", "/release/hf_root")
    _plist(agents, "tts", None)
    rows = install_env.units({"HF_HOME": "/w"}, agents, ["gateway", "mlx", "tts", "eval"])
    assert [ok for ok, _ in rows] == [True, False, False]
    assert rows[1][1].startswith("unit mlx has HF_HOME=/release/hf_root, not the recorded /w")
    assert rows[2][1].startswith("unit tts has HF_HOME=nothing")


def test_the_record_problem_names_a_missing_or_unreadable_weights_location(tmp_path):
    p = tmp_path / deploy_switch.INSTALL_ENV
    assert "no recorded install environment" in install_env.problem(p)
    p.write_text("PATH=/usr/bin\n", encoding="utf-8")
    assert "records no HF_HOME" in install_env.problem(p)
    p.write_text(f"HF_HOME={tmp_path / 'gone'}\n", encoding="utf-8")
    assert "cannot be read" in install_env.problem(p)
    p.write_text(f"HF_HOME={tmp_path}\nHF_HOME=/second\n", encoding="utf-8")
    assert install_env.problem(p) == "" and install_env.read(p)["HF_HOME"] == str(tmp_path)


@darwin
def test_smoke_fails_naming_a_unit_whose_weights_differ_from_the_record(tmp_path):
    from tests.test_gateway_key import Gateway, _smoke
    agents = tmp_path / "agents"
    agents.mkdir()
    (tmp_path / deploy_switch.INSTALL_ENV).write_text(f"HF_HOME={tmp_path}\n", encoding="utf-8")
    _plist(agents, "gateway", str(tmp_path))
    _plist(agents, "mlx", "/release/hf_root")
    g = Gateway("sk-right")
    try:
        r = _smoke({"SOHOT_GATEWAY_KEY": "sk-right", "GATEWAY_PORT": str(g.server_address[1]),
                    "SMOKE_INSTALL_CHECK": f"{sys.executable} -m harness.install_env units --agents {agents}"},
                   tmp_path)
    finally:
        g.shutdown()
    assert "PASS  unit gateway carries the recorded HF_HOME" in r.stdout, r.stdout
    assert "FAIL  unit mlx has HF_HOME=/release/hf_root" in r.stdout, r.stdout
    assert r.returncode != 0


CONFIG = {"model_list": [
    {"model_name": "sohot-code", "litellm_params": {"model": "openai/big", "api_base": "http://127.0.0.1:8081/v1"}},
    {"model_name": "small-mlx", "litellm_params": {"model": "openai/small-mlx", "api_base": "http://127.0.0.1:8081/v1"}},
    {"model_name": "other-mlx", "litellm_params": {"model": "openai/other", "api_base": "http://127.0.0.1:8081/v1"}},
    {"model_name": "on-node", "node": "box", "litellm_params": {"model": "openai/x", "api_base": "http://NODE_HOST:18082/v1"}},
    {"model_name": "cloud", "litellm_params": {"model": "anthropic/claude"}},
    {"model_name": "gguf", "litellm_params": {"model": "openai/gguf", "api_base": "http://127.0.0.1:8082/v1"}},
]}


class _Reply:
    def __init__(self, status: int, text: str):
        self.status_code, self.text = status, text


def test_one_completion_per_upstream_engine_and_a_404_names_the_engine():
    from harness import serving
    picks = engine_smoke.picks(CONFIG)
    assert picks == {serving.text_engine(): "small-mlx", serving.LLAMACPP: "gguf"}
    asked = []

    def ask(gateway, key, model, timeout):
        asked.append(model)
        return _Reply(404, "Not Found") if model == "small-mlx" else _Reply(200, '{"choices":[{"message":{"content":"OK"}}]}')

    rows = engine_smoke.smoke("http://g", "k", CONFIG, 5.0, ask=ask)
    assert asked == ["small-mlx", "gguf"]
    assert rows == [(False, f"engine {serving.text_engine()}: small-mlx answered HTTP 404: Not Found"),
                    (True, f"engine {serving.LLAMACPP} completes (gguf)")]


@darwin
def test_smoke_asks_each_engine_for_a_real_completion(tmp_path):
    import yaml
    from tests.test_gateway_key import Gateway, _smoke
    cfg = tmp_path / "config.yaml"
    cfg.write_text(yaml.safe_dump(CONFIG), encoding="utf-8")
    g = Gateway("sk-right")
    try:
        r = _smoke({"SOHOT_GATEWAY_KEY": "sk-right", "GATEWAY_PORT": str(g.server_address[1]),
                    "GATEWAY_CONFIG": str(cfg), "SMOKE_ENGINES_CHECK": ""}, tmp_path)
    finally:
        g.shutdown()
    assert "PASS  engine llama-server completes (gguf)" in r.stdout, r.stdout
    assert {b.get("model") for b in g.bodies} >= {"small-mlx", "gguf"}


def _fake_run(calls, bootstrap_rc: int, loaded: bool, reload_rc: int = 0):
    def run(argv, **kw):
        calls.append(argv)
        rc = 0
        if argv[:2] == ["launchctl", "bootstrap"]:
            rc = bootstrap_rc
        elif argv[:2] == ["launchctl", "print"]:
            rc = 0 if loaded else 113
        elif argv[-1] == "reload":
            rc = reload_rc
        return subprocess.CompletedProcess(argv, rc, "", "Bootstrap failed: 5: Input/output error" if rc else "")
    return run


def _install(monkeypatch, run, tmp_path):
    monkeypatch.setattr(monitor, "plist_path", lambda: tmp_path / "monit.plist")
    monkeypatch.setattr(monitor, "spec_here", lambda run=None: {"models": "", "data": "/", "services": []})
    monkeypatch.setattr(monitor, "render", lambda s: "check program p with path /usr/bin/true\n")
    monkeypatch.setattr(monitor, "syntax", lambda monit, rc, run=None: "")
    return monitor.install(run=run, which=lambda n: "/x/monit", platform="darwin", sleep=lambda s: None)


def test_monitor_install_reloads_a_monit_that_stayed_loaded(monkeypatch, tmp_path):
    calls = []
    got = _install(monkeypatch, _fake_run(calls, bootstrap_rc=5, loaded=True), tmp_path)
    assert got["reloaded"] is True
    assert ["/x/monit", "-c", str(monitor.rc_path()), "reload"] in calls


def test_monitor_install_fails_when_bootstrap_fails_and_nothing_is_loaded(monkeypatch, tmp_path):
    calls = []
    with pytest.raises(monitor.InstallError, match="Input/output error"):
        _install(monkeypatch, _fake_run(calls, bootstrap_rc=5, loaded=False), tmp_path)
    assert not [c for c in calls if c[-1] == "reload"]


def test_monitor_install_waits_for_the_old_monit_to_unload_before_bootstrap(monkeypatch, tmp_path):
    calls = []
    got = _install(monkeypatch, _fake_run(calls, bootstrap_rc=0, loaded=False), tmp_path)
    assert got["reloaded"] is False
    verbs = [c[1] for c in calls if c[0] == "launchctl"]
    assert verbs.index("bootout") < verbs.index("print") < verbs.index("bootstrap")


def test_status_says_a_running_monit_is_on_an_older_config():
    monitor.write_rc("check filesystem system_data with path /\ncheck program memory_pressure with path x\n")
    summary = " Service Name  Status  Type\n system_data  OK  Filesystem\n"
    got = monitor.status(run=lambda argv, **kw: subprocess.CompletedProcess(argv, 0, summary, ""),
                         which=lambda n: "/x/monit", expected=monitor.rc_path().read_text(encoding="utf-8"))
    assert got["running"] and got["current"]
    assert any("older config" in p and "memory_pressure" in p for p in got["problems"]), got["problems"]
