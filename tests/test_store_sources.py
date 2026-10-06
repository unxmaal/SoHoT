"""Discovery source state, neighbor scores and the HF size cache. #416."""
import json
import re
import sqlite3
import time
from pathlib import Path

import pytest

from harness import discover, feeds, paths
from harness import inspect as ins
from harness import memory_store as ms
from harness.feeds import FeedError, Source

HARNESS = Path(__file__).resolve().parent.parent / "harness"
ATOM = ('<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>t</title>'
        '<link href="https://example.invalid/a"/></entry></feed>')


@pytest.fixture
def store(tmp_path):
    conn = ms.connect(tmp_path / "d.db")
    yield conn
    conn.close()


# ---- feeds read and write the sources table ------------------------------

def test_a_read_writes_a_sources_row_and_no_state_file(store, tmp_path):
    src = Source("s", "https://example.invalid/f", kind="atom")
    feeds.read(src, cache_dir=tmp_path, store=store, fetcher=lambda u: ATOM)
    row = ms.source_row(store, "s")
    assert row["last_status"] == "ok" and row["failures"] == 0
    assert row["kind"] == "atom" and row["url"] == src.url
    assert row["last_read_at"] == pytest.approx(time.time(), abs=60)
    assert not (paths.home() / "discovery-state.json").exists()


def test_a_failed_read_counts_and_keeps_the_last_good_time(store, tmp_path):
    src = Source("s", "https://example.invalid/f")
    feeds.record_fetch(src, when=100.0, store=store)

    def boom(url):
        raise FeedError("HTTP 404")
    for _ in range(2):
        with pytest.raises(FeedError):
            feeds.read(src, cache_dir=tmp_path, store=store, fetcher=boom)
    row = ms.source_row(store, "s")
    assert (row["last_read_at"], row["failures"], row["last_status"]) == (
        100.0, 2, "failed")
    assert "404" in row["last_error"]
    feeds.read(src, cache_dir=tmp_path, store=store, fetcher=lambda u: ATOM)
    assert ms.source_row(store, "s")["failures"] == 0


def test_a_block_page_is_a_failure_not_a_read(store, tmp_path):
    src = Source("s", "https://example.invalid/f")
    with pytest.raises(FeedError):
        feeds.read(src, cache_dir=tmp_path, store=store,
                   fetcher=lambda u: "<html>blocked</html>")
    assert ms.source_row(store, "s")["last_read_at"] is None


def test_staleness_reads_the_table(store):
    now = time.time()
    store.execute("INSERT INTO sources (name, last_read_at, failures, "
                  "last_error) VALUES ('s', ?, 3, 'HTTP 503')",
                  (now - 2 * 86400,))
    rows = feeds.staleness([Source("s", "u")], now=now, days=7, store=store)
    assert not rows[0]["stale"] and rows[0]["failures"] == 3
    assert rows[0]["age_days"] == pytest.approx(2)
    assert feeds.staleness([Source("s", "u")], now=now, days=1,
                           store=store)[0]["stale"]


def test_the_sweep_records_through_the_store_it_was_given(store, monkeypatch,
                                                          tmp_path):
    """from_feeds hands its store to feeds.read rather than a default one."""
    monkeypatch.setattr(feeds, "read", lambda src, store=None: (
        ms.record_source(store, src.name, kind=src.kind, url=src.url) or []))
    monkeypatch.setattr(discover, "measured", lambda: set())
    discover.from_feeds(sources=[Source("s", "https://example.invalid/f")],
                        store=store, verify=False)
    assert ms.source_row(store, "s")["last_status"] == "ok"


def test_the_crowd_source_has_its_kind_and_url(store):
    feeds.record_fetch("github-crowd", store=store)
    row = ms.source_row(store, "github-crowd")
    assert row["kind"] == "crowd" and row["url"].startswith("https://github.com")


def test_no_harness_module_reads_or_writes_the_state_file():
    hits = [p.name for p in HARNESS.rglob("*.py")
            if "discovery-state.json" in p.read_text(encoding="utf-8")
            and p.name != "memory_store.py"]
    assert hits == []


# ---- neighbor scores are numbers ------------------------------------------

def _two(store):
    for n in ("a/seed", "b/repo"):
        ms.record(store, ms.Seen(name=n, source="t"))


def test_a_crowd_link_writes_numbers_and_no_prose(store):
    _two(store)
    ms.link(store, "a/seed", "b/repo", "crowd", shared=9, crowd=250,
            score=27.02884)
    r = store.execute("SELECT shared, crowd, score, note FROM edges").fetchone()
    assert (r["shared"], r["crowd"], r["score"], r["note"]) == (
        9, 250, pytest.approx(27.02884), "")


