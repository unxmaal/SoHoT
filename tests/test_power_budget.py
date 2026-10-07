"""Correlated repeats, the holdout size power needs, and the loop's time budget. #591."""
import argparse
import json

import pytest

from harness import adopt, power


# --- within-case correlation -----------------------------------------------

def test_icc_of_deterministic_cases_is_one():
    assert power.icc([[[1, 1, 1], [0, 0, 0], [1, 1, 1]]]) == pytest.approx(1.0)


def test_icc_matches_the_one_way_anova_estimator_by_hand():
    """Worked by hand: between-case and within-case mean squares give one half."""
    assert power.icc([[[1, 1], [0, 0], [1, 0]]]) == pytest.approx(0.5)


def test_icc_of_cases_sharing_one_rate_is_zero_not_negative():
    assert power.icc([[[1, 0, 1, 0], [0, 1, 0, 1], [1, 1, 0, 0]]]) == 0.0


def test_icc_is_unknown_without_a_repeated_case():
    assert power.icc([[[1], [0], [1]]]) is None
    assert power.icc([]) is None


def test_icc_centres_each_candidate_on_its_own_mean():
    """A candidate that always passes and one that always fails differ by
    candidate, not by case: no evidence about repeats either way."""
    assert power.icc([[[1, 1], [1, 1]], [[0, 0], [0, 0]]]) is None


def test_rows_icc_groups_by_candidate_and_case():
    rows = [{"candidate": c, "case_id": f"{case}#{k}", "passed": ok}
            for c, by in (("inc", {"a": [1, 1, 1], "b": [0, 0, 0]}),
                          ("ch", {"a": [1, 1, 1], "b": [1, 1, 1]}))
            for case, oks in by.items() for k, ok in enumerate(oks, 1)]
    rho, repeat = power.rows_icc(rows, ("inc", "ch"))
    assert rho == pytest.approx(1.0) and repeat == pytest.approx(3.0)


# --- power over effective cells --------------------------------------------

def test_correlated_repeats_add_no_power():
    """rho 1: a case repeated r times is still one case, at every repeat."""
    rates = [0.0] * 10 + [1.0] * 5
    once = power.power(rates, 0.2, repeat=1, rho=1.0)
    for r in range(1, power.CAP + 1):
        assert power.power(rates, 0.2, repeat=r, rho=1.0) == pytest.approx(once)


def test_independent_repeats_keep_the_old_cell_count():
    rates = [5 / 9] * 3
    assert power.power(rates, 4 / 9, repeat=8, rho=0.0) == pytest.approx(
        power.power(rates, 4 / 9, repeat=8))
    assert power.effective_cells(3, 8, 0.0) == 24
    assert power.effective_cells(17, 16, 1.0) == 17
    assert power.effective_cells(10, 4, 0.5) == 16


def test_power_is_exact_for_large_cell_counts_too():
    """The float path agrees with the integer one where both can be computed."""
    from fractions import Fraction
    from math import comb
    got = power.power([0.0], effect=0.3, repeat=40, rho=0.0)
    want = 0.0
    for d in range(1, 41):
        need = power._critical(d, 0.05)
        if need > d:
            continue
        want += float(comb(40, d) * Fraction(3, 10) ** d * Fraction(7, 10) ** (40 - d))
    assert got == pytest.approx(want, abs=1e-9)


# --- the plan: repeat when it helps, cases when it cannot -------------------

ORNITH_HOLDOUT = [1.0] * 13 + [0.0] * 4


def test_a_near_deterministic_lane_says_repeat_cannot_reach_the_target():
    got = power.plan(ORNITH_HOLDOUT, 0.2, rho=0.95)
    assert not got.enough
    assert got.repeat < power.CAP
    assert got.cases_needed and got.cases_needed > len(ORNITH_HOLDOUT)
    assert "correlated" in got.why and "more holdout case" in got.why
    assert str(got.cases_needed - len(ORNITH_HOLDOUT)) in got.why


