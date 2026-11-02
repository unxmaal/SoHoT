"""scripts/fetch-h3-weights.sh downloads online with the Xet fast path, under env.sh's offline guard. #1457."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import shells

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "fetch-h3-weights.sh"

FAKE_UV = """#!/usr/bin/env bash
printf '%s\\n' "$@" > "$H3_UV_ARGS"
PYTHONPATH="$H3_STUB" exec "$H3_PY" - "${@: -1}"
"""

FAKE_DF = """#!/usr/bin/env bash
echo "Filesystem 1024-blocks Used Available Capacity Mounted on"
echo "fake 1000000000 0 900000000 0% /"
"""

STUB = """import json, os
def snapshot_download(**kw):
    keys = ("HF_HUB_OFFLINE", "HF_XET_HIGH_PERFORMANCE", "HF_HUB_ENABLE_HF_TRANSFER")
    with open(os.environ["H3_SEEN"], "w", encoding="utf-8") as f:
        json.dump({"env": {k: os.environ.get(k) for k in keys}, "kw": kw}, f)
    return kw["local_dir"]
"""


def _exe(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8", newline="\n")
    path.chmod(0o755)


@pytest.mark.parametrize("caller", [None, "1"])
def test_the_download_step_sees_online_mode_and_the_xet_switch(tmp_path, caller):
    if shells.BASH is None:
        pytest.skip("no bash on this machine")
    bin_dir, stub = tmp_path / "bin", tmp_path / "stub" / "huggingface_hub"
    bin_dir.mkdir()
    stub.mkdir(parents=True)
    _exe(bin_dir / "uv", FAKE_UV)
    _exe(bin_dir / "df", FAKE_DF)
    (stub / "__init__.py").write_text(STUB, encoding="utf-8")
    dest, seen, args = tmp_path / "MiniMax-H3", tmp_path / "seen.json", tmp_path / "uv-args"
    env = {k: v for k, v in os.environ.items()
           if k not in ("HF_HUB_OFFLINE", "HF_XET_HIGH_PERFORMANCE", "HF_HUB_ENABLE_HF_TRANSFER",
                        "HF_HOME", "HF_ROOT", "PYTHONPATH")}
    env.update(PATH=f"{bin_dir.as_posix()}{os.pathsep}{env['PATH']}", HF_ROOT=str(tmp_path / "hf"),
               HF_MIN_FREE_GB="0", H3_MODEL_DIR=str(dest), H3_DOWNLOAD_PIDFILE=str(tmp_path / "pid"),
               H3_UV_ARGS=str(args), H3_SEEN=str(seen), H3_STUB=str(stub.parent),
               H3_PY=Path(sys.executable).as_posix())
    if caller is not None:
        env["HF_HUB_OFFLINE"] = caller
    p = subprocess.run([shells.BASH, str(SCRIPT)], capture_output=True, text=True, env=env, timeout=120)
    assert p.returncode == 0, p.stderr
    got = json.loads(seen.read_text(encoding="utf-8"))
    assert got["env"]["HF_HUB_OFFLINE"] == "0"
    assert got["env"]["HF_XET_HIGH_PERFORMANCE"] == "1"
    assert got["env"]["HF_HUB_ENABLE_HF_TRANSFER"] is None
    assert "hf_transfer" not in args.read_text(encoding="utf-8")
    assert got["kw"]["repo_id"] == "MiniMaxAI/MiniMax-H3"
    assert got["kw"]["allow_patterns"] == ["FL2VA/**"]
    assert Path(got["kw"]["local_dir"]) == dest
    assert not (tmp_path / "pid").exists()
