"""soh ledger, inventory and context share one store chooser that names its store; an unread store never reads as none. #1781."""
from __future__ import annotations

import json
import sqlite3
import time

import pytest

from harness import cli, ledger, paths, store
from harness import memory_store as ms
from tests.test_ledger_ratio_1688 import _ccusage


def _store(rows: int = 0):
    conn = ms.connect()
    now = time.time()
    conn.executemany("INSERT INTO gateway_requests (at, alias, lane, client, purpose, prompt_tokens, "
                     "completion_tokens) VALUES (?, 'sohot-decide', 'decide', 'python-httpx', 'work', 100, 20)",
                     [(now - 60 * i,) for i in range(rows)])
    conn.commit()
    conn.close()


def _drop(table: str) -> None:
    conn = ms.connect()
    conn.execute(f"DROP TABLE {table}" + (" CASCADE" if store.backend() == store.POSTGRES else ""))
    conn.commit()
    conn.close()


def _ledger(capsys, *argv) -> tuple[int, str, dict]:
    rc = cli.main(["ledger", "--since", "1d", *argv])
    text = capsys.readouterr().out
    rc_json = cli.main(["ledger", "--since", "1d", "--json"])
    doc = json.loads(capsys.readouterr().out)
    assert rc_json == 0
    return rc, text, doc


def _recorded() -> int:
    conn = ms.connect()
    try:
        return conn.execute("SELECT COUNT(*) AS n FROM ledger_days").fetchone()["n"]
    finally:
        conn.close()


@pytest.fixture
def live(monkeypatch):
    """This test's home is the default home, so its store is the live one."""
    monkeypatch.setattr(paths, "DEFAULT_HOME", paths.home())


def test_an_empty_window_on_the_live_store_says_none_and_records(monkeypatch, capsys, live):
    _ccusage(monkeypatch)
    _store(0)
    rc, text, doc = _ledger(capsys)
    assert rc == 0
    assert "local     none: no gateway requests in the window" in text
    assert f"store     {store.backend()} " in text
    assert doc["store"]["live"] and doc["store"]["outcome"] == "answered"
    assert doc["reads"]["gateway_requests"] == {"outcome": "answered", "rows": 0}
    assert cli.main(["ledger", "--since", "1d", "--record"]) == 0
    assert "recorded" in capsys.readouterr().out
    assert _recorded() > 0


def test_the_store_line_names_backend_where_and_schema(monkeypatch, capsys, live):
    _ccusage(monkeypatch)
    _store(3)
    rc, text, doc = _ledger(capsys)
    line = next(x for x in text.splitlines() if x.startswith("store "))
    where = "/discovery.db" if store.backend() == store.SQLITE else "/discovery as "
    assert line.startswith(f"store     {store.backend()} ") and where in line, line
    assert line.endswith(f", schema {ms.SCHEMA_VERSION}"), line
    assert "local     work" in text and "none" not in text.split("local     work")[1].splitlines()[0]
    assert doc["reads"]["gateway_requests"] == {"outcome": "answered", "rows": 3}


def test_a_missing_table_says_so_not_none_and_record_refuses(monkeypatch, capsys, live):
    _ccusage(monkeypatch)
    _store(0)
    _drop("gateway_requests")
    rc, text, doc = _ledger(capsys)
    assert rc == 0
    assert "no gateway requests" not in text
    assert "local     UNREAD gateway_requests missing_table: no table gateway_requests" in text
    assert text.splitlines()[0].startswith("local:cloud UNREAD: gateway_requests missing_table")
    assert doc["reads"]["gateway_requests"]["outcome"] == "missing_table"
    assert cli.main(["ledger", "--since", "1d", "--record"]) == 1
    out = capsys.readouterr().out
    assert "--record refused" in out and "gateway_requests missing_table" in out
    assert _recorded() == 0


def test_an_unreadable_store_says_so_not_none_and_record_refuses(monkeypatch, capsys, live):
    _ccusage(monkeypatch)
    with monkeypatch.context() as m:
        if store.backend() == store.POSTGRES:
            m.setenv("PGPORT", "1")
        else:
            (paths.home() / "discovery.db").write_bytes(b"this is not a database" * 100)
        rc, text, doc = _ledger(capsys)
        assert "no gateway requests" not in text
        assert "UNREADABLE" in text and "local     UNREAD gateway_requests unreadable" in text
        assert doc["store"]["outcome"] == "unreadable"
        assert cli.main(["ledger", "--since", "1d", "--record"]) == 1
        assert "--record refused" in capsys.readouterr().out


