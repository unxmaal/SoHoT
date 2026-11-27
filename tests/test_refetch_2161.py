"""#2161: no weight is downloaded before the check that refuses it, a refusal writes a verdict, and a repo is not fetched twice in a day without one."""
from __future__ import annotations

import time

import pytest
from test_screen_fetch_window_2127 import _row, screening  # noqa: F401 - the fetch is recorded, not run
from test_screen_window_2045 import planted  # noqa: F401 - the Studio of #2045

from harness import discovery_flow, fetching, memory, needs_you, reasons, refetch, serving
from harness import memory_store as ms
from harness import status_view as sv
from harness.commands import screen as screen_cmd

GIB = fetching.GIB
EDGE, BASE = "Edge0/Edge0-35B-A3B-preview", "Qwen/Qwen3.6-35B-A3B"
BIG = "Org/Big-27B"


@pytest.fixture(autouse=True)
def home(monkeypatch, tmp_path):
    monkeypatch.setattr(refetch, "path", lambda: tmp_path / refetch.FILE)
    monkeypatch.setattr(memory, "_REMOTE_KV", {})
    monkeypatch.setattr("harness.rank.serving", lambda *a, **k: set())
    monkeypatch.setattr("harness.rank.lanes_with_receipts", lambda *a, **k: set())


def _queued(conn, name, gib=18.4, lane="code", state="queued"):
    ms.record(conn, ms.Seen(name=name, source="t", kind="weights", lane=lane, registry=ms.HUGGINGFACE, resolved=name))
    ms.set_size(conn, name, int(gib * GIB))
    ms.decide(conn, name, "queued", tier="inspect", detail="fits")
    if state != "queued":
        ms.decide(conn, name, state, tier=ms.SCREEN, reason="candidate")
    conn.execute("UPDATE verdicts SET decided_at = decided_at - ?", (2 * 86400,))
    conn.commit()


def _downloaded(conn, repo, gib=18.4, ago_s=600.0, now=None):
    now = time.time() if now is None else now
    conn.execute("INSERT INTO downloads (repo, kind, path, origin, bytes, complete, state, started_at, finished_at, removed_at, "
                 "machine_id) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                 (repo, "hub", f"/w/{repo}-{now - ago_s}", "fetch", int(gib * GIB), 1, "removed", now - ago_s, now - ago_s + 5,
                  now - ago_s + 6, ms.remember_machine(conn)))
    conn.commit()


def _last(conn, name):
    got = conn.execute("SELECT v.tier, v.outcome, v.reason, v.until FROM proposals p JOIN verdicts v ON v.id = p.state_verdict_id "
                       "WHERE p.name = ?", (name,)).fetchone()
    return tuple(got) if got else None


# ---- path 1: a measure dependency over the cap --------------------------------------------------------------

def test_a_measure_whose_base_is_over_the_cap_downloads_nothing_and_leaves_the_queue(monkeypatch):
    fetched = []
    monkeypatch.setattr(fetching, "download", lambda repo, **k: fetched.append(repo) or f"/x/{repo}")
    monkeypatch.setattr(fetching, "requires", lambda name, conn=None: [BASE] if name == EDGE else [])
    monkeypatch.setattr("harness.inspect.hf_size", lambda repo: int(67 * GIB))
    conn = ms.connect()
    try:
        _queued(conn, EDGE, state="screened")
        for _ in range(2):
            why = fetching.ensure(conn, EDGE)
            assert "67.0 GiB is over the 60 GiB cap" in why and BASE in why
        assert fetched == []
        tier, outcome, reason, until = _last(conn, EDGE)
        assert (tier, outcome, reason) == (ms.MEASURE, "declined", reasons.LIMIT) and until.startswith("limit:")
    finally:
        conn.close()


def test_a_screen_whose_base_is_over_the_cap_downloads_nothing_and_is_declined(monkeypatch):
    monkeypatch.setattr(fetching, "requires", lambda name, conn=None: [BASE] if name == EDGE else [])
    conn = ms.connect()
    try:
        _queued(conn, EDGE)
        got = fetching.for_test(conn, fetching.row(conn, EDGE), free=900 * GIB, floor=0, sizer=lambda r: int(67 * GIB),
                                snapshot=lambda *a, **k: pytest.fail("the candidate was downloaded for a base it cannot have"))
        assert not got["ok"] and "over the 60 GiB cap" in got["why"]
        assert _last(conn, EDGE)[1:3] == ("declined", reasons.LIMIT)
    finally:
        conn.close()


def test_a_base_a_removed_download_named_is_foreseen_once_its_weights_are_gone(monkeypatch):
    conn = ms.connect()
    try:
        _downloaded(conn, EDGE, ago_s=3 * 86400)
        conn.execute("UPDATE downloads SET requires = ? WHERE repo = ?", ('["' + BASE + '"]', EDGE))
        conn.commit()
        from harness import downloads
        assert downloads.recorded_requires(EDGE, conn) == [BASE] and downloads.requires(EDGE, conn) == []
    finally:
        conn.close()


