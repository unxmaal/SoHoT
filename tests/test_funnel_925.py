"""soh funnel: time in state from entry, never the newest row, and one why_not shared with fetch. #925."""
import argparse
import time

import pytest

from harness import downloads, fetching, funnel, morning, report
from harness import memory_store as ms
from harness.commands import discover as discover_cmd
from harness.commands import loop as loop_cmd
from harness.commands import measure as measure_cmd
from harness.commands import screen as screen_cmd
from harness import cli, disk

GIB = fetching.GIB
DAY = 86400.0
T0 = 1_790_000_000.0


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr("harness.rank.serving", lambda *a, **k: set())
    monkeypatch.setattr("harness.rank.lanes_with_receipts", lambda *a, **k: set())
    monkeypatch.setattr(fetching, "requires", lambda name, conn=None: [])
    conn = ms.connect(tmp_path / "d.db")
    yield conn
    conn.close()


def _seen(conn, name, lane="code", gib=5.0, first_seen=None):
    ms.record(conn, ms.Seen(name=name, source="t", url="", why="", relevance=0, kind="candidate",
                            registry=ms.HUGGINGFACE, lane=lane, resolved=name))
    ms.set_size(conn, name, int(gib * GIB))
    if first_seen is not None:
        conn.execute("UPDATE proposals SET first_seen = ? WHERE name = ?", (first_seen, name))
        conn.commit()


def _raw(conn, name, outcome, at, tier="inspect", reopen_kind="", reason="candidate"):
    """A verdict row at an exact time that moves the proposal's state, as _write would."""
    pid = conn.execute("SELECT id FROM proposals WHERE name = ?", (name,)).fetchone()[0]
    vid = conn.execute("INSERT INTO verdicts (proposal_id, outcome, tier, detail, decided_at, reopen_kind, reason) "
                       "VALUES (?,?,?,?,?,?,?)", (pid, outcome, tier, "fits", at, reopen_kind, reason)).lastrowid
    conn.execute("UPDATE proposals SET state = ?, state_verdict_id = ? WHERE id = ?", (outcome, vid, pid))
    conn.commit()


# --- time in state is entry, never the newest row ---------------------------

def _ladder_store(conn):
    _seen(conn, "org/waypoints", first_seen=T0 - 5 * DAY)
    for i in range(200):
        _raw(conn, "org/waypoints", "queued", T0 + i * 3600)
    _seen(conn, "org/reopened", first_seen=T0 - 9 * DAY)
    _raw(conn, "org/reopened", "queued", T0 - 8 * DAY)
    _raw(conn, "org/reopened", "declined", T0 - 7 * DAY, reason="machine")
    _raw(conn, "org/reopened", "queued", T0 + 2 * DAY, reopen_kind="retraction", reason="reopened")
    for i in range(5):
        _raw(conn, "org/reopened", "queued", T0 + 3 * DAY + i * 3600)
    _seen(conn, "org/sighted", first_seen=T0 + 1 * DAY)
    _seen(conn, "org/declined", first_seen=T0 - 3 * DAY)
    _raw(conn, "org/declined", "queued", T0 - 2 * DAY)
    _raw(conn, "org/declined", "declined", T0 - 1 * DAY, reason="candidate")


def test_entry_times_and_stage_counts_come_from_the_fixture_not_the_newest_row(store, monkeypatch):
    _ladder_store(store)
    monkeypatch.setattr(report, "ranked", lambda conn, rows=None: [
        {"name": "org/waypoints", "lane": "code"}, {"name": "org/reopened", "lane": "code"}])
    now = T0 + 10 * DAY
    got = funnel.gather(store, now=now, budget=40 * GIB)
    by = {p["name"]: p for p in got["proposals"]}
    assert by["org/waypoints"]["entered"] == T0
    assert by["org/waypoints"]["in_state_days"] == 10.0
    assert by["org/reopened"]["entered"] == T0 + 2 * DAY
    assert by["org/reopened"]["age_days"] == 19.0
    assert by["org/sighted"]["entered"] == T0 + 1 * DAY
    assert by["org/sighted"]["stage"] == "seen"
    assert by["org/declined"]["entered"] == T0 - 1 * DAY
    counts = {s["stage"]: s["count"] for s in got["stages"]}
    assert counts == {"seen": 1, "inspected": 0, "ranked": 2, "fetched": 0, "screened": 0,
                      "measured": 0, "adopted": 0, "declined": 1}
    ranked = next(s for s in got["stages"] if s["stage"] == "ranked")
    assert ranked["oldest_days"] == 10.0 and ranked["oldest"][0]["name"] == "org/waypoints"


