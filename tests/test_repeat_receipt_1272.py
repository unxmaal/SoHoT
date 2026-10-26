"""--repeat on a lane outside STOCHASTIC_MODALITIES writes one row per case, and its receipt says repeat 1 (#1272)."""
import argparse

import pytest

from evals import core, environment
from evals import run as er
from evals.core import Case, Receipt, Result, comparable
from harness import memory_store as ms, runs


class _Runner:
    candidate = "fake/key"

    def warm(self):
        pass

    def run(self, case):
        return Result(case_id=case.id, candidate=self.candidate, passed=True, seconds=0.5,
                      peak_kb=7, detail="", metrics={"ink": 0.2})


def _execute(monkeypatch, tmp_path, modality, repeat):
    cases = [Case(id="a", modality=modality, prompt="p"), Case(id="b", modality=modality, prompt="q")]
    monkeypatch.setattr(core, "load_cases", lambda path: cases)
    monkeypatch.setattr(er, "build_runner", lambda *a, **k: _Runner())
    monkeypatch.setattr(er, "warn_if_pressed", lambda: argparse.Namespace(as_dict=lambda: {}))
    monkeypatch.setattr(ms.machines, "_THIS_MACHINE", None)
    monkeypatch.setattr(environment, "capture", lambda: {"hw_model": "Test,1", "os": "t", "arch": "a"})
    out = tmp_path / "out"
    args = argparse.Namespace(modality=modality, candidates="fake:spec", cases="x", out=str(out), screen=False,
                              repeat=repeat, adherence="", gateway="http://gw", from_winners=False)
    assert er._execute(args) == 0
    c = ms.connect()
    try:
        got = runs.receipt_at(c, out)
        rows = runs.rows(c, got["run_id"])
        row = c.execute("SELECT repeat_count FROM runs WHERE id = ?", (got["run_id"],)).fetchone()
        top = c.execute("SELECT MAX(repeat_index) FROM results WHERE run_id = ?", (got["run_id"],)).fetchone()[0]
        return got["receipt"]["repeat"], row["repeat_count"], top, sorted(r["case_id"] for r in rows)
    finally:
        c.close()


@pytest.mark.parametrize("modality", ["extract", "decide"])
def test_a_repeat_on_a_deterministic_lane_writes_what_its_receipt_says(monkeypatch, tmp_path, capsys, modality):
    receipt, count, top, ids = _execute(monkeypatch, tmp_path, modality, 2)
    assert ids == ["a", "b"]
    assert receipt == count == top == 1
    assert "--repeat 2" in capsys.readouterr().err


def test_a_repeat_on_a_stochastic_lane_still_repeats(monkeypatch, tmp_path):
    receipt, count, top, ids = _execute(monkeypatch, tmp_path, "svg", 2)
    assert ids == ["a#1", "a#2", "b#1", "b#2"]
    assert receipt == count == top == 2


def test_a_stored_receipt_that_claimed_repeats_it_never_ran_pairs_with_one_that_did_not():
    base = dict(modality="extract", case_ids=("a", "b"), sampling={}, gateway="http://gw")
    assert comparable(Receipt(repeat=3, **base), Receipt(repeat=1, **base))[0]
    svg = dict(base, modality="svg", case_ids=("a#1", "a#2"))
    ok, why = comparable(Receipt(repeat=2, **svg), Receipt(repeat=3, **svg))
    assert not ok and "repeat" in why
