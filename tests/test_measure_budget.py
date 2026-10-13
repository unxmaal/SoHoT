"""The measure step prices method calls and the reply budget, runs holdout only when dev does not fit, and stops at its deadline. #673."""
import argparse
import subprocess
import sys
import time
from pathlib import Path

import pytest

from harness import adopt, completion, exclusive, methods, power, reasons
from harness import memory_store as ms
from harness.commands import measure as measure_cmd

ROOT = Path(__file__).resolve().parents[1]
ORNITH = "llamacpp:Ornith-1.5-35B-Q4_K_M"


def _ns(**kw):
    base = {"repeat": None, "effect": 0.4, "power_budget_min": power.BUDGET_MIN}
    return argparse.Namespace(**{**base, **kw})


def _store(store_run, lane, spec, seconds, *, receipt=None, name=None):
    from harness import holdout
    split = holdout.for_lane(lane)
    rows = [{"case_id": f"{c}#{k}", "candidate": spec, "passed": k % 2 == 0,
             "seconds": seconds, "peak_kb": 0, "detail": ""}
            for c in (*split.dev, *split.holdout) for k in range(1, 5)]
    store_run(name or f"20261007-000000-adopt-{lane}", lane, rows=rows, receipt=receipt)


@pytest.mark.parametrize("spec,calls", [
    (ORNITH, 1), (f"best-of:3:{ORNITH}", 3), (f"best-of:5:{ORNITH}", 5),
    (f"plan:{ORNITH}", 2), ("trace:mflux:schnell", 1), ("best-of:x:broken", 1)])
def test_a_spec_costs_its_method_calls_per_attempt(spec, calls):
    assert methods.calls(spec) == calls


def test_a_best_of_3_challenger_is_projected_at_its_bases_expected_calls(store_run):
    _store(store_run, "svg", "inc", 10.0)
    _store(store_run, "svg", "ch", 10.0, name="ch-svg")
    _, plain = measure_cmd._plan(_ns(repeat=2, power_budget_min=10_000), "svg", "inc", "ch")
    _, best = measure_cmd._plan(_ns(repeat=2, power_budget_min=10_000), "svg", "inc",
                                "best-of:3:ch")
    cases = plain.cases_run
    assert plain.projected_s == pytest.approx(cases * 2 * (1 + 1) * 10.0)
    # ch passes half its draws, so best-of stops after 1 + 0.5 + 0.25 calls on average. #807.
    assert best.projected_s == pytest.approx(cases * 2 * (1 + 1.75) * 10.0)
    assert best.calls == 2.75


def test_a_projection_over_budget_runs_the_holdout_only(store_run):
    from harness import holdout
    split = holdout.for_lane("svg")
    _store(store_run, "svg", "inc", 100.0)
    _store(store_run, "svg", "ch", 100.0, name="ch-svg")
    _, fits = measure_cmd._plan(_ns(repeat=2, power_budget_min=10_000), "svg", "inc", "ch")
    assert fits.side == "all" and not fits.dev_skipped
    over = fits.projected_s / 60 * 0.75
    _, plan = measure_cmd._plan(_ns(repeat=2, power_budget_min=over), "svg", "inc", "ch")
    assert plan.side == "holdout"
    assert plan.cases_run == len(split.holdout)
    assert "dev: not run" in plan.dev_skipped
    assert plan.projected_s == pytest.approx(len(split.holdout) * 2 * 2 * 100.0)


def test_a_holdout_only_verdict_reports_dev_as_not_run():
    from harness import holdout
    split = holdout.Split("svg", dev=("d1",), holdout=("h1", "h2"), too_small=False)
    plan = power.Plan(1, 0.9, 2, 2, 0.2, 0.05, 0.8, 16, False, True, 0, "",
                      side="holdout", dev_skipped="dev: not run, over budget")
    rows = [{"candidate": n, "case_id": h, "passed": n == "ch"}
            for n in ("inc", "ch") for h in split.holdout]
    got = adopt.decide("svg", {"candidate": "inc", "pass_rate": 0.0},
                       {"candidate": "ch", "pass_rate": 1.0}, rows, split=split, plan=plan)
    assert "dev: not run" in got.why
    assert got.evidence["dev"] == {"not_run": "dev: not run, over budget"}


def test_the_measure_argv_names_the_holdout_when_dev_does_not_fit(monkeypatch, tmp_path):
    seen = {}

    class Done:
        returncode, stderr, timed_out = 0, "", False

    monkeypatch.setattr(measure_cmd, "_launch",
                        lambda argv, **kw: (seen.update(argv=argv, **kw), Done())[1])
    monkeypatch.setattr(adopt, "default_for", lambda lane, fallback, conn=None: "q3-4b")
    monkeypatch.setattr(measure_cmd, "_receipt_at", lambda out: None)
    real = measure_cmd._plan

    def fitted(a, lane, inc, spec, sweep=None):  # holdout fits the budget, dev and holdout do not. #796.
        from harness import holdout
        _, full = real(argparse.Namespace(repeat=3, power_budget_min=1e9), lane, inc, spec)
        hold = full.projected_s * len(holdout.for_lane(lane).holdout) / full.cases_run
        return real(argparse.Namespace(repeat=3, power_budget_min=hold / 60 * 1.01), lane, inc, spec)

    monkeypatch.setattr(measure_cmd, "_plan", fitted)
    measure_cmd._measure_and_adopt(argparse.Namespace(repeat=3, power_budget_min=1),
                                   {"name": "org/challenger", "lane": "code"})
    argv = seen["argv"]
    assert argv[argv.index("--split") + 1] == "holdout"
    assert seen["deadline_s"] > 0


