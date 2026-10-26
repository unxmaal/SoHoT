"""Adopt gate power, effect size and multiplicity: a null is not a loss it could not have seen. #698."""
import dataclasses
import json

import pytest

from harness import adopt, holdout, human, knobs, power, reasons
from harness import memory_store as ms
from harness import paths

FAKE_MACHINE = {"fingerprint": "test/rig", "hw_model": "", "os": "", "arch": "",
                "memory_gb": 0.0, "accelerator": "", "runtimes": "", "ceiling_gb": 0.0}


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv(paths.ENV_VAR, str(tmp_path))
    monkeypatch.setattr(ms.machines, "_THIS_MACHINE", FAKE_MACHINE)
    return tmp_path


def _cases(n):
    return tuple(f"h{i}" for i in range(n))


def _split(n):
    return holdout.Split("code", dev=(), holdout=_cases(n), too_small=False)


def _rows(cells):
    """cells: case -> list of (incumbent passed, challenger passed) per repeat."""
    out = []
    for case, pairs in cells.items():
        for k, (i, c) in enumerate(pairs, 1):
            cid = case if len(pairs) == 1 else f"{case}#{k}"
            out.append({"candidate": "inc", "case_id": cid, "passed": i, "seconds": 1.0, "metrics": {}})
            out.append({"candidate": "ch", "case_id": cid, "passed": c, "seconds": 1.0, "metrics": {}})
    return out


def _summary(name, rows):
    mine = [r for r in rows if r["candidate"] == name]
    return {"candidate": name, "pass_rate": sum(r["passed"] for r in mine) / len(mine),
            "median_s": 1.0, "metrics": {}}


def _small_gain(n):
    """A +0.10-ish challenger the gate cannot establish: 3 gained, 1 lost over n cases."""
    cells = {c: [(True, True)] for c in _cases(n)}
    for c in _cases(n)[:3]:
        cells[c] = [(False, True)]
    cells[_cases(n)[3]] = [(True, False)]
    return _rows(cells)


def _powered_plan(n=150):
    got = power.plan([0.5] * n, 0.2, stochastic=False, observed=n, rho=0.0)
    assert got.enough
    return got


def test_a_null_under_a_plan_for_a_bigger_effect_than_the_lane_cares_about_is_not_shown_and_retestable(monkeypatch, tmp_path):
    monkeypatch.setattr(power, "EFFECT", {"code": 0.1})
    rows = _small_gain(150)
    got = adopt.decide("code", _summary("inc", rows), _summary("ch", rows), rows,
                       split=_split(150), plan=_powered_plan())
    assert not got.adopt
    assert got.failure_class == reasons.UNDERPOWERED, got.why
    assert "not shown at +" in got.why
    assert got.evidence["power"]["mde"] > 0.1
    conn = ms.connect(tmp_path / "d.db")
    vid = adopt.record(conn, got, spec="org/x")
    assert conn.execute("SELECT reason FROM verdicts WHERE id = ?", (vid,)).fetchone()[0] == reasons.LIMIT


def test_a_powered_null_at_the_lanes_effect_is_a_loss_that_names_its_detectable_effect(monkeypatch):
    monkeypatch.setattr(power, "EFFECT", {"code": 0.2})
    rows = _small_gain(150)
    got = adopt.decide("code", _summary("inc", rows), _summary("ch", rows), rows,
                       split=_split(150), plan=_powered_plan())
    assert not got.adopt and got.failure_class == ""
    assert "no gain of +" in got.why


def test_the_minimum_detectable_effect_reaches_the_target_and_nothing_smaller_does():
    plan = _powered_plan()
    assert 0 < plan.mde <= plan.effect
    assert power.power([0.5] * 150, plan.mde, 1, plan.alpha, 0.0) >= plan.target
    assert power.power([0.5] * 150, plan.mde - 0.02, 1, plan.alpha, 0.0) < plan.target


