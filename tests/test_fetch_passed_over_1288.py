"""#1288, #2020: a row the screen keeps passing over rises in the shared rank; an unmeasured family base is not demoted."""
import pytest

from harness import family, knobs, rank
from tests import fakes
from harness import memory_store as ms

DAY = 86400.0
NOW = 2_000_000_000.0
GIB = 1024 ** 3
INC = {"code": "llamacpp:Ornith-1.5-35B-Q4_K_M"}


@pytest.fixture(autouse=True)
def runnable_here(monkeypatch):
    monkeypatch.setattr(rank, "unrunnable", lambda row, machine=None: "")


@pytest.fixture
def conn(tmp_path):
    c = ms.connect()
    yield c
    c.close()


def row(name, *, times=1, gib=15.0, parents=(), lane="code"):
    return {"name": name, "lane": lane, "times": times, "description": "", "size_bytes": int(gib * GIB),
            "first_seen": NOW - 5 * DAY, "last_seen": NOW - DAY,
            "parents": [(p, "finetune") for p in parents]}


def order(rows, conn=None, **kw):
    got = rank.rank(rows, serving=(), measured_lanes={"code"}, ceiling_gib=66.0, incumbents_by_lane=INC,
                    bases_by_lane={}, now=NOW, standing=family.standing(conn), conn=conn, **kw)
    return [r["name"] for r in got], {r["name"]: r for r in got}


def seen(conn, name, gib=15.0, lane="code"):
    ms.record(conn, ms.Seen(name=name, source="t", lane=lane))
    conn.execute("UPDATE proposals SET size_bytes = ? WHERE name = ?", (int(gib * GIB), name))
    conn.commit()


def refused(conn, name, at):
    fakes.passed_over(conn, name, at=at)


def test_a_row_the_screen_keeps_passing_over_rises_above_fresh_rows_of_higher_base_value(conn):
    big, fresh = row("old/Peer-27B-GGUF"), row("new/Peer-27B-GGUF", times=6)
    assert order([big, fresh])[0] == [fresh["name"], big["name"]]
    seen(conn, big["name"])
    days = 1 + int((order([fresh])[1][fresh["name"]]["value"] - order([big])[1][big["name"]]["value"]) / rank.PASSED_OVER)
    for d in range(days):
        refused(conn, big["name"], NOW - (days - d) * DAY)
    names, got = order([big, fresh], conn=conn)
    assert names == [big["name"], fresh["name"]]
    assert f"passed over by the screen on {days} days" in got[big["name"]]["value_why"]


def test_the_pass_over_term_counts_pass_over_days_since_the_last_other_fetch_verdict(conn):
    seen(conn, "a/Peer-27B-GGUF")
    refused(conn, "a/Peer-27B-GGUF", NOW - 4 * DAY)
    ms.decide(conn, "a/Peer-27B-GGUF", "queued", tier="fetch", reason="harness", at=NOW - 3 * DAY,
              detail="needs its own runner: no runner in the code lane can load it")
    refused(conn, "a/Peer-27B-GGUF", NOW - 2 * DAY)
    refused(conn, "a/Peer-27B-GGUF", NOW - 2 * DAY + 3600)
    refused(conn, "a/Peer-27B-GGUF", NOW - DAY)
    assert rank.passed_over(conn, before=NOW) == {"a/Peer-27B-GGUF": 2}


def test_the_pass_over_term_restarts_after_a_screen_verdict(conn):
    seen(conn, "a/Peer-27B-GGUF")
    for d in (5, 4, 3):
        refused(conn, "a/Peer-27B-GGUF", NOW - d * DAY)
    assert rank.passed_over(conn, before=NOW) == {"a/Peer-27B-GGUF": 3}
    ms.decide(conn, "a/Peer-27B-GGUF", "screened", tier=ms.SCREEN, at=NOW - 2 * DAY, reason="candidate", detail="ok")
    assert rank.passed_over(conn, before=NOW) == {}
    assert rank.passed_over(conn, before=NOW - 2.5 * DAY) == {"a/Peer-27B-GGUF": 3}


