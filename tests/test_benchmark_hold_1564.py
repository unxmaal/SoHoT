"""The owner's benchmark hold stops sweeps, reverifies and measurement jobs and nothing else; a launchctl-disabled unit does not fail an install. #1564."""
import argparse
import json
import sys
import time
from datetime import datetime

import pytest

from harness import cli, deploy, heartbeat, hold, morning, reverify, sweep_check, sweeps
from harness import memory_store as ms
from harness import workqueue as wq
from harness.commands import loop
from harness.commands import morning as morning_cmd
from tests.test_launchd import _install

SAID = "owner: the #1558 rebuild"


def at(day, hour, minute=0):
    return datetime(2026, 11, day, hour, minute).timestamp()


def eval_job(tmp_path, name="eval", **kw):
    """A job whose argv names evals.run but only touches a file, so the queue can really run it."""
    mark = tmp_path / name
    return wq.add([sys.executable, "-c", f"open({str(mark)!r}, 'w')", "-m", "evals.run"], title=name, **kw), mark


def test_with_a_hold_the_discover_loop_entry_returns_without_sweeping(monkeypatch, capsys):
    ran = []
    monkeypatch.setattr(loop, "_run_loop", lambda a: ran.append(a) or 0)
    a = argparse.Namespace(run=True, lane="")
    hold.hold(ms.connect(), SAID)
    assert loop._report_loop(a) == 0
    out = capsys.readouterr().out
    assert ran == [] and heartbeat.read() is None
    assert out.count("no sweep: benchmarks held since") == 1 and SAID in out
    hold.release(ms.connect())
    assert loop._report_loop(a) == 0 and len(ran) == 1


