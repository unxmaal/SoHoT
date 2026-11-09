"""launchd.sh restart recovers a serving unit while the store is down; gpu work stays refused. #1667."""
import os
import subprocess
import sys
from pathlib import Path

import pytest
import shells

from harness import exclusive

REPO = Path(__file__).resolve().parents[1]
LAUNCHD = REPO / "scripts" / "launchd.sh"
HELPER = REPO / "scripts" / "with-gpu-lock"
REASON = "the store is unreachable"

# kickstart also submits a gpu job through with-gpu-lock, as if from another shell, while the restart holds the lock.
FAKE_LAUNCHCTL = """#!/bin/sh
echo "$*" >> "$FAKE_STATE/launchctl"
if [ "$1" = kickstart ]; then
  env -u LH_GPU_LOCK_HELD "$WITH_GPU_LOCK" "$FAKE_PY" -c "open('$FAKE_STATE/gpu-ran', 'w')" \\
    2> "$FAKE_STATE/gpu-err"
  echo $? > "$FAKE_STATE/gpu-rc"
fi
exit 0
"""


def _restart(tmp_path, service="gateway"):
    home, state, bin_ = tmp_path / "home", tmp_path / "state", tmp_path / "bin"
    (home / "discovery.db").mkdir(parents=True)
    (home / "queue").mkdir()
    # A refusal already stands, so no child sends a desktop alert.
    (home / "queue" / exclusive.REFUSED).write_text("{}", encoding="utf-8")
    state.mkdir()
    bin_.mkdir()
    (bin_ / "launchctl").write_text(FAKE_LAUNCHCTL, encoding="utf-8")
    (bin_ / "launchctl").chmod(0o755)
    env = {k: v for k, v in os.environ.items() if k != exclusive.HELD_ENV}
    env.update({"LOCALHARNESS_HOME": str(home), "LOCALHARNESS_STORE": "sqlite", "FAKE_STATE": str(state),
                "FAKE_PY": sys.executable, "WITH_GPU_LOCK": str(HELPER),
                "PATH": f"{bin_}{os.pathsep}{env['PATH']}"})
    got = subprocess.run([shells.BASH, str(LAUNCHD), "restart", service], env=env,
                         capture_output=True, text=True, timeout=120)
    return got, state


@pytest.mark.skipif(sys.platform == "win32", reason="a POSIX script")
def test_restart_kickstarts_its_unit_and_exits_0_while_the_store_is_down(tmp_path):
    got, state = _restart(tmp_path)
    assert got.returncode == 0, got.stderr
    calls = (state / "launchctl").read_text(encoding="utf-8").splitlines()
    assert [c.split()[0] for c in calls] == ["print", "kickstart"], calls
    assert calls[1].startswith("kickstart -k gui/") and calls[1].endswith("com.unxmaal.localharness.gateway")
    assert "install holds the local lock only" in got.stderr and "external refused" not in got.stderr


@pytest.mark.skipif(sys.platform == "win32", reason="a POSIX script")
def test_a_gpu_job_submitted_during_the_restart_is_still_refused(tmp_path):
    got, state = _restart(tmp_path)
    assert got.returncode == 0, got.stderr
    assert (state / "gpu-rc").read_text(encoding="utf-8").strip() != "0"
    err = (state / "gpu-err").read_text(encoding="utf-8")
    assert "external refused" in err and REASON in err, err
    assert not (state / "gpu-ran").exists()


def test_restart_goes_through_the_repair_hold_and_only_kickstarts():
    text = LAUNCHD.read_text(encoding="utf-8")
    assert 'with-gpu-lock" --repair launchctl kickstart -k "gui/$UID/$label"' in text