def test_a_plan_with_no_incumbent_draws_is_unmeasured_and_its_null_underpowered():
    blind = power.plan([0.5] * 150, 0.2, stochastic=False, observed=0, rho=0.0)
    assert blind.unmeasured and blind.enough
    assert not power.plan([0.5] * 150, 0.2, stochastic=False, observed=150, rho=0.0).unmeasured
    rows = _small_gain(150)
    got = adopt.decide("code", _summary("inc", rows), _summary("ch", rows), rows,
                       split=_split(150), plan=blind)
    assert got.failure_class == reasons.UNDERPOWERED and "no stored draws" in got.why


def _shrunk(monkeypatch, lost, gained, unchanged=4):
    monkeypatch.setattr(power, "rows_icc", lambda rows, names: (0.5, 2.0))
    cells = {f"l{i}": [(True, False)] for i in range(lost)}
    cells.update({f"g{i}": [(False, True)] for i in range(gained)})
    cells.update({f"u{i}": [(True, True)] for i in range(unchanged)})
    return _rows(cells)


def test_worse_rounds_against_the_claim_that_the_challenger_is_worse(monkeypatch):
    rows = _shrunk(monkeypatch, lost=9, gained=1)
    assert adopt._worse(rows, "inc", "ch") == ""


def test_the_issues_four_lost_three_gained_at_design_effect_one_and_a_half_is_not_worse(monkeypatch):
    rows = _shrunk(monkeypatch, lost=4, gained=3)
    assert adopt._worse(rows, "inc", "ch") == ""


def test_the_adopt_gate_still_rounds_against_the_challenger(monkeypatch):
    rows = _shrunk(monkeypatch, lost=1, gained=9)
    cell, p, _ = adopt.paired_p(rows, "inc", "ch")
    assert p == pytest.approx(0.125)


def test_the_twentieth_challenger_on_one_holdout_faces_an_adjusted_alpha_and_says_so():
    assert adopt.alpha_for(0) == adopt.ALPHA
    assert adopt.alpha_for(19) == pytest.approx(adopt.ALPHA / 20)
    cells = {c: [(True, True)] for c in _cases(20)}
    for c in _cases(20)[:7]:
        cells[c] = [(False, True)]
    rows = _rows(cells)
    first = adopt.decide("code", _summary("inc", rows), _summary("ch", rows), rows,
                         split=_split(20))
    assert first.adopt
    late = adopt.decide("code", _summary("inc", rows), _summary("ch", rows), rows,
                        split=_split(20), tested=19)
    assert not late.adopt
    assert late.evidence["comparisons"] == 20
    assert late.evidence["alpha"] == pytest.approx(adopt.ALPHA / 20)
    assert "comparison 20" in late.why


def test_comparisons_count_the_lanes_verdicts_on_one_holdout_version(tmp_path):
    conn = ms.connect(tmp_path / "d.db")
    ev = {"split": _split(3).as_dict(), "power": {}}
    for i in range(3):
        adopt.record(conn, adopt.Verdict("code", "inc", f"org/c{i}", False, "x", evidence=ev),
                     spec=f"org/c{i}")
    adopt.record(conn, adopt.Verdict("svg", "inc", "org/s", False, "x", evidence=ev), spec="org/s")
    assert adopt.comparisons(conn, "code", holdout.VERSION) == 3
    assert adopt.comparisons(conn, "code", "2") == 0
    vid = adopt.record(conn, adopt.Verdict("code", "inc", "org/c9", False, "x",
                                           evidence={**ev, "comparisons": 4}), spec="org/c9")
    got = json.loads(conn.execute("SELECT power FROM verdicts WHERE id = ?", (vid,)).fetchone()[0])
    assert got["comparisons"] == 4


def test_one_win_and_three_ties_does_not_carry_the_lane(store):
    rows = [{"case_id": f"c{i}#1", "candidate": who, "passed": True,
             "artifact_path": f"/runs/{who}-{i}.png"}
            for i in range(4) for who in ("alpha", "beta")]
    pairs = human.pairings({"rows": rows})
    assert len(pairs) == 4
    for n, p in enumerate(pairs):
        for _ in range(human.ENOUGH):
            human.record("image", p["case"], p["a"], p["b"], "a" if n == 0 else "tie")
    won, why = human.lane_verdict("image", pairs)
    assert won == "", why
    v = adopt.decide_by_hand("image", pairs[0]["b"], pairs[0]["a"], pairs)
    assert not v.adopt


