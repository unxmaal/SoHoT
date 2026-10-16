"""A queued job can name its earliest start, so long work queued by day waits for night. #900."""
import json
import sys
from datetime import datetime

import pytest

from harness import cli, exclusive, heartbeat, watchdog, workqueue as wq


def at(day, hour, minute=0):
    return datetime(2026, 10, day, hour, minute).timestamp()


@pytest.fixture(autouse=True)
def _night_at_21(monkeypatch):
    monkeypatch.delenv(exclusive.HELD_ENV, raising=False)
    monkeypatch.setattr(heartbeat, "discover_hours", lambda: [21])
    monkeypatch.setattr(watchdog, "DAY_START_HOUR", 8)
    monkeypatch.setattr(watchdog, "DAY_END_HOUR", 21)


def py(code):
    return [sys.executable, "-c", code]


def test_a_night_job_queued_at_15_waits_while_the_gate_is_open_and_runs_at_21(tmp_path):
    night, day = tmp_path / "night", tmp_path / "day"
    wq.add(py(f"open({str(night)!r}, 'w')"), title="long",
           not_before=wq.start_at("night", now=at(16, 15)))
    wq.add(py(f"open({str(day)!r}, 'w')"), title="short")
    got = wq.run_pending(clock=lambda: at(16, 15, 1))
    assert [j["title"] for j in got] == ["short"] and day.exists() and not night.exists()
    assert [j["title"] for j in wq.pending()] == ["long"]
    assert wq.run_pending(clock=lambda: at(16, 20, 59)) == []
    got = wq.run_pending(clock=lambda: at(16, 21))
    assert [(j["title"], j["state"]) for j in got] == [("long", wq.DONE)] and night.exists()


def test_the_worker_does_not_wake_for_a_job_that_is_not_due(tmp_path):
    wq.add(py("pass"), not_before=at(16, 21))
    asked = []
    wq.serve(gate_fn=lambda: asked.append(1) or (True, ""), forever=False,
             clock=lambda: at(16, 15))
    assert asked == [] and wq.pending()[0]["state"] == wq.PENDING


@pytest.mark.parametrize("now, want", [
    (at(16, 15), at(16, 21)),
    (at(16, 8), at(16, 21)),
    (at(16, 23), at(16, 23)),
    (at(17, 3), at(17, 3)),
    (at(17, 7, 59), at(17, 7, 59)),
])
def test_night_is_from_the_discover_hour_until_the_day_starts(now, want):
    assert wq.night_start(now) == want


def test_night_follows_the_installed_discover_hours(monkeypatch):
    monkeypatch.setattr(heartbeat, "discover_hours", lambda: [22, 12])
    assert wq.night_start(at(16, 21, 30)) == at(16, 22)


def test_a_clock_time_already_past_today_means_tomorrow():
    assert wq.start_at("16:30", now=at(16, 15)) == at(16, 16, 30)
    assert wq.start_at("14:00", now=at(16, 15)) == at(17, 14)
    assert wq.start_at("", now=at(16, 15)) is None
    with pytest.raises(ValueError):
        wq.start_at("25:00", now=at(16, 15))


def test_the_cli_takes_night_and_not_before_and_lists_the_start(capsys, monkeypatch):
    monkeypatch.setattr(wq.time, "time", lambda: at(16, 15))
    assert cli.main(["jobs", "add", "--night", "--json", "--", "true"]) == 0
    assert json.loads(capsys.readouterr().out)["job"]["not_before"] == "2026-10-16T21:00:00"
    assert cli.main(["jobs", "add", "--not-before", "16:45", "--json", "--", "true"]) == 0
    assert json.loads(capsys.readouterr().out)["job"]["not_before"] == "2026-10-16T16:45:00"
    assert cli.main(["jobs", "add", "--not-before", "noon", "--", "true"]) != 0
    capsys.readouterr()
    assert cli.main(["jobs", "list"]) == 0
    shown = capsys.readouterr()
    text = shown.out + shown.err
    assert "from 2026-10-16 21:00" in text and "2 waiting for their start time" in text


def test_an_mcp_job_with_a_start_says_it_waits_for_it(monkeypatch):
    mcp_server = pytest.importorskip("harness.mcp_server")
    monkeypatch.setattr(wq.time, "time", lambda: at(16, 15))
    job = mcp_server.image("a fox", start="night")
    assert wq.get(job.job)["not_before"] == "2026-10-16T21:00:00"
    assert "start time" in mcp_server.job_status(job.job).waiting_for
    with pytest.raises(Exception, match="HH:MM"):
        mcp_server.video("a fox", start="later")
