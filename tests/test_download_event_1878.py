"""#1878: a download verdict is told apart by verdicts.event, set by its writer, never by its detail sentence."""
import pytest

from harness import fetch_replay, fetching, funnel, rank, reasons, screen
from harness import memory_store as ms

GIB = fetching.GIB
DAY = 86400.0
NOW = 2_000_000_000.0
REWORDED = "landed in the hub cache"


@pytest.fixture(autouse=True)
def runnable_here(monkeypatch):
    monkeypatch.setattr(rank, "unrunnable", lambda row, machine=None: "")


@pytest.fixture
def conn(monkeypatch):
    monkeypatch.setattr(fetching, "have", lambda *a, **k: False)
    monkeypatch.setattr(fetching, "download", lambda name, snapshot=None, **k: f"/x/{name}")
    monkeypatch.setattr(fetching, "requires", lambda name, conn=None: [])
    monkeypatch.setattr(screen, "runner_gap", lambda *a, **k: "")
    monkeypatch.setattr(rank, "serving", lambda *a, **k: set())
    monkeypatch.setattr(rank, "lanes_with_receipts", lambda *a, **k: set())
    c = ms.connect()
    yield c
    c.close()


def seed(conn, name, gib=16.0, at=NOW - 9 * DAY):
    ms.record(conn, ms.Seen(name=name, source="s", url="u", why="", relevance=0, kind="weights",
                            registry=ms.HUGGINGFACE, lane="code", resolved=name))
    ms.set_size(conn, name, int(gib * GIB))
    ms.decide(conn, name, "queued", tier="inspect", detail="fits", at=at)


def landed(conn, name, detail=REWORDED, at=NOW - DAY):
    return ms.decide(conn, name, "queued", tier="fetch", reason=reasons.CANDIDATE, at=at, detail=detail,
                     budget_gib=40.0, event=fetching.DOWNLOADED)


def test_the_replay_counts_a_download_whose_sentence_was_reworded(conn):
    seed(conn, "org/a")
    landed(conn, "org/a")
    got = fetch_replay.runs(conn, NOW - 2 * DAY)
    assert [(r["budget"], [x["name"] for x in r["rows"]], r["fetched"]) for r in got] == [(40.0, ["org/a"], ["org/a"])]


def test_a_fetch_verdict_that_only_says_downloaded_is_not_a_download(conn):
    seed(conn, "org/a")
    ms.decide(conn, "org/a", "queued", tier="fetch", reason=reasons.CANDIDATE, at=NOW - DAY,
              detail=fetching.DOWNLOADED_DETAIL, budget_gib=40.0)
    assert fetch_replay.runs(conn, NOW - 2 * DAY) == []


def test_the_funnel_does_not_read_a_reworded_download_back_as_a_skip(conn):
    seed(conn, "org/landed", 1, at=None)
    landed(conn, "org/landed", at=None)
    got = next(r for r in funnel.proposals(conn, top=3, budget=40 * GIB) if r["name"] == "org/landed")
    assert got["reason"] != fetching.SKIPPED


def test_the_funnel_reads_a_skip_that_happens_to_say_downloaded_as_a_skip(conn):
    seed(conn, "org/said", 1, at=None)
    ms.decide(conn, "org/said", "queued", tier="fetch", reason=reasons.LIMIT, detail=fetching.DOWNLOADED_DETAIL)
    got = next(r for r in funnel.proposals(conn, top=3, budget=40 * GIB) if r["name"] == "org/said")
    assert got["reason"] == fetching.SKIPPED


def test_a_fetch_run_marks_what_it_downloaded_by_event_whatever_it_says(conn, monkeypatch):
    monkeypatch.setattr(fetching, "DOWNLOADED_DETAIL", REWORDED)
    for i in range(2):
        seed(conn, f"org/code-{i}")
    got = fetching.run(conn, limit=2, free=1000 * GIB, budget=40 * GIB)
    assert [g["ok"] for g in got] == [True, True]
    said = conn.execute("SELECT detail, event FROM verdicts WHERE tier = 'fetch' ORDER BY id").fetchall()
    assert [tuple(r) for r in said] == [(REWORDED, fetching.DOWNLOADED)] * 2


def test_a_dependency_wait_records_the_runs_budget_and_is_not_a_replayed_row(conn, monkeypatch):
    monkeypatch.setattr(fetching, "requires", lambda name, conn=None: ["org/base"] if name == "org/top" else [])
    seed(conn, "org/top")
    fetching.run(conn, {"org/base": int(30 * GIB)}, limit=1, free=1000 * GIB, budget=40 * GIB)
    said = conn.execute("SELECT detail, reason, budget_gib, event FROM verdicts WHERE tier = 'fetch' ORDER BY id").fetchall()
    assert [(r["detail"].startswith("waiting on org/base"), r["reason"], r["budget_gib"], r["event"]) for r in said] == [
        (False, reasons.CANDIDATE, 40.0, fetching.DOWNLOADED), (True, reasons.LIMIT, 40.0, "")]
    runs = fetch_replay.runs(conn, 0)
    assert [([x["name"] for x in r["rows"]], r["fetched"]) for r in runs] == [(["org/top"], ["org/top"])]


@pytest.mark.gauntlet("a-shared-store-query-with-no-scope-or-a-scope-with-its-own-idea-of-null",
                      site="harness/memory_store/migrations/v105.py:data:verdicts")
def test_the_backfill_marks_each_older_download_once_and_nothing_else(conn):
    from harness.memory_store.migrations import v105
    for name in ("org/a", "org/b", "org/c"):
        seed(conn, name)
    ids = [ms.decide(conn, "org/a", "queued", tier="fetch", reason=reasons.CANDIDATE, at=NOW - DAY, detail="downloaded"),
           ms.decide(conn, "org/b", "queued", tier="fetch", reason=reasons.LIMIT, at=NOW - DAY,
                     detail="waiting on org/base, the base its runner needs: downloaded elsewhere"),
           ms.decide(conn, "org/c", "screened", tier="screen", reason=reasons.CANDIDATE, at=NOW - DAY, detail="downloaded")]
    v105.data(conn)
    v105.data(conn)
    got = {r[0]: r[1] for r in conn.execute("SELECT id, event FROM verdicts")}
    assert [got[i] for i in ids] == [fetching.DOWNLOADED, "", ""]
