"""The store's list limits, lock wait and README read record a limit_cuts row when they bind; the scan finds one that does not (#1087)."""
from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
from pathlib import Path

import httpx
import pytest

from harness import cuts, knobs, limit_trace
from harness import memory_store as ms
from harness.knobs.base import Knob
from harness.memory_store import Seen

FIXTURES = Path(__file__).parent / "fixtures" / "limit_trace"
P = "harness/memory_store/proposals.py:"


@pytest.fixture
def db(tmp_path):
    conn = ms.connect(tmp_path / "d.db")
    yield conn
    conn.close()


def _cuts(conn) -> list[tuple]:
    return [tuple(r) for r in conn.execute("SELECT knob, value, kept, dropped FROM limit_cuts ORDER BY id")]


def _spooled() -> list[tuple]:
    path = cuts._spool_path()
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    return [(r["knob"], r["kept"], r["dropped"]) for r in map(json.loads, lines)]


def _queued(db, *names):
    for n in names:
        ms.record(db, Seen(name=n, source="recap", url=f"https://x/{n}", why="w", resolved=n, lane="image",
                           registry=ms.HUGGINGFACE))
        ms.decide(db, n, "queued", tier="inspect", detail="fits")


def test_a_full_judgeable_page_is_a_cut_of_the_limit_that_set_it_and_a_short_one_is_not(db):
    _queued(db, "org/a", "org/b")
    assert len(ms.judgeable(db, limit=5)) == 2
    assert _cuts(db) == []
    assert len(ms.judgeable(db, limit=2)) == 2
    assert len(ms.judgeable(db, limit=1, limit_knob="discover_top")) == 1
    assert _cuts(db) == [(P + "judgeable(limit)", 2.0, 2, None), ("discover_top", 1.0, 1, None)]


def test_a_full_pending_page_is_a_cut_and_a_short_one_is_not(db):
    _queued(db, "org/a", "org/b")
    assert len(ms.pending(db, limit=3)) == 2
    assert _cuts(db) == []
    assert len(ms.pending(db, limit=1)) == 1
    assert _cuts(db) == [(P + "pending(limit)", 1.0, 1, None)]


def test_a_full_ranked_page_is_a_cut_and_a_short_one_is_not(db):
    _queued(db, "org/a", "org/b")
    for i, n in enumerate(("org/a", "org/b")):
        ms.decide(db, n, "queued", tier="judge", score=i, rubric="r@1", judge="j")
    assert len(ms.ranked(db, limit=3)) == 2
    assert _cuts(db) == []
    assert [r["name"] for r in ms.ranked(db, limit=1)] == ["org/b"]
    assert _cuts(db) == [(P + "ranked(limit)", 1.0, 1, None)]


def test_a_full_survivors_page_is_a_cut_and_a_short_one_is_not(db):
    _queued(db, "org/a", "org/b")
    for n in ("org/a", "org/b"):
        ms.decide(db, n, "screened", tier="screen", detail="passed")
    assert len(ms.survivors(db, limit=3)) == 2
    assert _cuts(db) == []
    assert len(ms.survivors(db, limit=2)) == 2
    assert _cuts(db) == [(P + "survivors(limit)", 2.0, 2, None)]


def test_callers_with_their_own_limit_name_their_own_site(monkeypatch):
    from harness.commands import loop, measure
    seen = []
    monkeypatch.setattr(ms, "judgeable", lambda conn, **kw: seen.append(kw["limit_knob"]) or [])
    monkeypatch.setattr(ms, "survivors", lambda conn, **kw: seen.append(kw["limit_knob"]) or [])
    loop._queueable(None)
    measure.measurable(None, 3)
    from harness.memory_store import proposals
    proposals.judgeable_total(None)
    assert seen == ["harness/commands/loop.py:_queueable->ms.judgeable(limit)",
                    "harness/commands/measure.py:measurable->ms.survivors(limit)",
                    P + "judgeable_total->ms.judgeable(limit)"]


def test_a_statement_the_lock_wait_gives_up_on_is_a_cut_and_a_quick_one_is_not(tmp_path, monkeypatch):
    from harness.memory_store import connection
    monkeypatch.setattr(connection, "BUSY_TIMEOUT_SECONDS", 0.05)
    path = tmp_path / "d.db"
    first = ms.connect(path)
    second = ms.connect(path)
    try:
        second.execute("INSERT INTO meta (key, value) VALUES ('a', '1')")
        second.commit()
        assert _spooled() == []
        first.execute("BEGIN IMMEDIATE")
        with pytest.raises(sqlite3.OperationalError, match="locked"):
            second.execute("INSERT INTO meta (key, value) VALUES ('b', '1')")
        assert _spooled() == [("harness/memory_store/connection.py:BUSY_TIMEOUT_SECONDS", 0, 1)]
    finally:
        first.rollback()
        first.close()
        second.close()


def test_a_readme_read_that_times_out_is_a_cut_and_a_missing_one_is_not(monkeypatch):
    from harness.commands import benchmarks
    monkeypatch.setattr(httpx, "get", lambda *a, **k: httpx.Response(404))
    assert benchmarks._readme("org/a") == ""
    assert _spooled() == []

    def slow(*a, **k):
        raise httpx.ReadTimeout("slow")
    monkeypatch.setattr(httpx, "get", slow)
    assert benchmarks._readme("org/a") == ""
    assert _spooled() == [("harness/commands/benchmarks.py:_readme->httpx.get(timeout)", 0, 1)]


def _repo(tmp_path, fixture: str, extra: str = "") -> Path:
    root = tmp_path / fixture
    (root / "harness").mkdir(parents=True)
    shutil.copy(FIXTURES / f"{fixture}.py", root / "harness" / "x.py")
    if extra:
        with open(root / "harness" / "x.py", "a", encoding="utf-8") as f:
            f.write(extra)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    return root


@pytest.mark.parametrize("fixture,flagged", [("traced", False), ("untraced", True)])
def test_the_scan_flags_a_registered_limit_whose_binding_site_records_no_cut(tmp_path, monkeypatch, fixture, flagged):
    site = "harness/x.py:MAX_ITEMS"
    monkeypatch.setattr(knobs, "KNOBS", {"fixture_cap": Knob("fixture_cap", (site,), (1, 5, 10))})
    root = _repo(tmp_path, fixture)
    assert (site in limit_trace.untraced(root)) is flagged
    assert limit_trace.cutting_uses({"harness/x.py": (root / "harness" / "x.py").read_text(encoding="utf-8")}, site)


def test_a_second_cap_with_no_cut_beside_a_traced_one_is_still_flagged(tmp_path, monkeypatch):
    monkeypatch.setattr(knobs, "KNOBS", {"fixture_cap": Knob("fixture_cap", ("harness/x.py:MAX_ITEMS",), (1, 5))})
    root = _repo(tmp_path, "traced", "\nMAX_ROWS = 7\n\n\ndef rows(items):\n    return items[:MAX_ROWS]\n")
    assert limit_trace.untraced(root) == ["harness/x.py:MAX_ROWS"]