def test_cases_needed_is_the_smallest_holdout_that_reaches_the_target():
    rates, rho = [0.5] * 4, 1.0
    need = power.cases_needed(rates, 0.2, rho=rho)
    assert need > 4

    def best(k):
        scaled = [0.5] * k
        return max(power.power(scaled, 0.2, r, rho=rho) for r in range(1, power.CAP + 1))
    assert best(need) >= power.TARGET
    assert all(best(k) < power.TARGET for k in range(4, need))


def test_a_saturated_holdout_needs_no_number_of_cases():
    got = power.plan([1.0] * 5, 0.2, rho=1.0)
    assert got.cases_needed is None
    assert "saturated" in got.why


def test_an_unmeasured_correlation_is_assumed_total():
    """Without a repeated case there is no evidence repeats are independent."""
    got = power.plan([0.5] * 6, 0.2)
    assert got.rho == 1.0 and not got.rho_measured


def test_a_stochastic_lane_still_reaches_the_target_by_repeat():
    got = power.plan([5 / 9] * 3, 4 / 9, rho=0.0)
    assert got.enough and got.repeat > 3 and got.cases_needed == 3


# --- the gate does not count correlated repeats as evidence -----------------

def _rows(by_case):
    """case -> list of (incumbent passed, challenger passed) per repeat."""
    out = []
    for case, pairs in by_case.items():
        for k, (i, c) in enumerate(pairs, 1):
            out.append({"candidate": "inc", "case_id": f"{case}#{k}", "passed": i,
                        "seconds": 1.0, "metrics": {}})
            out.append({"candidate": "ch", "case_id": f"{case}#{k}", "passed": c,
                        "seconds": 1.0, "metrics": {}})
    return out


def _summary(name, rows):
    mine = [r for r in rows if r["candidate"] == name]
    return {"candidate": name, "pass_rate": sum(r["passed"] for r in mine) / len(mine),
            "median_s": 1.0, "metrics": {}}


@pytest.mark.parametrize("repeat", range(1, power.CAP + 1))
def test_identical_candidates_are_never_adopted(repeat):
    pattern = {f"c{i}": [(i % 3 != 0, i % 3 != 0)] * repeat for i in range(12)}
    rows = _rows(pattern)
    got = adopt.decide("code", _summary("inc", rows), _summary("ch", rows), rows)
    assert not got.adopt


@pytest.mark.parametrize("repeat", range(1, power.CAP + 1))
def test_a_deterministic_two_for_one_trade_is_never_adopted(repeat):
    """The negative control: the challenger wins two cases and loses one, the
    same way on every draw. Three cases are not evidence at any repeat; the
    cell count used to make them so at the top repeats."""
    cases = {f"c{i}": [(True, True)] * repeat for i in range(9)}
    cases.update({"w1": [(False, True)] * repeat, "w2": [(False, True)] * repeat,
                  "l1": [(True, False)] * repeat})
    rows = _rows(cases)
    got = adopt.decide("code", _summary("inc", rows), _summary("ch", rows), rows)
    assert not got.adopt, got.why


def test_a_deterministic_win_on_many_cases_is_still_adopted():
    cases = {f"w{i}": [(False, True)] * 4 for i in range(10)}
    cases.update({f"c{i}": [(True, True)] * 4 for i in range(5)})
    rows = _rows(cases)
    got = adopt.decide("code", _summary("inc", rows), _summary("ch", rows), rows)
    assert got.adopt, got.why


def test_a_stochastic_lane_keeps_the_repeat_it_paid_for():
    """svg's shape: each case's incumbent passes about half its draws, so
    repeats are close to independent and eight of them still adopt."""
    pairs = [(k % 2 == 0, True) for k in range(8)]
    rows = _rows({"a": pairs, "b": pairs[1:] + pairs[:1], "c": pairs})
    got = adopt.decide("svg", _summary("inc", rows), _summary("ch", rows), rows)
    assert got.adopt, got.why


# --- the loop spends the repeat when it fits the budget ---------------------

