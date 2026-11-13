"""A rollback records the audit checks its failed step named; the poll retries no rolled-back sha (#1913). #1805."""
from __future__ import annotations

import json
import time

import pytest

from harness import deploy, deploy_hold
from harness import workqueue as wq
from tests.test_deploy_1506 import _commit, _green, _worker_runs, posix, world  # noqa: F401 - world is a fixture
from tests.test_deploy_wait_1672 import _leads  # noqa: F401 - autouse fixture

INSTALL = """echo "reinstall $(basename "$(pwd -P)")" >> "$DEPLOY_LOG"
[ -f fail-install ] && { echo "launchctl bootstrap: Input/output error"; exit 1; }
if [ -f fail-audit ]; then
  echo "  ok   sweep_on_schedule"
  sed 's/^/  FAIL /' fail-audit
  echo "NOT OK"
  exit 1
fi
"""
REVISITABLE = ("revisitable: 2: verdict 20261 t-evoteam:llamacpp:Ornith: plan:Ornith is met here, after the loop's "
               "requeue at 2026-11-10 21:39; verdict 20262 t-kl:llamacpp:Ornith: plan:Ornith is met here\n")


def _rolled_back(w, files: dict) -> dict:
    """Queue the commit, run its deploy to a rollback, settle it; the failed job."""
    _commit(w["work"], {"scripts/launchd.sh": INSTALL, **files}, "next")
    job = deploy.poll(src=w["link"], green=_green, environ={})["queued"]
    _worker_runs(job, w)
    assert [d["outcome"] for d in wq.settle_deploys()] == [deploy.ROLLED_BACK]
    assert wq.get(job["id"])["state"] == wq.FAILED
    return job


def _poll(w, said: list, after: float = deploy.RETRY_S + 1) -> dict:
    return deploy.poll(src=w["link"], green=_green, environ={}, now=time.time() + after, alert=said.append)


def _record(job) -> dict:
    with wq._store() as c:
        row = c.execute("SELECT id FROM deploys WHERE job_id = ?", (int(job["id"]),)).fetchone()
    return json.loads(deploy.record_path(row[0]).read_text(encoding="utf-8"))


def test_the_failing_checks_and_their_verdicts_are_read_from_the_audit_lines():
    text = ("FAIL  mcp at [::1]:8899 refuses\nFAIL  smoke: the gateway is down\n  ok   adoptions_pass_here\n  FAIL "
            + REVISITABLE
            + "  FAIL sweep_on_schedule: last discovery loop started 1d ago\n  warn gateway_errors: 1 row dropped\n")
    assert deploy_hold.failed(text) == {"revisitable": [20261, 20262], "sweep_on_schedule": []}


@pytest.mark.sqlite_store
@posix
def test_a_rollback_on_an_audit_check_records_the_checks_and_is_not_retried(world):
    job = _rolled_back(world, {"fail-audit": REVISITABLE})
    assert _record(job)["audit_failed"] == {"revisitable": [20261, 20262]}
    said = []
    got = _poll(world, said)
    assert got["queued"] is None and "soh deploy now" in got["why"] and said == []