def test_the_pass_over_term_is_capped():
    capped = int(rank.PASSED_OVER_MAX / rank.PASSED_OVER)
    a, b = row("a/Peer-27B-GGUF"), row("b/Peer-27B-GGUF")
    _, got = order([a, b], passed={a["name"]: capped, b["name"]: capped * 3})
    assert got[a["name"]]["value"] == pytest.approx(got[b["name"]]["value"])
    _, none = order([a])
    assert got[a["name"]]["value"] - none[a["name"]]["value"] == pytest.approx(rank.PASSED_OVER_MAX)


def test_a_row_at_the_pass_over_cap_records_a_cut(conn):
    a = row("a/Peer-27B-GGUF")
    order([a], conn=conn, passed={a["name"]: int(rank.PASSED_OVER_MAX / rank.PASSED_OVER)})
    assert conn.execute("SELECT COUNT(*) FROM limit_cuts WHERE knob = 'fetch_passed_over_max'").fetchone()[0] == 0
    order([a], conn=conn, passed={a["name"]: int(rank.PASSED_OVER_MAX / rank.PASSED_OVER) + 1})
    got = conn.execute("SELECT value, kept, dropped FROM limit_cuts WHERE knob = 'fetch_passed_over_max'").fetchall()
    assert [tuple(r) for r in got] == [(rank.PASSED_OVER_MAX, 0, 1)]


def test_the_pass_over_knobs_are_registered_with_the_values_the_rank_uses():
    step, cap = knobs.KNOBS["fetch_passed_over"], knobs.KNOBS["fetch_passed_over_max"]
    assert step.default() == rank.PASSED_OVER and step.default() in step.values and step.unit == "points"
    assert cap.default() == rank.PASSED_OVER_MAX and cap.default() in cap.values and cap.unit == "points"
    assert "#1288" in step.note and "#1288" in cap.note


def paired(conn, name, outcome, at, parents=("Qwen/Qwen3.8-27B",)):
    ms.record(conn, ms.Seen(name=name, source="t", lane="code"))
    pid = conn.execute("SELECT id FROM proposals WHERE name = ?", (name,)).fetchone()[0]
    for p in parents:
        conn.execute("INSERT OR IGNORE INTO lineage (proposal_id, parent, kind) VALUES (?, ?, 'finetune')", (pid, p))
    conn.commit()
    ms.decide(conn, name, outcome, tier=ms.ADOPT, at=at, reason="candidate", detail="code: does not beat the incumbent")


BASE = row("unsloth/Qwen3.8-27B-GGUF")
SIBLING = row("someone/Qwen3.8-27B-Tuned-GGUF", parents=("Qwen/Qwen3.8-27B",))


def test_a_familys_unmeasured_base_is_not_demoted_for_its_derivatives_losses(conn):
    paired(conn, "ukisai/Swift-Qwen3.8-27B-GGUF", "declined", NOW - 3 * DAY)
    paired(conn, "ISTA-DASLab/Qwen3.8-27B-GSQ-RCO-GGUF", "declined", NOW - 2 * DAY)
    st = family.standing(conn)
    base, why = st.demotion(BASE, "code")
    assert base == 0.0 and "qwen3.8-27b base itself has no paired loss in code" in why
    assert st.demotion(SIBLING, "code")[0] == family.DEMOTION
    assert st.demotion(row("bartowski/Qwen_Qwen3.8-27B-GGUF", parents=("Qwen/Qwen3.8-27B",)), "code")[0] == 0.0


def test_a_familys_base_forms_are_demoted_once_a_base_form_lost(conn):
    paired(conn, "ukisai/Swift-Qwen3.8-27B-GGUF", "declined", NOW - 3 * DAY)
    paired(conn, "mlx-community/Qwen3.8-27B-4bit", "declined", NOW - 2 * DAY)
    st = family.standing(conn)
    assert st.demotion(BASE, "code")[0] == family.DEMOTION