def _store_incumbent(store_run, lane, spec, by_case, seconds):
    rows = [{"case_id": f"{c}#{k}", "candidate": spec, "passed": ok,
             "seconds": seconds, "peak_kb": 0, "detail": ""}
            for c, oks in by_case.items() for k, ok in enumerate(oks, 1)]
    store_run("20261007-000000-adopt-" + lane, lane, rows=rows)


def _svg_rates(store_run, seconds):
    from harness import holdout
    ids = holdout.for_lane("svg").holdout
    _store_incumbent(store_run, "svg", "inc", {c: [1, 0, 1, 0, 1, 0] for c in ids},
                     seconds)
    return len(ids)


def _ns(**kw):
    base = {"repeat": None, "effect": 0.4, "power_budget_min": power.BUDGET_MIN}
    return argparse.Namespace(**{**base, **kw})


def test_the_loop_spends_the_needed_repeat_when_it_fits(store_run):
    from harness.commands import measure as measure_cmd
    _svg_rates(store_run, seconds=1.0)
    _, plan = measure_cmd._plan(_ns(power_budget_min=600), "svg", "inc")
    assert plan.enough and plan.repeat > 3
    assert plan.projected_s == pytest.approx(plan.repeat * 3 * 2 * 1.0)


def test_over_budget_runs_the_fallback_and_says_what_power_would_cost(store_run):
    from harness.commands import measure as measure_cmd
    _svg_rates(store_run, seconds=100.0)
    _, needed = measure_cmd._plan(_ns(power_budget_min=10_000), "svg", "inc")
    _, plan = measure_cmd._plan(_ns(power_budget_min=10), "svg", "inc")
    assert plan.repeat < needed.repeat and plan.repeat <= power.FALLBACK_REPEAT
    assert plan.needed_repeat == needed.repeat
    assert f"repeat {needed.repeat}" in plan.why and "budget" in plan.why
    assert "would take" in plan.why


def test_an_unmeasured_lane_has_no_cost_and_runs_the_fallback(store_run):
    from harness.commands import measure as measure_cmd
    _, plan = measure_cmd._plan(_ns(), "svg", "inc")
    assert plan.repeat <= power.FALLBACK_REPEAT
    assert "no measured seconds" in plan.why


def test_an_explicit_repeat_is_honoured(store_run):
    from harness.commands import measure as measure_cmd
    _svg_rates(store_run, seconds=100.0)
    _, plan = measure_cmd._plan(_ns(repeat=5, power_budget_min=1), "svg", "inc")
    assert plan.repeat == 5


def test_the_underpowered_verdict_carries_the_plan_reason():
    from harness import holdout
    split = holdout.Split("code", dev=("d1", "d2", "d3"), holdout=("h1", "h2", "h3"),
                          too_small=False)
    rows = _rows({h: [(True, True)] * 3 for h in split.holdout})
    weak = power.plan([1.0, 1.0, 0.0], 0.2, rho=1.0)
    got = adopt.decide("code", _summary("inc", rows), _summary("ch", rows), rows,
                       split=split, plan=weak)
    assert got.why.startswith("underpowered") and "more holdout case" in got.why


def test_a_significantly_worse_challenger_is_a_loss_whatever_the_power():
    """Power to see a gain says nothing about a loss in the other direction. #594."""
    from harness import holdout, reasons
    hold = tuple(f"h{i}" for i in range(8))
    split = holdout.Split("code", dev=("d1", "d2", "d3"), holdout=hold, too_small=False)
    rows = _rows({h: [(True, False)] * 3 for h in hold})
    weak = power.plan([1.0] * 8, 0.2, rho=1.0)
    got = adopt.decide("code", _summary("inc", rows), _summary("ch", rows), rows,
                       split=split, plan=weak)
    assert not got.adopt and got.failure_class != reasons.UNDERPOWERED
    assert "worse" in got.why


