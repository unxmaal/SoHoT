"""A cut with no store to move into is appended once, never taken and re-spooled: that was quadratic per cut (#1520)."""
import json
import sqlite3

from harness import cuts

SITE = "harness/ci_budget.py:WARN_SHARE"


def _spooled_whats():
    return [json.loads(line)["what"] for line in cuts._spool_path().read_text(encoding="utf-8").splitlines()]


def test_cuts_in_a_home_with_no_store_each_write_one_row(monkeypatch):
    monkeypatch.setattr(cuts, "_own_store", lambda: None)
    writes = []
    real = cuts._spool
    monkeypatch.setattr(cuts, "_spool", lambda *rows: writes.append(len(rows)) or real(*rows))
    for i in range(40):
        cuts.cut(SITE, f"cut {i}", value=1)
    assert writes == [1] * 40, "each cut appended once; a flush with no store must not re-spool the backlog"
    assert _spooled_whats() == [f"cut {i}" for i in range(40)]


def test_rows_a_store_refuses_go_back_to_the_spool_in_one_write(monkeypatch, tmp_path):
    monkeypatch.setattr(cuts, "_own_store", lambda: None)
    for i in range(5):
        cuts.cut(SITE, f"cut {i}", value=1)
    ro_path = tmp_path / "ro.db"
    sqlite3.connect(ro_path).close()
    refusing = sqlite3.connect(f"file:{ro_path}?mode=ro", uri=True)
    writes = []
    real = cuts._spool
    monkeypatch.setattr(cuts, "_spool", lambda *rows: writes.append(len(rows)) or real(*rows))
    assert cuts.flush(refusing) == 0
    refusing.close()
    assert writes == [5]
    assert _spooled_whats() == [f"cut {i}" for i in range(5)]
