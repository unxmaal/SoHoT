"""#2101: a look that sees every holdout cell decides there, and one with cells still to run does not."""
import dataclasses

import pytest

from harness import holdout, looks, power

INC, CH = "llamacpp:Inc", "llamacpp:Ch"
SPLIT = holdout.Split("code", tuple(f"d{i}" for i in range(60)), tuple(f"h{i}" for i in range(40)), False)
PLAN = power.Plan(repeat=1, power=0.6, cells=40, cases=40, effect=0.1, alpha=0.05, target=0.8, cap=16,
                  capped=True, stochastic=True, observed=200, why="", cases_needed=40, odds=(0.3, 0.02))


@pytest.fixture(autouse=True)
def code_lane(monkeypatch):
    monkeypatch.setattr(holdout, "for_lane", lambda lane, *a, **k: dataclasses.replace(SPLIT, lane=lane))


def _rows(n: int, gained: int, lost: int) -> list[dict]:
    out = []
    for i, c in enumerate(SPLIT.holdout[:n]):
        inc = not (i < gained)
        ch = inc if i >= gained + lost else not inc
        out += [{"case_id": c, "candidate": INC, "passed": inc, "seconds": 1.0},
                {"case_id": c, "candidate": CH, "passed": ch, "seconds": 1.0}]
    return out


def _look(rows):
    return looks.look(rows, lane="code", inc_key=INC, ch_key=CH, split=SPLIT, plan=PLAN.as_dict(),
                      alpha=0.0167, spent_before=0.0003, n=2, spec=CH)


def test_a_look_at_every_holdout_cell_with_the_challenger_ahead_but_short_declines():
    look, v = _look(_rows(40, gained=8, lost=6))
    assert (look.cells, look.cp) == (40, 0.0)
    assert look.decision == "final" and "continues" not in look.text
    assert v is not None and not v.adopt


def test_a_look_with_cells_left_and_power_above_the_bound_continues():
    look, v = _look(_rows(20, gained=6, lost=1))
    assert look.cp >= looks.FUTILITY_CP
    assert (look.decision, v) == ("continue", None)


def test_a_final_look_with_no_alpha_left_still_declines():
    look, v = looks.look(_rows(40, gained=8, lost=6), lane="code", inc_key=INC, ch_key=CH, split=SPLIT,
                         plan=PLAN.as_dict(), alpha=0.0167, spent_before=0.0167, n=3, spec=CH)
    assert look.decision == "final" and not v.adopt and v.why.startswith("final: look 3 at 40/40")
