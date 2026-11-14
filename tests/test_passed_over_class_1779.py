"""#1779, #1782: pass-over aging reads the refusal's class, never its sentence; an unreadable count is said, not {}."""
import sqlite3

import pytest

from harness import family, fetching, rank, reasons, store
from harness import memory_store as ms
from tests import fakes

GIB = fetching.GIB
DAY = 86400.0
NOW = 2_000_000_000.0
INC = {"code": "llamacpp:Ornith-1.5-35B-Q4_K_M"}
OLD = "16.0 GiB would take this run past its 40 GiB budget (32.0 GiB already fetched)"


@pytest.fixture(autouse=True)
def runnable_here(monkeypatch):
    monkeypatch.setattr(rank, "unrunnable", lambda row, machine=None: "")


@pytest.fixture
def conn():
    c = ms.connect()
    yield c
    c.close()


def seed(conn, name, gib=16.0):
    ms.record(conn, ms.Seen(name=name, source="s", url="u", why="", relevance=0, kind="weights",
                            registry=ms.HUGGINGFACE, lane="code", resolved=name))
    ms.set_size(conn, name, int(gib * GIB))
    ms.decide(conn, name, "queued", tier="inspect", detail="fits", at=NOW - 9 * DAY)


def ranked(rows, conn, **kw):
    return rank.rank(rows, serving=(), measured_lanes={"code"}, ceiling_gib=66.0, incumbents_by_lane=INC,
                     standing=family.Standing(), now=NOW, conn=conn, **kw)


def test_a_reworded_pass_over_ages_the_row_it_passed_over(conn):
    seed(conn, "org/code-0")
    fakes.passed_over(conn, "org/code-0", detail="no room tonight; try tomorrow")
    assert rank.passed_over(conn) == {"org/code-0": 1}


def test_the_old_sentence_without_its_class_does_not_age(conn):
    seed(conn, "org/a")
    ms.decide(conn, "org/a", "queued", tier="fetch", reason=reasons.LIMIT, at=NOW - DAY, detail=OLD)
    assert rank.passed_over(conn, before=NOW) == {}


