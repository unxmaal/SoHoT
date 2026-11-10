"""decide_by_hand and record read and cut in the store they are handed, never this home's. #1673."""
import pytest

from harness import adopt, human
from harness import memory_store as ms


@pytest.fixture
def other(tmp_path):
    home = ms.connect()
    conn = ms.connect(tmp_path / "other.db")
    try:
        yield conn, home
    finally:
        conn.close()
        home.close()


def _votes(conn, cases: int, answers=("b", "b", "b")) -> list[dict]:
    pairs = []
    for i in range(cases):
        for ans in answers:
            human.record("image", f"c{i}", "x", "y", ans, conn=conn)
        pairs.append({"case": f"c{i}", "a": "x", "b": "y"})
    return pairs


def _cuts(conn) -> list[tuple]:
    return [tuple(r) for r in conn.execute("SELECT knob, kept, dropped FROM limit_cuts ORDER BY id")]


def test_a_by_hand_win_is_read_from_the_votes_in_the_store_given(other):
    conn, _ = other
    v = adopt.decide_by_hand("image", "x", "y", _votes(conn, 4), conn=conn)
    assert (v.adopt, v.votes, v.held) == (True, 12, "")
    assert v.why.startswith("preferred by hand: ")


def test_a_by_hand_win_held_on_too_few_votes_is_cut_in_the_store_given(other):
    conn, home = other
    v = adopt.decide_by_hand("image", "x", "y", _votes(conn, 1), conn=conn)
    assert v.held and v.votes == 3
    assert _cuts(conn) == [("harness/adopt.py:MIN_VOTES", 0, 1)]
    assert _cuts(home) == []


def test_every_decline_cut_a_record_makes_lands_in_the_store_given(other):
    conn, home = other
    ms.record(conn, ms.Seen(name="org/new", source="feeds", lane="tts", kind="weights", resolved="org/new"))
    evidence = {"min_effect": {"noise": 0.05, "effect": 0.1, "seen": 0.08},
                "lane_effect": {"noise": 0.12, "seen": 0.08}}
    adopt.record(conn, adopt.Verdict("tts", "inc", "org/new", False, "not established", evidence=evidence,
                                     alpha_cut=(0.0312, 0.0125)))
    assert _cuts(conn) == [("adopt_min_effect", 0, 1), ("adopt_effect", 0, 1), ("adopt_alpha", 0, 1)]
    assert _cuts(home) == []
