"""#2181: stt, tts and ocr are gated by a paired signed-rank test on the per-case WER/CER, and planned in the metric's own units."""
import itertools
import random
import statistics
from types import SimpleNamespace

import pytest

from harness import adopt, continuous, holdout, lane_gate, looks, paired, power
from harness import memory_store as ms


def _rows(pairs, lane_metric="wer", inc="inc", ch="ch", repeats=1, passed_under=0.0):
    """Rows for `pairs` of (incumbent error, challenger error) per case, each drawn `repeats` times."""
    out = []
    for i, (a, b) in enumerate(pairs):
        for name, v in ((inc, a), (ch, b)):
            for r in range(1, repeats + 1):
                out.append({"candidate": name, "case_id": f"c{i}" + (f"#{r}" if repeats > 1 else ""), "passed": v <= passed_under,
                            "failure_class": "", "metrics": {lane_metric: v}})
    return out


def _planted(n=60, seed=1, gain=0.04):
    """Every case fails the pass bar for both models, the challenger's error lower by a case-sized amount."""
    rng = random.Random(seed)
    base = [rng.uniform(0.2, 0.6) for _ in range(n)]
    return [(x, max(0.0, x - rng.uniform(0.0, 2 * gain))) for x in base]


def _exact_signed_rank_p(d):
    d = [x for x in d if x]
    n = len(d)
    order = sorted(abs(x) for x in d)
    ranks = [(order.index(abs(x)) + order.count(abs(x)) / 2 + 0.5) for x in d]
    plus = sum(r for r, x in zip(ranks, d) if x > 0)
    sums = [sum(r for r, keep in zip(ranks, mask) if keep) for mask in itertools.product((0, 1), repeat=n)]
    lo = sum(s <= plus + 1e-9 for s in sums)
    hi = sum(s >= plus - 1e-9 for s in sums)
    return min(1.0, 2 * min(lo, hi) / 2 ** n)


def test_the_signed_rank_p_is_the_exact_permutation_p_with_ties_and_zeros():
    rng = random.Random(3)
    for _ in range(12):
        d = [rng.choice([-0.3, -0.2, -0.1, 0.0, 0.1, 0.1, 0.2, 0.4, 0.7]) for _ in range(rng.randint(5, 11))]
        assert continuous.signed_rank(d)[2] == pytest.approx(_exact_signed_rank_p(d), abs=1e-9)
    assert continuous.signed_rank([0.0, 0.0, 0.0]) == (0.0, 0, 1.0)


def test_the_normal_p_above_the_exact_limit_stays_within_a_hundredth_of_the_exact_sum(monkeypatch):
    rng = random.Random(5)
    d = [rng.gauss(0.2, 1.0) for _ in range(continuous.EXACT_N + 1)]
    approx = continuous.signed_rank(d)[2]
    monkeypatch.setattr(continuous, "EXACT_N", 200)
    assert approx == pytest.approx(continuous.signed_rank(d)[2], abs=0.006)


def _mixed():
    """A few large gains against many small losses: the signs favour the incumbent, the sizes the challenger."""
    return [(0.3, 0.2 + 0.001 * i) for i in range(28)] + [(0.2, 0.21 + 0.0004 * i) for i in range(32)]


def test_the_normal_p_with_a_block_of_tied_changes_matches_the_exact_sum_too(monkeypatch):
    sets = []
    for seed in range(1, 9):
        rng = random.Random(seed)
        sets.append([rng.choice([-0.1, 0.1, 0.1]) for _ in range(30)] + [rng.choice([-1, 1]) * (0.2 + 0.05 * i) for i in range(12)])
    approx = [continuous.signed_rank(d)[2] for d in sets]
    monkeypatch.setattr(continuous, "EXACT_N", 200)
    for got, d in zip(approx, sets):
        assert got == pytest.approx(continuous.signed_rank(d)[2], abs=0.006)


def test_the_signed_rank_test_reads_the_sizes_of_the_changes_where_the_sign_test_reads_their_direction():
    cell = continuous.cell(_rows(_mixed()), "inc", "ch", "tts")
    assert cell.gained == 28 and cell.lost == 32 and cell.shift > 0 and cell.ahead
    assert cell.p <= adopt.ALPHA < paired.sign_test(28, 60)
    won = adopt.decide("tts", {"candidate": "inc"}, {"candidate": "ch"}, _rows(_mixed()))
    assert won.adopt and "28 gained against 32 lost" in won.why
    back = adopt.decide("tts", {"candidate": "inc"}, {"candidate": "ch"}, _rows([(b, a) for a, b in _mixed()]))
    assert not back.adopt and "significantly worse" in back.why


