"""#2199 and #2198: the lane gate's level does not decay with the lane's verdicts, an open lane needs a lower bar to close, and unmeasured holdout cases follow their own family."""
import json
from types import SimpleNamespace

import pytest

from harness import adopt, holdout, lane_gate, power
from harness import memory_store as ms

SPLIT = SimpleNamespace(version=holdout.VERSION, dev=["d"], holdout=["h"], as_dict=lambda: {"version": holdout.VERSION})


def _fake(monkeypatch, by_lane):
    def calc(conn, lane, split, receipts=None, effect=None):
        plan = SimpleNamespace(power=by_lane[lane], unmeasured=False, cases_needed=400, rho=0.5)
        return lane_gate.Calc("k", "spec", {}, None, (), [], {}, 5, 0.1, 0, adopt.alpha_for(0), plan)
    monkeypatch.setattr(lane_gate, "calc", calc)


def test_a_lane_gaining_verdicts_keeps_the_level_of_its_next_comparison():
    conn = ms.connect()
    ev = {"split": {"version": holdout.VERSION}, "power": {}}
    before = adopt.alpha_for(adopt.comparisons(conn, "code", holdout.VERSION))
    for i in range(30):
        adopt.record(conn, adopt.Verdict("code", "inc", f"org/c{i}", False, "x", evidence=ev), spec=f"org/c{i}")
    tested = adopt.comparisons(conn, "code", holdout.VERSION)
    assert tested == 30
    assert adopt.alpha_for(tested) == before == pytest.approx(adopt.ALPHA / adopt.FAMILY)
    conn.close()


def test_an_open_lane_at_079_stays_open_and_a_closed_one_at_079_stays_closed(monkeypatch):
    by = {"code": 0.85, "svg": 0.70}
    _fake(monkeypatch, by)
    assert lane_gate.gate_for(None, "code", SPLIT) is None
    assert lane_gate.gate_for(None, "svg", SPLIT) is not None
    by.update(code=0.79, svg=0.79)
    assert lane_gate.gate_for(None, "code", SPLIT) is None
    assert lane_gate.gate_for(None, "svg", SPLIT) is not None


def test_an_open_lane_closes_under_the_stay_bar_and_reopens_only_at_the_opening_bar(monkeypatch):
    by = {"code": 0.85}
    _fake(monkeypatch, by)
    assert lane_gate.gate_for(None, "code", SPLIT) is None
    by["code"] = 0.74
    got = lane_gate.gate_for(None, "code", SPLIT)
    assert got is not None and "lane_gate_stay_power 0.75" in got.why
    by["code"] = 0.79
    assert lane_gate.gate_for(None, "code", SPLIT) is not None
    by["code"] = 0.80
    assert lane_gate.gate_for(None, "code", SPLIT) is None


def test_a_lane_the_gate_has_not_judged_is_held_to_the_opening_bar(monkeypatch):
    _fake(monkeypatch, {"tts": 0.79})
    got = lane_gate.gate_for(None, "tts", SPLIT)
    assert got is not None and "lane_gate_power 0.80" in got.why


def _draws(family, n, passes):
    return {f"{family}-{i:03d}": [passes] for i in range(n)}


def test_unmeasured_cases_take_the_rates_of_their_own_family_not_the_lane_mix():
    draws = {**_draws("synth", 6, True), **_draws("hand", 10, False)}
    ids = [f"synth-{i:03d}" for i in range(6, 12)] + [f"hand-{i:03d}" for i in range(10, 14)]
    rates, _ = power.rates_from(draws, ids)
    assert all(rates[f"synth-{i:03d}"] == 1.0 for i in range(6, 12))
    assert all(rates[f"hand-{i:03d}"] == 0.0 for i in range(10, 14))


def test_a_family_with_too_few_measured_cases_falls_back_to_the_lane_mix():
    draws = {**_draws("hand", 10, False), **_draws("synth", power.FAMILY_MIN - 1, True)}
    rates, _ = power.rates_from(draws, [f"synth-{i:03d}" for i in range(20, 24)])
    assert set(rates.values()) <= {0.0, 1.0} and 0.0 in rates.values()


def test_a_saturated_unmeasured_block_does_not_read_as_open_through_the_lane_mix():
    draws = {**_draws("hand", 40, False), **_draws("synth", 8, True)}
    ids = [f"synth-{i:03d}" for i in range(8, 108)]
    rates, _ = power.rates_from(draws, ids)
    assert sum(rates.values()) / len(rates) == 1.0
