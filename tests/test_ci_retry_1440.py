"""A DNS blip during dependency install retries instead of failing the nightly (#1440)."""
import os
import subprocess
from pathlib import Path

import pytest
import yaml

from tests import shells

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ci-retry.sh"
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))

BASH = shells.resolve("bash")
needs_bash = pytest.mark.skipif(BASH is None, reason="needs bash")


def _steps():
    for wf in WORKFLOWS:
        doc = yaml.safe_load(wf.read_text(encoding="utf-8"))
        for name, job in doc.get("jobs", {}).items():
            for step in job.get("steps", []):
                yield wf.name, name, step.get("run", ""), doc


def test_every_uv_sync_in_ci_goes_through_the_retry():
    seen = []
    for wf, job, run, _ in _steps():
        for line in run.splitlines():
            if "uv sync" in line:
                seen.append((wf, job))
                assert line.strip().startswith("bash scripts/ci-retry.sh uv sync"), (wf, job, line)
    assert len(seen) >= 4, seen


def test_every_workflow_that_syncs_gives_each_uv_download_more_retries():
    for wf, _, run, doc in _steps():
        if "uv sync" in run:
            assert int(doc.get("env", {}).get("UV_HTTP_RETRIES", 0)) >= 6, wf


def _run(tmp_path, fail_times, attempts="3"):
    count = tmp_path / "count"
    count.write_text("0", encoding="utf-8")
    cmd = (f'n=$(cat "{count.as_posix()}"); n=$((n+1)); echo $n > "{count.as_posix()}"; '
           f'[ $n -gt {fail_times} ] || exit 7')
    env = dict(os.environ, CI_RETRY_ATTEMPTS=attempts, CI_RETRY_DELAY="0")
    proc = subprocess.run([BASH, SCRIPT.as_posix(), BASH, "-c", cmd],
                          capture_output=True, text=True, env=env, timeout=60)
    return proc, int(count.read_text(encoding="utf-8"))


@needs_bash
def test_a_transient_failure_is_retried_until_it_passes(tmp_path):
    proc, ran = _run(tmp_path, fail_times=2)
    assert proc.returncode == 0, proc.stderr
    assert ran == 3


@needs_bash
def test_a_success_runs_once(tmp_path):
    proc, ran = _run(tmp_path, fail_times=0)
    assert proc.returncode == 0 and ran == 1


@needs_bash
def test_a_persistent_failure_still_fails_with_the_commands_status(tmp_path):
    proc, ran = _run(tmp_path, fail_times=99)
    assert proc.returncode == 7
    assert ran == 3
    assert "failed 3 times" in proc.stderr
