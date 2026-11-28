"""The discovery yield: GPU hours and GiB per decided verdict and per adoption, per lane, from the store. #2163."""
from __future__ import annotations

import json
import time

import pytest

from harness import memory_store as ms
from harness import morning, pipeline_yield as py
from harness import status_view as sv
from tests.test_morning_867 import _report, _store, deploy_dir  # noqa: F401

NOW = time.time()
GIB = 1 << 30
H = 3600.0
CYCLE = "1795778386"


def _me(conn) -> int:
    return ms.remember_machine(conn)


def _job(conn, step: str, hours: float, ago_days: float = 1.0, by: str = "discover") -> int:
    at = NOW - ago_days * 86400
    argv = ["py", "-m", "harness.cli", "discover", "--loop", "--run", "--step", step, "--cycle", CYCLE]
    return conn.execute("INSERT INTO jobs (title, argv, state, rc, requested_by, resource, created_at, started_at, finished_at, machine_id) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?)", (f"discover {step}", json.dumps(argv), "done", 0, by, "gpu", at, at, at + hours * H,
                                                         _me(conn))).lastrowid


def _proposal(conn, name: str, lane: str) -> int:
    return conn.execute("INSERT INTO proposals (name, first_seen, last_seen, state, lane) VALUES (?,?,?,?,?)",
                        (name, NOW - 9e5, NOW - 9e5, "screened", lane)).lastrowid


def _measure(conn, lane: str, hours: float, outcome: str, ago_days: float = 1.0, **v) -> None:
    """One measure job of `hours` hours with its run, and the adopt verdict the run ended in."""
    job = _job(conn, "measure", hours, ago_days)
    at = NOW - ago_days * 86400
    rid = conn.execute("INSERT INTO runs (path, lane, tier, recorded_at, job_id, machine_id) VALUES (?,?,?,?,?,?)",
                       (f"/runs/{lane}-{job}", lane, "measure", at, job, _me(conn))).lastrowid
    pid = _proposal(conn, f"org/{lane}-{job}", lane)
    conn.execute("INSERT INTO verdicts (proposal_id, tier, outcome, event, reason, failure_class, lane, run_id, decided_at, machine_id) "
                 "VALUES (?,?,?,?,?,?,?,?,?,?)", (pid, "adopt", outcome, v.get("event", ""), v.get("reason", "candidate"),
                                                  v.get("failure_class", ""), lane, rid, at + hours * H, _me(conn)))


def _download(conn, lane: str, gib: float, removed: bool = False) -> None:
    pid = _proposal(conn, f"org/dl-{lane}-{gib}", lane)
    at = NOW - 3 * 86400
    conn.execute("INSERT INTO downloads (proposal_id, repo, kind, path, origin, bytes, complete, state, started_at, finished_at, removed_at, "
                 "removed_by, machine_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                 (pid, f"org/dl-{lane}-{gib}", "hub", f"/w/{lane}-{gib}", "fetch", int(gib * GIB), 1, "removed" if removed else "complete",
                  at, at + 300, at + 3000 if removed else None, "test" if removed else "", _me(conn)))


def _plant(conn) -> None:
    """Lane a mixes decided and undecided measures and a download removed with no verdict; lane b is clean."""
    _measure(conn, "a", 1, "measured", reason="candidate")
    _measure(conn, "a", 1, "declined", event="worse")
    _measure(conn, "a", 2, "declined", reason="limit", failure_class="lane_too_small")
    _measure(conn, "a", 2, "declined", reason="limit", failure_class="underpowered")
    _measure(conn, "a", 2, "declined", event="futility")
    _download(conn, "a", 30, removed=True)
    _download(conn, "a", 10)
    _measure(conn, "b", 1, "measured")
    _measure(conn, "b", 1, "declined", event="worse")
    _download(conn, "b", 5)