def test_a_planted_better_pair_separates_and_two_identical_models_do_not():
    cell = continuous.cell(_rows(_planted()), "inc", "ch", "stt")
    assert cell.p_value is not None and cell.p <= adopt.ALPHA and cell.ahead and not cell.behind
    assert cell.shift > 0.01 and cell.gained > cell.lost
    same = continuous.cell(_rows([(x, x) for x, _ in _planted()]), "inc", "ch", "stt")
    assert same.p == 1.0 and not same.ahead and same.gained == same.lost == 0 and same.unchanged == 60
    flipped = continuous.cell(_rows([(b, a) for a, b in _planted()]), "inc", "ch", "stt")
    assert flipped.behind and flipped.p <= adopt.ALPHA and not flipped.ahead


def test_the_case_is_the_unit_so_repeats_of_it_add_no_evidence():
    once = continuous.cell(_rows(_planted(20)), "inc", "ch", "tts")
    five = continuous.cell(_rows(_planted(20), repeats=5), "inc", "ch", "tts")
    assert five.p == pytest.approx(once.p) and five.shift == pytest.approx(once.shift) and five.draws == 100


def test_a_timeout_is_not_judged_and_a_row_with_no_metric_scores_the_worst_error():
    rows = _rows([(0.1, 0.0)] * 4)
    rows.append({"candidate": "ch", "case_id": "c0", "passed": False, "failure_class": "timeout", "metrics": {}})
    assert continuous.scores(rows, "ch", "wer")["c0"] == [0.0]
    rows.append({"candidate": "ch", "case_id": "x", "passed": False, "failure_class": "crashed", "metrics": {}})
    assert continuous.scores(rows, "ch", "wer")["x"] == [continuous.SCORE_CAP]
    huge = [{"candidate": "ch", "case_id": "y", "passed": False, "failure_class": "", "metrics": {"wer": 7.5}}]
    assert continuous.scores(huge, "ch", "wer")["y"] == [continuous.SCORE_CAP]


@pytest.mark.gauntlet("a-closed-table-fronting-an-open-set", site="harness/continuous.py:METRIC")
def test_a_lane_the_metric_table_does_not_name_keeps_the_pass_fail_sign_test():
    from harness import lanes
    assert set(continuous.METRIC) == {"stt", "tts", "ocr"} <= set(lanes.ALL)
    for lane in set(lanes.ALL) - set(continuous.METRIC):
        assert continuous.metric_of(lane) == ""
        assert adopt.lane_cell(_rows([(0.0, 1.0)] * 3, "x"), "inc", "ch", lane, "challenger").p_value is None
    assert continuous.metric_of(" STT ") == "wer"
    assert adopt.lane_cell(_rows(_planted()), "inc", "ch", "ocr", "challenger").p_value is not None


@pytest.mark.gauntlet("a-closed-table-fronting-an-open-set", site="harness/continuous.py:EFFECT")
def test_a_lane_the_effect_table_does_not_name_is_planned_at_the_pass_fail_effect():
    from harness import lanes
    assert set(continuous.EFFECT) == set(continuous.METRIC)
    for lane in set(lanes.ALL) - set(continuous.EFFECT):
        assert continuous.effect_for(lane) == 0.0
        assert power.effect_in(lane) == power.effect_for(lane) and power.noise_in(lane) == power.noise_for(lane)
    for lane, effect in continuous.EFFECT.items():
        assert power.effect_in(lane) == power.noise_in(lane) == effect


def test_the_gate_adopts_a_planted_better_challenger_and_declines_identical_and_worse_ones():
    won = adopt.decide("stt", {"candidate": "inc"}, {"candidate": "ch"}, _rows(_planted()))
    assert won.adopt and "mean wer down" in won.why and "p=" in won.why
    same = adopt.decide("stt", {"candidate": "inc"}, {"candidate": "ch"}, _rows([(x, x) for x, _ in _planted()]))
    assert not same.adopt and "does not beat" in same.why
    worse = adopt.decide("stt", {"candidate": "inc"}, {"candidate": "ch"}, _rows([(b, a) for a, b in _planted()]))
    assert not worse.adopt and "significantly worse" in worse.why


