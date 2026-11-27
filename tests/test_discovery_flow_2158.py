"""The status page's discovery flow panel: counts per node and edge, repeats and leaks from the store, jobs and disk rows. #2158."""
from __future__ import annotations

import json
import time

import pytest

from harness import discovery_flow as df
from harness import memory_store as ms
from harness import status_view as sv

NOW = time.time()
GIB = 1 << 30
CYCLE = "1795778386"


def _argv(step: str, cycle: str = CYCLE) -> str:
    return json.dumps(["py", "-m", "harness.cli", "discover", "--loop", "--run", "--step", step, "--cycle", cycle])


def _me(conn) -> int:
    return ms.remember_machine(conn)


def _job(conn, step: str, state: str = "done", rc: int = 0, at: float = NOW - 3000, took: float = 600, cycle: str = CYCLE) -> int:
    return conn.execute("INSERT INTO jobs (title, argv, state, rc, requested_by, created_at, started_at, finished_at, machine_id) "
                        "VALUES (?,?,?,?,?,?,?,?,?)", (f"discover {step} (cycle {cycle})", _argv(step, cycle), state, rc,
                                                       "discover", at, at, at + took, _me(conn))).lastrowid


def _proposal(conn, name: str, state: str = "queued") -> int:
    return conn.execute("INSERT INTO proposals (name, first_seen, last_seen, state, lane) VALUES (?,?,?,?, 'tts')",
                        (name, NOW - 5000, NOW - 5000, state)).lastrowid


def _verdict(conn, pid: int, tier: str, outcome: str, at: float = NOW - 2000, event: str = "", run_id=None, power=None) -> int:
    return conn.execute("INSERT INTO verdicts (proposal_id, tier, outcome, event, run_id, power, decided_at, machine_id) "
                        "VALUES (?,?,?,?,?,?,?,?)", (pid, tier, outcome, event, run_id, json.dumps(power or {}), at, _me(conn))).lastrowid


def _download(conn, pid: int, repo: str, gib: float = 30, at: float = NOW - 4000, removed: bool = False) -> None:
    conn.execute("INSERT INTO downloads (proposal_id, repo, kind, path, origin, bytes, complete, state, started_at, finished_at, "
                 "removed_at, removed_by, machine_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                 (pid, repo, "hub", f"/w/{repo}-{at}", "fetch", int(gib * GIB), 1, "removed" if removed else "complete", at,
                  at + 300, at + 3000 if removed else None, "test: no test is about to run them" if removed else "", _me(conn)))


def _run(conn, lane: str, a: str, b: str, job: int | None, at: float = NOW - 1500) -> int:
    rid = conn.execute("INSERT INTO runs (path, lane, tier, recorded_at, job_id, machine_id) VALUES (?,?,?,?,?,?)",
                       (f"/runs/{lane}-{at}-{job}", lane, "measure", at, job, _me(conn))).lastrowid
    for seq, cand in enumerate((a, b)):
        conn.execute("INSERT INTO results (run_id, seq, candidate, case_id, passed) VALUES (?,?,?,?,1)", (rid, seq, cand, "c1"))
    return rid


def _clean(conn) -> None:
    for step in ("sweep", "inspect", "queue", "screen", "measure"):
        _job(conn, step)
    one, two = _proposal(conn, "org/one", "screened"), _proposal(conn, "org/two", "measured")
    _verdict(conn, one, "inspect", "queued")
    _verdict(conn, two, "inspect", "queued")
    _verdict(conn, one, "fetch", "queued", event="downloaded")
    _verdict(conn, two, "fetch", "queued")
    _download(conn, one, "org/one")
    _verdict(conn, one, "screen", "screened")
    job = _job(conn, "measure", cycle="1795778999")
    rid = _run(conn, "tts", "org/one", "base/inc", job)
    _verdict(conn, one, "measure", "measured", run_id=rid, power={"power": 0.93})


