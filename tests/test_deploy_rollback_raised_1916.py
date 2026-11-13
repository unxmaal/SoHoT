"""A switch whose rollback raised ends rollback_raised, which the poll never retries; `soh deploy now SHA` does. #1916."""
from __future__ import annotations

import shlex

import pytest

from harness import cli, deploy, deploy_retry, deploy_switch
from harness import deploy_state as ds
from harness import workqueue as wq
from harness.commands import deploy as deploy_cmd
from tests.test_deploy_1506 import _commit, _green, _worker_runs, posix, world  # noqa: F401 - world is a fixture
from tests.test_deploy_rollback_retry_1913 import INSTALL, _alerts, _poll
from tests.test_deploy_wait_1672 import _leads  # noqa: F401 - autouse fixture


def _raised(w, monkeypatch) -> dict:
    """One poll queues a release whose install exits 1; its rollback install raises; the worker settles it."""
    real = deploy_switch._step

    def step(rec, argv, cwd, timeout, log, what, **kw):
        if what == "rollback install":
            raise KeyError("rollback_install")
        return real(rec, argv, cwd, timeout, log, what, **kw)
    monkeypatch.setattr(deploy_switch, "_step", step)
    _commit(w["work"], {"scripts/launchd.sh": INSTALL, "fail-install": ""}, "install exits 1")
    said: list = []
    job = _poll(w, said, 0)["queued"]
    assert job is not None and said == []
    _worker_runs(job, w)
    assert [d["outcome"] for d in wq.settle_deploys()] == [ds.ROLLBACK_RAISED]
    assert wq.get(job["id"])["state"] == wq.FAILED
    return job


@pytest.mark.gauntlet("a-wait-with-no-deadline-owner-or-end-state", site="harness/deploy_state.py:MOVES:rollback_raised")
@pytest.mark.sqlite_store
@posix
def test_two_polls_past_the_retry_delay_after_a_raised_rollback_queue_nothing_and_alert_once(world, monkeypatch):
    job = _raised(world, monkeypatch)
    assert len(_alerts(world)) == 1
    said: list = []
    for after in (deploy.RETRY_S + 1, deploy.RETRY_S * 2 + 1):
        got = _poll(world, said, after)
        assert got["queued"] is None and got["why"].startswith(f"{job['output'][:12]} {ds.ROLLBACK_RAISED} as deploy ")
    assert said == [] and len(_alerts(world)) == 1
    with wq._store() as c:
        assert len(deploy._jobs_for(c, job["output"])) == 1


@pytest.mark.sqlite_store
@posix
def test_the_record_still_says_failed_for_an_older_settle_and_the_row_says_rollback_raised(world, monkeypatch):
    job = _raised(world, monkeypatch)
    with wq._store() as c:
        row = c.execute("SELECT id, outcome, stage FROM deploys WHERE sha = ?", (job["output"],)).fetchone()
    assert (row["outcome"], row["stage"]) == (ds.ROLLBACK_RAISED, ds.ROLLBACK_RAISED)
    rec = deploy_switch.load(deploy.record_path(row["id"]))
    assert rec["outcome"] == ds.FAILED and rec["rollback_raised"] == "KeyError: 'rollback_install'"
    assert "the rollback itself failed at flipped_back" in rec["detail"]


@pytest.mark.sqlite_store
@posix
def test_the_raised_rollback_alert_names_its_outcome_and_the_command_that_deploys_the_sha_again(world, monkeypatch):
    job = _raised(world, monkeypatch)
    (line,) = _alerts(world)
    cmd = deploy_retry.command(job["output"])
    assert f" {ds.ROLLBACK_RAISED}: " in line and line.endswith(f"`{cmd}` does")
    a = cli.build_parser().parse_args(shlex.split(cmd)[1:])
    assert a.func is deploy_cmd.cmd_deploy and (a.action, a.sha) == ("now", job["output"])
    got = deploy.poll(src=world["link"], sha=a.sha, force=True, green=_green, environ={})
    assert got["queued"] is not None and got["queued"]["output"] == job["output"]


def test_only_a_failed_record_that_says_its_rollback_raised_reads_rollback_raised():
    assert ds.outcome_of({"outcome": ds.FAILED, "rollback_raised": "OSError: x"}) == ds.ROLLBACK_RAISED
    assert ds.outcome_of({"outcome": ds.FAILED}) == ds.FAILED
    assert ds.outcome_of({"outcome": ds.FAILED, "stage": ds.FAILED, "restore_failed": "x"}) == ds.FAILED_FORWARD
    assert ds.ROLLBACK_RAISED in deploy_retry.FINAL and ds.ROLLBACK_RAISED not in ds.EXPECT
    ds.check(ds.HANDED_OFF, ds.ROLLBACK_RAISED, ds.SETTLE)
    ds.check(ds.HANDED_OFF, ds.FAILED, ds.SETTLE)
