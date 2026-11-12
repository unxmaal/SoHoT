"""Every state exclusive.state_of derives is one MOVES declares, and a holder's death is a listed move (#1821)."""
import itertools

import pytest
from gauntlet.moves import normalize

from harness import exclusive

NOW = 1_000.0


def _rows():
    for alive, expires, kind in itertools.product((True, False), (NOW - 1, NOW + 60), ("", "image")):
        yield alive, {"id": 1, "released_at": None, "expires_at": expires, "state": kind, "pid": 4242, "job_id": None}


def _state(monkeypatch, alive: bool, row: dict) -> str:
    monkeypatch.setattr(exclusive, "_holder_alive", lambda h: alive)
    return exclusive.state_of(row, NOW)


def test_every_state_state_of_returns_is_a_state_in_moves(monkeypatch):
    declared = set(normalize(exclusive.MOVES))
    seen = {exclusive.state_of(None, NOW), exclusive.state_of({"released_at": NOW}, NOW)}
    seen |= {_state(monkeypatch, alive, row) for alive, row in _rows()}
    assert seen == {exclusive.FREE, exclusive.RESERVED, exclusive.LOADING, exclusive.LAPSED, exclusive.ABANDONED}
    assert seen <= declared
    assert all(any(to == s for _, to in exclusive.MOVES) for s in seen - {exclusive.FREE})


@pytest.mark.parametrize("row", [row for alive, row in _rows() if alive], ids=lambda r: f"{r['expires_at']}-{r['state']}")
def test_a_holders_death_is_a_move_moves_lists(monkeypatch, row):
    before = _state(monkeypatch, True, row)
    after = _state(monkeypatch, False, row)
    assert after == exclusive.ABANDONED
    assert "death" in exclusive.MOVES.get((before, after), ()), f"{before} -> {after} is not in exclusive.MOVES"