def test_effect_alpha_and_the_unseen_rate_are_registered_knobs():
    sites = {s for k in knobs.KNOBS.values() for s in k.sites}
    assert {"harness/power.py:EFFECT", "harness/power.py:DEFAULT_EFFECT",
            "harness/power.py:UNSEEN", "harness/adopt.py:ALPHA"} <= sites
    assert knobs.KNOBS["adopt_effect"].default("code") == power.effect_for("code")


def test_an_underpowered_null_names_the_smallest_gain_the_run_could_see():
    rows = _small_gain(150)
    weak = dataclasses.replace(power.plan([0.5] * 150, 0.2, stochastic=False, observed=150, rho=0.0, repeat=1,
                                          alpha=0.05, target=0.999), cases_needed=150)
    assert not weak.enough
    got = adopt.decide("code", _summary("inc", rows), _summary("ch", rows), rows,
                       split=_split(150), plan=weak)
    assert got.failure_class == reasons.UNDERPOWERED
    assert f"smallest gain this run could see: +{weak.mde:.2f}" in got.why, got.why
    blind = power.plan([0.5] * 150, 0.2, stochastic=False, observed=0, rho=0.0)
    got = adopt.decide("code", _summary("inc", rows), _summary("ch", rows), rows,
                       split=_split(150), plan=blind)
    assert f"smallest gain this run could see: +{blind.mde:.2f}" in got.why, got.why


def test_an_underpowered_null_with_no_detectable_gain_says_so():
    rows = _small_gain(4)
    tiny = power.plan([0.5] * 4, 0.2, stochastic=False, observed=4, rho=0.0)
    assert tiny.mde is None and not tiny.enough
    got = adopt.decide("code", _summary("inc", rows), _summary("ch", rows), rows,
                       split=_split(4), plan=tiny)
    assert "no gain up to +1.00 is detectable" in got.why, got.why


def test_a_verdict_landing_mid_run_is_recorded_beside_the_alpha_the_plan_used():
    rows = _small_gain(150)
    planned = _powered_plan()
    got = adopt.decide("code", _summary("inc", rows), _summary("ch", rows), rows,
                       split=_split(150), plan=planned, tested=1)
    assert got.evidence["planned_alpha"] == pytest.approx(planned.alpha)
    assert got.evidence["alpha"] == pytest.approx(adopt.ALPHA / 2)
    assert f"planned at alpha {planned.alpha}" in got.why, got.why
    same = adopt.decide("code", _summary("inc", rows), _summary("ch", rows), rows,
                        split=_split(150), plan=planned)
    assert "planned_alpha" not in same.evidence and "planned at alpha" not in same.why


def test_adopt_power_plans_at_the_holdouts_adjusted_alpha(store, capsys, monkeypatch, tmp_path):
    from harness import cli
    monkeypatch.setattr(adopt, "default_for", lambda lane, fallback, *a, **k: "inc")
    split = holdout.for_lane("code")
    conn = ms.connect()
    ev = {"split": split.as_dict(), "power": {}}
    for i in range(3):
        adopt.record(conn, adopt.Verdict("code", "inc", f"org/c{i}", False, "x", evidence=ev),
                     spec=f"org/c{i}")
    conn.close()
    rows = [{"case_id": f"{c}#{k}", "candidate": "inc", "passed": i % 4 != 0, "seconds": 2.0}
            for i, c in enumerate(split.holdout) for k in (1, 2)]
    receipt = tmp_path / "results.json"
    receipt.write_text(json.dumps({"receipt": {"modality": "code"}, "rows": rows}),
                       encoding="utf-8")
    assert cli.main(["adopt", "--json", "--power", "--lane", "code",
                     "--receipt", str(receipt)]) == 0
    row = json.loads(capsys.readouterr().out)["lanes"][0]
    assert row["comparisons"] == 3
    assert row["alpha"] == pytest.approx(adopt.ALPHA / 4)
    rates = [r for r in power.rates_from(
        power.draws_from(rows, "inc")[0], split.holdout)[0].values()]
    assert row["power"] == pytest.approx(
        power.power(rates, row["effect"], row["repeat"], adopt.ALPHA / 4, row["rho"]), abs=1e-4)
