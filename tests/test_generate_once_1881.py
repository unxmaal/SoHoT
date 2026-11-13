"""launchd.sh generate asks env.sh for the weights root once per run, and every unit carries that answer (#1881)."""
from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
from pathlib import Path

from tests import shells

REPO = Path(__file__).resolve().parents[1]

# Counts its own runs and answers like env.sh does; launchd.sh finds it beside itself.
STUB_ENV = """\
printf 'x\\n' >> "$ENV_RUNS"
HF_ROOT="$STUB_HF"
export HF_HOME="$HF_ROOT"
"""


def _generate(tmp_path: Path, **extra) -> tuple[int, dict[str, dict]]:
    scripts = tmp_path / "repo" / "scripts"
    scripts.mkdir(parents=True)
    shutil.copy(REPO / "scripts" / "launchd.sh", scripts / "launchd.sh")
    (scripts / "env.sh").write_text(STUB_ENV, encoding="utf-8", newline="\n")
    runs = tmp_path / "runs"
    env = {k: v for k, v in os.environ.items() if k not in ("LH_ROLE", "HF_ROOT", "HF_HOME")}
    env.update(HOME=str(tmp_path / "home"), LOCALHARNESS_HOME=str(tmp_path / "lh"), ENV_RUNS=str(runs),
               STUB_HF="/weights/hf", **extra)
    out = tmp_path / "agents"
    proc = subprocess.run([shells.BASH, str(scripts / "launchd.sh"), "generate", str(out)],
                          capture_output=True, text=True, env=env)
    assert proc.returncode == 0, proc.stderr
    units = {p.stem.rsplit(".", 1)[-1]: plistlib.loads(p.read_bytes()) for p in out.glob("*.plist")}
    return len(runs.read_text(encoding="utf-8").splitlines()), units


def test_generate_runs_env_sh_once_for_every_unit(tmp_path):
    runs, units = _generate(tmp_path)
    assert len(units) > 10
    assert runs == 1
    for name, unit in units.items():
        got = unit["EnvironmentVariables"]
        assert (got.get("HF_ROOT"), got.get("HF_HOME")) == ("/weights/hf", "/weights/hf"), name


def test_a_unit_with_its_own_variables_still_gets_the_weights_root(tmp_path):
    runs, units = _generate(tmp_path, LH_WATCHDOG_ACT="1")
    assert runs == 1
    got = units["watchdog"]["EnvironmentVariables"]
    assert got["LH_WATCHDOG_ACT"] == "1" and got["HF_HOME"] == "/weights/hf"