def test_relinking_refreshes_the_score(store):
    """INSERT OR IGNORE kept the first run's note forever."""
    _two(store)
    ms.link(store, "a/seed", "b/repo", "crowd", shared=9, crowd=250, score=1.0)
    ms.link(store, "a/seed", "b/repo", "crowd", shared=4, crowd=200, score=2.5)
    rows = store.execute("SELECT shared, crowd, score FROM edges").fetchall()
    assert [tuple(r) for r in rows] == [(4, 200, 2.5)]


def test_an_edge_without_a_score_stays_null(store):
    _two(store)
    ms.link(store, "a/seed", "b/repo", "needs")
    r = store.execute("SELECT shared, score FROM edges").fetchone()
    assert (r["shared"], r["score"]) == (None, None)


def test_the_neighbors_writer_passes_numbers(monkeypatch, tmp_path):
    """cli._report_neighbors links with shared/crowd/score, never a note."""
    from harness import cli, github, neighbors as nb
    links = []
    monkeypatch.setattr(github, "Client", lambda **k: type(
        "C", (), {"spent": 0, "stale": []})())
    monkeypatch.setattr(nb, "cohort", lambda **k: ["p1", "p2"])
    monkeypatch.setattr(nb, "neighbors", lambda *a, **k: [nb.Neighbor(
        repo="b/repo", shared=7, crowd=250, score=3.5, stars=10)])
    monkeypatch.setattr(ms, "link", lambda conn, s, d, rel, note="", **kw:
                        links.append((rel, note, kw)))
    monkeypatch.setattr(feeds, "relevance", lambda text, machine=None: 0)
    import argparse
    cli._report_neighbors(argparse.Namespace(json=False, budget=1, crowd=2,
                                             top=1, control=False, judge=False))
    assert links and all(rel == "crowd" and note == "" and kw == {
        "shared": 7, "crowd": 250, "score": 3.5} for rel, note, kw in links)
    assert ms.source_row(ms.connect(), "github-crowd")["last_status"] == "ok"


def test_no_reader_parses_edges_note():
    """Only the one-time backfill reads edges.note or its score pattern."""
    hits = []
    for p in HARNESS.rglob("*.py"):
        text = p.read_text(encoding="utf-8")
        for sql in re.findall(r"SELECT[^;]*?FROM edges", text, re.S):
            if re.search(r"\bnote\b", sql):
                hits.append(p.name)
        if p.name != "memory_store.py" and ("_EDGE_NOTE" in text
                                            or "e.note" in text):
            hits.append(p.name)
    body = (HARNESS / "memory_store.py").read_text(encoding="utf-8")
    lift = body[body.index("def lift_edge_scores"):]
    lift = lift[:lift.index("\ndef ")]
    assert body.count("_EDGE_NOTE") == lift.count("_EDGE_NOTE") + 1
    assert hits == ["memory_store.py"], hits


# ---- the HF size cache is an HTTP cache -----------------------------------

def test_a_cached_answer_has_no_lane_field():
    cache = {}
    ins.hf_facts("org/x", cache=cache, fetch=lambda u: json.dumps({
        "siblings": [{"size": 7}], "pipeline_tag": "text-to-speech",
        "tags": ["mlx"]}))
    assert "lane" not in cache["org/x"]
    assert cache["org/x"]["pipeline_tag"] == "text-to-speech"


def test_a_cache_hit_derives_the_lane_from_the_card_without_asking():
    calls = []
    cache = {"org/x": {"size": 7, "pipeline_tag": "text-to-speech", "tags": []}}
    got = ins.hf_facts("org/x", cache=cache, fetch=lambda u: calls.append(u))
    assert got == {"size": 7, "lane": "tts"} and calls == []


def test_a_stored_lane_in_the_cache_is_never_trusted():
    """The negative control: an old entry's lane says stt, the card says tts."""
    got = ins.hf_facts("org/x", cache={"org/x": {"size": 7, "lane": "stt"}},
                       fetch=lambda u: json.dumps({
                           "siblings": [{"size": 7}],
                           "pipeline_tag": "text-to-speech"}))
    assert got["lane"] == "tts"


def test_writing_the_cache_drops_old_lane_fields(monkeypatch, tmp_path):
    monkeypatch.setattr(ins, "_sizes_path", lambda: tmp_path / "hf-sizes.json")
    ins._write_size_cache({"a/b": {"size": 1, "lane": "stt"}, "c/d": 5})
    assert json.loads((tmp_path / "hf-sizes.json").read_text(encoding="utf-8")) == {
        "a/b": {"size": 1}, "c/d": 5}


# ---- the migration imports once -------------------------------------------

