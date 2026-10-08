"""What the discovery loop is doing while it runs, and whether it is still alive. #251."""
import argparse
import contextlib
import io
import json
import os

import pytest

from harness import heartbeat as hb
from harness import report


class Clock:
    def __init__(self, t=1_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


@pytest.fixture
def clock(monkeypatch):
    c = Clock()
    monkeypatch.setattr(hb, "clock", c)
    return c


def test_a_beat_records_tier_candidate_and_step_n_of_m(clock):
    hb.start(lane="code", total=9)
    clock.t += 30
    hb.beat("measure", step=9, candidate="org/model", item=2, items=3)
    got = hb.read()
    assert got["tier"] == "measure" and got["candidate"] == "org/model"
    assert (got["step"], got["total"], got["item"], got["items"]) == (9, 9, 2, 3)
    assert got["lane"] == "code" and got["pid"] == os.getpid()
    assert got["started"] == 1_000_000.0 and got["updated"] == 1_000_030.0
    assert got["state"] == hb.RUNNING


def test_the_file_lives_under_the_harness_home(clock, _home):
    hb.start(lane="", total=3)
    assert hb.path().parent == _home and hb.path().exists()


def test_a_fresh_beat_reads_as_running(clock):
    hb.start(lane="code", total=9)
    hb.beat("screen", step=8)
    clock.t += hb.STALL_S - 1
    assert hb.status(hb.read()) == "running"


def test_a_beat_older_than_the_threshold_reads_as_stalled(clock):
    hb.start(lane="code", total=9)
    hb.beat("measure", step=9, candidate="org/model")
    clock.t += hb.STALL_S + 1
    assert hb.status(hb.read()) == "stalled"
    line = hb.summary()["line"]
    assert "stalled" in line and "org/model" in line and "running" not in line


def test_a_loop_whose_process_is_gone_reads_as_stalled_at_once(clock):
    hb.start(lane="code", total=9)
    hb.beat("fetch", step=7)
    assert hb.status(hb.read(), alive=lambda pid: False) == "stalled"


def test_finishing_marks_it_finished_with_the_exit_code(clock):
    hb.start(lane="code", total=9)
    hb.beat("screen", step=8)
    clock.t += 60
    hb.finish(rc=1)
    got = hb.read()
    assert got["state"] == hb.FINISHED and got["rc"] == 1
    assert got["finished"] == clock.t
    clock.t += hb.STALL_S * 10
    assert hb.status(got) == "finished"
    assert "finished" in hb.summary()["line"]


def test_another_process_cannot_finish_this_loops_heartbeat(clock):
    hb.start(lane="code", total=9)
    data = hb.read()
    data["pid"] = os.getpid() + 1
    hb.path().write_text(json.dumps(data), encoding="utf-8")
    hb.finish(rc=0)
    assert hb.read()["state"] == hb.RUNNING


def test_no_heartbeat_means_no_summary(clock):
    assert hb.read() is None and hb.summary() is None


def test_a_corrupt_heartbeat_reads_as_none(clock):
    hb.path().write_text("{not json", encoding="utf-8")
    assert hb.read() is None


def test_the_summary_says_how_long_since_progress(clock):
    hb.start(lane="image", total=9)
    hb.beat("measure", step=9, candidate="c", item=1, items=2)
    clock.t += 12 * 60
    s = hb.summary()
    assert s["status"] == "running" and s["age_s"] == 12 * 60
    assert "measure" in s["line"] and "step 9 of 9" in s["line"]
    assert "1 of 2" in s["line"] and "12m" in s["line"]


# --- the loop writes it ----------------------------------------------------

def _quiet(fn, *a):
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return fn(*a)


def test_the_loop_beats_each_step_and_finishes(monkeypatch, clock):
    from harness.commands import discover as discover_cmd, loop
    seen = []

    def step(a):
        clock.t += 5
        seen.append(dict(hb.read()))
        return 0
    monkeypatch.setattr(discover_cmd, "cmd_discover", step)
    assert _quiet(loop._report_loop,
                  argparse.Namespace(run=False, lane="ocr", top=1, json=False)) == 0
    assert [s["tier"] for s in seen] == ["sweep", "queue"]
    assert all(s["state"] == hb.RUNNING and s["lane"] == "ocr" for s in seen)
    assert seen[0]["step"] < seen[1]["step"] <= seen[1]["total"]
    assert hb.read()["state"] == hb.FINISHED and hb.read()["rc"] == 0


def test_a_loop_that_raises_is_not_left_running(monkeypatch, clock):
    from harness.commands import discover as discover_cmd, loop

    def boom(a):
        raise RuntimeError("tier fell over")
    monkeypatch.setattr(discover_cmd, "cmd_discover", boom)
    with pytest.raises(RuntimeError):
        _quiet(loop._report_loop,
               argparse.Namespace(run=False, lane="ocr", top=1, json=False))
    got = hb.read()
    assert got["state"] == hb.FINISHED and "tier fell over" in got["error"]


def test_the_spend_beats_each_candidate_it_measures(monkeypatch, clock):
    from harness import disk
    from harness.commands import discover as discover_cmd
    from harness.commands import loop, measure as measure_cmd, screen as screen_cmd
    seen = []
    monkeypatch.setattr(loop, "_reopen_retests", lambda now=None: [])
    monkeypatch.setattr(loop, "_reverify", lambda: {})
    monkeypatch.setattr(disk, "sweep", lambda *a, **k: None)
    monkeypatch.setattr(screen_cmd, "screenable_backlog", lambda want: [])
    monkeypatch.setattr(screen_cmd, "cmd_fetch",
                        lambda a: seen.append(dict(hb.read())) or 0)
    monkeypatch.setattr(discover_cmd, "cmd_discover",
                        lambda a: seen.append(dict(hb.read())) or 0)
    monkeypatch.setattr(measure_cmd, "measurable",
                        lambda store, top, want: [{"name": "a/one"}, {"name": "b/two"}])
    monkeypatch.setattr(measure_cmd, "_measure_and_adopt",
                        lambda a, row: seen.append(dict(hb.read())) or 0)
    hb.start(lane="code", total=loop.LOOP_TOTAL)
    _quiet(loop._loop_spend, argparse.Namespace(top=2, budget_gib=12.0, lane="code"), 0, [])
    tiers = [(s["tier"], s["candidate"], s["item"], s["items"]) for s in seen]
    assert tiers == [("fetch", "", 0, 0), ("screen", "", 0, 0),
                     ("measure", "a/one", 1, 2), ("measure", "b/two", 2, 2)]
    assert seen[-1]["step"] == seen[-1]["total"] == loop.LOOP_TOTAL


# --- and the reports show it -----------------------------------------------

def _page_state(**over):
    base = {"generated": 0.0,
            "machine": {"runtimes": ["mlx"], "accelerator": "x", "kind": "unified",
                        "total_gb": 32.0, "available_gb": 8.0},
            "funnel": [], "lanes": [],
            "queue": {"waiting": 0, "rankable": 0, "by_lane": {}, "top": [],
                      "wanted_with_none": []},
            "sources": []}
    base.update(over)
    return base


def test_the_page_shows_a_running_loop(clock):
    hb.start(lane="code", total=9)
    hb.beat("measure", step=9, candidate="org/model")
    page = report.render(_page_state(loop=hb.summary()), {})
    assert "org/model" in page and "running" in page


def test_the_page_shows_a_stalled_loop_as_stalled(clock):
    hb.start(lane="code", total=9)
    hb.beat("measure", step=9, candidate="org/model")
    clock.t += hb.STALL_S * 2
    page = report.render(_page_state(loop=hb.summary()), {})
    assert '<span class="tag bad">stalled</span>' in page


def test_the_page_renders_without_a_heartbeat():
    assert "<h1>SoHoT</h1>" in report.render(_page_state(), {})


def test_soh_report_prints_the_heartbeat(monkeypatch, clock, tmp_path, capsys):
    from harness import cli
    monkeypatch.setattr(report, "state", lambda conn=None: _page_state(loop=hb.summary()))
    hb.start(lane="code", total=9)
    hb.beat("screen", step=8)
    assert cli.main(["report", "--out", str(tmp_path / "r.html")]) == 0
    assert "discovery loop running" in capsys.readouterr().out


def test_jobs_list_prints_and_emits_the_heartbeat(clock, capsys):
    from harness import cli
    hb.start(lane="code", total=9)
    hb.beat("fetch", step=7)
    clock.t += hb.STALL_S + 5
    assert cli.main(["jobs", "list"]) == 0
    assert "discovery loop stalled" in capsys.readouterr().out
    assert cli.main(["jobs", "list", "--json"]) == 0
    got = json.loads(capsys.readouterr().out)
    assert got["loop"]["status"] == "stalled" and got["loop"]["tier"] == "fetch"


def test_a_sweep_started_within_its_interval_plus_slack_is_on_time(clock):
    hb.start()
    hb.finish(0)
    clock.t += hb.SWEEP_EVERY_S + hb.SWEEP_SLACK_S - 1
    assert hb.overdue() == ""


def test_a_last_sweep_older_than_a_day_and_an_hour_is_overdue(clock):
    """A reload postponed StartInterval all day and nothing said so (#625); one loop a day (#646)."""
    assert hb.SWEEP_EVERY_S + hb.SWEEP_SLACK_S == 25 * 3600
    hb.start()
    hb.finish(0)
    clock.t += 25 * 3600 + 60
    assert "1d 1h ago" in hb.overdue()


def test_no_sweep_at_all_is_overdue(clock):
    assert "no discovery loop" in hb.overdue()
