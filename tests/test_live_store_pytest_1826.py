"""Under pytest the live store is refused before any connection, by a guard no monkeypatch.undo() drops (#1826)."""
import json
import os
import sqlite3
import subprocess
import sys
import types
from pathlib import Path

import pytest
from gauntlet import scanners as gscanners

from harness import memory_store as ms
from harness import paths, store
from tests import conftest
from tests.gauntlet import scanners

LIVE_DB = (paths.DEFAULT_HOME / "discovery.db").resolve()


@pytest.fixture
def spies(monkeypatch):
    """Every sqlite3 and psycopg connection the code tries, none of them made."""
    calls = []
    monkeypatch.setattr(sqlite3, "connect", lambda *a, **k: calls.append(("sqlite", a)) or pytest.fail("sqlite opened"))
    fake = types.SimpleNamespace(connect=lambda *a, **k: calls.append(("psycopg", a)) or pytest.fail("psycopg opened"),
                                 ClientCursor=object)
    monkeypatch.setitem(sys.modules, "psycopg", fake)
    # No Keychain read for a password either, had the guard let the dsn be built.
    monkeypatch.setenv("PGPASSWORD", "never-used")
    yield calls
    del store.REFUSALS[:]


def _undo_or_real_home(monkeypatch, how):
    if how == "undo":
        monkeypatch.undo()
        monkeypatch.delenv(paths.ENV_VAR, raising=False)
    else:
        monkeypatch.setenv(paths.ENV_VAR, str(paths.DEFAULT_HOME))


@pytest.mark.parametrize("how", ["undo", "real-home"])
@pytest.mark.parametrize("backend", [store.SQLITE, store.POSTGRES])
def test_a_test_that_drops_its_home_is_refused_the_live_store_before_any_connection(monkeypatch, how, backend):
    _undo_or_real_home(monkeypatch, how)
    monkeypatch.setenv(store.BACKEND_ENV, backend)
    calls = []
    monkeypatch.setattr(sqlite3, "connect", lambda *a, **k: calls.append(a))
    monkeypatch.setitem(sys.modules, "psycopg", types.SimpleNamespace(connect=lambda *a, **k: calls.append(a),
                                                                       ClientCursor=object))
    monkeypatch.setenv("PGPASSWORD", "never-used")
    assert ms.db_path().resolve() == LIVE_DB
    with pytest.raises(store.LiveStoreUnderTest, match="live store"):
        ms.connect()
    assert calls == [] and len(store.REFUSALS) == 1
    del store.REFUSALS[:]


@pytest.mark.parametrize("opener", ["open_ro", "open_as_is", "use_pool", "scratch"])
def test_every_store_opener_is_refused_the_live_home(monkeypatch, spies, opener):
    monkeypatch.setenv(paths.ENV_VAR, str(paths.DEFAULT_HOME))
    monkeypatch.setenv(store.BACKEND_ENV, store.POSTGRES if opener in ("use_pool", "scratch") else store.SQLITE)
    monkeypatch.setitem(sys.modules, "psycopg_pool", types.SimpleNamespace(ConnectionPool=lambda *a, **k: spies.append(a)))
    with pytest.raises(store.LiveStoreUnderTest):
        getattr(store, opener)()
    assert spies == [] and store._POOL == {}


def _fake_live(tmp_path, port):
    live = tmp_path / "live"
    live.mkdir()
    (live / store.MARKER).write_text(json.dumps({"backend": "postgres", "host": "127.0.0.1", "port": port,
                                                 "dbname": "discovery"}), encoding="utf-8")
    return live


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "::1"])
def test_pg_variables_naming_the_live_postgres_are_refused_from_a_scratch_home(tmp_path, monkeypatch, spies, host):
    flag = store.guard_flag(_fake_live(tmp_path, 5433), os.environ[store.GUARD_ENV])
    monkeypatch.setenv(store.GUARD_ENV, flag)
    monkeypatch.setenv(store.BACKEND_ENV, store.POSTGRES)
    monkeypatch.setenv("PGHOST", host)
    monkeypatch.setenv("PGPORT", "5433")
    monkeypatch.setenv("PGDATABASE", "discovery")
    with pytest.raises(store.LiveStoreUnderTest, match="5433/discovery"):
        ms.connect()
    assert spies == []


def test_another_postgres_is_let_through(tmp_path, monkeypatch, spies):
    monkeypatch.setenv(store.GUARD_ENV, store.guard_flag(_fake_live(tmp_path, 5433)))
    monkeypatch.setenv(store.BACKEND_ENV, store.POSTGRES)
    monkeypatch.setenv("PGHOST", "127.0.0.1")
    monkeypatch.setenv("PGPORT", "5432")
    with pytest.raises(pytest.fail.Exception, match="psycopg opened"):
        ms.connect()
    assert [k for k, _ in spies] == ["psycopg"] and store.REFUSALS == []


