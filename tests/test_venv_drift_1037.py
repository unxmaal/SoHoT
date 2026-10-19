"""The nimble and decider venvs rebuild when a pin moves and are inside the drift check (#1037)."""
import json
import os
import platform
import re
import subprocess
import sys
from pathlib import Path

import pytest

from harness import live_audit, paths, runner_gaps, venv_drift
from tests import shells
from tests.test_venv_drift_1032 import FAKE_UV, _dist

ROOT = Path(__file__).resolve().parent.parent

VERSIONS = 'NIMBLE_MLX_PIN="mlx==0.32.2"\nDECIDER_MLX_LM_PIN="mlx-lm==0.32.0"\nNIMBLE_TORCH_PIN="torch==2.8.0"\n'
SCRIPT = ('if [ "$(uname -s)" = "Darwin" ] && [ "$(uname -m)" = "arm64" ]; then\n  EXTRA="[mlx]"\n'
          '  DECIDER_MLX=("$NIMBLE_MLX_PIN" "$DECIDER_MLX_LM_PIN")\nelse\n  EXTRA=""\n  DECIDER_MLX=()\nfi\n'
          'DECIDER_VENV_PINS=("${DECIDER_ROOT}${EXTRA}" "$NIMBLE_TORCH_PIN")\n')


def _repo(tmp_path) -> Path:
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True, exist_ok=True)
    (repo / "scripts" / "versions.sh").write_text(VERSIONS, encoding="utf-8")
    (repo / "scripts" / "decider-venv.sh").write_text(SCRIPT, encoding="utf-8")
    return repo


def _decider(tmp_path, local=True) -> Path:
    root = tmp_path / "venv"
    root.mkdir()
    (root / "pyvenv.cfg").write_text("version_info = 3.12.14\n", encoding="utf-8")
    _dist(root, "strands-decider", "0.1.0+g3e94e9d", "torch>=2.7", "fastapi>=0.115",
          'mlx>=0.32.2; (sys_platform == "darwin" and platform_machine == "arm64") and extra == "mlx"',
          'pytest>=8.0; extra == "dev"')
    if local:
        info = next((root / "lib" / "python3.12" / "site-packages").glob("strands_decider-*.dist-info"))
        (info / "direct_url.json").write_text(json.dumps({"url": "file:///x/checkout", "dir_info": {}}),
                                              encoding="utf-8")
    _dist(root, "torch", "2.8.0")
    _dist(root, "fastapi", "0.142.2", "starlette")
    _dist(root, "starlette", "1.7.0")
    _dist(root, "mlx", "0.32.2")
    _dist(root, "mlx-lm", "0.32.0", "mlx")
    return root


@pytest.mark.parametrize("name, home_var", [("nimble", "NIMBLE_HOME"), ("decider", "DECIDER_HOME")])
def test_the_checkout_venvs_live_where_their_scripts_build_them(tmp_path, monkeypatch, name, home_var):
    monkeypatch.setenv("LOCALHARNESS_HOME", str(tmp_path))
    monkeypatch.delenv(home_var, raising=False)
    monkeypatch.delenv(f"{name.upper()}_VENV", raising=False)
    assert runner_gaps.venv_path(name) == tmp_path / name / "venv"
    monkeypatch.setenv(home_var, str(tmp_path / "elsewhere"))
    assert runner_gaps.venv_path(name) == tmp_path / "elsewhere" / "venv"
    monkeypatch.setenv(f"{name.upper()}_VENV", str(tmp_path / "v"))
    assert runner_gaps.venv_path(name) == tmp_path / "v"


@pytest.mark.parametrize("plat, machine, mlx", [("darwin", "arm64", True), ("darwin", "x86_64", False),
                                                ("linux", "aarch64", False)])
def test_the_decider_pins_mlx_only_on_apple_silicon(tmp_path, monkeypatch, plat, machine, mlx):
    monkeypatch.setattr(sys, "platform", plat)
    monkeypatch.setattr(platform, "machine", lambda: machine)
    got = venv_drift.pins("decider", _repo(tmp_path))
    assert got == {"torch": "torch==2.8.0", **({"mlx": "mlx==0.32.2", "mlx-lm": "mlx-lm==0.32.0"} if mlx else {})}
    assert venv_drift.checkouts("decider", _repo(tmp_path)) == ["${DECIDER_ROOT}${EXTRA}"]


