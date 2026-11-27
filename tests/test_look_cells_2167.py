"""A paired run looks every K holdout cells, holdout first, and a queued job goes on looking; a paused run keeps its weights. #2167."""
import json
from types import SimpleNamespace

import pytest

from evals import run as evals_run
from evals import watch
from harness import disk, holdout, looks, paused, weedout, weedout_replay
from harness.commands import measure as measure_cmd
from tests.test_disk_paused_2099 import _paused, world  # noqa: F401
from tests.test_weedout_1439 import CASES, CH, INC, _plan

PAIR_S = 120.0


def _rows(cells: dict) -> list[dict]:
    out = []
    for i, (c, (inc, ch)) in enumerate(cells.items()):
        for n, (who, passed) in enumerate(((INC, inc), (CH, ch))):
            out.append({"case_id": c, "base": c, "candidate": who, "passed": passed, "seconds": PAIR_S / 2,
                        "metrics": {}, "seq": 2 * i + n})
    return out


def _walk(grid: dict, **kw):
    plan = _plan({c: 0.5 for c in CASES})
    return weedout_replay.walk("code", _rows(grid), CASES, INC, CH, plan, 0.05, **kw)


def test_a_look_is_sized_so_it_costs_a_twentieth_of_the_cells_between_looks_and_the_knob_overrides(monkeypatch):
    for pair_s in (6.0, 40.0, 120.0, 460.0):
        k = looks.every(pair_s)
        assert looks.LOOK_COST_S / (k * pair_s) <= looks.LOOK_SHARE and (k == 1 or looks.LOOK_COST_S / ((k - 1) * pair_s) > looks.LOOK_SHARE)
    assert looks.every(None) == 0 and looks.every(0.0) == 0
    monkeypatch.setattr(looks, "LOOK_CELLS", 7)
    assert looks.every(120.0) == 7 and looks.every(None) == 7


def test_a_run_pauses_for_a_look_after_its_cases_and_the_kind_says_so():
    eye = watch.Watch(left={"a": 3, "b": 3}, stop_cases=2)
    for key in ("a", "b"):
        eye.before(key)
        eye.lap(key)
    with pytest.raises(watch.Stop) as stop:
        eye.before("a")
    assert stop.value.kind == watch.STOP_LOOK and stop.value.why.startswith(watch.AT_LOOK)
    assert watch.pause_kind({"why": stop.value.why}) == watch.STOP_LOOK
    assert watch.Watch(left={"a": 3}).before("a") is False


def test_the_cells_of_a_look_round_up_to_whole_paired_blocks_once_per_candidate():
    assert evals_run.look_cases(5, 4, 2) == 16 and evals_run.look_cases(8, 4, 2) == 16
    assert evals_run.look_cases(3, None, 2) == 6 and evals_run.look_cases(3, None, 1) == 3
    assert evals_run.look_cases(None, 4, 2) is None and evals_run.look_cases(0, 4, 2) is None
    assert evals_run.parse_args(["--modality", "code", "--stop-cells", "9"]).stop_cells == 9


def test_a_look_at_the_end_of_a_look_slice_goes_on_in_the_budgets_last_slice_but_a_stop_time_does_not(tmp_path):
    proc = SimpleNamespace(returncode=watch.PAUSED, timed_out=False)

    def between(kind, last):
        (tmp_path / watch.PROGRESS).write_text(json.dumps({"why": "x", watch.PAUSE_KIND: kind}), encoding="utf-8")
        return measure_cmd._between_looks(proc, tmp_path, last=last, before=-1, idle=0)
    assert between(watch.STOP_LOOK, last=True) and between(watch.STOP_LOOK, last=False)
    assert between(watch.STOP_TIME, last=False) and not between(watch.STOP_TIME, last=True)
    assert not between(watch.REQUESTED, last=False)


def test_a_planted_futile_challenger_stops_within_two_looks_and_sooner_than_looks_by_the_clock():
    futile = {c: (True, False) for c in CASES}
    k = looks.every(PAIR_S)
    cells = _walk(futile, step=0, cells=k)
    clock = _walk(futile)
    assert cells.how == "futility" and not cells.adopt and cells.looks <= 2
    assert cells.cases <= 2 * k and cells.seconds < clock.seconds


def test_the_planted_better_and_worse_challengers_adopt_and_decline_as_by_the_clock():
    better = {c: (False, True) if i < 30 else (True, True) for i, c in enumerate(CASES)}
    worse = {c: (True, False) if i < 30 else (True, True) for i, c in enumerate(CASES)}
    equal = {c: (True, True) for c in CASES}
    k = looks.every(PAIR_S)
    for cells, adopts in ((better, True), (worse, False), (equal, False)):
        assert _walk(cells, step=0, cells=k).adopt is adopts is _walk(cells).adopt


def test_the_cell_walk_counts_only_cells_both_candidates_ran():
    half = [r for r in _rows({c: (True, True) for c in CASES}) if r["candidate"] == INC]
    plan = _plan({c: 0.5 for c in CASES})
    got = weedout_replay.walk("code", half, CASES, INC, CH, plan, 0.05, step=0, cells=2)
    assert got.looks == 0 and got.how == "final"


def test_a_paused_run_on_a_closed_lane_keeps_its_weights_until_a_verdict(world, monkeypatch):
    from harness import lane_gate
    _paused(world, "org/held")
    monkeypatch.setattr(lane_gate, "hold_back", lambda conn, name, lane, now=None: "the lane is closed")
    assert disk.resumed(world.conn) == {"org/held"}
    paused.settle(world.conn, paused.waiting(world.conn)[0]["id"], "done", "finished")
    assert disk.resumed(world.conn) == set()


def test_ten_stored_paired_runs_replay_to_the_verdicts_by_the_clock_in_no_more_cells_or_hours(tmp_path, monkeypatch):
    import random

    from tests.test_weedout_1439 import SPLIT, _store
    monkeypatch.setattr(holdout, "for_lane", lambda lane, root=None: SPLIT)
    conn = _store(tmp_path)
    rng = random.Random(11)
    rate = {c: (1.0 if i < 15 else 0.0 if i < 20 else 0.5) for i, c in enumerate(CASES)}
    for rid in range(1, 11):
        conn.execute("INSERT INTO runs VALUES (?, 'code', 'measure', 'holdout', 1)", (rid,))
        shift = (-0.3, 0.0, 0.5)[rid % 3]
        for seq, (c, who) in enumerate((c, w) for c in CASES for w in (INC, f"other{rid}")):
            p = rate[c] if who == INC else min(1.0, max(0.0, rate[c] + shift))
            conn.execute("INSERT INTO results (run_id, seq, candidate, case_id, passed, seconds, metrics, "
                         "failure_class) VALUES (?, ?, ?, ?, ?, 600, '{}', '')", (rid, seq, who, c, int(rng.random() < p)))
    got = weedout_replay.replay(conn, "code")
    assert len(got) == 10
    assert all(x["looked"].adopt == x["weedout"].adopt and x["looked"].how == x["weedout"].how for x in got)
    assert all(x["looked"].cases <= x["weedout"].cases and x["looked"].seconds <= x["weedout"].seconds for x in got)
    assert any(x["looked"].how == "futility" for x in got)
    assert weedout_replay.replay_lines(got)[-2].startswith("looks every K cells against every 1800 s: same verdict 10/10")
