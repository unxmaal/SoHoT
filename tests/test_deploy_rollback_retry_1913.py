"""The poll never queues a sha whose deploy rolled back again, and alerts it once; `soh deploy now SHA` does. #1913."""
from __future__ import annotations

import shlex
import time

import pytest

from harness import cli, deploy, deploy_retry
from harness import deploy_state as ds
from harness import memory_store as ms
from harness import workqueue as wq
from harness.commands import deploy as deploy_cmd
from tests.test_deploy_1506 import _commit, _green, _worker_runs, posix, world  # noqa: F401 - world is a fixture
from tests.test_deploy_wait_1672 import _leads  # noqa: F401 - autouse fixture

INSTALL = """echo "reinstall $(basename "$(pwd -P)")" >> "$DEPLOY_LOG"
[ -f fail-install ] && { echo "launchctl bootstrap: Input/output error"; exit 1; }
true
"""


def _poll(w, said: list, after: float, **kw) -> dict:
    return deploy.poll(src=w["link"], green=_green, environ={}, now=time.time() + after, alert=said.append, **kw)


def _alerts(w) -> list[str]:
    return [ln for ln in w["log"].read_text(encoding="utf-8").splitlines() if ln.startswith("alert ")]


def _rolled_back(w) -> dict:
    """One poll queues a release whose install exits 1; the worker runs it to a rollback and settles it."""
    _commit(w["work"], {"scripts/launchd.sh": INSTALL, "fail-install": ""}, "install exits 1")
    said: list = []
    job = _poll(w, said, 0)["queued"]
    assert job is not None and said == []
    _worker_runs(job, w)
    assert [d["outcome"] for d in wq.settle_deploys()] == [deploy.ROLLED_BACK]
    assert wq.get(job["id"])["state"] == wq.FAILED
    return job


@pytest.mark.sqlite_store
@posix
def test_the_poll_after_a_rollback_queues_nothing_and_alerts_nothing(world):
    job = _rolled_back(world)
    assert len(_alerts(world)) == 1
    said: list = []
    for after in (deploy.RETRY_S + 1, deploy.RETRY_S * 2 + 1, deploy.RETRY_S * (deploy.RETRIES + 2)):
        got = _poll(world, said, after)
        assert got["queued"] is None and deploy_retry.command(job["output"]) in got["why"]
    assert said == [] and len(_alerts(world)) == 1
    with wq._store() as c:
        assert len(deploy._jobs_for(c, job["output"])) == 1


@pytest.mark.gauntlet("state-is-whichever-row-came-last", site="harness/deploy_retry.py:rolled_back")
@pytest.mark.sqlite_store
@posix
def test_a_later_deploy_of_the_sha_that_failed_otherwise_does_not_clear_its_rollback(world):
    job = _rolled_back(world)
    sha = job["output"]
    with wq._store() as c:
        later = deploy._insert(c, sha, None, world["link"], world["first"], time.time())
        assert deploy.move(c, later, ds.BUILDING, ds.FAILED, ds.JOB, detail="sync failed", finished_at=time.time())
        assert deploy_retry.rolled_back(c, sha)["outcome"] == ds.ROLLED_BACK
    got = _poll(world, [], deploy.RETRY_S + 1)
    assert got["queued"] is None and deploy_retry.command(sha) in got["why"]


@pytest.mark.gauntlet("state-is-whichever-row-came-last", site="harness/deploy_retry.py:rolled_back")
def test_a_rollback_on_another_machine_or_unstamped_does_not_stop_this_one():
    conn = ms.connect()
    try:
        ms.remember_machine(conn)
        other = conn.execute("INSERT INTO machines (fingerprint, hw_model, os, arch, first_seen, last_seen) "
                             "VALUES ('other/macOS/arm64', 'other', 'macOS', 'arm64', 0, 0)").lastrowid
        for mid in (other, None):
            conn.execute("INSERT INTO deploys (sha, machine_id, stage, outcome, started_at) VALUES (?,?,?,?,?)",
                         ("a" * 40, mid, ds.ROLLED_BACK, ds.ROLLED_BACK, 1.0))
        conn.commit()
        assert deploy_retry.rolled_back(conn, "a" * 40) is None and deploy_retry.why(conn, "a" * 40) == ""
    finally:
        conn.close()


@pytest.mark.sqlite_store
@posix
def test_the_rollback_alert_names_the_command_that_deploys_the_sha_again(world):
    job = _rolled_back(world)
    (line,) = _alerts(world)
    cmd = deploy_retry.command(job["output"])
    assert line.endswith(f"`{cmd}` does")
    words = shlex.split(cmd)
    assert words[0] == "soh"
    a = cli.build_parser().parse_args(words[1:])
    assert a.func is deploy_cmd.cmd_deploy and (a.action, a.sha) == ("now", job["output"])
    got = deploy.poll(src=world["link"], sha=a.sha, force=True, green=_green, environ={})
    assert got["queued"] is not None and got["queued"]["output"] == job["output"]


@pytest.mark.sqlite_store
@posix
def test_a_newer_main_sha_deploys_past_one_that_rolled_back(world):
    job = _rolled_back(world)
    said: list = []
    assert _poll(world, said, deploy.RETRY_S + 1)["queued"] is None
    head = _commit(world["work"], {"fail-install": None, "f": "fixed\n"}, "fix")
    got = _poll(world, said, deploy.RETRY_S + 1)
    assert got["queued"] is not None and got["queued"]["output"] == head != job["output"] and said == []


@pytest.mark.sqlite_store
@posix
def test_a_deploy_that_failed_before_the_switch_is_still_retried(world):
    _commit(world["work"], {"fail-smoke": ""}, "smoke fails before the switch")
    said: list = []
    job = _poll(world, said, 0)["queued"]
    _worker_runs(job, world)
    wq.settle_deploys()
    assert wq.get(job["id"])["state"] == wq.FAILED
    with wq._store() as c:
        assert deploy_retry.rolled_back(c, job["output"]) is None
    got = _poll(world, said, deploy.RETRY_S + 1)
    assert got["queued"] is not None and got["queued"]["output"] == job["output"]
