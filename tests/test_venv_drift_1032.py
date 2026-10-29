"""A runner venv holds what its script resolves to and nothing else; drift is a soh audit inventory (#1032)."""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from harness import live_audit, paths, runner_gaps, venv_drift
from tests import shells

ROOT = Path(__file__).resolve().parent.parent

VERSIONS = 'TORCH_MPS_PIN="torch==2.6.0"\nTORCH_CUDA_PIN="torch==2.6.0+cu124"\nTORCH_CUDA_INDEX="https://x/cu124"\n' \
           'DIFFUSERS_PIN="diffusers==0.40.0"\nFTFY_PIN="ftfy==6.3.1"\n'
SCRIPT = ('if [ "$(uname -s)" = "Darwin" ]; then\n  DIFFUSERS_TORCH=("$TORCH_MPS_PIN")\nelse\n'
          '  DIFFUSERS_TORCH=(--index-url "$TORCH_CUDA_INDEX" "$TORCH_CUDA_PIN")\nfi\n'
          'DIFFUSERS_VENV_PINS=("$DIFFUSERS_PIN" "$FTFY_PIN")\n')


def _repo(tmp_path) -> Path:
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True, exist_ok=True)
    (repo / "scripts" / "versions.sh").write_text(VERSIONS, encoding="utf-8")
    (repo / "scripts" / "diffusers-venv.sh").write_text(SCRIPT, encoding="utf-8")
    return repo


def _dist(root: Path, name: str, version: str, *requires: str) -> None:
    info = root / "lib" / "python3.12" / "site-packages" / f"{name.replace('-', '_')}-{version}.dist-info"
    info.mkdir(parents=True)
    lines = [f"Name: {name}", f"Version: {version}", *(f"Requires-Dist: {r}" for r in requires)]
    (info / "METADATA").write_text("Metadata-Version: 2.1\n" + "\n".join(lines) + "\n", encoding="utf-8")


def _venv(tmp_path, torch="2.6.0") -> Path:
    root = tmp_path / "venv"
    (root).mkdir()
    (root / "pyvenv.cfg").write_text("version_info = 3.12.14\n", encoding="utf-8")
    _dist(root, "torch", torch, "sympy>=1.13", 'nvidia-cudnn-cu12; sys_platform == "linux"',
          'opt-einsum>=3.3; extra == "opt-einsum"')
    _dist(root, "sympy", "1.13.1", "mpmath<1.4,>=1.1.0", 'pytest>=7; extra == "dev"')
    _dist(root, "mpmath", "1.3.0")
    _dist(root, "diffusers", "0.40.0", "huggingface-hub[torch]>=0.34")
    _dist(root, "huggingface-hub", "1.32.0", "filelock", 'safetensors; extra == "torch"')
    _dist(root, "filelock", "4.0.1")
    _dist(root, "safetensors", "0.8.0")
    _dist(root, "ftfy", "6.3.1", "wcwidth")
    _dist(root, "wcwidth", "0.9.2")
    return root


@pytest.mark.parametrize("platform, torch", [("darwin", "torch==2.6.0"), ("linux", "torch==2.6.0+cu124"),
                                             ("win32", "torch==2.6.0+cu124")])
def test_the_pins_are_the_scripts_branch_for_this_platform(tmp_path, monkeypatch, platform, torch):
    monkeypatch.setattr(sys, "platform", platform)
    assert venv_drift.pins("diffusers-cuda", _repo(tmp_path)) == {
        "torch": torch, "diffusers": "diffusers==0.40.0", "ftfy": "ftfy==6.3.1"}


