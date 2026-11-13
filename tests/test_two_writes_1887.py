"""#1887: a process killed between a site's two writes leaves nothing a rerun cannot finish."""
import json

import pytest

from harness import coherence, download_state as ds, downloads, holdout, paths, reasons
from harness import memory_store as ms
from harness.memory_store import transitions

T = 1791000000.0
PLAN = {"repeat": 1, "power": 0.0, "cells": 3, "cases": 3, "effect": 0.2, "target": 0.8, "cap": 16,
        "cases_needed": None, "side": "all", "cases_run": 3, "unmeasured": False, "odds": [0.0, 0.0]}
NAME = "OmniSVG/OmniSVG1.1_8B"


class Died(BaseException):
    """The process killed mid-way: nothing after this point runs or commits."""


class _KilledAt:
    def __init__(self, conn, sql):
        self._conn, self._sql = conn, sql

    def execute(self, sql, *a, **kw):
        if sql.startswith(self._sql):
            raise Died(sql)
        return self._conn.execute(sql, *a, **kw)

    def __getattr__(self, name):
        return getattr(self._conn, name)


@pytest.fixture
def grown(monkeypatch):
    split = holdout.Split("svg", tuple(f"d{i}" for i in range(448)), tuple(f"h{i}" for i in range(195)), False)
    one = holdout.Split("other", ("o",), ("o",), True)
    monkeypatch.setattr(holdout, "for_lane", lambda lane, *a, **k: split if lane == "svg" else one)


def _held(conn):
    return conn.execute("SELECT v.until, v.power, v.split_version FROM proposals p "
                        "JOIN verdicts v ON v.id = p.state_verdict_id WHERE p.name = ?", (NAME,)).fetchone()


def _declined(conn):
    ms.record(conn, ms.Seen(name=NAME, source="t", lane="svg", resolved=NAME))
    ms.decide(conn, NAME, "screened", tier=ms.SCREEN, reason=reasons.CANDIDATE, at=T)
    pid = conn.execute("SELECT id FROM proposals WHERE name = ?", (NAME,)).fetchone()[0]
    vid = transitions._write(conn, pid, NAME, {"outcome": "declined", "tier": ms.ADOPT, "reason": reasons.LIMIT,
                                               "until": "cases:svg>643", "detail": "svg: underpowered",
                                               "decided_at": T, "failure_class": reasons.LANE_TOO_SMALL})
    conn.execute("UPDATE verdicts SET power = ?, split_version = '1' WHERE id = ?", (json.dumps(PLAN), vid))
    conn.commit()


def test_a_re_decided_verdict_never_lands_without_its_power_and_split(grown):
    conn = ms.connect()
    _declined(conn)
    found = coherence.changes(conn)
    assert [c["now"][3] for c in found] == ["cases:svg>3"]
    with pytest.raises(Died):
        coherence.apply(_KilledAt(conn, "UPDATE verdicts SET power"), found)
    conn.close()
    conn = ms.connect()
    try:
        held = _held(conn)
        assert (held["power"], held["split_version"]) == (json.dumps(PLAN), "1"), dict(held)
        coherence.apply(conn, coherence.changes(conn))
        assert dict(_held(conn)) == {"until": "cases:svg>3", "power": json.dumps(PLAN), "split_version": "1"}
    finally:
        conn.close()


def test_a_backfill_killed_before_it_settles_a_gone_path_settles_it_on_the_rerun(tmp_path, monkeypatch):
    manifest = paths.home() / "gguf-sources.json"
    manifest.write_text(json.dumps({"org/gone": "gone-Q4_K_M.gguf"}), encoding="utf-8")
    hub, ggufs = tmp_path / "hub", tmp_path / "gguf"
    move = ds.move

    def killed(conn, rid, frm, to, *a, **kw):
        if to == ds.REMOVED:
            raise Died("after record(), before settle()")
        return move(conn, rid, frm, to, *a, **kw)

    conn = ms.connect()
    conn.execute("CREATE TABLE disk_removals (id INTEGER PRIMARY KEY, path TEXT NOT NULL, "
                 "repo TEXT NOT NULL DEFAULT '', grp TEXT NOT NULL, bytes INTEGER NOT NULL DEFAULT 0, "
                 "verdict_id INTEGER, source TEXT NOT NULL DEFAULT '', removed_at REAL NOT NULL)")
    conn.execute("INSERT INTO disk_removals (path, repo, grp, bytes, source, removed_at) VALUES (?,?,?,?,?,?)",
                 (str(ggufs / "gone-Q4_K_M.gguf"), "org/gone", "rejected", 5, "discover", T))
    conn.commit()
    monkeypatch.setattr(ds, "move", killed)
    with pytest.raises(Died):
        downloads.backfill(conn, hub, ggufs, manifest)
    conn.close()
    monkeypatch.setattr(ds, "move", move)
    conn = ms.connect()
    try:
        downloads.backfill(conn, hub, ggufs, manifest)
        rows = [dict(r) for r in conn.execute("SELECT state, removed_by, removed_at FROM downloads")]
        assert rows == [{"state": ds.REMOVED, "removed_by": "discover", "removed_at": T}]
    finally:
        conn.close()
