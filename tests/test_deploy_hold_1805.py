"""A sha that rolled back on audit checks reading unchanged inputs is held, not retried; a transient failure still is. #1805."""
from __future__ import annotations

import json
import time

import pytest

from harness import deploy, deploy_hold, heartbeat, live_audit
from harness import memory_store as ms
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


@pytest.mark.gauntlet("a-closed-table-fronting-an-open-set", site="harness/live_audit.py:REPAIRED_BY")
def test_a_verdict_check_no_loop_step_repairs_reads_the_newest_verdict_and_one_it_does_reads_its_repair():
    assert "terminal_reason_coherent" in live_audit.VERDICTS and "terminal_reason_coherent" not in live_audit.REPAIRED_BY
    conn = ms.connect()
    try:
        checks = {"terminal_reason_coherent": [], "revisitable": []}
        was = deploy_hold.inputs(conn, checks, data={})
        conn.execute("INSERT INTO verdicts (outcome, decided_at) VALUES ('declined', 1.0)")
        conn.commit()
        now = deploy_hold.inputs(conn, checks, data={})
        assert now["terminal_reason_coherent"] != was["terminal_reason_coherent"]
        assert now["revisitable"] == was["revisitable"]
        assert deploy_hold.inputs(conn, {**checks, "served_matches_adoption": []}, data={}) is None
    finally:
        conn.close()


@pytest.mark.sqlite_store
@posix
def test_a_sha_rolled_back_on_an_audit_check_is_held_while_its_inputs_are_unchanged(world):
    job = _rolled_back(world, {"fail-audit": REVISITABLE})
    rec = _record(job)
    assert rec["audit_failed"] == {"revisitable": [20261, 20262]} and set(rec["held_inputs"]) == {"revisitable"}
    said = []
    for after in (deploy.RETRY_S + 1, deploy.RETRY_S * 2):
        got = _poll(world, said, after)
        assert got["queued"] is None and "held: deploy" in got["why"] and "revisitable" in got["why"]
    assert len(said) == 1 and said[0].startswith("held: deterministic audit failure, waiting for a newer sha")


@pytest.mark.sqlite_store
@posix
def test_a_held_sha_is_retried_once_what_its_check_reads_changes(world):
    job = _rolled_back(world, {"fail-audit": REVISITABLE})
    said = []
    assert _poll(world, said)["queued"] is None
    heartbeat._write({**(heartbeat.read() or {}), live_audit.REPAIRED_BY["revisitable"]: time.time()})
    got = _poll(world, said)
    assert got["queued"] is not None and got["queued"]["output"] == job["output"]


@pytest.mark.sqlite_store
@posix
def test_a_newer_green_sha_deploys_past_a_held_one(world):
    job = _rolled_back(world, {"fail-audit": REVISITABLE})
    said = []
    assert _poll(world, said)["queued"] is None
    head = _commit(world["work"], {"fail-audit": None, "f": "fixed\n"}, "fix")
    got = _poll(world, said)
    assert got["queued"] is not None and got["queued"]["output"] == head != job["output"]


@pytest.mark.sqlite_store
@posix
@pytest.mark.parametrize("files", [{"fail-install": ""},
                                   {"fail-audit": "served_matches_adoption: the gateway serves q3 not q4\n"}],
                         ids=["install-crash", "check-with-unknown-inputs"])
def test_a_transient_rollback_is_retried_as_before(world, files):
    job = _rolled_back(world, files)
    said = []
    got = _poll(world, said)
    assert got["queued"] is not None and got["queued"]["output"] == job["output"] and said == []