def test_a_venv_holding_its_pins_and_their_dependencies_has_no_drift(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    assert venv_drift.drift("diffusers-cuda", _repo(tmp_path), _venv(tmp_path)) == {
        "extra": [], "missing": [], "version": []}


def test_a_hand_installed_dist_and_what_it_pulled_in_are_extra(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    root = _venv(tmp_path)
    _dist(root, "nnAudio", "0.3.4", "scipy")
    _dist(root, "scipy", "1.18.1", "numpy")
    _dist(root, "numpy", "2.5.3")
    _dist(root, "pytest", "8.0.0")
    got = venv_drift.drift("diffusers-cuda", _repo(tmp_path), root)
    assert got["extra"] == ["nnaudio 0.3.4", "numpy 2.5.3", "pytest 8.0.0", "scipy 1.18.1"]


def test_a_dist_only_another_platforms_marker_reaches_is_extra(tmp_path, monkeypatch):
    root = _venv(tmp_path, torch="2.6.0+cu124")
    _dist(root, "nvidia-cudnn-cu12", "9.1.0")
    monkeypatch.setattr(sys, "platform", "linux")
    assert venv_drift.drift("diffusers-cuda", _repo(tmp_path), root)["extra"] == []
    monkeypatch.setattr(sys, "platform", "darwin")
    assert venv_drift.drift("diffusers-cuda", _repo(tmp_path), root)["extra"] == ["nvidia-cudnn-cu12 9.1.0"]


def test_a_pin_not_installed_or_off_version_is_drift(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    root = _venv(tmp_path, torch="2.5.1")
    shutil.rmtree(next((root / "lib" / "python3.12" / "site-packages").glob("ftfy-*.dist-info")))
    got = venv_drift.drift("diffusers-cuda", _repo(tmp_path), root)
    assert got == {"extra": ["wcwidth 0.9.2"], "missing": ["ftfy==6.3.1"],
                   "version": ["torch 2.5.1 (pins torch==2.6.0)"]}


@pytest.mark.parametrize("venv", sorted(runner_gaps.VENV_SCRIPTS))
@pytest.mark.parametrize("platform", ["darwin", "linux", "win32"])
def test_every_runner_venv_script_pins_each_package_exactly(monkeypatch, venv, platform):
    monkeypatch.setattr(sys, "platform", platform)
    got = venv_drift.pins(venv, ROOT)
    assert {"torch", "transformers" if venv != "shots" else "transnetv2-pytorch"} <= set(got)
    assert all("==" in pin for pin in got.values()), got


def test_the_hand_installed_packages_on_record_are_not_pinned_in_the_diffusers_venv():
    for platform in ("darwin", "linux"):
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(sys, "platform", platform)
            assert not {"nnaudio", "onnxruntime", "soundfile"} & set(venv_drift.pins("diffusers-cuda", ROOT))


def test_drift_is_an_audit_inventory_that_never_fails(tmp_path, monkeypatch):
    from harness import memory_store as ms
    monkeypatch.setenv("LOCALHARNESS_HOME", str(tmp_path))
    for var in (*runner_gaps._VENV_ENV.values(), *runner_gaps._CHECKOUT_VENVS.values()):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(sys, "platform", "darwin")
    ms.connect(tmp_path / "discovery.db").close()
    root = tmp_path / "venvs" / "diffusers-cuda"
    root.parent.mkdir()
    _venv(tmp_path).rename(root)
    _dist(root, "onnxruntime", "1.30.0")
    monkeypatch.setattr(paths, "REPO", _repo(tmp_path))
    got = live_audit.audit(tmp_path / "discovery.db")
    check = {c["name"]: c for c in got["checks"]}["venv_matches_script"]
    assert check["ok"] and check["warn"]
    assert "diffusers-cuda: extra onnxruntime 1.30.0" in check["detail"]
    shutil.rmtree(next((root / "lib" / "python3.12" / "site-packages").glob("onnxruntime-*")))
    check = {c["name"]: c for c in live_audit.audit(tmp_path / "discovery.db")["checks"]}["venv_matches_script"]
    assert check["ok"] and not check["warn"] and not check["detail"]


FAKE_UV = r"""#!/bin/sh
echo "$*" >> "$UV_LOG"
if [ "$1" = venv ]; then
  for a in "$@"; do d="$a"; done
  case " $* " in *" --clear "*) rm -rf "$d" ;; *) [ -e "$d" ] && exit 2 ;; esac
  mkdir -p "$d/bin" "$d/lib/python3.12/site-packages"
  printf '#!/bin/sh\n' > "$d/bin/python"; chmod +x "$d/bin/python"
elif [ "$1 $2" = "pip install" ]; then
  shift 2
  for a in "$@"; do
    case "$a" in *==*) mkdir -p "$VIRTUAL_ENV/lib/python3.12/site-packages/${a%%==*}-${a#*==}.dist-info" ;; esac
  done
fi
"""


def _source(tmp_path, script: str, env_var: str, venv: Path) -> list[str]:
    log = tmp_path / "uv.log"
    log.write_text("", encoding="utf-8")
    env = {**os.environ, "PATH": f"{tmp_path / 'bin'}{os.pathsep}{os.environ['PATH']}", "UV_LOG": str(log),
           env_var: str(venv)}
    subprocess.run([shells.BASH, "-c", f"set -euo pipefail; source scripts/versions.sh; source scripts/{script}"],
                   cwd=ROOT, env=env, check=True, capture_output=True, text=True, timeout=60)
    return log.read_text(encoding="utf-8").splitlines()


@pytest.mark.skipif(sys.platform == "win32" or not shells.BASH, reason="sources a bash script with a fake uv")
@pytest.mark.parametrize("script, env_var", [("diffusers-venv.sh", "DIFFUSERS_VENV"), ("hf-task-venv.sh", "HF_TASK_VENV"),
                                             ("shots-venv.sh", "SHOTS_VENV")])
def test_a_venv_script_rebuilds_from_empty_when_anything_but_its_pins_is_installed(tmp_path, script, env_var):
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "uv").write_text(FAKE_UV, encoding="utf-8")
    (tmp_path / "bin" / "uv").chmod(0o755)
    venv = tmp_path / "venv"
    site = venv / "lib" / "python3.12" / "site-packages"
    first = _source(tmp_path, script, env_var, venv)
    assert first[0].startswith("venv --clear") and len(first) == 3
    built = sorted(p.name for p in site.iterdir())
    assert _source(tmp_path, script, env_var, venv) == []
    (site / "nnaudio-0.3.4.dist-info").mkdir()
    assert _source(tmp_path, script, env_var, venv)[0].startswith("venv --clear")
    assert sorted(p.name for p in site.iterdir()) == built
    (venv / ".pins").write_text("an older stamp", encoding="utf-8")
    (site / "soundfile-0.14.0.dist-info").mkdir()
    assert _source(tmp_path, script, env_var, venv)[0].startswith("venv --clear")
    assert sorted(p.name for p in site.iterdir()) == built


def test_the_decider_venv_rebuilds_from_empty_when_its_revision_moves():
    text = (ROOT / "scripts" / "decider-venv.sh").read_text(encoding="utf-8")
    assert 'uv venv --clear --python 3.12 "$DECIDER_VENV"' in text and "[ -x \"$PY\" ] || uv venv" not in text