def test_what_the_local_checkout_pulls_in_is_not_extra(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(platform, "machine", lambda: "arm64")
    assert venv_drift.drift("decider", _repo(tmp_path), _decider(tmp_path)) == {
        "extra": [], "missing": [], "version": []}


def test_the_same_dist_not_from_a_checkout_is_extra_and_the_checkout_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(platform, "machine", lambda: "arm64")
    got = venv_drift.drift("decider", _repo(tmp_path), _decider(tmp_path, local=False))
    assert got["extra"] == ["fastapi 0.142.2", "starlette 1.7.0", "strands-decider 0.1.0+g3e94e9d"]
    assert got["missing"] == ["${DECIDER_ROOT}${EXTRA}"]


def test_a_checkout_dist_in_a_venv_whose_script_installs_none_is_extra(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(platform, "machine", lambda: "arm64")
    repo = _repo(tmp_path)
    (repo / "scripts" / "decider-venv.sh").write_text(SCRIPT.replace('"${DECIDER_ROOT}${EXTRA}" ', ""),
                                                      encoding="utf-8")
    assert "strands-decider 0.1.0+g3e94e9d" in venv_drift.drift("decider", repo, _decider(tmp_path))["extra"]


def test_the_nimble_venv_pins_huggingface_hub():
    assert re.fullmatch(r"huggingface-hub==\d+(\.\d+)+", venv_drift.pins("nimble", ROOT)["huggingface-hub"])


def test_the_audit_reads_the_nimble_venv_beside_its_checkout(tmp_path, monkeypatch):
    from harness import memory_store as ms
    monkeypatch.setenv("LOCALHARNESS_HOME", str(tmp_path))
    for var in (*runner_gaps._VENV_ENV.values(), *runner_gaps._CHECKOUT_VENVS.values()):
        monkeypatch.delenv(var, raising=False)
    ms.connect(tmp_path / "discovery.db").close()
    root = tmp_path / "nimble" / "venv"
    for name, pin in venv_drift.pins("nimble", ROOT).items():
        _dist(root, name, pin.partition("==")[2])
    _dist(root, "nnaudio", "0.3.4")
    monkeypatch.setattr(paths, "REPO", ROOT)
    check = {c["name"]: c for c in live_audit.audit(tmp_path / "discovery.db")["checks"]}["venv_matches_script"]
    assert check["ok"] and "nimble: extra nnaudio 0.3.4" in check["detail"]


FAKE_GIT = '#!/bin/sh\ncase "$*" in *rev-parse*) echo "$GIT_HEAD" ;; esac\n'
FAKE_UNAME = '#!/bin/sh\ncase "$1" in -s) echo "$FAKE_OS" ;; -m) echo "$FAKE_ARCH" ;; esac\n'


def _rev(name: str) -> str:
    text = (ROOT / "scripts" / "versions.sh").read_text(encoding="utf-8")
    return re.search(rf'^{name}="([0-9a-f]+)"', text, re.M).group(1)


def _source(tmp_path, script: str, prefix: str, after: str = ":", arch: str = "arm64") -> list[str]:
    log = tmp_path / "uv.log"
    log.write_text("", encoding="utf-8")
    (tmp_path / "checkout" / ".git").mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "PATH": f"{tmp_path / 'bin'}{os.pathsep}{os.environ['PATH']}", "UV_LOG": str(log),
           f"{prefix}_VENV": str(tmp_path / "venv"), f"{prefix}_ROOT": str(tmp_path / "checkout"),
           f"{prefix}_HOME": str(tmp_path), "GIT_HEAD": _rev(f"{prefix}_REV"), "FAKE_OS": "Darwin", "FAKE_ARCH": arch}
    subprocess.run([shells.BASH, "-c", f"set -euo pipefail; source scripts/versions.sh; {after}; source scripts/{script}"],
                   cwd=ROOT, env=env, check=True, capture_output=True, text=True, timeout=60)
    return log.read_text(encoding="utf-8").splitlines()


@pytest.mark.skipif(sys.platform == "win32" or not shells.BASH, reason="sources a bash script with a fake uv")
@pytest.mark.parametrize("script, prefix, pin", [("nimble-venv.sh", "NIMBLE", "NIMBLE_MLX_LM_PIN"),
                                                 ("decider-venv.sh", "DECIDER", "DECIDER_MLX_LM_PIN"),
                                                 ("decider-venv.sh", "DECIDER", "PEFT_PIN")])
def test_a_checkout_venv_rebuilds_from_empty_when_a_pin_moves_or_a_hand_install_lands(tmp_path, script, prefix, pin):
    (tmp_path / "bin").mkdir()
    for name, body in (("uv", FAKE_UV), ("git", FAKE_GIT), ("uname", FAKE_UNAME)):
        (tmp_path / "bin" / name).write_text(body, encoding="utf-8")
        (tmp_path / "bin" / name).chmod(0o755)
    site = tmp_path / "venv" / "lib" / "python3.12" / "site-packages"
    first = _source(tmp_path, script, prefix)
    assert first[0].startswith("venv --clear") and len(first) == 2
    assert _source(tmp_path, script, prefix) == []
    (site / "nnaudio-0.3.4.dist-info").mkdir()
    assert _source(tmp_path, script, prefix)[0].startswith("venv --clear")
    assert not (site / "nnaudio-0.3.4.dist-info").exists()
    moved = _source(tmp_path, script, prefix, after=f'{pin}="${{{pin}%==*}}==99.0"')
    assert moved[0].startswith("venv --clear") and "==99.0" in moved[1]
    assert _source(tmp_path, script, prefix)[0].startswith("venv --clear")


@pytest.mark.skipif(sys.platform == "win32" or not shells.BASH, reason="sources a bash script with a fake uv")
def test_the_decider_installs_mlx_only_on_apple_silicon(tmp_path):
    (tmp_path / "bin").mkdir()
    for name, body in (("uv", FAKE_UV), ("git", FAKE_GIT), ("uname", FAKE_UNAME)):
        (tmp_path / "bin" / name).write_text(body, encoding="utf-8")
        (tmp_path / "bin" / name).chmod(0o755)
    arm = _source(tmp_path, "decider-venv.sh", "DECIDER")[1]
    assert f"{tmp_path / 'checkout'}[mlx]" in arm and "mlx-lm==" in arm
    intel = _source(tmp_path, "decider-venv.sh", "DECIDER", arch="x86_64")
    assert intel[0].startswith("venv --clear") and "[mlx]" not in intel[1] and "mlx-lm==" not in intel[1]
