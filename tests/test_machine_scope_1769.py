"""One declared meaning for an unstamped row per question of the store (#1769); job twins are one machine's (#1770)."""
import sqlite3
import sys
import time
from pathlib import Path

import pytest

from harness import adopt, deploy, node_deploy, paused_jobs, reasons
from harness import job_state as js
from harness import memory_store as ms
from harness import workqueue as wq
from harness import job_settle

OTHER = {"hw_model": "Other1,1", "os": "Linux", "arch": "x86_64", "host": "b-host"}
REPO = Path(__file__).resolve().parent.parent


def _other(conn) -> int:
    """Machine B's row in the shared store, this process still answering as machine A."""
    from harness import machine
    got = ms.remember_machine(conn, {**OTHER, "fingerprint": machine.fingerprint(*OTHER.values())})
    conn.commit()
    return got


def _stamp(conn, job_id, mid) -> None:
    conn.execute("UPDATE jobs SET machine_id = ? WHERE id = ?", (mid, int(job_id)))
    conn.commit()


@pytest.fixture
def conn():
    c = ms.connect()
    ms.remember_machine(c)
    c.commit()
    try:
        yield c
    finally:
        c.close()


def test_every_rule_names_a_store_table_with_a_machine_column_and_one_declared_meaning(conn):
    from harness import machine_scope as scope
    for rule, null in scope.RULES.items():
        assert null in scope.MEANINGS, rule
        assert "." in rule, f"{rule}: name the question, table.question"
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info({scope.table(rule)})")} if isinstance(
            conn, sqlite3.Connection) else None
        assert cols is None or "machine_id" in cols, rule


@pytest.mark.parametrize("null,mid,seen", [
    ("every", 1, {1, None}), ("every", None, {None}), ("every", [1, 2], {1, 2, None}), ("every", [], {None}),
    ("unknown", 1, {1}), ("unknown", None, {None}), ("unknown", [1, 2], {1, 2}),
    ("nobody", 1, {1}), ("nobody", None, set()), ("nobody", [], set()),
])
def test_each_meaning_of_an_unstamped_row_selects_what_it_says(monkeypatch, null, mid, seen):
    from harness import machine_scope as scope
    monkeypatch.setitem(scope.RULES, "t.q", null)
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE t (machine_id INTEGER)")
    db.executemany("INSERT INTO t VALUES (?)", [(1,), (2,), (3,), (None,)])
    here, args = scope.where("t.q", mid)
    assert {r[0] for r in db.execute(f"SELECT machine_id FROM t WHERE {here}", args)} == seen


@pytest.mark.parametrize("null", ["every", "unknown", "nobody"])
@pytest.mark.parametrize("mid", [1, None, [1, 2], []])
def test_holds_answers_one_read_row_as_where_selects_it(monkeypatch, null, mid):
    from harness import machine_scope as scope
    monkeypatch.setitem(scope.RULES, "t.q", null)
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE t (machine_id INTEGER)")
    db.executemany("INSERT INTO t VALUES (?)", [(1,), (2,), (3,), (None,)])
    here, args = scope.where("t.q", mid)
    assert {r[0] for r in db.execute(f"SELECT machine_id FROM t WHERE {here}", args)} == {
        m for m in (1, 2, 3, None) if scope.holds("t.q", m, mid)}


def test_an_unstamped_adoption_serves_every_machine_by_the_declared_rule(monkeypatch):
    from harness import adoption_state as st
    from harness import machine_scope as scope
    row = {"all_machines": 0, "machine_id": None}
    assert st._applies(row, (7,))
    monkeypatch.setitem(scope.RULES, "adoptions.served", scope.NOBODY)
    assert not st._applies(row, (7,))


def test_an_undeclared_question_is_refused():
    from harness import machine_scope as scope
    with pytest.raises(KeyError):
        scope.where("deploys", 1)


#: Backfills that stamp legacy rows; they ask no machine whose a row is.
_BACKFILLS = "harness/memory_store/migrations/"


def _own_meanings(files: dict) -> list:
    from gauntlet import detectors

    from tests.gauntlet import registry
    hits = detectors.unscoped_query(detectors.parse(files), production=registry.production,
                                    **registry.DETECTOR_CONFIG["unscoped_query"])
    return [h.site for h in hits if h.site.endswith(":null-scope") and not h.site.startswith(_BACKFILLS)]