def test_soh_report_shows_the_same_stage_counts_as_soh_funnel(store, monkeypatch):
    _ladder_store(store)
    shown = [(s["stage"], s["count"]) for s in report.funnel(store)]
    assert shown == [(s["stage"], s["count"]) for s in funnel.gather(store)["stages"]]
    assert dict(shown)["declined"] == 1 and dict(shown)["seen"] == 1


def test_untried_counts_queued_rows_with_a_lane_and_no_fetch_record(store):
    _ladder_store(store)
    _seen(store, "org/laneless", lane="")
    _raw(store, "org/laneless", "queued", T0)
    _seen(store, "org/fetched-once")
    _raw(store, "org/fetched-once", "queued", T0, tier="fetch")
    _raw(store, "org/fetched-once", "queued", T0 + 1, tier="inspect")
    _seen(store, "org/linked")
    _raw(store, "org/linked", "queued", T0)
    downloads.removed(store, "/gone/linked.gguf", by="test", repo="org/linked", kind=downloads.GGUF)
    assert funnel.gather(store)["untried"] == 2


# --- one why_not, used by fetch and the funnel -----------------------------

def _skip_store(conn, tmp_path):
    for name in ("org/budget", "org/format", "org/nolane", "org/reopened", "org/failed", "org/fine"):
        _seen(conn, name, lane="" if name == "org/nolane" else "code", gib=5.0)
        ms.decide(conn, name, "queued", tier="inspect", detail=f"fits: {name}")
    ms.decide(conn, "org/budget", "queued", tier="fetch", detail="too big for 12", reason="limit",
              until="limit:download_budget_gib>12")
    ms.decide(conn, "org/format", "queued", tier="fetch", detail="pth only", reason="harness",
              until="format:.pth")
    ms.decide(conn, "org/reopened", "declined", tier="inspect", detail="too-big", reason="machine")
    ms.retract(conn, "org/reopened", "re-inspect against a bigger ceiling")
    rid = downloads.start(conn, "org/failed", downloads.GGUF, tmp_path / "gguf" / "failed.gguf",
                          file="failed.gguf", proposal="org/failed")
    downloads.finish(conn, rid, failed=True)


SKIPS = {"org/budget": fetching.BUDGET, "org/format": fetching.FORMAT, "org/nolane": fetching.NO_LANE,
         "org/reopened": fetching.UNINSPECTED, "org/failed": fetching.FAILED, "org/fine": None}


def test_why_not_names_each_skip_path(store, tmp_path):
    _skip_store(store, tmp_path)
    rows = {r["name"]: r for r in fetching.queued(store)}
    got = {n: (fetching.why_not(r, budget=10 * GIB) or (None,))[0] for n, r in rows.items()}
    assert got == SKIPS
    held = fetching.why_not(rows["org/fine"], budget=10 * GIB, backlog=3, top=3)
    assert held[0] == fetching.BACKPRESSURE and "already on disk wait for a screen" in held[1]
    assert fetching.why_not(rows["org/fine"], budget=4 * GIB)[0] == fetching.OVER_BUDGET


