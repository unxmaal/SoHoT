"""#893: rank() and its incumbent lookup take the store; they never open one or fall back."""
import sqlite3

import pytest

from harness import adopt, rank, winners
from harness import memory_store as ms


def test_rank_without_a_store_is_a_type_error():
    with pytest.raises(TypeError):
        rank.rank([], serving=(), measured_lanes=(), ceiling_gib=22.0)


def test_the_incumbent_lookup_without_a_store_is_a_type_error():
    with pytest.raises(TypeError):
        rank.incumbents()


def test_a_none_store_raises_instead_of_opening_the_live_one(monkeypatch):
    monkeypatch.setattr(ms, "connect", lambda *a, **k: pytest.fail("opened a store"))
    with pytest.raises(ValueError):
        rank.incumbents(None)
    with pytest.raises(ValueError):
        rank.rank([], serving=(), measured_lanes=(), ceiling_gib=22.0, conn=None)


def test_a_refused_store_raises_instead_of_ranking_against_the_typed_default(tmp_path):
    conn = sqlite3.connect(tmp_path / "old.db")
    conn.row_factory = sqlite3.Row
    with pytest.raises(sqlite3.Error):
        rank.incumbents(conn)
    with pytest.raises(sqlite3.Error):
        rank.rank([{"name": "org/m", "lane": "code"}], serving=(), measured_lanes=(),
                  ceiling_gib=22.0, conn=conn)
    conn.close()


def test_an_adopted_incumbent_wins_over_the_typed_one(store_conn, monkeypatch):
    monkeypatch.setattr(adopt, "adopted", lambda conn, machine=adopt.HERE: {"code": "llamacpp:X-35B"})
    got = rank.incumbents(store_conn)
    assert got["code"] == "llamacpp:X-35B"
    typed = winners.typed()
    assert all(got[lane] == typed[lane] for lane in got if lane != "code")


def test_explicit_incumbents_need_no_lookup(monkeypatch):
    monkeypatch.setattr(rank, "incumbents", lambda conn: pytest.fail("looked up"))
    rank.rank([], serving=(), measured_lanes=(), ceiling_gib=22.0,
              incumbents_by_lane={}, bases_by_lane={}, conn=None)