def test_a_held_eval_stays_pending_and_named_while_a_deploy_and_a_plain_job_start(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(deploy, "blocked", lambda *a, **k: "")
    conn = ms.connect()
    job, mark = eval_job(tmp_path)
    dep = wq.add(["true"], title="deploy", kind=wq.DEPLOY, conn=conn)
    plain = tmp_path / "plain"
    wq.add([sys.executable, "-c", f"open({str(plain)!r}, 'w')"], title="plain", conn=conn)
    hold.hold(conn, SAID)
    assert [j["title"] for j in wq.ready(conn)] == ["deploy", "plain"]
    assert cli.main(["jobs", "list"]) == 0
    shown = capsys.readouterr()
    text = shown.out + shown.err
    assert f"benchmarks held since" in text and SAID in text and "1 measurement job(s) wait" in text
    held_line = next(x for x in text.splitlines() if x.strip().startswith(job["id"]))
    assert "pending" in held_line and "[held: benchmarks]" in held_line
    assert dep["id"] in text and "[held" not in next(x for x in text.splitlines() if x.strip().startswith(dep["id"]))
    conn.execute("DELETE FROM jobs WHERE id = ?", (wq._key(dep["id"]),))
    conn.commit()
    got = wq.run_pending()
    assert [j["title"] for j in got] == ["plain"] and plain.exists() and not mark.exists()
    assert wq.get(job["id"])["state"] == wq.PENDING


def test_releasing_the_hold_lets_the_pending_measurement_job_start(tmp_path):
    conn = ms.connect()
    job, mark = eval_job(tmp_path)
    hold.hold(conn, SAID)
    assert wq.run_pending() == [] and wq.get(job["id"])["state"] == wq.PENDING
    hold.release(conn)
    got = wq.run_pending()
    assert [(j["id"], j["state"]) for j in got] == [(job["id"], wq.DONE)] and mark.exists()


@pytest.mark.gauntlet("state-is-whichever-row-came-last", site="harness/hold.py:active")
def test_a_second_hold_is_released_with_the_first_and_shows_the_latest_text():
    conn = ms.connect()
    hold.hold(conn, "owner: morning", now=at(7, 9))
    hold.hold(conn, SAID, now=at(7, 10))
    assert hold.active(conn, at(7, 11))["said"] == SAID
    hold.release(conn, now=at(7, 12))
    assert hold.active(conn, at(7, 12, 1)) is None


def test_a_hold_with_an_end_lifts_by_itself(tmp_path):
    conn = ms.connect()
    hold.hold(conn, SAID, until=at(8, 6), now=at(7, 20))
    assert hold.active(conn, at(7, 23)) is not None and hold.active(conn, at(8, 6)) is None
    with pytest.raises(ValueError):
        hold.hold(conn, SAID, until=at(7, 19), now=at(7, 20))


def test_despite_hold_lets_one_owner_queued_job_through(tmp_path, capsys):
    conn = ms.connect()
    hold.hold(conn, SAID)
    other, _ = eval_job(tmp_path, "other")
    mark = tmp_path / "mine"
    assert cli.main(["jobs", "add", "--despite-hold", "--", sys.executable, "-c",
                     f"open({str(mark)!r}, 'w')", "-m", "evals.run"]) == 0
    capsys.readouterr()
    mine = [j["id"] for j in wq.pending() if j["id"] != other["id"]]
    assert [j["id"] for j in wq.ready()] == mine
    assert cli.main(["hold", "let", other["id"]]) == 0
    assert sorted(j["id"] for j in wq.ready()) == sorted(mine + [other["id"]])


@pytest.mark.parametrize("job, measures", [
    ({"argv": ["uv", "run", "python", "-m", "evals.run", "--modality", "code"]}, True),
    ({"argv": ["uv", "run", "soh", "adopt", "--lane", "svg", "--challenger", "q3-30b"]}, True),
    ({"argv": ["/x/.venv/bin/python", "-m", "harness.cli", "adopt", "--confirm", "15807"]}, True),
    ({"argv": ["uv", "run", "soh", "reverify", "--lane", "code"]}, True),
    ({"argv": ["/x/deploy/.venv/bin/soh", "--json", "adopt", "--lane", "code"]}, True),
    ({"argv": ["uv", "run", "python", "-m", "evals.run_report"]}, False),
    ({"argv": ["uv", "run", "lh", "discover", "--loop", "--run"]}, True),
    ({"argv": ["sh", "-c", "test -f x && uv run python -m evals.run --modality repo"]}, True),
    ({"argv": ["anything"], "requested_by": "sweep"}, True),
    ({"argv": ["uv", "run", "soh", "report", "--publish"]}, False),
    ({"argv": ["uv", "run", "soh", "cases", "import", "librispeech"]}, False),
    ({"argv": ["uv", "run", "python", "-m", "harness.cli", "deploy", "run", "abc"], "kind": "deploy",
      "requested_by": "deploy"}, False),
])
def test_what_counts_as_measurement(job, measures):
    assert hold.measurement(job) is measures


def _entry():
    return {"lane": "code", "spec": "q3", "triggers": ["age"], "skip": "", "argv": ["x"], "candidate_id": 1,
            "incumbent": "", "baseline_run_id": None}


def test_reverify_queues_no_new_rerun_while_held(monkeypatch):
    conn = ms.connect()
    monkeypatch.setattr(reverify, "settle", lambda *a, **k: [])
    monkeypatch.setattr(reverify, "plan", lambda *a, **k: [_entry()])
    queued = []
    monkeypatch.setattr(reverify, "_queue", lambda c, e, now, add: queued.append(e) or {**e, "job": "0001"})
    hold.hold(conn, SAID)
    got = reverify.check(conn, facts={}, add=lambda *a, **k: None)
    assert queued == [] and got["queued"] == [] and SAID in got["held"]
    hold.release(conn)
    assert reverify.check(conn, facts={}, add=lambda *a, **k: None)["queued"] and len(queued) == 1


def test_knob_sweeps_queue_nothing_while_held(monkeypatch):
    conn = ms.connect()
    monkeypatch.setattr(sweeps, "settle", lambda *a, **k: [])
    monkeypatch.setattr(sweeps, "plan", lambda *a, **k: [{"skip": "", "argv": [["x"]]}])
    queued = []
    monkeypatch.setattr(sweeps, "_queue", lambda c, e, now, add: queued.append(e) or e)
    hold.hold(conn, SAID)
    got = sweeps.check(conn)
    assert queued == [] and SAID in got["held"]
    hold.release(conn)
    sweeps.check(conn)
    assert len(queued) == 1


def test_the_sweep_check_reads_a_held_night_as_quiet_but_still_sees_a_stall():
    now, unit = at(7, 23), {"loaded": True, "state": "waiting", "runs": 1}
    line = hold.line({"held_at": at(7, 10), "said": SAID, "until": None})
    got = sweep_check.check(now=now, unit=unit, beat={}, hours=[21], held=line)
    assert got["verdict"] == sweep_check.HELD and SAID in got["line"]
    assert not sweep_check.should_notify(got, "")
    assert sweep_check.check(now=now, unit=unit, beat={}, hours=[21])["verdict"] == sweep_check.NEVER
    stalled = {"pid": 1, "started": at(7, 21), "updated": at(7, 21), "tier": "measure", "step": 3, "total": 9}
    got = sweep_check.check(now=now, unit=unit, beat=stalled, hours=[21], held=line, alive=lambda pid: True)
    assert got["verdict"] == sweep_check.STALLED


def test_morning_names_the_hold_instead_of_a_missing_sweep(monkeypatch):
    monkeypatch.setattr(morning, "_gh", lambda argv: "[]")
    rep = {"since": at(7, 8), "sweep": {"loop": None, "screened": {}, "measured": {"runs": [], "verdicts": {}},
                                       "paused": [], "stopped": [], "settled": {"verdicts": {}, "adopted": []}},
           "watchdog": [], "ci": {"available": False, "why": "-"}, "ledger": None, "stale": [],
           "deploy": {"available": False, "why": "-"}}
    assert "no discovery sweep ran last night" in morning.needs(rep)
    rep["hold"] = hold.line({"held_at": at(7, 10), "said": SAID, "until": None})
    got = morning.needs(rep)
    assert "no discovery sweep ran last night" not in got and any(SAID in x and "soh hold release" in x for x in got)
    assert [x for x in morning_cmd.render(rep) if x.startswith("held ")] == [f"held      {rep['hold']}"]
    conn = ms.connect()
    hold.hold(conn, SAID)
    assert SAID in morning.gather(conn, time.time(), time.time() - 3600)["hold"]


def test_the_cli_holds_shows_and_releases(capsys):
    assert cli.main(["hold", "status"]) == 0
    assert "no hold" in capsys.readouterr().out
    assert cli.main(["hold", "benchmarks"]) != 0
    capsys.readouterr()
    assert cli.main(["hold", "benchmarks", SAID, "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["hold"]["said"] == SAID
    assert cli.main(["hold", "status"]) == 0
    assert SAID in capsys.readouterr().out
    assert cli.main(["hold", "release"]) == 0
    assert "released" in capsys.readouterr().out
    assert hold.active(ms.connect()) is None


DISCOVER = "com.unxmaal.localharness.discover"


def _run_install(tmp_path, disabled=(), extra_env=None):
    import subprocess
    argv, env = _install(tmp_path, run=False, extra_env=extra_env)
    for label in disabled:
        (tmp_path / "state" / f"{label}.disabled").touch()
    got = subprocess.run(argv, env=env, capture_output=True, text=True, timeout=120)
    return got, (tmp_path / "state" / "log").read_text(encoding="utf-8").splitlines()


def test_install_with_a_launchctl_disabled_unit_warns_and_succeeds(tmp_path):
    got, calls = _run_install(tmp_path, disabled=(DISCOVER,))
    assert got.returncode == 0, got.stderr[-1500:]
    assert f"NOT loading {DISCOVER}: launchctl disable is in force" in got.stderr
    assert f"launchctl enable gui/" in got.stderr and "not loaded:" not in got.stderr
    assert not [c for c in calls if c.startswith("bootstrap") and c.endswith(".discover.plist")], calls
    assert "loaded com.unxmaal.localharness.gateway" in got.stdout


def test_install_still_fails_on_a_unit_that_will_not_load_for_another_reason(tmp_path):
    got, _ = _run_install(tmp_path, extra_env={"FAKE_FAIL_ALWAYS": DISCOVER})
    assert got.returncode != 0
    assert "not loaded: discover" in got.stderr and "launchctl disable" not in got.stderr