# ---- paths 2 and 3: the screen decides on the load need before it fetches ---------------------------------------

def _priced(conn, monkeypatch, weights_gib, kv_gib, available):
    monkeypatch.setattr(memory, "remote_kv_bytes_per_token", lambda repo: int(kv_gib * GIB / serving.MLX_REQUEST_CTX))
    monkeypatch.setattr(memory, "available_gb", lambda: available)
    monkeypatch.setattr("harness.screen.deadline_s", lambda candidate, modality=None: 900.0)
    ms.record(conn, ms.Seen(name=BIG, source="t", kind="weights", lane="text", why="seeded", resolved=BIG))
    ms.set_size(conn, BIG, int(weights_gib * GIB))
    conn.commit()


def test_a_screen_whose_load_need_is_over_the_window_but_whose_weights_are_not_fetches_nothing(screening, monkeypatch):
    conn, fetched = screening
    _priced(conn, monkeypatch, 53.8, 8.0, available=64.0)
    assert memory.need_gb(BIG, None, f"hf-text:{BIG}", 1, True) == pytest.approx(61.8)
    assert screen_cmd._screen_one(None, conn, _row(BIG)) == (False, "queued", None)
    assert fetched == []
    assert _last(conn, BIG)[1:3] == ("queued", reasons.MEMORY)


def test_the_same_screen_whose_load_need_fits_the_window_is_fetched(screening, monkeypatch):
    conn, fetched = screening
    _priced(conn, monkeypatch, 40.0, 8.0, available=64.0)
    screen_cmd._screen_one(None, conn, _row(BIG))
    assert fetched == [BIG]


def test_a_screen_the_memory_left_once_the_pins_are_released_cannot_hold_is_refused_before_the_fetch(screening, monkeypatch):
    conn, fetched = screening
    _priced(conn, monkeypatch, 48.1, 0.8, available=8.7)
    assert memory.released_gb() == pytest.approx(23.5)
    assert screen_cmd._screen_one(None, conn, _row(BIG)) == (False, "queued", None)
    assert fetched == []
    assert _last(conn, BIG)[1:3] == ("queued", reasons.MEMORY)


# ---- the catch-all: a repo is not downloaded again within a day without a verdict ---------------------------------

def test_a_repo_downloaded_and_removed_with_no_verdict_is_refused_a_second_download(monkeypatch):
    fetched = []
    monkeypatch.setattr(fetching, "download", lambda repo, **k: fetched.append(repo) or f"/x/{repo}")
    monkeypatch.setattr(fetching, "requires", lambda name, conn=None: [])
    conn = ms.connect()
    try:
        _queued(conn, EDGE, state="screened")
        _downloaded(conn, EDGE, ago_s=3600)
        why = fetching.ensure(conn, EDGE, free=900 * GIB, floor=0, via="measure")
        assert fetched == [] and "no verdict was written since" in why and "measure" in why
        assert refetch.read()[EDGE]["via"] == "measure"
        assert any(c["title"].startswith(EDGE) for c in needs_you._refetch({"stops": {"refetch": needs_you.read_refetch()}}))
    finally:
        conn.close()


def test_a_verdict_written_between_the_two_downloads_lets_the_second_one_go(monkeypatch):
    fetched = []
    monkeypatch.setattr(fetching, "download", lambda repo, **k: fetched.append(repo) or f"/x/{repo}")
    monkeypatch.setattr(fetching, "requires", lambda name, conn=None: [])
    conn = ms.connect()
    try:
        _queued(conn, EDGE)
        _downloaded(conn, EDGE, ago_s=3600)
        ms.decide(conn, EDGE, "declined", tier=ms.SCREEN, detail="it does not load", reason=reasons.CANDIDATE)
        conn.commit()
        assert fetching.ensure(conn, EDGE, free=900 * GIB, floor=0) == ""
        assert fetched == [EDGE]
    finally:
        conn.close()


def test_the_downloaded_verdict_and_a_waiting_verdict_are_no_answer_about_the_weights(monkeypatch):
    conn = ms.connect()
    try:
        _queued(conn, EDGE)
        _downloaded(conn, EDGE, ago_s=3600)
        ms.decide(conn, EDGE, "queued", tier="fetch", detail=fetching.DOWNLOADED_DETAIL, reason=reasons.CANDIDATE, event=fetching.DOWNLOADED)
        ms.decide(conn, EDGE, "queued", tier="fetch", detail=f"{refetch.WAITING}{BASE}: nope", reason=reasons.HARNESS,
                  event=refetch.WAITING_EVENT)
        conn.commit()
        assert "no verdict was written since" in refetch.refusal(conn, EDGE, "the screen")
    finally:
        conn.close()