def _v33(path: Path) -> None:
    """A hand-written schema 33 store: edges with prose notes, no sources."""
    old = sqlite3.connect(path)
    old.executescript("""
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
        INSERT INTO meta VALUES ('schema','33');
        CREATE TABLE proposals (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE,
            kind TEXT NOT NULL DEFAULT 'candidate',
            registry TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT '',
            lane TEXT NOT NULL DEFAULT '', resolved TEXT NOT NULL DEFAULT '',
            consumes TEXT NOT NULL DEFAULT '', produces TEXT NOT NULL DEFAULT '',
            first_seen REAL NOT NULL, last_seen REAL NOT NULL,
            state TEXT NOT NULL DEFAULT '', state_verdict_id INTEGER,
            retest_count INTEGER NOT NULL DEFAULT 0, next_retest_at REAL,
            size_bytes INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE edges (id INTEGER PRIMARY KEY,
            src INTEGER NOT NULL REFERENCES proposals(id) ON DELETE CASCADE,
            dst INTEGER NOT NULL REFERENCES proposals(id) ON DELETE CASCADE,
            relation TEXT NOT NULL, note TEXT NOT NULL DEFAULT '',
            UNIQUE (src, dst, relation));
        INSERT INTO proposals (id, name, lane, first_seen, last_seen) VALUES
            (1, 'a/seed', '', 0, 0), (2, 'b/repo', '', 0, 0),
            (3, 'c/repo', '', 0, 0), (4, 'org/tts', '', 0, 0),
            (5, 'org/kept', 'image', 0, 0);
        INSERT INTO edges (src, dst, relation, note) VALUES
            (1, 2, 'crowd', '9/250 at 27.02884'),
            (1, 3, 'crowd', 'something a person wrote'),
            (2, 3, 'needs', '');
    """)
    old.commit()
    old.close()


def _files(home: Path) -> None:
    (home / "discovery-state.json").write_text(json.dumps({"fetched": {
        "reddit-sd-week": 1000.0, "github-crowd": 2000.0, "gone": 3000.0,
        "junk": "yesterday"}}), encoding="utf-8")
    (home / "cache" / "github").mkdir(parents=True)
    (home / "cache" / "github" / "hf-sizes.json").write_text(json.dumps({
        "org/tts": {"size": 1, "lane": "tts"},
        "org/kept": {"size": 1, "lane": "video"}, "org/bare": 4}),
        encoding="utf-8")


def test_an_older_store_imports_state_scores_and_lanes(tmp_path, _home):
    _files(_home)
    path = tmp_path / "old.db"
    _v33(path)
    conn = ms.connect(path)
    try:
        src = {r["name"]: dict(r) for r in conn.execute("SELECT * FROM sources")}
        assert {n: r["last_read_at"] for n, r in src.items()} == {
            "reddit-sd-week": 1000.0, "github-crowd": 2000.0, "gone": 3000.0}
        assert src["github-crowd"]["kind"] == "crowd"
        assert src["reddit-sd-week"]["last_status"] == "ok"
        e = {(r["src"], r["dst"]): tuple(r) for r in conn.execute(
            "SELECT src, dst, shared, crowd, score, note FROM edges")}
        assert e[(1, 2)][2:] == (9, 250, pytest.approx(27.02884), "")
        assert e[(1, 3)][2:] == (None, None, None, "something a person wrote")
        assert e[(2, 3)][2:] == (None, None, None, "")
        lanes = dict(conn.execute("SELECT name, lane FROM proposals"))
        assert lanes["org/tts"] == "tts" and lanes["org/kept"] == "image"
    finally:
        conn.close()
    assert (_home / "discovery-state.json").exists()


def test_the_import_is_idempotent(tmp_path, _home):
    _files(_home)
    path = tmp_path / "old.db"
    _v33(path)
    ms.connect(path).close()
    conn = ms.connect(path)
    try:
        before = [tuple(r) for r in conn.execute(
            "SELECT * FROM sources ORDER BY name")]
        assert ms.import_discovery_state_json(conn) == 0
        assert ms.lift_edge_scores(conn)["lifted"] == 0
        assert ms.import_size_cache_lanes(conn) == 0
        assert [tuple(r) for r in conn.execute(
            "SELECT * FROM sources ORDER BY name")] == before
    finally:
        conn.close()


def test_an_import_never_moves_a_newer_read_backwards(store, _home):
    _files(_home)
    feeds.record_fetch("reddit-sd-week", when=5000.0, store=store)
    ms.import_discovery_state_json(store)
    assert ms.source_row(store, "reddit-sd-week")["last_read_at"] == 5000.0


def test_a_fresh_store_with_no_files_imports_nothing(store):
    assert store.execute("SELECT COUNT(*) FROM sources").fetchone()[0] == 0