def test_a_null_that_is_not_significantly_worse_stays_underpowered():
    from harness import holdout, reasons
    hold = tuple(f"h{i}" for i in range(8))
    split = holdout.Split("code", dev=("d1", "d2", "d3"), holdout=hold, too_small=False)
    rows = _rows({h: [(True, h != "h0")] * 3 for h in hold})
    weak = power.plan([1.0] * 8, 0.2, rho=1.0)
    got = adopt.decide("code", _summary("inc", rows), _summary("ch", rows), rows,
                       split=split, plan=weak)
    assert got.failure_class == reasons.UNDERPOWERED


def test_the_budget_flag_reaches_adopt_and_the_loop():
    from harness import cli
    p = cli.build_parser()
    assert p.parse_args(["adopt", "--lane", "svg", "--challenger", "x"]
                        ).power_budget_min == power.BUDGET_MIN
    assert p.parse_args(["discover", "--loop", "--power-budget-min", "30"]
                        ).power_budget_min == 30


# --- soh adopt --power ------------------------------------------------------

def test_adopt_power_prints_every_lane(store_run, capsys, monkeypatch):
    from harness import cli, holdout
    monkeypatch.setattr(adopt, "default_for", lambda lane, fallback, *a, **k: "inc")
    ids = holdout.for_lane("code").holdout
    _store_incumbent(store_run, "code", "inc",
                     {c: [i % 4 != 0] * 3 for i, c in enumerate(ids)}, 2.5)
    assert cli.main(["adopt", "--power"]) == 0
    out = capsys.readouterr().out
    for lane in ("code", "svg", "decide"):
        assert f"\n  {lane} " in out or out.startswith(f"  {lane} ")
    code = [l for l in out.splitlines() if l.strip().startswith("code ")][0]
    assert "more holdout" in code or "repeat" in code


def test_adopt_power_reads_receipts_and_speaks_json(tmp_path, capsys, monkeypatch):
    from harness import cli, holdout
    monkeypatch.setattr(adopt, "default_for", lambda lane, fallback, *a, **k: "inc")
    ids = holdout.for_lane("code").holdout
    rows = []
    for name, ok in (("inc", lambda i: i % 4 != 0), ("ch", lambda i: False)):
        rows += [{"case_id": f"{c}#{k}", "candidate": name, "passed": ok(i),
                  "seconds": 2.0} for i, c in enumerate(ids) for k in (1, 2, 3)]
    receipt = tmp_path / "results.json"
    receipt.write_text(json.dumps({"receipt": {"modality": "code"}, "rows": rows}),
                       encoding="utf-8")
    assert cli.main(["adopt", "--json", "--power", "--lane", "code",
                     "--receipt", str(receipt)]) == 0
    got = json.loads(capsys.readouterr().out)
    row = got["lanes"][0]
    assert row["lane"] == "code" and row["incumbent"] == "inc"
    assert row["holdout"] == len(ids)
    assert row["rho"] == pytest.approx(1.0)
    assert row["median_s"] == pytest.approx(2.0)
    assert row["cases_needed"] > len(ids)
    assert row["projected_s"] > 0


def test_adopt_still_needs_a_challenger_without_power(capsys):
    from harness import cli
    assert cli.main(["adopt", "--lane", "code"]) == 1


# --- unseen holdout cases are projected from the measured distribution (#608) ---

def test_an_unseen_case_is_drawn_from_the_measured_rates_not_the_pooled_one():
    """Measured cases sit at 0 and 1; a pooled 0.5 would credit every unseen case with room both ways."""
    draws = {"a": [1, 1], "b": [0, 0]}
    rates, seen = power.rates_from(draws, ["a", "b", "c", "d"])
    assert rates["a"] == 1.0 and rates["b"] == 0.0
    assert sorted([rates["c"], rates["d"]]) == [0.0, 1.0]
    assert seen == 4


def test_unseen_cases_follow_the_measured_distribution_in_proportion():
    draws = {f"s{i}": [1] * 3 if i < 6 else [0] * 3 for i in range(8)}
    unseen = [f"u{i}" for i in range(40)]
    rates, _ = power.rates_from(draws, unseen)
    assert sum(rates[u] for u in unseen) == 30