def test_the_pass_fail_sign_test_cannot_see_what_the_signed_rank_test_does():
    rows = _rows(_planted())
    assert paired.head_to_head(rows, "inc", "ch").p == 1.0
    assert adopt.lane_cell(rows, "inc", "ch", "tts", "challenger").p <= adopt.ALPHA
    assert adopt.paired_p(_rows(_planted(), "cer"), "inc", "ch", "ocr")[1] <= adopt.ALPHA


def test_the_power_model_is_the_closed_form_and_grows_with_cases_and_effect():
    m = continuous.Model("wer", 0.1)
    assert m.sd_diff == pytest.approx(0.1 * (2 * (1 - continuous.CORR)) ** 0.5)
    z = 1.959964
    want = statistics.NormalDist().cdf(0.02 / m.sd_diff * (continuous.ARE * 200) ** 0.5 - z)
    assert m.power_cells(200, 0.02, 0.05) == pytest.approx(want, abs=1e-4)
    assert m.power_cells(100, 0.02, 0.05) < m.power_cells(200, 0.02, 0.05) < m.power_cells(400, 0.02, 0.05)
    assert m.power_cells(200, 0.01, 0.05) < m.power_cells(200, 0.03, 0.05)
    assert m.power_cells(0, 0.02, 0.05) == 0.0 and continuous.Model("wer", 0.0).power_cells(50, 0.02, 0.05) == 0.0


def test_a_plan_on_the_model_sizes_the_holdout_in_the_metrics_units():
    m = continuous.Model("wer", 0.09)
    got = power.plan([0.0] * 134, 0.02, stochastic=False, alpha=0.05, rho=1.0, model=m)
    assert got.continuous == m.as_dict() and power.unit_of(got) == "wer" and power.unit_note(got) == " wer"
    assert got.power == pytest.approx(m.power_cells(134, 0.02, 0.05), abs=1e-6)
    assert not got.enough and got.cases_needed and got.cases_needed > 134
    assert m.power_cells(got.cases_needed, 0.02, 0.05) >= power.TARGET > m.power_cells(got.cases_needed - 1, 0.02, 0.05)
    assert got.mde and got.mde > 0.02
    assert power.unit_of(power.plan([0.5] * 50, 0.1, stochastic=False, alpha=0.05, rho=1.0)) == "per cell"


def _split(n=134):
    ids = tuple(f"c{i}" for i in range(n))
    return holdout.Split("stt", (), ids, False)


def _profile(scored_draws, bit_draws):
    def fake(lane, receipts, conn, scored=None):
        draws = scored_draws if scored is not False else bit_draws
        return "inc", "stt:inc", draws, None, (), []
    return fake


def test_the_lane_gate_plans_a_continuous_lane_on_its_error_rate_and_keeps_the_sign_plan_beside_it(monkeypatch):
    rng = random.Random(2)
    split = _split()
    scored = {c: [rng.choice([0.0] * 5 + [0.1, 0.4])] for c in split.holdout}
    bits = {c: [int(v[0] <= 0.0)] for c, v in scored.items()}
    monkeypatch.setattr(lane_gate, "profile", _profile(scored, bits))
    conn = ms.connect()
    try:
        got = lane_gate.calc(conn, "stt", split)
        assert got.effect == continuous.EFFECT["stt"] and got.plan.continuous["metric"] == "wer"
        assert got.sign_plan is not None and got.plan.sign_cases_needed == got.sign_plan.cases_needed
        assert got.plan.continuous["sd"] == pytest.approx(statistics.pstdev([v[0] for v in scored.values()]))
        monkeypatch.setattr(lane_gate, "calc", lambda *a, **k: got)
        gate = lane_gate.gate_for(conn, "stt")
        assert gate and gate.unit == "wer" and "-0.02 wer" in gate.why and "pass/fail sign test needed" in gate.why
        assert gate.as_dict()["sign_cases_needed"] == got.sign_plan.cases_needed
    finally:
        conn.close()