def test_a_download_older_than_the_window_is_not_a_refetch():
    conn = ms.connect()
    try:
        _downloaded(conn, EDGE, ago_s=refetch.REFETCH_WINDOW_S + 60)
        assert refetch.refusal(conn, EDGE, "measure") == ""
    finally:
        conn.close()


def test_a_dependency_downloaded_a_moment_ago_is_not_fetched_again_for_the_next_candidate(monkeypatch):
    fetched = []
    monkeypatch.setattr(fetching, "download", lambda repo, **k: fetched.append(repo) or f"/x/{repo}")
    monkeypatch.setattr(fetching, "requires", lambda name, conn=None: [BASE] if name == EDGE else [])
    monkeypatch.setattr("harness.inspect.hf_size", lambda repo: int(10 * GIB))
    conn = ms.connect()
    try:
        _queued(conn, EDGE, state="screened")
        _downloaded(conn, BASE, gib=10, ago_s=600)
        monkeypatch.setattr(fetching, "have", lambda m, conn=None: m == EDGE)
        why = fetching.ensure(conn, EDGE, free=900 * GIB, floor=0)
        assert fetched == [] and BASE in why and "no verdict was written since" in why
    finally:
        conn.close()


# ---- the flow panel's fetch node ------------------------------------------------------------------------------

def test_the_flow_panels_fetch_node_shows_the_gib_downloaded_again_in_a_day():
    now = time.time()
    conn = ms.connect()
    try:
        _downloaded(conn, "org/a", gib=10, ago_s=7200, now=now)
        _downloaded(conn, "org/a", gib=10, ago_s=3600, now=now)
        _downloaded(conn, "org/b", gib=5, ago_s=1800, now=now)
        _downloaded(conn, "org/c", gib=7, ago_s=3 * 86400, now=now)
        _downloaded(conn, "org/c", gib=7, ago_s=600, now=now)
        got = discovery_flow.gather(conn, now)
    finally:
        conn.close()
    assert [n for n in got["nodes"] if n["name"] == "fetch"][0]["redone"] == {"gib": 17.0, "n": 2, "repos": 2}
    html = sv._flow(got, now, [])
    assert "17 GiB again, 24 h" in html and "data-leak='refetched'" in html


# ---- the mark file and the shared store ------------------------------------------------------------------------

@pytest.mark.gauntlet("nothing-and-failed-return-the-same-value", site="harness/refetch.py:_read_all:except")
def test_an_unreadable_mark_is_not_reported_as_no_mark(tmp_path):
    assert refetch.read() == {}
    (tmp_path / refetch.FILE).write_text("{not json", encoding="utf-8")
    assert refetch.read()["?"]["why"] == "unreadable mark file"


@pytest.mark.gauntlet("a-copy-whose-key-leaves-out-an-input-or-that-nothing-invalidates", site="harness/refetch.py:mark")
def test_a_mark_is_keyed_by_repo_and_a_later_refusal_replaces_it():
    refetch.mark("org/a", "measure", "x", now=1)
    refetch.mark("org/b", "the screen", "y", now=2)
    refetch.mark("org/a", "the screen", "z", now=3)
    got = refetch.read(now=4)
    assert set(got) == {"org/a", "org/b"} and got["org/a"]["via"] == "the screen"
    assert refetch.read(now=3 + refetch.REFETCH_WINDOW_S + 1) == {}, "a mark ends with the window it refused"


@pytest.mark.gauntlet("a-copy-whose-key-leaves-out-an-input-or-that-nothing-invalidates", site="harness/refetch.py:clear")
def test_a_repo_downloaded_with_leave_clears_only_its_own_mark():
    refetch.mark("org/a", "measure", "x")
    refetch.mark("org/b", "measure", "y")
    refetch.clear("org/a")
    assert set(refetch.read()) == {"org/b"}


@pytest.mark.gauntlet("a-shared-store-query-with-no-scope-or-a-scope-with-its-own-idea-of-null",
                      site="harness/refetch.py:_verdict_since:verdicts")
def test_a_verdict_no_machine_stamped_still_answers_for_the_weights():
    conn = ms.connect()
    try:
        _queued(conn, EDGE)
        _downloaded(conn, EDGE, ago_s=3600)
        assert refetch.refusal(conn, EDGE, "measure")
        ms.decide(conn, EDGE, "declined", tier=ms.SCREEN, detail="it does not load", reason=reasons.CANDIDATE)
        conn.execute("UPDATE verdicts SET machine_id = NULL")
        conn.commit()
        assert refetch.refusal(conn, EDGE, "measure") == ""
    finally:
        conn.close()