def _plant(conn) -> None:
    _clean(conn)
    jobs = [_job(conn, "measure", state="failed", rc=1, at=NOW - 1900 + i * 10) for i in range(3)]
    for j in jobs:
        _run(conn, "tts", "org/moss", "base/kokoro", j, at=NOW - 1800)
    moss = _proposal(conn, "org/moss", "screened")
    _download(conn, moss, "org/moss")
    _download(conn, moss, "org/moss", at=NOW - 3500, removed=True)
    weak = _run(conn, "svg", "org/weak", "base/svg", None, at=NOW - 900)
    _verdict(conn, moss, "measure", "declined", run_id=weak, power={"power": 0.07, "target": 0.8})


def _flow(populate, now: float = NOW) -> dict:
    conn = ms.connect()
    try:
        populate(conn)
        conn.commit()
        return df.gather(conn, now)
    finally:
        conn.close()


def test_a_clean_store_shows_no_repeat_and_no_leak():
    r = _flow(_clean)
    assert [e for e in r["edges"] if e["repeats"]] == []
    assert r["leaks"] == []
    html = sv._flow(r, NOW, [])
    assert "data-leak=" not in html and "class='edge rep" not in html


def test_each_planted_defect_is_a_highlighted_edge_or_a_leak_marker():
    r = _flow(_plant)
    edges = {(e["src"], e["dst"]): e for e in r["edges"]}
    assert [(x["kind"], x["n"]) for x in edges[("screen", "measure")]["repeats"]] == [("pair", 3), ("failure", 3)]
    assert any(x["name"] == "org/moss" and x["n"] == 2 for x in edges[("rank", "fetch")]["repeats"])
    leaks = {x["key"]: x for x in r["leaks"]}
    assert leaks["power"]["n"] == 1
    html = sv._flow(r, NOW, [])
    assert html.count("class='edge rep") == 2
    assert "data-leak='power'" in html and "0.07" in html


def test_gib_downloaded_then_deleted_without_a_verdict_is_a_leak():
    def plant(conn):
        _clean(conn)
        lost = _proposal(conn, "org/lost", "declined")
        _download(conn, lost, "org/lost", gib=12, removed=True)
    r = _flow(plant)
    gone = {x["key"]: x for x in r["leaks"]}["deleted"]
    assert gone["n"] == pytest.approx(12.0)


def test_weights_evicted_while_their_measure_waits_is_a_leak():
    def plant(conn):
        _clean(conn)
        waits = _proposal(conn, "org/waits", "screened")
        _download(conn, waits, "org/waits", removed=True)
    assert {x["key"]: x for x in _flow(plant)["leaks"]}["evicted"]["n"] == 1


def test_the_measure_backlog_over_the_measure_capacity_is_a_leak():
    def plant(conn):
        _clean(conn)
        for i in range(5):
            _proposal(conn, f"org/wait{i}", "screened")
    got = {x["key"]: x for x in _flow(plant)["leaks"]}["backlog"]
    assert got["n"] >= 5 and "measure" in got["text"]


def test_a_job_repeating_a_failure_marks_its_edge():
    def plant(conn):
        _clean(conn)
        for i in range(3):
            _job(conn, "screen", state="failed", rc=1, at=NOW - 2000 + i)
    edges = {(e["src"], e["dst"]): e for e in _flow(plant)["edges"]}
    assert edges[("fetch", "screen")]["repeats"]


def test_nodes_carry_in_out_and_seconds():
    nodes = {n["name"]: n for n in _flow(_plant)["nodes"]}
    assert list(nodes) == ["sweep", "inspect", "rank", "fetch", "screen", "measure", "adopt"]
    assert nodes["inspect"]["in"] == 2 and nodes["inspect"]["out"] == 2
    assert (nodes["fetch"]["in"], nodes["fetch"]["out"]) == (2, 1)
    assert nodes["measure"]["seconds"] == pytest.approx(600 * 5)


def test_a_leak_links_to_its_needs_you_entry_when_one_exists():
    r = _flow(_plant)
    jid = next(x for e in r["edges"] for x in e["repeats"] if x["kind"] == "failure")["jobs"][0]
    failed = [{"key": f"job-failed-{jid}", "title": "A job failed", "why": "", "fix": []}]
    assert f"href='#need-job-failed-{jid}'" in sv._flow(r, NOW, failed)
    assert "href='#need-" not in sv._flow(r, NOW, [])