def test_a_lane_off_the_metric_table_keeps_its_pass_fail_plan_and_effect(monkeypatch):
    split = holdout.Split("code", (), tuple(f"c{i}" for i in range(50)), False)
    monkeypatch.setattr(lane_gate, "profile", _profile({c: [1, 0] for c in split.holdout}, {c: [1, 0] for c in split.holdout}))
    conn = ms.connect()
    try:
        plain = lane_gate.calc(conn, "code", split)
        assert plain.plan.continuous is None and plain.effect == power.effect_for("code") and plain.sign_plan is None
    finally:
        conn.close()


def _look_plan(sd_diff_model, cases):
    return {"repeat": 3, "cells": cases * 3, "cases": cases, "effect": 0.02, "continuous": sd_diff_model.as_dict(), "odds": None}


def _look_split(n):
    return SimpleNamespace(holdout=tuple(f"c{i}" for i in range(n)), dev=(), version="v", too_small=False, caveat="",
                           side=lambda cid: "holdout", as_dict=lambda: {})


def test_the_interim_looks_spend_alpha_by_information_and_stop_a_continuous_run_for_success_only_at_its_level():
    model = continuous.Model("wer", 0.09)
    rows = _rows(_planted(60))
    early = looks.look([r for r in rows if int(r["case_id"][1:]) < 12], lane="stt", inc_key="inc", ch_key="ch",
                       split=_look_split(60), plan=_look_plan(model, 60), alpha=0.05, spent_before=0.0, n=1)[0]
    assert early.t == pytest.approx(12 / 60) and early.nominal == pytest.approx(looks.spent(12 / 60, 0.05))
    assert early.nominal < 0.005 and early.decision == "continue"
    final, verdict = looks.look(rows, lane="stt", inc_key="inc", ch_key="ch", split=_look_split(60),
                                plan=_look_plan(model, 60), alpha=0.05, spent_before=early.spent, n=2)
    assert final.t == 1.0 and final.decision == "success" and verdict.adopt


def test_a_continuous_plan_without_its_model_never_stops_for_futility():
    rows = _rows([(b, a) for a, b in _planted(60)])
    plan = {**_look_plan(continuous.Model("wer", 0.05), 60), "continuous": None}
    got = looks.look([r for r in rows if int(r["case_id"][1:]) < 40], lane="stt", inc_key="inc", ch_key="ch",
                     split=_look_split(60), plan=plan, alpha=0.05, spent_before=0.0, n=1)[0]
    assert got.cp == 1.0 and got.decision == "continue"


def test_a_continuous_run_that_is_behind_and_cannot_catch_up_stops_for_futility():
    model = continuous.Model("wer", 0.05)
    rows = _rows([(b, a) for a, b in _planted(60)])
    got, verdict = looks.look([r for r in rows if int(r["case_id"][1:]) < 40], lane="stt", inc_key="inc", ch_key="ch",
                              split=_look_split(60), plan=_look_plan(model, 60), alpha=0.05, spent_before=0.0, n=1)
    assert got.decision == "futility" and got.cp < looks.FUTILITY_CP and not verdict.adopt
    assert continuous.conditional_power(0.03, 40, 60, 0.02, 0.05, 0.05) > continuous.conditional_power(-0.03, 40, 60, 0.02, 0.05, 0.05)
    assert continuous.conditional_power(0.05, 60, 60, 0.02, 0.05, 0.05) == 1.0
    assert continuous.conditional_power(0.0, 60, 60, 0.02, 0.05, 0.05) == 0.0


def test_a_replay_of_a_planted_pair_needs_fewer_cases_under_the_signed_rank_test_and_its_control_never_separates():
    rows = _rows(_planted(80, seed=4))
    got = continuous.replay(rows, "inc", "ch", "stt", reps=60, seed=1)
    assert got["p"]["signed_rank"] <= adopt.ALPHA and got["p"]["sign_pass"] == 1.0
    need = got["cases_needed"]
    assert need["signed_rank"] is not None and need["signed_rank"] <= 80 and need["sign_pass"] is None
    assert got["null_rate"]["signed_rank"] <= adopt.ALPHA
    ctl = continuous.replay(_rows([(x, x) for x, _ in _planted(80, seed=4)]), "inc", "ch", "stt", reps=40)
    assert set(ctl["p"].values()) == {1.0} and set(ctl["cases_needed"].values()) == {None}