def test_a_bimodal_lane_projects_the_power_of_its_measured_cases_not_of_their_mean():
    draws = {f"s{i}": [1] * 3 if i % 4 else [0] * 3 for i in range(20)}
    ids = list(draws) + [f"u{i}" for i in range(60)]
    rates, _ = power.rates_from(draws, ids)
    projected = power.power([rates[c] for c in ids], 0.2, 3, rho=1.0)
    pooled = power.power([0.75] * len(ids), 0.2, 3, rho=1.0)
    same_shape = power.power([1.0] * 60 + [0.0] * 20, 0.2, 3, rho=1.0)
    assert projected == pytest.approx(same_shape)
    assert projected < pooled


def test_negative_control_a_lane_measured_all_passing_projects_no_power():
    draws = {f"s{i}": [1, 1, 1] for i in range(10)}
    ids = list(draws) + [f"u{i}" for i in range(100)]
    rates, _ = power.rates_from(draws, ids)
    assert all(rates[c] == 1.0 for c in ids)
    assert power.power([rates[c] for c in ids], 0.2, 3, rho=0.0) == 0.0
    assert power.plan([rates[c] for c in ids], 0.2, rho=0.0).cases_needed is None


def test_with_nothing_measured_every_case_takes_the_unseen_prior():
    rates, seen = power.rates_from({}, ["a", "b"])
    assert rates == {"a": power.UNSEEN, "b": power.UNSEEN} and seen == 0


def test_unmeasured_lists_the_cases_with_no_draws():
    assert power.unmeasured({"a": [1], "b": []}, ["a", "b", "c"]) == ["b", "c"]


def test_adopt_power_labels_the_projection_and_reports_the_measured_power(
        tmp_path, capsys, monkeypatch):
    from harness import cli, holdout
    monkeypatch.setattr(adopt, "default_for", lambda lane, fallback, *a, **k: "inc")
    ids = holdout.for_lane("code").holdout
    measured = ids[:6]
    rows = [{"case_id": f"{c}#{k}", "candidate": "inc", "passed": i % 2 == 0,
             "seconds": 2.0} for i, c in enumerate(measured) for k in (1, 2, 3)]
    receipt = tmp_path / "results.json"
    receipt.write_text(json.dumps({"receipt": {"modality": "code"}, "rows": rows}),
                       encoding="utf-8")
    assert cli.main(["adopt", "--json", "--power", "--lane", "code",
                     "--receipt", str(receipt)]) == 0
    out = capsys.readouterr()
    row = json.loads(out.out)["lanes"][0]
    assert row["unmeasured"] == len(ids) - 6
    assert row["measured"] == 6
    assert row["power_measured"] == pytest.approx(
        power.power([1.0, 0.0] * 3, row["effect"], row["repeat"], rho=row["rho"]), abs=1e-4)
    assert f"{len(ids) - 6} of {len(ids)} holdout unmeasured" in out.err


def test_adopt_power_with_every_holdout_case_measured_says_nothing_is_projected(
        tmp_path, capsys, monkeypatch):
    from harness import cli, holdout
    monkeypatch.setattr(adopt, "default_for", lambda lane, fallback, *a, **k: "inc")
    ids = holdout.for_lane("code").holdout
    rows = [{"case_id": f"{c}#{k}", "candidate": "inc", "passed": i % 2 == 0,
             "seconds": 2.0} for i, c in enumerate(ids) for k in (1, 2)]
    receipt = tmp_path / "results.json"
    receipt.write_text(json.dumps({"receipt": {"modality": "code"}, "rows": rows}),
                       encoding="utf-8")
    assert cli.main(["adopt", "--json", "--power", "--lane", "code",
                     "--receipt", str(receipt)]) == 0
    row = json.loads(capsys.readouterr().out)["lanes"][0]
    assert row["unmeasured"] == 0
    assert row["power_measured"] == pytest.approx(row["power"])