def _screen_hours(conn) -> None:
    job = _job(conn, "screen", 2)
    conn.execute("INSERT INTO runs (path, lane, tier, recorded_at, job_id, machine_id) VALUES (?,?,?,?,?,?)",
                 ("/runs/a-screen", "a", "screen", NOW - 86400, job, _me(conn)))


def _gather(populate, days=(7, 30), lane: str = "") -> dict:
    conn = ms.connect()
    try:
        populate(conn)
        conn.commit()
        return py.gather(conn, NOW, days, lane)
    finally:
        conn.close()


def _lanes(r: dict, days: str = "7") -> dict:
    return {x["lane"]: x for x in r["windows"][days]["lanes"]}


def _both(conn) -> None:
    _plant(conn)
    _screen_hours(conn)


def test_each_lane_gets_its_exact_hours_gib_and_verdict_split():
    lanes = _lanes(_gather(_both))
    a, b = lanes["a"], lanes["b"]
    assert (a["gpu_hours"], a["steps"]) == (10.0, {"measure": 8.0, "screen": 2.0})
    assert (a["gib"], a["wasted_gib"]) == (40.0, 30.0)
    assert (a["decided"], a["undecided"], a["adopted"]) == (2, 3, 1)
    assert {k: n for k, n in a["verdicts"].items() if n} == {"adopted": 1, "lost": 1, "lane_too_small": 1, "underpowered": 1, "futile": 1}
    assert (a["hours_per_decided"], a["hours_per_adoption"]) == (5.0, 10.0)
    assert (a["measure_hours"], a["undecided_measure_hours"], a["undecided_share"]) == (8.0, 6.0, 0.75)
    assert (b["gpu_hours"], b["gib"], b["wasted_gib"], b["decided"], b["undecided"]) == (2.0, 5.0, 0.0, 2, 0)
    assert (b["hours_per_decided"], b["hours_per_adoption"], b["undecided_share"]) == (1.0, 2.0, 0.0)


def test_the_red_marker_is_on_the_lane_over_half_undecided_and_not_on_the_clean_one():
    r = _gather(_both)
    lanes = _lanes(r)
    assert (lanes["a"]["red"], lanes["b"]["red"]) == (True, False)
    html = sv._yield({**r, "as_of": NOW}, NOW)
    assert "data-lane='a' data-red='1'" in html and "data-lane='b' data-red='0'" in html


def test_the_total_row_adds_the_lanes():
    t = _gather(_both)["windows"]["7"]["total"]
    assert (t["gpu_hours"], t["decided"], t["undecided"], t["gib"], t["wasted_gib"]) == (12.0, 4, 3, 45.0, 30.0)


def test_a_job_outside_the_window_is_in_the_longer_window_only():
    def plant(conn):
        _both(conn)
        _measure(conn, "b", 4, "declined", ago_days=10, reason="limit", failure_class="lane_too_small")
    r = _gather(plant)
    assert _lanes(r, "7")["b"]["gpu_hours"] == 2.0
    b30 = _lanes(r, "30")["b"]
    assert (b30["gpu_hours"], b30["undecided"], b30["undecided_share"], b30["red"]) == (6.0, 1, 0.667, True)


def test_a_lane_filter_and_a_single_window_keep_one_lane():
    r = _gather(_both, days=(30,), lane="b")
    assert list(r["windows"]) == ["30"] and [x["lane"] for x in r["windows"]["30"]["lanes"]] == ["b"]
    assert r["windows"]["30"]["total"]["gpu_hours"] == 2.0


def test_a_lane_with_no_decision_has_no_per_verdict_hours():
    def plant(conn):
        _measure(conn, "c", 3, "declined", reason="limit", failure_class="lane_too_small")
    c = _lanes(_gather(plant))["c"]
    assert (c["hours_per_decided"], c["hours_per_adoption"], c["undecided_share"], c["red"]) == (None, None, 1.0, True)


