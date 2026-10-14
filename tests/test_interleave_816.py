"""A paired run alternates incumbent and challenger case by case, so a run paused early has paired cells to look at. #816."""
from collections import Counter

import pytest

from evals import run as R
from evals import watch
from evals.runners.base import BaseRunner
from tests.test_pause_813 import _args, clock, quiet  # noqa: F401

INC, CH = "org/inc", "org/ch"


class Named(BaseRunner):
    """Each case takes `each` seconds of the fake clock and records itself in the shared `log`."""

    def __init__(self, name, clock, log, each=10.0):
        self.candidate = self.spec = name
        self.clock, self.log, self.each = clock, log, each
        self.ran, self.warms = [], 0

    def warm(self):
        self.warms += 1

    def generate(self, case):
        self.ran.append(case.id)
        self.log.append(self.candidate)
        self.clock.now += self.each
        return "", 0


def _pair(monkeypatch, clock, block=1):
    log = []
    runners = {INC: Named(INC, clock, log), CH: Named(CH, clock, log)}
    monkeypatch.setattr(R, "build_runner", lambda candidate, *a, **k: runners[candidate])
    monkeypatch.setattr(R, "pair_block", lambda candidates, gateway: block)
    return runners, log


def _paired(rows) -> int:
    seen = Counter(r["case_id"] for r in rows)
    return sum(1 for n in seen.values() if n == 2)


@pytest.mark.parametrize("k", [1, 2, 7, 9, 10])
def test_a_run_paused_after_k_cases_has_half_of_them_paired(monkeypatch, tmp_path, quiet, clock, k):
    out = tmp_path / "run"
    _pair(monkeypatch, clock)
    rc = R._execute(_args(out, candidates=f"{INC},{CH}", stop_at=clock.now + 10.0 * k - 1))
    assert rc == watch.PAUSED
    _, rows = watch.read(out)
    assert len(rows) == k
    assert _paired(rows) == k // 2


def test_cases_alternate_incumbent_then_challenger_on_the_same_case(monkeypatch, tmp_path, quiet, clock):
    out = tmp_path / "run"
    runners, log = _pair(monkeypatch, clock)
    R._execute(_args(out, candidates=f"{INC},{CH}", stop_at=clock.now + 59.0))
    assert log == [INC, CH] * 3
    assert runners[INC].ran == runners[CH].ran
    assert runners[INC].warms == runners[CH].warms == 1


def test_blocks_bound_the_swaps_when_both_models_cannot_be_held(monkeypatch, tmp_path, quiet, clock):
    out = tmp_path / "run"
    runners, log = _pair(monkeypatch, clock, block=3)
    R._execute(_args(out, candidates=f"{INC},{CH}", stop_at=clock.now + 119.0))
    assert log == [INC] * 3 + [CH] * 3 + [INC] * 3 + [CH] * 3
    # One untimed warm per block, so the reload a block switch costs is never charged to a case.
    assert runners[INC].warms == runners[CH].warms == 2


def test_no_block_keeps_the_candidate_major_order(monkeypatch, tmp_path, quiet, clock):
    out = tmp_path / "run"
    runners, log = _pair(monkeypatch, clock, block=None)
    R._execute(_args(out, candidates=f"{INC},{CH}", stop_at=clock.now + 59.0))
    assert log == [INC] * 6


def test_a_checkpoint_of_the_old_order_resumes_with_the_challenger_catching_up(monkeypatch, tmp_path, quiet, clock):
    """The 2026-10-13 run paused with every row the incumbent's; resumed, the challenger runs those cases first."""
    out = tmp_path / "run"
    runners, _ = _pair(monkeypatch, clock, block=None)
    R._execute(_args(out, candidates=f"{INC},{CH}", stop_at=clock.now + 59.0))
    done = list(runners[INC].ran)
    assert len(done) == 6 and not runners[CH].ran
    runners, log = _pair(monkeypatch, clock)
    rc = R._execute(_args(out, candidates=f"{INC},{CH}", resume=True, stop_at=clock.now + 99.0))
    assert rc == watch.PAUSED
    assert runners[CH].ran[:6] == done and log[:6] == [CH] * 6
    assert log[6:] == [INC, CH, INC, CH]
    assert not set(runners[INC].ran) & set(done)
    _, rows = watch.read(out)
    assert _paired(rows) == 8


def test_a_resumed_paired_run_finishes_every_case_once(monkeypatch, tmp_path, quiet, clock):
    out = tmp_path / "run"
    _pair(monkeypatch, clock)
    R._execute(_args(out, candidates=f"{INC},{CH}", stop_at=clock.now + 49.0))
    runners, _ = _pair(monkeypatch, clock)
    assert R._execute(_args(out, candidates=f"{INC},{CH}", resume=True)) == 0
    _, rows = watch.read(out)
    keys = [(r["candidate"], r["case_id"]) for r in rows]
    assert len(keys) == len(set(keys))
    assert _paired(rows) * 2 == len(rows)


class Home:
    def __init__(self, table):
        self.table = table

    def __call__(self, candidate, gateway):
        return self.table.get(candidate, ("", "", None))


def test_both_on_one_router_that_holds_two_alternate_case_by_case():
    home = Home({"a": ("http://r", "A", 2), "b": ("http://r", "B", 2)})
    assert R.pair_block(["a", "b"], "", home=home) == 1


def test_a_router_that_holds_one_runs_in_blocks():
    home = Home({"a": ("http://r", "A", 1), "b": ("http://r", "B", 1)})
    assert R.pair_block(["a", "b"], "", home=home) == R.PAIR_BLOCK


def test_two_servers_each_holding_one_model_alternate():
    home = Home({"a": ("http://r", "A", 2), "b": ("http://mlx", "B", 1)})
    assert R.pair_block(["a", "b"], "", home=home) == 1


def test_one_model_under_two_settings_alternates_on_a_router_that_holds_one():
    home = Home({"a": ("http://r", "A", 1), "a,x": ("http://r", "A", 1)})
    assert R.pair_block(["a", "a,x"], "", home=home) == 1


def test_a_ds4_candidate_keeps_the_candidate_major_order():
    assert R.pair_block(["ds4:Q", "b"], "", home=Home({})) is None


def test_the_segments_merge_consecutive_runs_of_one_candidate():
    order = ["c1", "c2", "c3", "c4"]
    rest = [["c3", "c4"], order]
    got = R.paired_segments(order, rest, 1)
    assert got == [(1, ["c1", "c2"]), (0, ["c3"]), (1, ["c3"]), (0, ["c4"]), (1, ["c4"])]
