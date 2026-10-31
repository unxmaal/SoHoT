"""A store that cannot be read surfaces: no reader swallows the error and answers as if nothing were stored. #1432."""
from __future__ import annotations

import ast
import sqlite3
import sys
import types
from pathlib import Path

import pytest

from harness import adopt, discover, engine_timeout, memory, reply_cap, screen, yield_stop
from harness import memory_store as ms
from harness.commands import discover as discover_cmd
from harness.commands import measure as measure_cmd

ROOT = Path(__file__).resolve().parents[1]
SAYS = {"print", "note", "err", "say", "warn"}
#: "file:function" -> why a broad except around opening this home's store there answers quietly.
QUIET = {
    "harness/usage.py:record": "a usage row is written beside a generation and must never fail it; False says so",
}
#: "file:function" -> why it may call ms.connect() itself inside a broad except: it writes, so a lend never reaches it.
WRITERS = {
    "harness/delegations.py:record": "records a delegation outcome",
    "harness/disk.py:sweep": "deletes weights and records their rows",
    "harness/commands/store.py:cmd_disk": "the disk verb's own connection for deletes; it says so when there is none",
}


def _tries():
    """(file:function, Try node) for every try in harness, evals and gateway, by its innermost function."""
    for f in sorted([*ROOT.glob("harness/**/*.py"), *ROOT.glob("evals/**/*.py"), *ROOT.glob("gateway/**/*.py")]):
        rel = f.relative_to(ROOT).as_posix()

        def walk(node, fn):
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    yield from walk(child, child.name)
                else:
                    if isinstance(child, ast.Try) and fn:
                        yield f"{rel}:{fn}", child
                    yield from walk(child, fn)
        yield from walk(ast.parse(f.read_text(encoding="utf-8")), "")


def _calls(node, attrs, owners, bare=False):
    return [c for s in node.body for c in ast.walk(s) if isinstance(c, ast.Call)
            and isinstance(c.func, ast.Attribute) and c.func.attr in attrs
            and isinstance(c.func.value, ast.Name) and c.func.value.id in owners
            and (not bare or not (c.args or c.keywords))]


def _broad(h) -> bool:
    return h.type is None or any(n in ast.unparse(h.type) for n in ("Exception", "sqlite3.Error"))


def _loud(h) -> bool:
    return any(isinstance(x, ast.Raise) or isinstance(x, ast.Call) and isinstance(x.func, ast.Name) and x.func.id in SAYS
               for s in h.body for x in ast.walk(s))


def quiet_fallbacks() -> set[str]:
    """Functions that open the store inside a broad except whose handler neither raises nor says why."""
    return {where for where, t in _tries() if _calls(t, {"connect", "store"}, {"ms", "runs"})
            and any(_broad(h) and not _loud(h) for h in t.handlers)}


def lend_blind() -> set[str]:
    """Functions that call ms.connect() inside a broad except: under a lend that raises ReadOnlyStore and the reader falls back."""
    return {where for where, t in _tries() if _calls(t, {"connect"}, {"ms"}, bare=True)
            and any(_broad(h) and not any(isinstance(x, ast.Raise) for s in h.body for x in ast.walk(s)) for h in t.handlers)}


def test_no_reader_answers_quietly_when_the_store_cannot_be_read():
    assert quiet_fallbacks() == set(QUIET)


def test_no_reader_opens_the_store_itself_where_a_lent_connection_would_be_refused():
    assert lend_blind() <= set(WRITERS), "read through runs.store() so a lent connection is taken"


def test_the_scanners_see_a_quiet_fallback_and_a_lend_blind_reader(tmp_path, monkeypatch):
    bad = tmp_path / "harness" / "bad.py"
    bad.parent.mkdir()
    bad.write_text("def reader():\n    try:\n        conn = ms.connect()\n    except Exception:\n        return {}\n", encoding="utf-8")
    monkeypatch.setattr(sys.modules[__name__], "ROOT", tmp_path)
    assert quiet_fallbacks() == {"harness/bad.py:reader"}
    assert lend_blind() == {"harness/bad.py:reader"}


@pytest.fixture
def locked(monkeypatch):
    def refuse(*a, **kw):
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(ms, "connect", refuse)


def test_lane_defaults_raises_rather_than_name_the_typed_default(locked):
    with pytest.raises(sqlite3.OperationalError):
        adopt.lane_defaults()


def test_discovery_raises_rather_than_call_everything_unmeasured(locked, monkeypatch):
    monkeypatch.setattr(discover, "measured", set)
    with pytest.raises(sqlite3.OperationalError):
        discover.annotate([discover.Capability("model", "x/Model-9B", "text", "", "")])


def test_a_queued_measurement_is_not_priced_without_its_store(locked, monkeypatch):
    monkeypatch.setattr(memory, "need_gb", lambda *a, **kw: 1.0)
    monkeypatch.setattr(memory, "check_model", lambda *a, **kw: (True, "fits"))
    with pytest.raises(sqlite3.OperationalError):
        measure_cmd.room_for({"name": "x/Model-9B", "lane": "code"})


@pytest.mark.parametrize("call, says", [
    (lambda: engine_timeout.for_engine(types.SimpleNamespace(modality="code", name="x", timeout=60.0)), "engine timeout"),
    (lambda: memory.measured_reserve_gb(), "memory"),
    (lambda: reply_cap.budget_for("code", ["x"]), "reply cap"),
])
def test_a_run_guard_says_when_its_store_cannot_be_read(call, says, locked, capsys):
    call()
    err = capsys.readouterr().err
    assert says in err and "database is locked" in err


def test_a_stale_sources_warning_says_when_their_reads_cannot_be_read(monkeypatch, capsys):
    from harness import feeds

    def refuse(*a, **kw):
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(feeds, "staleness", refuse)
    assert discover_cmd._stale_sources() == []
    assert "database is locked" in capsys.readouterr().err


@pytest.mark.parametrize("module, name, call", [
    (yield_stop, "point", lambda: __import__("evals.run").run.yield_point("code", "x")),
    (engine_timeout, "basis", lambda: engine_timeout.for_engine(types.SimpleNamespace(modality="code", name="x", timeout=60.0))),
    (screen, "incumbent_draws", lambda: screen.incumbent_measure("code", ["c1"])),
])
def test_a_reader_under_a_lend_reads_the_lent_store(module, name, call, monkeypatch, tmp_path):
    seen = []
    real = getattr(module, name)

    def spy(*a, **kw):
        seen.append([x for x in (*a, *kw.values()) if isinstance(x, sqlite3.Connection)])
        return real(*a, **kw)
    monkeypatch.setattr(module, name, spy)
    conn = ms.connect(tmp_path / "lent.db")
    try:
        with ms.lend(conn):
            call()
    finally:
        conn.close()
    assert seen and all(got == [conn] for got in seen)