@pytest.mark.gauntlet("a-guard-built-and-tested-that-nothing-invokes", site="harness/store.py:guard_flag")
def test_the_session_guard_names_the_real_live_home_and_its_postgres():
    entries = json.loads(os.environ[store.GUARD_ENV])
    real = {"db": str(LIVE_DB), "postgres": ""}
    if store.marker(paths.DEFAULT_HOME).get("backend") == store.POSTGRES:
        real["postgres"] = store.pg_target({}, paths.DEFAULT_HOME)
        assert real["postgres"].count(":") == 1 and "/" in real["postgres"]
    assert real in entries


@pytest.mark.parametrize("spell", ["str", "path", "uri", "as_uri", "bytes"])
def test_conftests_sqlite_connect_refuses_the_live_file_in_any_spelling(monkeypatch, spell):
    opened = []
    monkeypatch.setattr(sqlite3.connect, "real", lambda *a, **k: opened.append(a))
    target = {"str": str(LIVE_DB), "path": LIVE_DB, "uri": f"file:{LIVE_DB}?mode=ro",
              "as_uri": f"{LIVE_DB.as_uri()}?mode=rw", "bytes": os.fsencode(LIVE_DB)}[spell]
    with pytest.raises(store.LiveStoreUnderTest):
        sqlite3.connect(target, uri=spell.endswith("uri"))
    assert opened == []
    del store.REFUSALS[:]
    sqlite3.connect(":memory:")
    assert len(opened) == 1


def test_a_nested_session_keeps_the_live_homes_it_inherited(tmp_path):
    one, two = tmp_path / "one", tmp_path / "two"
    both = store.guard_flag(two, store.guard_flag(one))
    assert [e["db"] for e in json.loads(both)] == [str((h / "discovery.db").resolve()) for h in (one, two)]
    assert store.guard_flag(two, both) == both


def test_the_guard_outlives_monkeypatch_undo(monkeypatch):
    flag = os.environ[store.GUARD_ENV]
    monkeypatch.setenv(paths.ENV_VAR, "/elsewhere")
    monkeypatch.undo()
    assert os.environ[store.GUARD_ENV] == flag
    assert getattr(sqlite3.connect, "real", None) is not None


INNER = '''
from harness import memory_store as ms
from harness import paths, store
import pytest


def test_swallows(monkeypatch):
    monkeypatch.undo()
    try:
        ms.connect()
    except Exception:
        pass


def test_expects(monkeypatch):
    monkeypatch.undo()
    with pytest.raises(store.LiveStoreUnderTest):
        ms.connect()
    del store.REFUSALS[:]
'''


def test_a_test_that_swallows_the_refusal_still_fails_and_the_live_home_is_untouched(tmp_path):
    real = Path(conftest.__file__)
    (tmp_path / "conftest.py").write_text(
        f"exec(compile(open({str(real)!r}).read(), {str(real)!r}, 'exec'))\n", encoding="utf-8")
    (tmp_path / "test_inner.py").write_text(INNER, encoding="utf-8")
    user = tmp_path / "user"
    (user / "localharness").mkdir(parents=True)
    clean = {k: v for k, v in os.environ.items()
             if k not in (store.BACKEND_ENV, paths.ENV_VAR, "PYTEST_ADDOPTS") and not k.startswith("PG")}
    got = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:xdist", "-p", "no:randomly",
                          "-p", "no:cacheprovider", "-o", "addopts=", str(tmp_path / "test_inner.py")],
                         capture_output=True, text=True, cwd=paths.REPO,
                         env={**clean, "HOME": str(user), "USERPROFILE": str(user)}, timeout=conftest.HANG_DUMP_S)
    assert "2 passed, 1 error" in got.stdout, got.stdout[-3000:]
    assert "ERROR at teardown of test_swallows" in got.stdout and "reached the live store" in got.stdout
    assert list((user / "localharness").iterdir()) == []


def test_the_scanner_finds_an_undo_left_unpinned_and_a_lifted_guard():
    bad = ("def test_x(monkeypatch):\n    monkeypatch.setattr(m, 'a', 1)\n    monkeypatch.undo()\n    run()\n"
           "def test_y(monkeypatch):\n    monkeypatch.delenv(store.GUARD_ENV)\n")
    assert scanners.undone_home_pins(bad, "tests/test_x.py") == [
        "tests/test_x.py:3: monkeypatch.undo() drops conftest's LOCALHARNESS_HOME; setenv it again after",
        "tests/test_x.py:6: lifts SOHOT_TEST_LIVE, the guard that keeps a test off the live store"]
    good = ("def test_x(monkeypatch, tmp_path):\n    monkeypatch.undo()\n"
            "    monkeypatch.setenv(paths.ENV_VAR, str(tmp_path))\n    run()\n")
    assert scanners.undone_home_pins(good, "tests/test_x.py") == []
    twice = good.replace("    run()\n", "    monkeypatch.undo()\n    run()\n")
    assert scanners.undone_home_pins(twice, "tests/test_x.py") == [
        "tests/test_x.py:4: monkeypatch.undo() drops conftest's LOCALHARNESS_HOME; setenv it again after"]


def test_no_test_undoes_conftests_home_without_pinning_it_again():
    found = gscanners.scan_tree(paths.REPO, scanners.undone_home_pins, gscanners.is_python,
                                lambda rel: rel.startswith("tests/"))
    assert found == [], "\n".join(found)
