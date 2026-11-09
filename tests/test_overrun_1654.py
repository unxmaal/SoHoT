"""A paired overrun needs measured incumbent seconds; without them the challenger is held to its plan per case. #1654."""
import json
from pathlib import Path

from evals import watch
from harness import cuts, reuse
from harness import watchdog as wd
from tests.test_overrun_864 import _eval_at
from tests.test_watchdog import ids, judged

RUN = Path(__file__).parent / "fixtures" / "watchdog_1654" / "20261108-232512-adopt-decide"
INC, CH = "imajev-4b-Q8_0", "nimble/Bespoke-Nimble-9B"


def _load():
    ident, rows = watch.read(RUN)
    return ident, rows, json.loads((RUN / watch.PROGRESS).read_text(encoding="utf-8"))


def _overruns(fake):
    return [f for f in judged(fake)[1] if f.criterion == "overrun"]


def _recorded(monkeypatch):
    got = []
    monkeypatch.setattr(cuts, "cut", lambda knob, what, **kw: got.append((knob, what, kw)))
    return got


def test_the_logged_run_is_the_one_the_watchdog_stopped(tmp_path):
    ident, rows, progress = _load()
    walls = {k: {r["case_id"]: r["wall_s"] for r in rows if r["candidate"] == k} for k in (INC, CH)}
    pairs = [c for c in walls[CH] if c in walls[INC]]
    assert len(pairs) == 195 and all(r["failure_class"] == "harness_error" for r in rows if r["candidate"] == INC)
    ratio = sum(walls[CH][c] for c in pairs) / sum(walls[INC][c] for c in pairs)
    assert round(ratio, 3) == 11692.635
    planned = progress["planned_s_per_case"]
    assert round(planned[CH] / planned[INC], 3) == 12.078
    assert round(sum(walls[CH].values()) / len(walls[CH]), 2) < planned[CH]


def test_a_challenger_within_plan_against_an_incumbent_that_measured_nothing_is_not_an_overrun(tmp_path, monkeypatch):
    got = _recorded(monkeypatch)
    ident, rows, progress = _load()
    assert ids(judged(_eval_at(tmp_path, ident, rows, progress))[1], "overrun") == []
    (why,) = [w for k, w, _ in got if k == "watchdog_overrun_min_pairs"]
    assert f"195 paired case(s) carry no measured seconds against {INC}: judged per case" in why


def test_a_challenger_over_plan_per_case_is_still_an_overrun_when_the_incumbent_measured_nothing(tmp_path):
    ident, rows, progress = _load()
    slow = [{**r, "wall_s": r["wall_s"] * 3, "seconds": r["seconds"] * 3} if r["candidate"] == CH else r for r in rows]
    (f,) = _overruns(_eval_at(tmp_path, ident, slow, progress))
    assert f.evidence["candidate"] == CH and f.evidence["basis"] == "seconds per case"
    assert "observed_ratio" not in f.evidence and "no measured seconds" in f.evidence["why"]


def _pair_rows(n_bad, inc_s=1.0, ch_s=10.0, n=10):
    rows = []
    for i in range(n):
        took = 0.0 if i < n_bad else inc_s
        rows.append({"case_id": f"c{i}", "candidate": INC, "wall_s": took, "seconds": took,
                     "failure_class": "harness_error" if i < n_bad else "", "metrics": {}})
        rows.append({"case_id": f"c{i}", "candidate": CH, "wall_s": ch_s, "seconds": ch_s, "failure_class": "",
                     "metrics": {}})
    return rows


IDENT = {"modality": "decide", "candidates": [INC, "nimble:x"], "repeat": 1, "max_tokens": 4000}
PROGRESS = {"total": 100, "specs": {INC: INC, CH: "nimble:x"}}


def test_the_measured_pairs_are_still_compared_when_some_incumbent_rows_failed(tmp_path):
    planned = {INC: 1.0, CH: 4.0}
    (f,) = _overruns(_eval_at(tmp_path, IDENT, _pair_rows(4), PROGRESS, planned))
    assert f.evidence["basis"] == "seconds" and f.evidence["paired"] == 6 and f.evidence["observed_ratio"] == 10.0


def test_a_harness_error_row_with_seconds_is_not_paired(tmp_path):
    ck = watch.Checkpoint(tmp_path, IDENT)
    for r in _pair_rows(6):
        r = {**r, "wall_s": 0.01, "seconds": 0.01} if r["failure_class"] else r
        ck.add(r, r["wall_s"])
    _, by = wd._cells({**PROGRESS, "_dir": str(tmp_path)})
    assert wd._paired(by, INC, CH) is None and wd._unmeasured(by, INC, CH) == 6


def test_reused_incumbent_cells_with_no_stored_seconds_carry_none(tmp_path, monkeypatch):
    ck = watch.Checkpoint(tmp_path, {**IDENT, "reuse": {"digest": "d"}})
    for r in _pair_rows(0):
        if r["candidate"] == CH:
            ck.add(r, r["wall_s"])
    monkeypatch.setattr(reuse, "timing", lambda out: {f"c{i}": (None if i < 6 else 1.0, None) for i in range(10)})
    _, by = wd._cells({**PROGRESS, "_dir": str(tmp_path)})
    assert [by[INC][f"c{i}"][0] for i in (0, 9)] == [None, 1.0]
    assert wd._paired(by, INC, CH) is None and wd._unmeasured(by, INC, CH) == 6