def test_a_flow_section_that_cannot_render_leaves_the_page_up():
    out = sv._safe("Discovery flow", sv._flow, {"error": "boom"}, NOW, [])
    assert "not read" in out
    broken = sv._safe("Discovery flow", sv._flow, {"nodes": None}, NOW, [])
    assert "could not render" in broken


def test_the_store_down_is_an_error_section_not_a_crash():
    assert df.gather(None, NOW) == {"error": "store down: discovery flow not read"}


def test_the_page_carries_the_flow_panel_and_a_broken_flow_does_not_take_it_down(tmp_path):
    from tests.test_status_view_2078 import _gather

    r = _gather(tmp_path, connect=ms.connect)
    page = sv.page(r, {}, NOW)
    assert "data-flow='1'" in page and "data-node='measure'" in page and "discovery_flow" in json.dumps(r)
    r["discovery_flow"] = {"nodes": None}
    assert "could not render" in sv.page(r, {}, NOW) and "SoHoT status" in sv.page(r, {}, NOW)


@pytest.mark.gauntlet("a-closed-table-fronting-an-open-set", site="harness/discovery_flow.py:STEP_NODE")
def test_every_sweep_step_has_a_node_or_is_named_undrawn():
    from harness.commands import loop_steps
    names = {s.name for s in loop_steps.STEPS}
    assert names == set(df.STEP_NODE) | set(df.UNDRAWN)
    assert set(df.STEP_NODE.values()) <= set(df.NODES)


def test_another_machines_rows_are_not_this_machines_flow():
    def plant(conn):
        _plant(conn)
        other = conn.execute("INSERT INTO machines (fingerprint, first_seen, last_seen) VALUES ('other-box', ?, ?)", (NOW, NOW)).lastrowid
        for table in ("jobs", "runs", "verdicts", "downloads"):
            conn.execute(f"UPDATE {table} SET machine_id = ?", (other,))
    r = _flow(plant)
    assert [e for e in r["edges"] if e["repeats"]] == [] and [x["key"] for x in r["leaks"]] == ["backlog"]


@pytest.mark.gauntlet("a-shared-store-query-with-no-scope-or-a-scope-with-its-own-idea-of-null",
                      site="harness/discovery_flow.py:_powers:verdicts")
@pytest.mark.gauntlet("a-shared-store-query-with-no-scope-or-a-scope-with-its-own-idea-of-null",
                      site="harness/discovery_flow.py:_powers:paused_runs")
def test_another_machines_power_plan_for_this_machines_run_is_not_its_power():
    def plant(conn):
        _clean(conn)
        other = conn.execute("INSERT INTO machines (fingerprint, first_seen, last_seen) VALUES ('other-box', ?, ?)", (NOW, NOW)).lastrowid
        rid = _run(conn, "svg", "org/x", "base/svg", None, at=NOW - 800)
        vid = _verdict(conn, _proposal(conn, "org/x"), "measure", "declined", run_id=rid, power={"power": 0.07})
        conn.execute("UPDATE verdicts SET machine_id = ? WHERE id = ?", (other, vid))
        conn.execute("INSERT INTO paused_runs (lane, incumbent, challenger, out, plan, run_id, machine_id, paused_at) "
                     "VALUES ('svg','a','b','/o',?,?,?,?)", (json.dumps({"power": {"power": 0.05}}), rid, other, NOW))
    assert "power" not in {x["key"] for x in _flow(plant)["leaks"]}


@pytest.mark.gauntlet("an-effect-reachable-from-a-run-that-is-not-the-live-deploy",
                      site="harness/status_page.py:_discovery_flow:gather")
def test_the_flow_gather_starts_no_process_and_writes_nothing(monkeypatch):
    import subprocess

    from harness import status_page as sp

    def refuse(*a, **kw):
        raise AssertionError(f"started a process: {a}")
    monkeypatch.setattr(subprocess, "Popen", refuse)
    conn = ms.connect()
    try:
        _plant(conn)
        conn.commit()
        before = conn.total_changes
        assert sp._discovery_flow(conn, NOW)["nodes"]
        assert conn.total_changes == before
    finally:
        conn.close()
