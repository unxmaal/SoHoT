"""A delegation from any checkout lands in the live store as it stands, never migrating it. #1717."""
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

import pytest

from harness import cli, completion, delegations, local_tools, paths, store, usage
from harness import memory_store as ms
from harness.memory_store.schema import SCHEMA_VERSION
from tests.test_mcp_delegate import fake  # noqa: F401

# The subjects are SQLite files: a fake live home's store, and the stand-in behind a stubbed postgres_connect.
pytestmark = pytest.mark.sqlite_store


def _open(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _rows(path, table):
    conn = _open(path)
    try:
        return [dict(r) for r in conn.execute(f"SELECT * FROM {table}")]
    finally:
        conn.close()


def _digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@pytest.fixture
def elsewhere(tmp_path, monkeypatch, fake):  # noqa: F811
    """This code is not the deploy checkout, the fake engine answers directly, and no connect may migrate the live store."""
    monkeypatch.setattr(paths, "runs_elsewhere", lambda: tmp_path / "deploy")
    monkeypatch.setattr(completion, "is_gateway", lambda base, *a, **k: False)
    monkeypatch.setattr(delegations, "_SKIPPED", set(), raising=False)
    real = ms.connect

    def connect(path=None):
        caller = sys._getframe(1).f_globals.get("__name__")
        if caller == delegations.__name__ and paths.is_live(path or ms.db_path()):
            raise AssertionError("a delegation opened the live store with migrate rights")
        return real(path)
    monkeypatch.setattr(ms, "connect", connect)
    return fake


def _live(tmp_path, monkeypatch, name="live"):
    """A head-schema SQLite store made before its home becomes the default one."""
    home = tmp_path / name
    path = home / "discovery.db"
    ms.connect(path).close()
    monkeypatch.setattr(paths, "DEFAULT_HOME", home)
    monkeypatch.delenv(paths.ENV_VAR, raising=False)
    assert paths.is_live(ms.db_path()) and usage.target() is None
    return path


@pytest.fixture
def live_sqlite(tmp_path, monkeypatch, elsewhere):
    return _live(tmp_path, monkeypatch)


@pytest.fixture
def live_pg(tmp_path, monkeypatch, elsewhere):
    """The live home names Postgres in store.json; postgres_connect hands out a stand-in at head schema."""
    standin = tmp_path / "pg.db"
    ms.connect(standin).close()
    home = tmp_path / "live"
    home.mkdir()
    (home / store.MARKER).write_text(json.dumps({"backend": store.POSTGRES}), encoding="utf-8")
    monkeypatch.setattr(paths, "DEFAULT_HOME", home)
    monkeypatch.delenv(paths.ENV_VAR, raising=False)
    monkeypatch.delenv(store.BACKEND_ENV, raising=False)
    monkeypatch.setattr(store, "postgres_connect", lambda *a, **k: _open(standin))
    from harness import delegate
    # The machine lock reads the store through Postgres SQL the stand-in cannot answer.
    monkeypatch.setattr(delegate, "busy", lambda: "")
    assert store.backend() == store.POSTGRES and usage.target() is None
    return standin


def _delegate_and_close(capsys):
    got = local_tools.complete(prompt="write add", lane="code")
    assert cli.main(["delegated", got["call_id"], "used", "it ran", "--json"]) == 0
    return got


def test_a_delegation_from_another_checkout_writes_both_rows_to_the_live_sqlite_store(live_sqlite, capsys):
    got = _delegate_and_close(capsys)
    (d,) = _rows(live_sqlite, "delegations")
    (r,) = _rows(live_sqlite, "gateway_requests")
    assert d["call_id"] == r["call_id"] == got["call_id"]
    assert (d["outcome"], d["why"]) == ("used", "it ran")
    assert r["client"] == usage.DIRECT_CLIENT and r["purpose"] == "work"


def test_a_delegation_from_another_checkout_writes_both_rows_to_the_live_postgres_store(live_pg, capsys):
    got = _delegate_and_close(capsys)
    (d,) = _rows(live_pg, "delegations")
    (r,) = _rows(live_pg, "gateway_requests")
    assert d["call_id"] == r["call_id"] == got["call_id"] and d["outcome"] == "used"
    assert not (paths.DEFAULT_HOME / "discovery.db").exists()


def test_a_live_store_at_another_schema_is_left_alone_with_one_line(live_pg, capsys):
    conn = _open(live_pg)
    conn.execute("UPDATE meta SET value = ? WHERE key = 'schema'", (str(SCHEMA_VERSION - 1),))
    conn.commit()
    conn.close()
    before = _digest(live_pg)
    got = local_tools.complete(prompt="write add", lane="code")
    assert got["call_id"] and got["text"]
    err = capsys.readouterr().err
    assert err.count("not recorded in the live store") == 1, err
    assert f"schema {SCHEMA_VERSION - 1}" in err
    assert cli.main(["delegated", got["call_id"], "used"]) == 1
    assert _digest(live_pg) == before


def test_a_process_on_another_backend_never_writes_the_live_home(tmp_path, monkeypatch, live_pg, capsys):
    monkeypatch.setenv(store.BACKEND_ENV, store.SQLITE)
    monkeypatch.setattr(store, "postgres_connect", lambda *a, **k: pytest.fail("connected"))
    local_tools.complete(prompt="write add", lane="code")
    assert "this process talks sqlite" in capsys.readouterr().err
    assert not (paths.DEFAULT_HOME / "discovery.db").exists()


def test_other_rows_keep_the_branch_guard(live_sqlite):
    from harness import delegate
    delegate.complete("code", "write add")
    assert usage.record(usage.direct_row("code", "", "m", 0.0)) is False
    assert _rows(live_sqlite, "gateway_requests") == []


def test_requests_made_on_a_delegation_s_behalf_take_its_route(live_sqlite):
    from harness import delegate
    with delegations.on_behalf("local-1"):
        delegate.complete("code", "write add")
    (r,) = _rows(live_sqlite, "gateway_requests")
    assert r["call_id"] == "local-1" and r["client"] == usage.DIRECT_CLIENT


@pytest.mark.parametrize("delegated", [True, False])
def test_ask_s_requests_are_on_behalf_only_of_a_delegation(tmp_path, delegated):
    from harness import ask
    (tmp_path / "a.log").write_text("FAILED tests/test_x.py::test_y\n", encoding="utf-8")
    seen = []

    def complete(lane, prompt, **kw):
        seen.append(delegations.behalf())
        return {"text": "none", "lane": lane, "prompt_tokens": 1, "completion_tokens": 1}
    ask.ask([str(tmp_path / "a.log")], "what failed", roots=[ask.Root(tmp_path)], delegated=delegated,
            complete=complete)
    assert seen and {bool(c) for c in seen} == {delegated} and len(set(seen)) == 1 and not delegations.behalf()


def test_under_the_test_home_nothing_reaches_the_real_home(monkeypatch, elsewhere):
    monkeypatch.setattr(delegations, "_live_as_is", lambda path: pytest.fail("opened the live store"))
    assert not paths.is_live(ms.db_path())
    got = _delegate_and_close(None)
    conn = ms.connect()
    try:
        row = conn.execute("SELECT outcome FROM delegations WHERE call_id = ?", (got["call_id"],)).fetchone()
        assert row["outcome"] == "used"
        assert conn.execute("SELECT COUNT(*) FROM gateway_requests").fetchone()[0] == 1
    finally:
        conn.close()


def test_an_eval_reading_the_live_home_writes_no_delegation(monkeypatch, live_sqlite):
    monkeypatch.setenv(paths.EVAL_ENV, "1")
    assert local_tools.complete(prompt="write add", lane="code")["call_id"]
    assert _rows(live_sqlite, "delegations") == _rows(live_sqlite, "gateway_requests") == []


@pytest.mark.parametrize("delegated", [True, False])
def test_spans_requests_are_on_behalf_only_of_a_delegation(tmp_path, delegated):
    from harness import ask, spans
    from tests.test_spans_1336 import TEXT, model, quote
    (tmp_path / "a.py").write_text(TEXT, encoding="utf-8", newline="\n")
    inner, seen = model(quote(20, 22)), []

    def complete(*a, **kw):
        seen.append(delegations.behalf())
        return inner(*a, **kw)
    spans.ask_file(str(tmp_path / "a.py"), "q", roots=[ask.Root(tmp_path)], delegated=delegated, complete=complete)
    assert seen and {bool(c) for c in seen} == {delegated} and len(set(seen)) == 1 and not delegations.behalf()