def test_a_mean_from_a_smaller_reply_budget_is_scaled_up_to_this_one(store_run):
    _store(store_run, "code", "inc", 2.5, receipt={"max_tokens": 4000})
    _, plan = measure_cmd._plan(_ns(repeat=1, power_budget_min=10_000_000), "code", "inc", "ch")
    per_case = 2.5 * completion.budget("code") / 4000
    assert plan.projected_s == pytest.approx(plan.cases_run * 1 * (per_case + power.floor_seconds("code")))
    assert "4000-token" in plan.why


def test_a_median_at_this_reply_budget_is_used(store_run):
    _store(store_run, "code", "inc", 2.5, receipt={"max_tokens": 4000}, name="a-old")
    _store(store_run, "code", "inc", 35.0,
           receipt={"max_tokens": completion.budget("code")}, name="b-new")
    _store(store_run, "code", "ch", 35.0,
           receipt={"max_tokens": completion.budget("code")}, name="c-ch")
    _, plan = measure_cmd._plan(_ns(repeat=1, power_budget_min=10_000_000), "code", "inc", "ch")
    assert plan.projected_s == pytest.approx(plan.cases_run * 1 * 2 * 35.0)


def test_a_laddered_receipt_is_not_this_runs_budget_but_bounds_it(store_run):
    _store(store_run, "code", "inc", 3.0,
           receipt={"max_tokens": 65536, "budget_ladder": [4000, 16000, 32000, 65536]})
    _, plan = measure_cmd._plan(_ns(repeat=1, power_budget_min=10_000_000), "code", "inc", "ch")
    assert plan.estimate["incumbent_source"] == "bounded"
    per_case = 3.0
    assert plan.projected_s == pytest.approx(plan.cases_run * 1 * (per_case + power.floor_seconds("code")))


HOLDER = """
import subprocess, sys
child = subprocess.Popen([sys.executable, "-c", '''
import pathlib, sys, time
from harness import exclusive
with exclusive.held("eval"):
    pathlib.Path(sys.argv[1]).write_text("held", encoding="utf-8")
    time.sleep(120)
''', sys.argv[1]])
child.wait()
"""


@pytest.mark.long
def test_a_run_past_its_deadline_is_stopped_and_the_lock_released(tmp_path):
    marker = tmp_path / "held"
    started = time.monotonic()
    got = measure_cmd._launch([sys.executable, "-c", HOLDER, str(marker)],
                              deadline_s=5.0, cwd=str(ROOT), grace_s=2.0)
    assert got.timed_out
    assert time.monotonic() - started < 60
    assert marker.read_text(encoding="utf-8") == "held", "the grandchild never took the lock"
    with exclusive.try_held("eval") as free:
        assert free, "generation.lock is still held after the deadline"


def test_a_run_inside_its_deadline_returns_its_output():
    got = measure_cmd._launch([sys.executable, "-c", "import sys; sys.stderr.write('x')"],
                              deadline_s=30.0)
    assert not got.timed_out and got.returncode == 0 and got.stderr == "x"


def test_a_deadline_stop_records_a_partial_inconclusive_verdict(monkeypatch, tmp_path):
    class Stopped:
        returncode, stderr, timed_out, elapsed_s = -15, "", True, 7300.0

    monkeypatch.setattr(measure_cmd, "_launch", lambda argv, **kw: Stopped())
    monkeypatch.setattr(adopt, "default_for", lambda lane, fallback, conn=None: "q3-4b")
    monkeypatch.setattr(measure_cmd, "_receipt_at", lambda out: None)
    real = ms.connect
    monkeypatch.setattr(ms, "connect", lambda *a, **k: real(tmp_path / "d.db"))
    rc = measure_cmd._measure_and_adopt(argparse.Namespace(repeat=3, power_budget_min=1e9),
                                        {"name": "org/challenger", "lane": "code"})
    assert rc == 1
    conn = real(tmp_path / "d.db")
    try:
        row = conn.execute("SELECT outcome, detail, failure_class, power FROM verdicts "
                           "WHERE tier = ? ORDER BY id DESC", (adopt.TIER,)).fetchone()
    finally:
        conn.close()
    assert row["failure_class"] == reasons.INCONCLUSIVE
    assert row["outcome"] == "declined"
    assert "partial" in row["detail"] and "inconclusive" in row["detail"]
    assert '"partial"' in row["power"]


def test_the_critical_count_holds_past_a_thousand_discordant_cells():
    assert power._critical(1100, 0.05) <= 1100
    assert power.power_cells(0.3, 0.1, 4000, 0.05) > 0.99
