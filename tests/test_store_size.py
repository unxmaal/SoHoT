"""A candidate's measured size is proposals.size_bytes, never a sentence. #413.

#211: inspect reworded its verdict from `bytes=N` to `fits: weights from 5.5 to
8.9 GiB`, nothing read the new spelling, and every candidate was declined for a
size sitting in the row above. The fix then was a second regex. These tests
pin the column as the only thing the readers consult, so a format change in
prose cannot move a number again.
"""
import sqlite3

import pytest

from harness import fetching, rank
from harness import memory_store as ms

GIB = 1024 ** 3


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf"))
    monkeypatch.setattr(fetching, "have", lambda *a, **k: False)
    monkeypatch.setattr(fetching, "requires", lambda name: [])
    monkeypatch.setattr("harness.rank.serving", lambda *a, **k: set())
    monkeypatch.setattr("harness.rank.lanes_with_receipts",
                        lambda *a, **k: set())
    monkeypatch.setattr("harness.rank.unrunnable", lambda row, m=None: "")
    conn = ms.connect(tmp_path / "s.db")
    yield conn
    conn.close()


def _see(conn, name, description="", lane="code"):
    ms.record(conn, ms.Seen(name=name, source="t", url="", why="",
                            relevance=0, kind="weights",
                            registry=ms.HUGGINGFACE, lane=lane,
                            resolved=name, description=description))


def _size(conn, name):
    return conn.execute("SELECT size_bytes FROM proposals WHERE name = ?",
                        (name,)).fetchone()["size_bytes"]


# --- the #211 regression: a wording change cannot lose a size --------------

def test_a_size_survives_any_change_to_the_verdict_prose(store):
    _see(store, "org/m")
    ms.set_size(store, "org/m", int(5.5 * GIB))
    ms.decide(store, "org/m", "queued", tier=ms.INSPECT,
              detail="fits: weights from 5.5 to 5.5 GiB")
    ms.decide(store, "org/m", "queued", tier="fetch",
              detail="no measured size; inspect it first")
    ms.decide(store, "org/m", "queued", tier=ms.INSPECT,
              detail="fits: a sentence in a format nobody has written yet")
    (row,) = fetching.queued(store)
    assert row["size_bytes"] == int(5.5 * GIB)


def test_an_unmeasured_candidate_stays_unmeasured(store):
    """Negative control: nothing invents a size."""
    _see(store, "org/none")
    ms.decide(store, "org/none", "queued", tier=ms.INSPECT, detail="fits")
    assert [r["size_bytes"] for r in fetching.queued(store)] == [0]


def test_a_zero_never_overwrites_a_measured_size(store):
    _see(store, "org/m")
    ms.set_size(store, "org/m", 7 * GIB)
    assert not ms.set_size(store, "org/m", 0)
    assert _size(store, "org/m") == 7 * GIB


# --- readers read the column, and only the column --------------------------

def test_fetch_reads_the_column_not_the_verdict_prose(store):
    """Red-proof: restoring a `bytes=` reader makes this row sized and fetched."""
    _see(store, "org/prose-only")
    ms.decide(store, "org/prose-only", "queued", tier=ms.INSPECT,
              detail="bytes=1073741824 fits: weights from 1.0 to 1.0 GiB")
    got = fetching.run(store, {}, limit=1, free=900 * GIB,
                       snapshot=lambda **k: pytest.fail("fetched an unsized row"))
    assert got and not got[0]["ok"]
    assert "no measured size" in got[0]["why"]


def test_fetch_budgets_on_the_column(store):
    _see(store, "org/big")
    ms.set_size(store, "org/big", 19 * GIB)
    ms.decide(store, "org/big", "queued", tier=ms.INSPECT, detail="fits")
    got = fetching.run(store, {}, limit=1, free=900 * GIB,
                       budget=12 * GIB,
                       snapshot=lambda **k: pytest.fail("over budget"))
    assert "19.0 GiB would take this run past" in got[0]["why"]


def test_rank_reads_the_column_not_the_card_description(store):
    """Red-proof both ways: the card's `N GiB of weights` earns nothing, the
    column earns `cheap to screen`."""
    _see(store, "org/card-only", description="task x; 2.3 GiB of weights")
    _see(store, "org/column", description="task x")
    ms.set_size(store, "org/column", int(2.3 * GIB))
    for name in ("org/card-only", "org/column"):
        ms.decide(store, name, "queued", tier=ms.INSPECT, detail="fits")
    rows = {r["name"]: r for r in ms.judgeable(store)}
    _, why_card = rank.value(rows["org/card-only"], ceiling_gib=22.0)
    _, why_col = rank.value(rows["org/column"], ceiling_gib=22.0)
    assert not any("cheap to screen" in w for w in why_card), why_card
    assert "2.3 GiB, cheap to screen" in why_col


def test_the_regex_readers_are_gone():
    assert not hasattr(fetching, "size_of")
    assert not hasattr(rank, "size_gib")


# --- the writer ------------------------------------------------------------

@pytest.mark.parametrize("verdict, largest", [("fits", 3 * GIB),
                                              ("too-big", 40 * GIB)])
