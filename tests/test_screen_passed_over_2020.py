"""#2020: the screen's bound, not a download budget, is what passes a fetchable row over, and rank ages it for that."""
import argparse
import time

import pytest

from harness import fetching, rank, reasons, screen
from harness.commands import screen as screen_cmd
from harness import memory_store as ms

GIB = fetching.GIB


@pytest.fixture
def store():
    c = ms.connect()
    yield c
    c.close()


def seed(conn, name, lane="code"):
    ms.record(conn, ms.Seen(name=name, source="s", url="u", why="", relevance=0, kind="weights",
                            registry=ms.HUGGINGFACE, lane=lane, resolved=name))
    ms.set_size(conn, name, 4 * GIB)
    ms.decide(conn, name, "queued", tier="inspect", detail="fits")


def plan_row(name, state=screen.WAITING, lane="code"):
    return {"name": name, "resolved": name, "lane": lane, "modality": lane, "state": state, "why_not": "",
            "candidate": name}


def run(store, monkeypatch, plan, **kw):
    screened = []
    monkeypatch.setattr("harness.wip.LIMIT", 99)
    monkeypatch.setattr(screen_cmd, "_screen_plan", lambda want: plan)
    monkeypatch.setattr(screen_cmd, "_release", lambda store, r: None)
    monkeypatch.setattr(screen_cmd, "_screen_one",
                        lambda a, store, r: (screened.append(r["name"]), (True, "screened", None))[1])
    a = argparse.Namespace(lane="", run=True, top=None, limit=kw.get("limit", 9), screen_s=kw.get("screen_s", 0),
                           screen_until=kw.get("screen_until"))
    assert screen_cmd._report_screen(a) == 0
    return screened


def passed(store):
    return {r[0] for r in store.execute(
        "SELECT p.name FROM verdicts v JOIN proposals p ON p.id = v.proposal_id WHERE v.failure_class = ?",
        (reasons.PASSED_OVER,))}


def test_the_rows_a_screen_count_leaves_are_passed_over_and_rise_in_rank(store, monkeypatch):
    for name in ("org/a", "org/b", "org/c"):
        seed(store, name)
    seed(store, "org/laneless", lane="")
    plan = [plan_row("org/a"), plan_row("org/b"), plan_row("org/c"), plan_row("org/laneless", lane="")]
    assert run(store, monkeypatch, plan, limit=1) == ["org/a"]
    assert passed(store) == {"org/b", "org/c"}
    assert rank.passed_over(store) == {"org/b": 1, "org/c": 1}
    got = store.execute("SELECT v.tier, v.reason, v.until, v.detail FROM verdicts v JOIN proposals p "
                        "ON p.id = v.proposal_id WHERE p.name = 'org/b' ORDER BY v.id DESC LIMIT 1").fetchone()
    day = time.strftime("%Y-%m-%d", time.gmtime())
    assert tuple(got) == ("fetch", reasons.LIMIT, "", f"not fetched {day}: the screen count is reached")


def test_a_screen_on_the_next_day_ages_the_row_again_and_a_second_the_same_day_does_not(store, monkeypatch):
    seed(store, "org/a")
    plan = [plan_row("org/a")]
    run(store, monkeypatch, plan, limit=0)
    run(store, monkeypatch, plan, limit=0)
    assert rank.passed_over(store, before=time.time() + 1) == {"org/a": 1}
    real = time.gmtime
    monkeypatch.setattr(time, "gmtime", lambda t=None: real(time.time() + 86400 if t is None else t))
    run(store, monkeypatch, plan, limit=0)
    assert len(passed_rows(store)) == 2


def passed_rows(store):
    return store.execute("SELECT id FROM verdicts WHERE failure_class = ?", (reasons.PASSED_OVER,)).fetchall()


def test_the_rows_the_ceiling_leaves_are_passed_over_and_a_ready_row_is_not(store, monkeypatch):
    for name in ("org/a", "org/b"):
        seed(store, name)
    plan = [plan_row("org/a"), plan_row("org/ready", state=screen.READY), plan_row("org/b")]
    assert run(store, monkeypatch, plan, screen_until=time.time() - 1, screen_s=600) == []
    assert passed(store) == {"org/a", "org/b"}


def test_a_screen_that_reaches_every_row_passes_none_over(store, monkeypatch):
    for name in ("org/a", "org/b"):
        seed(store, name)
    assert run(store, monkeypatch, [plan_row("org/a"), plan_row("org/b")]) == ["org/a", "org/b"]
    assert passed(store) == set()
