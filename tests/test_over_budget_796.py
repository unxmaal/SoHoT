"""A paired run projected past its time budget is refused, and an incumbent receipt at another reply budget bounds the projection. #796."""
import argparse

import pytest

from harness import adopt, completion, power, reasons
from harness import memory_store as ms
from harness.commands import measure as measure_cmd

#: Per-case seconds of Ornith's flat 32000-token code run: a fast median, a slow tail. Mean 67.
SKEWED = (15.0, 15.0, 15.0, 223.0)


def _ns(**kw):
    base = {"repeat": None, "effect": 0.4, "power_budget_min": power.BUDGET_MIN}
    return argparse.Namespace(**{**base, **kw})


def _rows(lane, spec, seconds):
    from harness import holdout
    split = holdout.for_lane(lane)
    return [{"case_id": f"{c}#{k}", "candidate": spec, "passed": k % 2 == 0,
             "seconds": s, "peak_kb": 0, "detail": ""}
            for c in (*split.dev, *split.holdout) for k, s in enumerate(seconds, 1)]


def test_a_plan_projected_over_its_budget_is_refused(store_run):
    store_run("inc-1", "svg", rows=_rows("svg", "inc", (100.0,) * 4),
              receipt={"max_tokens": completion.budget("svg")})
    _, plan = measure_cmd._plan(_ns(power_budget_min=1), "svg", "inc", "inc")
    assert plan.projected_s > plan.budget_s
    assert "not run" in plan.refused and "over the 1m budget" in plan.refused


def test_an_explicit_repeat_over_budget_is_refused_too(store_run):
    store_run("inc-1", "svg", rows=_rows("svg", "inc", (100.0,) * 4),
              receipt={"max_tokens": completion.budget("svg")})
    _, plan = measure_cmd._plan(_ns(repeat=2, power_budget_min=1), "svg", "inc", "inc")
    assert plan.repeat == 2 and plan.refused


def test_a_plan_inside_its_budget_is_not_refused(store_run):
    store_run("inc-1", "svg", rows=_rows("svg", "inc", (1.0,) * 4),
              receipt={"max_tokens": completion.budget("svg")})
    _, plan = measure_cmd._plan(_ns(repeat=1, power_budget_min=10_000), "svg", "inc", "inc")
    assert not plan.refused
    assert plan.deadline_s == pytest.approx(plan.budget_s * power.DEADLINE_GRACE)


@pytest.mark.long
def test_a_refused_run_is_never_launched_and_records_why(monkeypatch, tmp_path):
    launched = []
    monkeypatch.setattr(measure_cmd, "_launch", lambda argv, **kw: launched.append(argv))
    monkeypatch.setattr(adopt, "default_for", lambda lane, fallback, conn=None: "q3-4b")
    real = ms.connect
    monkeypatch.setattr(ms, "connect", lambda *a, **k: real(tmp_path / "d.db"))
    rc = measure_cmd._measure_and_adopt(_ns(power_budget_min=1),
                                        {"name": "org/challenger", "lane": "code"})
    assert rc == 0 and launched == []
    conn = real(tmp_path / "d.db")
    try:
        row = conn.execute("SELECT outcome, detail, failure_class FROM verdicts "
                           "WHERE tier = ? ORDER BY id DESC", (adopt.TIER,)).fetchone()
    finally:
        conn.close()
    assert row["failure_class"] == reasons.INCONCLUSIVE
    assert "not run" in row["detail"] and "budget" in row["detail"]


def test_a_receipt_at_a_smaller_reply_budget_bounds_the_incumbent(store_run):
    store_run("inc-1", "code", rows=_rows("code", "inc", SKEWED), receipt={"max_tokens": 32000})
    _, plan = measure_cmd._plan(_ns(repeat=1, power_budget_min=10_000_000), "code", "inc", "inc")
    est = plan.estimate
    want = 67.0 * completion.budget("code") / 32000
    assert est["incumbent_source"] == "bounded"
    assert est["incumbent_s"] == pytest.approx(want)
    assert est["incumbent_s"] < power.estimated_seconds("code")
    assert "32000-token" in plan.why


def test_a_receipt_at_a_larger_reply_budget_bounds_the_incumbent_unscaled(store_run):
    store_run("inc-1", "code", rows=_rows("code", "inc", (40.0,) * 4),
              receipt={"max_tokens": 65536, "budget_ladder": [4000, 16000, 32000, 65536]})
    _, plan = measure_cmd._plan(_ns(repeat=1, power_budget_min=10_000_000), "code", "inc", "inc")
    assert plan.estimate["incumbent_source"] == "bounded"
    assert plan.estimate["incumbent_s"] == pytest.approx(40.0)


def test_the_bound_never_exceeds_the_whole_budget_estimate(store_run):
    store_run("inc-1", "code", rows=_rows("code", "inc", (900.0,) * 4), receipt={"max_tokens": 4000})
    _, plan = measure_cmd._plan(_ns(repeat=1, power_budget_min=10_000_000), "code", "inc", "inc")
    assert plan.estimate["incumbent_s"] == pytest.approx(power.estimated_seconds("code"))


def test_wall_time_is_priced_at_the_mean_not_the_median(store_run):
    store_run("inc-1", "code", rows=_rows("code", "inc", SKEWED),
              receipt={"max_tokens": completion.budget("code")})
    _, plan = measure_cmd._plan(_ns(repeat=1, power_budget_min=10_000_000), "code", "inc", "inc")
    assert plan.estimate["incumbent_s"] == pytest.approx(67.0)
