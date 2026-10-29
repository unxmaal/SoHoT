"""A queued job's delegation is not refused by its own job's lock, and a refusal names the holder's job. #1349."""
import os
import subprocess
import sys
import time

import pytest

from evals import claims_judge
from harness import delegate, exclusive, pressure
from harness import workqueue as wq
from tests.test_mcp_delegate import fake  # noqa: F401

SCHEMA = {"urgent": {"type": "boolean", "description": "needs action today"}}


def _running(title):
    job = wq.add(["sh", "-c", "true"], title=title)
    job.update(state=wq.RUNNING, started=time.strftime(wq._STAMP))
    wq._write(job)
    return job


def _hold(job_id=None, kind="external"):
    env = {k: v for k, v in os.environ.items() if k not in (wq.JOB_ENV, exclusive.HELD_ENV)}
    if job_id is not None:
        env[wq.JOB_ENV] = str(int(job_id))
    code = ("from harness import exclusive; import time\n"
            f"with exclusive.held({kind!r}):\n print('held', flush=True); time.sleep(30)\n")
    child = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True, env=env)
    assert child.stdout.readline().strip() == "held"
    return child


@pytest.fixture
def stop():
    children = []
    yield children.append
    for c in children:
        c.kill()
        c.wait()


@pytest.fixture
def not_resident(monkeypatch):
    monkeypatch.setattr(pressure, "sample", lambda *a, **k: pressure.Pressure(level=pressure.NORMAL))
    monkeypatch.setattr(delegate, "loaded", lambda where, **k: False)


def test_a_delegation_from_the_job_that_holds_the_lock_goes(fake, not_resident, stop, monkeypatch):  # noqa: F811
    job = _running("claims judge")
    stop(_hold(job["id"]))
    monkeypatch.setenv(wq.JOB_ENV, str(int(job["id"])))
    monkeypatch.delenv(exclusive.HELD_ENV, raising=False)
    assert delegate.busy() == ""
    delegate.complete("code", "write add")
    assert len(fake.seen) == 1


def test_another_jobs_lock_still_refuses_naming_that_job(fake, not_resident, stop, monkeypatch):  # noqa: F811
    holder = _running("decide eval")
    mine = _running("claims judge")
    stop(_hold(holder["id"]))
    monkeypatch.setenv(wq.JOB_ENV, str(int(mine["id"])))
    with pytest.raises(delegate.Refused) as got:
        delegate.decide("is it urgent?", SCHEMA)
    assert f"job {holder['id']} (decide eval)" in str(got.value)
    assert f"job {mine['id']}" not in str(got.value)
    assert fake.seen == []


def test_a_lock_held_outside_any_job_does_not_name_the_callers_job(fake, not_resident, stop, monkeypatch):  # noqa: F811
    mine = _running("claims #655: calibrate the decide-lane claims judge")
    stop(_hold(None))
    monkeypatch.setenv(wq.JOB_ENV, str(int(mine["id"])))
    with pytest.raises(delegate.Refused, match="busy with external") as got:
        delegate.decide("is it urgent?", SCHEMA)
    assert f"job {mine['id']}" not in str(got.value)
    assert "calibrate" not in str(got.value)


def test_the_claims_judge_asks_holding_the_machine(monkeypatch):
    seen = []

    def ask(case, user, claim, refs):
        seen.append((os.environ.get(exclusive.HELD_ENV), exclusive.holder().get("kind")))
        return "supported"
    monkeypatch.delenv(exclusive.HELD_ENV, raising=False)
    monkeypatch.setattr(claims_judge, "_claims_cases", lambda root=None: ["case"])
    monkeypatch.setattr(claims_judge, "judge_spec", lambda: "fake")
    monkeypatch.setattr(claims_judge, "write_calibration", lambda result, root=None: None)
    monkeypatch.setattr(claims_judge, "render", lambda result: "")
    monkeypatch.setattr(claims_judge, "ask_local", ask)
    monkeypatch.setattr(claims_judge, "calibrate", lambda cases, ask, judge: ask(None, "u", "c", [1]))
    assert claims_judge.main(["calibrate"]) == 0
    assert seen == [("1", "eval")]
    assert os.environ.get(exclusive.HELD_ENV) is None