def test_inspect_writes_the_column_whatever_it_decides(tmp_path, monkeypatch,
                                                      verdict, largest):
    from harness import cli, inspect as ins

    def fake_inspect(repo, data=None, **kw):
        fit = ins.Fit(repo=repo, registry=ms.HUGGINGFACE, verdict=verdict,
                      why="stub", largest=largest, smallest=largest)
        fit.weights[repo] = largest
        fit.lanes[repo] = "code"
        return fit

    monkeypatch.setattr(cli, "resolve_registry",
                        lambda name, client, model=None: (ms.HUGGINGFACE, {}))
    monkeypatch.setattr(ins, "inspect_model", fake_inspect)
    assert cli.main(["discover", "--inspect", "--repos", "org/w"]) == 0
    conn = ms.connect()
    try:
        assert _size(conn, "org/w") == largest
        detail = conn.execute(
            "SELECT detail FROM verdicts ORDER BY id DESC LIMIT 1"
        ).fetchone()["detail"]
        assert "bytes=" not in detail
    finally:
        conn.close()


# --- the one-time backfill -------------------------------------------------

def _old(conn, name, description, verdicts):
    _see(conn, name, description=description)
    for tier, detail, size in verdicts:
        ms.decide(conn, name, "queued", tier=tier, detail=detail,
                  size_bytes=size)


def test_backfill_precedence(store):
    _old(store, "a/column", "9.0 GiB of weights",
         [(ms.INSPECT, "bytes=7516192768", 5 * GIB)])
    _old(store, "b/prose-bytes", "9.0 GiB of weights",
         [(ms.INSPECT, "bytes=7516192768 lane=code named by x", 0)])
    _old(store, "c/prose-range", "",
         [(ms.INSPECT, "fits: weights from 1.0 to 2.0 GiB", 0)])
    _old(store, "d/card", "task x; 4.0 GiB of weights", [])
    _old(store, "e/fetch-prose", "",
         [("fetch", "5.0 GiB would take this run past its 6 GiB budget "
                    "(3.0 GiB already fetched)", 6 * GIB)])
    _old(store, "f/nothing", "task x", [(ms.INSPECT, "fits", 0)])
    _old(store, "g/newest-inspect", "",
         [(ms.INSPECT, "fits: one", 1 * GIB), (ms.INSPECT, "fits: two", 2 * GIB),
          ("fetch", "no measured size; inspect it first", 0)])
    store.execute("UPDATE proposals SET size_bytes = 0")
    ms.backfill_sizes(store)
    got = {r["name"]: r["size_bytes"] for r in
           store.execute("SELECT name, size_bytes FROM proposals")}
    assert got == {"a/column": 5 * GIB, "b/prose-bytes": 7516192768,
                   "c/prose-range": 2 * GIB, "d/card": 4 * GIB,
                   "e/fetch-prose": 0, "f/nothing": 0,
                   "g/newest-inspect": 2 * GIB}


def test_backfill_keeps_a_size_already_written(store):
    _old(store, "a/x", "9.0 GiB of weights", [])
    ms.set_size(store, "a/x", 3 * GIB)
    ms.backfill_sizes(store)
    assert _size(store, "a/x") == 3 * GIB


def test_an_older_store_is_backfilled_on_connect(tmp_path):
    """A hand-written schema 13 store, migrated by the real chain. No DROP
    COLUMN: CI's SQLite rejects it on the current proposals table."""
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.executescript("""
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
        INSERT INTO meta VALUES ('schema','13');
        CREATE TABLE proposals (id INTEGER PRIMARY KEY, name TEXT,
            kind TEXT DEFAULT '', lane TEXT DEFAULT '',
            resolved TEXT DEFAULT '', consumes TEXT DEFAULT '',
            produces TEXT DEFAULT '', first_seen REAL DEFAULT 0,
            last_seen REAL DEFAULT 0, registry TEXT DEFAULT '',
            description TEXT DEFAULT '');
        CREATE TABLE verdicts (id INTEGER PRIMARY KEY, proposal_id INTEGER,
            outcome TEXT, tier TEXT DEFAULT '', detail TEXT DEFAULT '',
            issue INTEGER, run_path TEXT DEFAULT '', score REAL,
            rubric TEXT DEFAULT '', judge TEXT DEFAULT '', decided_at REAL,
            machine_id INTEGER, until TEXT DEFAULT '',
            size_bytes INTEGER DEFAULT 0);
        CREATE TABLE machines (id INTEGER PRIMARY KEY, fingerprint TEXT UNIQUE,
            hw_model TEXT DEFAULT '', os TEXT DEFAULT '', arch TEXT DEFAULT '',
            memory_gb REAL DEFAULT 0, accelerator TEXT DEFAULT '',
            runtimes TEXT DEFAULT '', ceiling_gb REAL DEFAULT 0,
            first_seen REAL DEFAULT 0, last_seen REAL DEFAULT 0);
        INSERT INTO proposals (id, name, description) VALUES
            (1, 'org/prose', '9.0 GiB of weights'),
            (2, 'org/card', 'task x; 4.0 GiB of weights'),
            (3, 'org/budget', '');
        INSERT INTO verdicts (proposal_id, outcome, tier, detail, decided_at)
          VALUES (1, 'queued', 'inspect', 'bytes=1234 lane=code named by x', 0),
                 (3, 'queued', 'fetch',
                  '5.0 GiB would take this run past its 6 GiB budget', 0);
    """)
    old.commit()
    old.close()
    conn = ms.connect(path)
    try:
        assert {r["name"]: r["size_bytes"] for r in conn.execute(
            "SELECT name, size_bytes FROM proposals")} == {
            "org/prose": 1234, "org/card": 4 * GIB, "org/budget": 0}
    finally:
        conn.close()
