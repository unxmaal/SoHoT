"""Before the switch, a release whose checks fail only the old services warns; the serving release's own smoke judges them. #1790."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from harness import deploy
from tests import shells

REPO = Path(__file__).resolve().parents[1]
BASH = shells.resolve("bash")
pytestmark = pytest.mark.skipif(sys.platform == "win32" or BASH is None, reason="bash scripts")
SMOKE = (REPO / "scripts" / "smoke.sh").read_text(encoding="utf-8")


def _verdict() -> str:
    """How the real scripts/smoke.sh ends once its checks have run."""
    return [ln for ln in SMOKE.splitlines() if ln.strip()][-1]


def _release(root: Path, checks: str) -> Path:
    """A release whose smoke.sh is `checks`, then the real smoke.sh's ending; the real verdict script beside it."""
    (root / "scripts").mkdir(parents=True)
    head = 'FAIL=0\nno(){ printf "FAIL  %s\\n" "$1"; FAIL=1; }\nok(){ printf "PASS  %s\\n" "$1"; }\n'
    (root / "scripts" / "smoke.sh").write_text(f"cd \"$(dirname \"$0\")/..\" || exit 1\n{head}{checks}\n{_verdict()}\n",
                                               encoding="utf-8")
    verdict = REPO / "scripts" / "smoke-verdict.sh"
    if verdict.is_file():
        shutil.copy(verdict, root / "scripts" / "smoke-verdict.sh")
    return root


def _serving(root: Path, rc: int) -> Path:
    (root / "scripts").mkdir(parents=True)
    (root / "scripts" / "smoke.sh").write_text(
        f'printf "%s" "${{SMOKE_PHASE:-}}" > "$(dirname "$0")/../asked"\necho "PASS  its own checks"\nexit {rc}\n',
        encoding="utf-8")
    return root


def _smoke(release: Path, serving: Path | None, phase: str | None):
    env = {k: v for k, v in os.environ.items() if k not in (deploy.SMOKE_PHASE_ENV, "SMOKE_SERVING")}
    if phase:
        env[deploy.SMOKE_PHASE_ENV] = phase
    if serving is not None:
        env["SMOKE_SERVING"] = str(serving)
    return subprocess.run([BASH, str(release / "scripts" / "smoke.sh")], cwd=release, env=env, capture_output=True,
                          text=True, timeout=60)


TIGHTENED = 'no "gateway sends the new x-sohot-engine-build header"'


def test_a_check_the_new_release_tightened_does_not_fail_its_own_deploy(tmp_path):
    """The old services lack what the new release adds; their own smoke passes, so the switch goes ahead."""
    serving = _serving(tmp_path / "13-old", 0)
    got = _smoke(_release(tmp_path / "16-new", TIGHTENED), serving, "before")
    assert got.returncode == 0, got.stdout + got.stderr
    assert "FAIL  gateway sends the new x-sohot-engine-build header" in got.stdout
    assert "WARN  the serving release's own smoke passes" in got.stdout
    assert "serving  PASS  its own checks" in got.stdout
    assert (serving / "asked").read_text(encoding="utf-8") == "after"


def test_services_broken_by_their_own_release_stop_the_deploy(tmp_path):
    serving = _serving(tmp_path / "13-old", 1)
    got = _smoke(_release(tmp_path / "16-new", TIGHTENED), serving, "before")
    assert got.returncode == 1
    assert "FAIL  the serving release's own smoke fails too" in got.stdout


@pytest.mark.parametrize("phase", ["after", None], ids=["after-the-switch", "by-hand"])
def test_after_the_switch_or_by_hand_a_failure_fails_and_nothing_else_is_asked(tmp_path, phase):
    serving = _serving(tmp_path / "13-old", 0)
    got = _smoke(_release(tmp_path / "16-new", TIGHTENED), serving, phase)
    assert got.returncode == 1
    assert not (serving / "asked").exists()


def test_a_release_smoking_itself_as_the_serving_one_is_not_asked_twice(tmp_path):
    release = _release(tmp_path / "16-new", TIGHTENED)
    got = _smoke(release, release, "before")
    assert got.returncode == 1 and "serving" not in got.stdout


def test_a_passing_smoke_asks_nobody(tmp_path):
    serving = _serving(tmp_path / "13-old", 1)
    got = _smoke(_release(tmp_path / "16-new", 'ok "everything"'), serving, "before")
    assert got.returncode == 0
    assert not (serving / "asked").exists()


def test_every_way_smoke_ends_after_its_checks_start_goes_through_the_verdict():
    """The gateway readiness and key checks run new code too (model ids, key lookup), so they end the same way."""
    ends = [ln.strip() for ln in SMOKE[SMOKE.index("FAIL=0"):].splitlines()
            if re.search(r"(^|[;&|]\s*)exit\b(?! 0$)", ln.strip()) and not ln.lstrip().startswith("#")]
    assert ends == [], f"smoke.sh ends without the verdict: {ends}"
    assert "scripts/smoke-verdict.sh" in _verdict()
