"""Columns nothing read are dropped, and what they held is kept elsewhere. #419."""
import pytest

from harness import memory_store as ms


def _schema_35_store(path):
    """A store as schema 35 left it: the four columns still there, with data."""
    conn = ms.connect(path)
    conn.execute("ALTER TABLE proposals ADD COLUMN consumes TEXT NOT NULL DEFAULT ''")
    conn.execute("ALTER TABLE proposals ADD COLUMN produces TEXT NOT NULL DEFAULT ''")
    conn.execute("ALTER TABLE verdicts ADD COLUMN issue INTEGER")
    conn.execute("ALTER TABLE verdicts ADD COLUMN attaches_to TEXT NOT NULL DEFAULT ''")
    for pid, name, attaches in ((1, "ComfyUI", ""), (2, "org/lora", ""),
                                (3, "org/wf", "comfyui"), (4, "org/plain", "")):
        conn.execute("INSERT INTO proposals (id, name, first_seen, last_seen, "
                     "attaches_to, consumes, produces) VALUES (?,?,0,0,?,?,?)",
                     (pid, name, attaches, "text" if pid == 4 else "",
                      "image" if pid == 4 else ""))
    rows = ((1, "declined", "mflux ships them", 20, ""),
            (1, "queued", "see #7 for why", 7, ""),
            (2, "declined", "lora in its own card", None, "lora"),
            (3, "declined", "lora in its own card", None, "lora"),
            (4, "queued", "fits", None, ""))
    for pid, outcome, detail, issue, attaches in rows:
        conn.execute("INSERT INTO verdicts (proposal_id, outcome, tier, detail, "
                     "decided_at, issue, attaches_to) VALUES (?,?,'fetch',?,0,?,?)",
                     (pid, outcome, detail, issue, attaches))
    conn.execute("UPDATE meta SET value = '35' WHERE key = 'schema'")
    conn.commit()
    conn.close()


def _cols(conn):
    return {t: ms._columns(conn, t) for t in ("proposals", "verdicts")}


def test_a_new_store_has_none_of_the_dead_columns(tmp_path):
    conn = ms.connect(tmp_path / "new.db")
    try:
        cols = _cols(conn)
        assert not [f"{t}.{c}" for t, c in ms.DEAD_COLUMNS if c in cols[t]]
    finally:
        conn.close()


def test_the_migration_drops_them_and_keeps_what_they_held(tmp_path):
    path = tmp_path / "old.db"
    _schema_35_store(path)
    conn = ms.connect(path)
    try:
        cols = _cols(conn)
        assert not [f"{t}.{c}" for t, c in ms.DEAD_COLUMNS if c in cols[t]]
        details = [r[0] for r in conn.execute("SELECT detail FROM verdicts ORDER BY id")]
        assert details[:2] == ["mflux ships them (#20)", "see #7 for why"]
        kinds = dict(conn.execute("SELECT name, attaches_to FROM proposals").fetchall())
        assert kinds == {"ComfyUI": "", "org/lora": "lora", "org/wf": "comfyui",
                         "org/plain": ""}
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        ms.decide(conn, "org/plain", "declined", tier="fetch", detail="after")
    finally:
        conn.close()


def test_an_sqlite_that_cannot_drop_keeps_the_columns_and_still_works(tmp_path,
                                                                     monkeypatch):
    """Negative control: the drop is gated, the data is still kept."""
    path = tmp_path / "old.db"
    _schema_35_store(path)
    monkeypatch.setattr(ms.sqlite3, "sqlite_version_info", (3, 31, 1))
    conn = ms.connect(path)
    try:
        cols = _cols(conn)
        assert {"consumes", "produces"} <= cols["proposals"]
        assert {"issue", "attaches_to"} <= cols["verdicts"]
        assert conn.execute("SELECT detail FROM verdicts WHERE id = 1"
                            ).fetchone()[0] == "mflux ships them (#20)"
        ms.decide(conn, "org/plain", "declined", tier="fetch", detail="after")
    finally:
        conn.close()


def test_decide_no_longer_takes_the_dropped_columns(tmp_path):
    conn = ms.connect(tmp_path / "s.db")
    try:
        for kw in ({"issue": 20}, {"attaches_to": "lora"}):
            with pytest.raises(TypeError):
                ms.decide(conn, "x", "queued", **kw)
        assert not hasattr(ms, "composable") and not hasattr(ms, "types")
    finally:
        conn.close()