@pytest.mark.parametrize("row,kind", [
    (("measured", "", "candidate", ""), "adopted"), (("declined", "worse", "candidate", ""), "lost"),
    (("declined", "", "candidate", ""), "lost"), (("declined", "futility", "candidate", ""), "futile"),
    (("declined", "", "limit", "lane_too_small"), "lane_too_small"), (("declined", "", "limit", "underpowered"), "underpowered"),
    (("declined", "", "harness", ""), "harness"), (("declined", "", "owner", ""), "other")])
def test_a_verdict_row_is_decided_only_when_adopted_or_lost_on_the_candidate(row, kind):
    assert py.kind_of(*row) == kind
    assert (kind in py.DECIDED) == (kind in ("adopted", "lost"))


@pytest.mark.gauntlet("a-shared-store-query-with-no-scope-or-a-scope-with-its-own-idea-of-null", site="harness/pipeline_yield.py:_gpu:runs")
def test_another_machines_rows_are_not_this_machines_yield():
    def plant(conn):
        _both(conn)
        other = conn.execute("INSERT INTO machines (fingerprint, first_seen, last_seen) VALUES ('other-box', ?, ?)", (NOW, NOW)).lastrowid
        for table in ("jobs", "runs", "verdicts", "downloads"):
            conn.execute(f"UPDATE {table} SET machine_id = ?", (other,))
    t = _gather(plant)["windows"]["7"]["total"]
    assert (t["gpu_hours"], t["decided"], t["gib"]) == (0.0, 0, 0.0)


def test_the_trend_line_names_both_windows_and_the_morning_report_carries_it():
    def plant(conn):
        _both(conn)
        _measure(conn, "b", 6, "measured", ago_days=40)
    conn = ms.connect()
    try:
        plant(conn)
        conn.commit()
        t = py.trend(conn, NOW)
    finally:
        conn.close()
    assert (t["now"]["hours_per_decided"], t["before"]["hours_per_decided"]) == (3.0, 6.0)
    line = py.trend_line(t)
    assert "3.0 h per decided verdict (before 6.0)" in line and "decided / 3 undecided" in line


def test_the_morning_report_prints_the_trend_line(deploy_dir):
    from harness.commands import morning as cmd
    r = _report(_store(), deploy_dir)
    assert r["yield_trend"]["days"] == 30
    assert any(ln.startswith("yield     30 d:") for ln in cmd.render(r))


def test_the_page_reads_the_yield_through_its_own_section_and_survives_a_bad_one():
    html = sv._safe("Discovery yield", sv._yield, {"error": "boom"}, NOW)
    assert "not read" in html
    assert "could not render" in sv._safe("Discovery yield", sv._yield, {"windows": {"7": {"lanes": [{}]}}, "as_of": NOW}, NOW)


@pytest.mark.gauntlet("an-effect-reachable-from-a-run-that-is-not-the-live-deploy", site="harness/commands/pipeline_yield.py:cmd_pipeline_yield:gather")
@pytest.mark.gauntlet("an-effect-reachable-from-a-run-that-is-not-the-live-deploy", site="harness/status_page.py:_yield:gather")
@pytest.mark.sqlite_store
def test_the_gather_writes_nothing_and_starts_no_process(monkeypatch):
    import subprocess
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: (_ for _ in ()).throw(AssertionError("started a process")))
    conn = ms.connect()
    try:
        _both(conn)
        conn.commit()
        before = conn.total_changes
        from harness import status_page as sp
        assert py.gather(conn, NOW)["windows"]["7"]["lanes"] and sp._yield(conn, NOW)["windows"]["30"]["lanes"]
        assert conn.total_changes == before
    finally:
        conn.close()


def test_morning_gather_takes_the_trend_from_the_store(monkeypatch):
    seen = []
    monkeypatch.setattr(py, "trend", lambda conn, now: seen.append(now) or {"days": 30})
    assert morning.yield_trend(object(), NOW) == {"days": 30} and seen == [NOW]