def test_no_code_but_machine_scope_writes_what_an_unstamped_row_means():
    from gauntlet import detectors

    from tests.gauntlet import registry
    files = detectors.sources(REPO, production=registry.production)
    assert "harness/machine_scope.py" in files
    assert _own_meanings(files) == [], "ask harness/machine_scope.where with a declared rule instead"


def test_a_reader_with_its_own_meaning_for_an_unstamped_row_is_found():
    src = ('def f(conn, mid):\n    return conn.execute("SELECT * FROM deploys WHERE machine_id = ? '
           'OR machine_id IS NULL", (mid,))\n')
    assert _own_meanings({"harness/x.py": "def f():\n    pass\n"}) == []
    assert _own_meanings({"harness/x.py": src}) == ["harness/x.py:f:null-scope"]
    assert _own_meanings({"harness/machine_scope.py": src.replace("def f", "def where")}) == []


def _unstamped_deploy(conn, outcome: str = "") -> int:
    did = deploy._insert(conn, "c" * 40, None, Path("/releases/x"), "d" * 40, time.time() - 3600)
    conn.execute("UPDATE deploys SET machine_id = NULL WHERE id = ?", (did,))
    if outcome:
        conn.execute("UPDATE deploys SET outcome = ?, stage = ?, finished_at = ? WHERE id = ?",
                     (outcome, outcome, time.time(), did))
    conn.commit()
    return did


def test_an_unstamped_deploy_is_no_machines_to_follow_serve_or_date(conn):
    _unstamped_deploy(conn, deploy.DEPLOYED)
    assert node_deploy.target(conn) is None, "a node would follow a deploy no machine is known to have made"
    assert deploy.serving(conn) is None
    assert deploy.deployed_at(conn) is None


def test_an_unstamped_unfinished_deploy_is_no_machines_to_settle(conn):
    did = _unstamped_deploy(conn)
    assert deploy.settle(conn, now=time.time() + 86400) == []
    assert conn.execute("SELECT outcome FROM deploys WHERE id = ?", (did,)).fetchone()[0] == ""


def test_another_machines_pending_confirmation_does_not_stand_for_this_machines(conn, monkeypatch):
    monkeypatch.delenv(wq.JOB_ENV, raising=False)
    held = adopt.Verdict("code", "inc-spec", "org/x", False, "", failure_class=reasons.CONFIRMING)
    theirs = adopt.queue_confirmation(conn, 7, held)
    _stamp(conn, theirs["id"], _other(conn))
    mine = adopt.queue_confirmation(conn, 7, held)
    assert mine is not None and mine["id"] != theirs["id"]
    assert wq.get(mine["id"], conn=conn)["machine_id"] == ms.machine_row(conn)
    assert adopt.queue_confirmation(conn, 7, held) is None, "this machine's own pending one still counts"


def _running(conn, argv) -> dict:
    job = wq.add(argv, conn=conn)
    assert js.move(conn, job["id"], wq.PENDING, wq.RUNNING, js.CLAIMED, machine_id=ms.machine_row(conn))
    conn.commit()
    return wq.get(job["id"], conn=conn)


def test_a_paused_job_is_not_continued_by_another_machines_job_with_its_argv(conn):
    argv = [sys.executable, "-c", "pass"]
    job = _running(conn, argv)
    twin = wq.add(argv, conn=conn)
    _stamp(conn, twin["id"], _other(conn))
    assert job_settle._repend(conn, job, js.CONTENTION_PAUSE)
    got = wq.get(job["id"], conn=conn)
    assert got["state"] == wq.PENDING, f"machine B's job {twin['id']} was taken to carry it on: {got['note']}"


def test_a_paused_job_is_continued_by_this_machines_job_with_its_argv(conn):
    argv = [sys.executable, "-c", "pass"]
    job = _running(conn, argv)
    twin = wq.add(argv, conn=conn)
    assert job_settle._repend(conn, job, js.CONTENTION_PAUSE)
    got = wq.get(job["id"], conn=conn)
    assert got["state"] == wq.PAUSED and wq.label(twin["id"]) in got["note"]


def test_a_paused_jobs_twin_is_looked_for_on_its_own_machine_only(conn):
    argv = [sys.executable, "-c", "pass"]
    job = wq.add(argv, conn=conn)
    later = wq.add(argv, conn=conn)
    _stamp(conn, later["id"], _other(conn))
    job = wq.get(job["id"], conn=conn)
    assert paused_jobs._twin(conn, job, None) is None
    _stamp(conn, later["id"], job["machine_id"])
    assert paused_jobs._twin(conn, job, None) == int(later["id"])