def test_fetch_skips_exactly_the_rows_why_not_names(store, tmp_path, monkeypatch):
    _skip_store(store, tmp_path)
    tried = []
    monkeypatch.setattr(fetching, "download", lambda name, **k: tried.append(name) or f"/x/{name}")
    monkeypatch.setattr(fetching, "have", lambda *a, **k: False)
    rows = fetching.queued(store)
    named = {r["name"] for r in rows
             if (fetching.why_not(r, budget=10 * GIB) or ("",))[0] in fetching.SILENT}
    fetching.run(store, limit=10, free=500 * GIB, budget=10 * GIB, sizer=lambda n: 0)
    assert set(tried) == {r["name"] for r in rows} - named == {"org/failed", "org/fine"}


def test_the_funnel_gives_each_queued_row_the_reason_fetch_would(store, tmp_path, monkeypatch):
    _skip_store(store, tmp_path)
    monkeypatch.setattr(fetching, "have", lambda *a, **k: False)
    rows = {p["name"]: p for p in funnel.gather(store, budget=10 * GIB, top=3)["proposals"]}
    for name, reason in SKIPS.items():
        assert rows[name]["reason"] == (reason or "next"), name
        assert rows[name]["why"]


def test_the_loop_skips_the_fetch_on_what_fetching_held_says(monkeypatch, capsys):
    fetched = []
    monkeypatch.setattr(disk, "sweep", lambda *a, **k: {})
    monkeypatch.setattr(loop_cmd, "_reopen_retests", lambda *a, **k: [])
    monkeypatch.setattr(loop_cmd, "_reopen_missing_in_snapshot", lambda *a, **k: [])
    monkeypatch.setattr(loop_cmd, "_reverify", lambda *a, **k: {})
    monkeypatch.setattr(loop_cmd, "_sweeps", lambda *a, **k: {})
    monkeypatch.setattr(screen_cmd, "screenable_backlog", lambda want="", **k: [])
    monkeypatch.setattr(screen_cmd, "cmd_fetch", lambda a: fetched.append(a) or 0)
    monkeypatch.setattr(discover_cmd, "cmd_discover", lambda a: 0)
    monkeypatch.setattr(measure_cmd, "measurable", lambda store, top, want="": [])
    monkeypatch.setattr(measure_cmd, "resume_first", lambda store, fresh, want="": fresh)
    monkeypatch.setattr("harness.memory_store.connect",
                        lambda *a, **k: type("S", (), {"close": lambda s: None})())
    monkeypatch.setattr(fetching, "held", lambda backlog, top: ("backpressure", "held by the shared predicate"))
    cli._loop_spend(argparse.Namespace(top=3, budget_gib=40, lane=""), 0)
    assert fetched == []
    assert "held by the shared predicate" in capsys.readouterr().out


# --- the morning line -------------------------------------------------------

def _head(conn, monkeypatch, days_waiting):
    now = time.time()
    _seen(conn, "org/head", first_seen=now - 40 * DAY)
    _raw(conn, "org/head", "queued", now - days_waiting * DAY)
    _raw(conn, "org/head", "queued", now - 0.1 * DAY)
    monkeypatch.setattr(report, "ranked", lambda conn, rows=None: [{"name": "org/head", "lane": "code"}])
    monkeypatch.setattr(fetching, "have", lambda *a, **k: False)


def test_the_morning_line_fires_on_an_old_ranked_head(store, monkeypatch):
    _head(store, monkeypatch, morning.STALL_DAYS + 1)
    got = morning.stalled(store)
    assert [s["name"] for s in got] == ["org/head"] and got[0]["reason"]
    r = {"sweep": {"loop": {"in_window": True, "status": "finished", "rc": 0, "line": ""}}, "watchdog": [],
         "ci": {}, "deploy": {}, "stale": [], "stalled": got}
    assert any("ranked head not fetched" in n and "org/head" in n for n in morning.needs(r))


def test_the_morning_line_is_quiet_on_a_young_ranked_head(store, monkeypatch):
    _head(store, monkeypatch, morning.STALL_DAYS - 1)
    assert morning.stalled(store) == []