def test_no_store_says_so_not_none(monkeypatch, capsys, live):
    _ccusage(monkeypatch)
    assert not (paths.home() / "discovery.db").exists()
    rc, text, doc = _ledger(capsys)
    assert "no gateway requests" not in text and "local     UNREAD gateway_requests no_store" in text
    assert not (paths.home() / "discovery.db").exists()
    assert cli.main(["ledger", "--since", "1d", "--record"]) == 1
    assert "--record refused" in capsys.readouterr().out


def test_the_stale_sqlite_file_under_a_postgres_home_is_the_wrong_store(monkeypatch, capsys, live):
    _ccusage(monkeypatch)
    _store(5)
    was = store.backend()
    (paths.home() / store.MARKER).write_text(json.dumps({"backend": "postgres", "host": "127.0.0.1"}),
                                             encoding="utf-8")
    monkeypatch.setenv(store.BACKEND_ENV, "sqlite")
    rc, text, doc = _ledger(capsys)
    assert "no gateway requests" not in text and "local     work" not in text
    assert "local     UNREAD gateway_requests wrong_store: LOCALHARNESS_STORE=sqlite overrides" in text
    assert "pre-cutover file" in text
    assert doc["store"]["outcome"] == "wrong_store" and not doc["store"]["live"]
    assert cli.main(["ledger", "--since", "1d", "--record"]) == 1
    assert "--record refused" in capsys.readouterr().out
    monkeypatch.setenv(store.BACKEND_ENV, was)
    (paths.home() / store.MARKER).unlink()
    assert _recorded() == 0


def test_a_stray_pg_variable_against_the_home_marker_is_the_wrong_store(monkeypatch):
    (paths.home() / store.MARKER).write_text(json.dumps({"backend": "postgres", "host": "127.0.0.1", "port": 5433,
                                                         "dbname": "discovery"}), encoding="utf-8")
    with monkeypatch.context() as m:
        m.delenv(store.BACKEND_ENV, raising=False)
        m.setenv("PGHOST", "elsewhere.example")
        m.setattr(store, "postgres_connect", lambda **k: pytest.fail("a wrong store is never opened"))
        c = store.choose_read()
    (paths.home() / store.MARKER).unlink()
    assert (c.backend, c.outcome, c.conn) == ("postgres", "wrong_store", None)
    assert "PGHOST=elsewhere.example overrides store.json's host 127.0.0.1" in c.line()


def test_a_scratch_home_is_named_and_record_refuses(monkeypatch, capsys):
    _ccusage(monkeypatch)
    _store(0)
    rc, text, doc = _ledger(capsys)
    assert "NOT the live store: LOCALHARNESS_HOME is not the default home" in text
    assert "local     none: no gateway requests in the window" in text
    assert cli.main(["ledger", "--since", "1d", "--record"]) == 1
    assert "not the live store" in capsys.readouterr().out
    assert _recorded() == 0


def test_a_failed_query_is_failed_not_none(monkeypatch):
    _store(1)
    conn = store.open_ro(paths.home() / "discovery.db")
    try:
        with pytest.raises(store.Unread) as got:
            store.read(conn, "gateway_requests", "SELECT no_such_column FROM gateway_requests")
        assert got.value.outcome == "failed"
        with pytest.raises(store.Unread, match="missing_table"):
            ledger.recorded(sqlite3.connect(":memory:"), "2026-01-01")
    finally:
        conn.close()


def test_inventory_and_context_name_the_store_and_refuse_a_wrong_one(monkeypatch, capsys):
    _store(1)
    (paths.home() / store.MARKER).write_text(json.dumps({"backend": "postgres"}), encoding="utf-8")
    monkeypatch.setenv(store.BACKEND_ENV, "sqlite")
    assert cli.main(["inventory", "time", "--no-effort"]) == 1
    out = capsys.readouterr().out
    assert "store: sqlite <LOCALHARNESS_HOME>/discovery.db" in out and "UNREAD wrong_store" in out
    assert cli.main(["context", "--source", "otel"]) == 1
    out = capsys.readouterr().out
    assert "otel_events UNREAD wrong_store" in out and "no tool results" not in out


def test_context_on_a_store_without_otel_events_says_missing_not_none(capsys):
    _store(0)
    _drop("otel_events")
    assert cli.main(["context", "--source", "otel"]) == 1
    out = capsys.readouterr().out
    assert "otel_events UNREAD missing_table" in out and "no tool results" not in out


def test_inventory_on_a_store_missing_a_table_says_which(capsys):
    _store(0)
    _drop("jobs")
    assert cli.main(["inventory", "time", "--no-effort"]) == 1
    assert "store UNREAD missing_table" in capsys.readouterr().out
