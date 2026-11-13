"""#1822: the fetch replay reads each run's budget from verdicts.budget_gib, never the refusal's sentence."""
import pytest

from harness import fetch_replay, fetching, rank, reasons, screen
from harness import memory_store as ms

GIB = fetching.GIB
DAY = 86400.0
NOW = 2_000_000_000.0
OLD = "16.0 GiB would take this run past its 40 GiB budget (32.0 GiB already fetched)"
KW = dict(serving=(), measured_lanes={"code"}, ceiling_gib=66.0,
          incumbents_by_lane={"code": "llamacpp:Ornith-1.5-35B-Q4_K_M"}, bases_by_lane={})


@pytest.fixture(autouse=True)
def runnable_here(monkeypatch):
    monkeypatch.setattr(rank, "unrunnable", lambda row, machine=None: "")


@pytest.fixture
def conn():
    c = ms.connect()
    yield c
    c.close()


def seed(conn, name, gib=16.0):
    ms.record(conn, ms.Seen(name=name, source="s", url="u", why="", relevance=0, kind="weights",
                            registry=ms.HUGGINGFACE, lane="code", resolved=name))
    ms.set_size(conn, name, int(gib * GIB))
    ms.decide(conn, name, "queued", tier="inspect", detail="fits", at=NOW - 9 * DAY)


def test_a_wholly_reworded_refusal_still_replays_with_its_budget(conn, monkeypatch):
    monkeypatch.setattr(fetching, "budget_refusal", lambda size, budget, spent: "no room tonight; try tomorrow")
    seed(conn, "org/a")
    fetching.refuse_over_budget(conn, "org/a", 16 * GIB, 40 * GIB, 32 * GIB, at=NOW - DAY)
    got = fetch_replay.runs(conn, NOW - 2 * DAY)
    assert [(r["budget"], [x["name"] for x in r["rows"]]) for r in got] == [(40.0, ["org/a"])]
    assert [r["budget"] for r in fetch_replay.replay(conn, NOW - 2 * DAY, **KW)] == [40.0]


def test_a_fetch_run_records_its_budget_on_what_it_fetched_and_what_it_refused(conn, monkeypatch):
    monkeypatch.setattr(fetching, "have", lambda *a, **k: False)
    monkeypatch.setattr(fetching, "download", lambda name, snapshot=None, **k: f"/x/{name}")
    monkeypatch.setattr(fetching, "requires", lambda name, conn=None: [])
    monkeypatch.setattr(screen, "runner_gap", lambda *a, **k: "")
    monkeypatch.setattr(rank, "serving", lambda *a, **k: set())
    monkeypatch.setattr(rank, "lanes_with_receipts", lambda *a, **k: set())
    for i in range(3):
        seed(conn, f"org/code-{i}")
    got = fetching.run(conn, limit=3, free=1000 * GIB, budget=40 * GIB)
    assert [g["ok"] for g in got] == [True, True, False]
    said = conn.execute("SELECT event = ? AS fetched, budget_gib FROM verdicts WHERE tier = 'fetch' ORDER BY id",
                        (fetching.DOWNLOADED,)).fetchall()
    assert [(bool(r[0]), r[1]) for r in said] == [(True, 40.0), (True, 40.0), (False, 40.0)]


def test_a_run_whose_budget_is_not_recorded_is_reported_not_dropped(conn):
    seed(conn, "org/a")
    ms.decide(conn, "org/a", "queued", tier="fetch", reason=reasons.CANDIDATE, at=NOW - DAY,
              detail=fetching.DOWNLOADED_DETAIL, event=fetching.DOWNLOADED)
    got = fetch_replay.runs(conn, NOW - 2 * DAY)
    assert [(r["budget"], r["fetched"]) for r in got] == [(None, ["org/a"])]
    lines = fetch_replay.report(conn, 2, now=NOW, **KW)
    said = [i for i, line in enumerate(lines) if "budget not recorded" in line]
    assert len(said) == 1 and "not replayed" in lines[said[0]] and "org/a" in lines[said[0] + 1]


@pytest.mark.gauntlet("a-shared-store-query-with-no-scope-or-a-scope-with-its-own-idea-of-null",
                      site="harness/memory_store/migrations/v104.py:data:verdicts")
def test_the_backfill_lifts_each_older_refusals_budget_once_and_leaves_the_rest_unknown(conn):
    from harness.memory_store.migrations import v104
    for name in ("org/a", "org/b", "org/c"):
        seed(conn, name)
    ids = [ms.decide(conn, "org/a", "queued", tier="fetch", reason=reasons.LIMIT, at=NOW - DAY, detail=OLD,
                     failure_class=reasons.PASSED_OVER),
           ms.decide(conn, "org/b", "queued", tier="fetch", reason=reasons.LIMIT, at=NOW - DAY,
                     detail=OLD.replace("40 GiB", "12.5 GiB"), until="limit:download_budget_gib>12.5"),
           ms.decide(conn, "org/c", "queued", tier="fetch", reason=reasons.LIMIT, at=NOW - DAY,
                     detail="no room tonight", failure_class=reasons.PASSED_OVER),
           ms.decide(conn, "org/c", "queued", tier="fetch", reason=reasons.LIMIT, at=NOW - DAY, detail=OLD,
                     failure_class=reasons.PASSED_OVER, budget_gib=24.0)]
    v104.data(conn)
    v104.data(conn)
    got = {r[0]: r[1] for r in conn.execute("SELECT id, budget_gib FROM verdicts WHERE tier = 'fetch'")}
    assert [got[i] for i in ids] == [40.0, 12.5, None, 24.0]