def test_two_runs_on_one_utc_day_are_one_day_on_either_store(conn):
    seed(conn, "org/a")
    day = (NOW // DAY - 2) * DAY
    for frac in (0.3, 0.7):
        fakes.passed_over(conn, "org/a", at=day + frac * DAY, detail=f"16.0 GiB would take this run past its budget ({frac})")
    assert conn.execute("SELECT COUNT(*) FROM verdicts WHERE failure_class = ?", (reasons.PASSED_OVER,)).fetchone()[0] == 2
    assert rank.passed_over(conn, before=NOW) == {"org/a": 1}


def test_an_unreadable_count_raises_a_named_error(conn):
    conn.execute("ALTER TABLE verdicts RENAME TO verdicts_gone")
    conn.commit()
    with pytest.raises(rank.HintUnreadable, match="verdicts"):
        rank.passed_over(conn, before=NOW)
    with pytest.raises(rank.HintUnreadable, match="no store"):
        rank.passed_over(None)


def test_rank_says_aging_is_unavailable_and_why(conn, capsys):
    conn.execute("ALTER TABLE verdicts RENAME TO verdicts_gone")
    conn.commit()
    row = {"name": "org/a", "lane": "code", "times": 1, "description": "", "size_bytes": 16 * GIB,
           "first_seen": NOW - 5 * DAY, "last_seen": NOW - DAY}
    got = ranked([row], conn, bases_by_lane={})
    assert [r["name"] for r in got] == ["org/a"]
    err = capsys.readouterr().err
    assert "pass-over aging unavailable" in err and "verdicts" in err
    cut = conn.execute("SELECT what, dropped FROM limit_cuts WHERE knob = 'fetch_passed_over'").fetchall()
    assert len(cut) == 1 and "pass-over aging unavailable" in cut[0][0] and cut[0][1] == 1


def test_an_unreadable_family_lookup_is_said_too(tmp_path, capsys):
    empty = sqlite3.connect(tmp_path / "empty.db")
    with pytest.raises(rank.HintUnreadable):
        rank.incumbent_bases(empty, INC["code"])
    with pytest.raises(rank.HintUnreadable, match="no store"):
        rank.incumbent_bases(None, INC["code"])
    assert rank.incumbent_bases(None, "") == set()
    ranked([], empty, trace=False)
    err = capsys.readouterr().err
    assert "code incumbent's family bases unavailable" in err and "pass-over aging unavailable" in err
    empty.close()


class Recording:
    def __init__(self, conn):
        self.conn, self.sql = conn, []

    def execute(self, sql, params=()):
        self.sql.append(sql)
        return self.conn.execute(sql, params)


def test_the_aging_reads_need_no_sqlite_only_construct_on_postgres(conn):
    rec = Recording(conn)
    rank.passed_over(rec, before=NOW)
    assert len(rec.sql) == 1
    for sql in rec.sql:
        pg = store.translate(sql)
        assert "GLOB" not in sql.upper() and "sqlite_glob" not in pg, "GLOB rides on a compat function; select on the class"
        assert "AS BIGINT" not in pg, "Postgres rounds a CAST to integer where SQLite truncates"


@pytest.mark.gauntlet("a-shared-store-query-with-no-scope-or-a-scope-with-its-own-idea-of-null", site="harness/memory_store/migrations/v101.py:data:verdicts")
def test_the_backfill_classes_exactly_the_rows_the_sentence_reader_counted(conn):
    from harness.memory_store.migrations import v101
    for name in ("org/a", "org/b", "org/c"):
        seed(conn, name)
    old = [("org/a", OLD, ""), ("org/a", OLD.replace("16.0", "17.5"), ""),
           ("org/b", "65.0 GiB would take this run past its 40 GiB budget (0.0 GiB already fetched)",
            "limit:download_budget_gib>40"),
           ("org/c", "waiting on b/base, the base its runner needs, is 30.0 GiB and would take this run past "
                     "its 40 GiB budget", "")]
    for i, (name, detail, until) in enumerate(old):
        ms.decide(conn, name, "queued", tier="fetch", reason=reasons.LIMIT, at=NOW - (4 - i) * DAY,
                  detail=detail, until=until)
    ms.decide(conn, "org/c", "queued", tier="inspect", reason=reasons.LIMIT, at=NOW - 0.5 * DAY, detail=OLD)
    v101.data(conn)
    conn.commit()
    got = conn.execute("SELECT p.name, v.tier, v.failure_class FROM verdicts v JOIN proposals p "
                       "ON p.id = v.proposal_id WHERE v.failure_class <> '' ORDER BY v.id").fetchall()
    assert [tuple(r) for r in got] == [("org/a", "fetch", reasons.PASSED_OVER)] * 2
    assert rank.passed_over(conn, before=NOW) == {"org/a": 2}


@pytest.mark.gauntlet("a-shared-store-query-with-no-scope-or-a-scope-with-its-own-idea-of-null",
                      site="harness/memory_store/migrations/v104.py:data:verdicts")
def test_the_backfill_lifts_each_older_refusals_budget_once_and_leaves_the_rest_unknown(conn):
    """Schema 104 still lifts a store an older release wrote, though nothing reads the budget since #2020."""
    from harness.memory_store.migrations import v104
    for name in ("org/a", "org/b", "org/c"):
        seed(conn, name)
    ids = [ms.decide(conn, "org/a", "queued", tier="fetch", reason=reasons.LIMIT, at=NOW - DAY, detail=OLD,
                     failure_class=reasons.PASSED_OVER),
           ms.decide(conn, "org/b", "queued", tier="fetch", reason=reasons.LIMIT, at=NOW - DAY,
                     detail=OLD.replace("40 GiB", "12.5 GiB"), until="limit:download_budget_gib>12.5"),
           ms.decide(conn, "org/c", "queued", tier="fetch", reason=reasons.LIMIT, at=NOW - DAY,
                     detail="no room tonight", failure_class=reasons.PASSED_OVER),
           ms.decide(conn, "org/c", "queued", tier="fetch", reason=reasons.LIMIT, at=NOW - DAY, detail=OLD,
                     failure_class=reasons.PASSED_OVER)]
    conn.execute("UPDATE verdicts SET budget_gib = 24.0 WHERE id = ?", (ids[-1],))
    v104.data(conn)
    v104.data(conn)
    got = {r[0]: r[1] for r in conn.execute("SELECT id, budget_gib FROM verdicts WHERE tier = 'fetch'")}
    assert [got[i] for i in ids] == [40.0, 12.5, None, 24.0]
