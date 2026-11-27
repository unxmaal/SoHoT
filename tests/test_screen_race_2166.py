"""A screen is a paired sequential race against the incumbent's stored cells: planted pairs, the stopping rule, the verdict and the rank. #2166."""
import math

import pytest

from evals import run
from evals.core import Case, Result
from harness import measure_gain, screen, screen_race
from harness.screen_race import Plan, Race

IDS = tuple(f"case-{i:02d}" for i in range(12))


def _plan(rates, cap=6, effect=0.1, futility=0.05, promise=0.5, lane="code") -> Plan:
    return Plan(lane, tuple(rates), dict(rates), effect, futility, promise, cap)


def _race(plan: Plan, passes) -> Race:
    """The cases in the plan's order, each passed or failed by `passes(case)`, until the race stops."""
    race = Race(plan)
    for case in plan.order:
        if race.add(case, passes(case)):
            break
    return race


def _incumbent(rate=0.9):
    return {c: rate for c in IDS}


def test_a_known_worse_challenger_is_declined_in_at_most_8_cases():
    race = _race(_plan(_incumbent(), cap=12), lambda c: int(c[-2:]) % 4 == 0)
    assert race.decision == screen_race.DECLINE
    assert race.cases <= 8, race.record()


def test_a_known_better_challenger_passes():
    race = _race(_plan(_incumbent(0.3)), lambda c: True)
    assert race.decision == screen_race.PASS
    assert race.cases < race.plan.cap


def test_a_tie_runs_to_the_cap():
    rates = {c: 1.0 if i % 2 else 0.0 for i, c in enumerate(IDS)}
    race = _race(_plan(rates, cap=6), lambda c: rates[c] == 1.0)
    assert (race.gained, race.lost) == (0, 0)
    assert race.cases == 6 and race.decision == screen_race.CAP


def test_two_identical_challengers_get_the_same_verdict():
    plan = _plan(_incumbent(0.6), cap=12)
    seen = {c: int(c[-2:]) % 3 != 0 for c in IDS}
    one, two = _race(plan, seen.get), _race(plan, seen.get)
    assert one.record() == two.record()
    summary = {"k": {"passed": 3, "total": 3, screen_race.KEY: one.record()}}
    other = {"k": {"passed": 3, "total": 3, screen_race.KEY: two.record()}}
    assert screen.outcome(0, summary, candidate="k") == screen.outcome(0, other, candidate="k")


def test_the_posterior_is_the_beta_tail_over_half_plus_half_the_effect():
    a, b, t = 3, 5, 0.55
    exact = sum(math.comb(a + b - 1, k) * t ** k * (1 - t) ** (a + b - 1 - k) for k in range(a))
    assert screen_race.posterior(a - 1, b - 1, 0.1) == pytest.approx(exact, abs=1e-9)
    assert screen_race.posterior(0, 0, 0.1) == pytest.approx(0.45, abs=1e-9)
    assert screen_race.posterior(2.5, 0.5, 0.1) > screen_race.posterior(2, 1, 0.1) > screen_race.posterior(1, 2, 0.1)


def test_a_pair_is_the_expected_discordance_against_the_stored_rate():
    assert screen_race.pair(True, 0.25) == (0.75, 0.0)
    assert screen_race.pair(False, 0.25) == (0.0, 0.25)
    assert screen_race.pair(True, 1.0) == (0.0, 0.0) and screen_race.pair(False, 0.0) == (0.0, 0.0)


def test_a_case_the_incumbent_has_no_cell_on_is_not_paired():
    race = Race(_plan({"a": 0.9}))
    assert race.add("elsewhere", False) == "" and race.cases == 0
    assert race.add("a#2", False) == "" and race.cases == 1
    assert race.add("a#3", False) == "" and race.cases == 1


def test_a_stopped_race_keeps_its_verdict():
    race = _race(_plan(_incumbent(), cap=12), lambda c: False)
    cases, p = race.cases, race.p
    assert race.add("later", True) == screen_race.DECLINE and (race.cases, race.p) == (cases, p)


def test_the_record_names_the_cases_and_the_posterior():
    got = _race(_plan(_incumbent(), cap=12), lambda c: False).record()
    assert got["decision"] == screen_race.DECLINE and got["cases"] == 4
    assert got["posterior"] < got["futility"] and got["lost"] == pytest.approx(3.6)


def test_the_knobs_set_the_stopping_rule():
    assert _race(_plan(_incumbent(), cap=12, futility=0.2), lambda c: False).cases == 2
    assert _race(_plan(_incumbent(0.3), promise=0.9, cap=12), lambda c: True).cases > 1


# --- the verdict -----------------------------------------------------------

def _summary(race, passed=2):
    return {"k": {"passed": passed, "total": race.cases, screen_race.KEY: race.record()}}


def test_a_futile_race_declines_a_model_that_passed_cases():
    race = _race(_plan(_incumbent(), cap=12), lambda c: int(c[-2:]) % 4 == 0)
    v = screen.outcome(0, _summary(race), candidate="k")
    assert v[0] == "declined"
    assert "P(beats it by 0.1)" in v[1] and f"raced {race.cases} case(s)" in v[1]
    assert v[3].startswith("limit:screen_futility>")


def test_a_race_that_did_not_stop_it_screens_the_model_with_its_posterior():
    race = _race(_plan(_incumbent(0.3)), lambda c: True)
    v = screen.outcome(0, _summary(race, 1), candidate="k")
    assert v[0] == "screened" and "P(beats it by" in v[1]


def test_a_screen_without_a_race_still_passes_at_one_case():
    assert screen.outcome(0, {"k": {"passed": 1, "total": 6}}, candidate="k")[0] == "screened"


def test_the_does_it_run_checks_come_before_the_race():
    race = _race(_plan(_incumbent(), cap=12), lambda c: False)
    crashed = screen.outcome(1, _summary(race, 0), candidate="k")
    assert crashed[0] == "broken"
    nothing = screen.outcome(0, {"k": {"passed": 0, "total": 3, "failures": [], screen_race.KEY: race.record()}},
                             candidate="k")
    assert nothing[1] == "it ran and passed nothing" and nothing[3] != "limit:screen_futility>0.05"


# --- the plan and the harness ----------------------------------------------

def _stored(monkeypatch, rates, secs=None):
    monkeypatch.setattr(screen_race, "stored", lambda lane, conn: (rates, secs or {}))


def test_the_plan_orders_the_cases_by_expected_discordance_per_second(monkeypatch):
    rates = {"easy": 1.0, "mixed": 0.5, "slow": 0.5, "hard": 0.0}
    _stored(monkeypatch, rates, {"easy": 2.0, "mixed": 10.0, "slow": 500.0, "hard": 5.0})
    got = screen_race.plan("code", ["easy", "mixed", "slow", "hard", "unseen"], 4, conn=object())
    assert got.order == ("mixed", "hard", "slow", "easy") and "unseen" not in got.rates and got.cap == 4
    assert (got.futility, got.promise) == (screen_race.SCREEN_FUTILITY, screen_race.SCREEN_PROMISE)


@pytest.mark.parametrize("lane", ["stt", "image", "video"])
def test_a_lane_whose_cells_are_not_the_incumbents_is_not_raced(monkeypatch, lane):
    _stored(monkeypatch, {"a": 0.5})
    assert screen_race.plan(lane, ["a"], 6, conn=object()) is None


def test_no_stored_cell_is_no_race(monkeypatch):
    _stored(monkeypatch, {})
    assert screen_race.plan("code", ["a"], 6, conn=object()) is None


def _cases(n=8, **params):
    return [Case(f"case-{i:02d}", "code", "p", params=params) for i in range(n)]


def test_the_screen_draws_the_raced_cases_in_weed_out_order(monkeypatch):
    rates = {f"case-{i:02d}": r for i, r in enumerate([1.0, 0.5, 0.0, 0.5, 1.0, 0.9, 0.1, 0.5])}
    _stored(monkeypatch, rates)
    plan = screen_race.plan("code", list(rates), 5, conn=object())
    got = run.screen_cases(_cases(), counts={("code", ""): 2}, plan=plan)
    assert [c.id for c in got] == list(plan.order[:5]) and plan.order[0] != "case-00"


def test_a_shrunk_case_is_never_raced(monkeypatch):
    rates = {f"case-{i:02d}": 0.5 for i in range(4)}
    _stored(monkeypatch, rates)
    args = run.parse_args(["--screen"])
    args.modality = "code"
    assert run.race_plan(args, _cases(4, width=1024)) is None
    assert run.race_plan(args, _cases(4, width=128)) is not None


class Fake:
    candidate = "fake"

    def __init__(self, passes):
        self.passes, self.ran = passes, []

    def warm(self):
        pass

    def run(self, case):
        self.ran.append(case.id)
        return Result(case.id, self.candidate, self.passes(case.id), 0.1, 0, "")

    def failed(self, case, exc):
        return Result(case.id, self.candidate, False, 0.0, 0, exc.detail)

    def artifact(self, case, suffix):
        return f"{case.id}{suffix}"


def _screened(tmp_path, passes, plan):
    runner, rows = Fake(passes), []
    race = Race(plan)
    cases = [Case(c, "code", "p") for c in plan.order]
    run._run_candidate(run.parse_args(["--screen"]), "fake", runner, cases, rows, tmp_path, kept={"race": race})
    return runner, rows, race


def test_the_run_stops_asking_cases_once_the_race_is_decided(tmp_path):
    plan = _plan(_incumbent(), cap=12)
    runner, rows, race = _screened(tmp_path, lambda c: False, plan)
    assert race.decision == screen_race.DECLINE and len(rows) == race.cases == 4 == len(runner.ran)


def test_a_tie_asks_every_case_up_to_the_cap(tmp_path):
    plan = _plan({c: 1.0 for c in IDS}, cap=6)
    runner, rows, race = _screened(tmp_path, lambda c: True, plan)
    assert race.decision == screen_race.CAP and len(rows) == 6 == len(runner.ran)


def test_a_row_the_harness_refused_is_not_a_lost_case(tmp_path, monkeypatch):
    plan = _plan(_incumbent(), cap=12)
    seen = []
    monkeypatch.setattr(Race, "add", lambda self, case_id, passed: seen.append(case_id) or "")
    row = Result("case-00", "fake", False, 0.0, 0, "refused", failure_class="refused_by_gateway")
    monkeypatch.setattr(run, "_one_case", lambda *a, **k: row)
    run._run_candidate(run.parse_args(["--screen"]), "fake", Fake(lambda c: False), [Case("case-00", "code", "p")],
                       [], tmp_path, kept={"race": Race(plan)})
    assert seen == []


# --- the measure rank -------------------------------------------------------

def _gain(name, posterior, key):
    return measure_gain.Gain(name, "code", 0.0, 0.3, 0.1, 0.0, 10.0 if key else None, posterior=posterior)


def test_a_screen_posterior_ranks_measure_ahead_of_gain_per_minute(monkeypatch):
    gains = {"cheap": _gain("cheap", 0.2, True), "sure": _gain("sure", 0.9, True),
             "unscreened": _gain("unscreened", None, True), "likely": _gain("likely", 0.6, True)}
    monkeypatch.setattr(measure_gain, "context", lambda conn, before=None: None)
    monkeypatch.setattr(measure_gain, "score", lambda ctx, row, want="", gated=False: gains[row["name"]])
    rows = [{"name": n} for n in ("cheap", "unscreened", "likely", "sure")]
    ordered, _ = measure_gain.order(None, rows)
    assert [r["name"] for r in ordered] == ["sure", "likely", "cheap", "unscreened"]


def test_the_stored_screen_rows_give_the_posterior(monkeypatch):
    ctx = measure_gain.Context(None, rates={"code": {f"case-0{i}": 0.9 for i in range(4)}})
    rows = [{"case_id": f"case-0{i}", "passed": False, "metrics": {}} for i in range(4)]
    ctx.screens[("m", "code")] = rows
    assert measure_gain.screen_posterior(ctx, "m", "code", 0.1) < 0.05
    ctx.screens[("m", "image")] = rows
    assert measure_gain.screen_posterior(ctx, "m", "image", 0.1) is None
    ctx.screens[("n", "code")] = []
    assert measure_gain.screen_posterior(ctx, "n", "code", 0.1) is None


def test_only_the_media_lanes_are_shrunk():
    from evals.core import load_suite
    shrunk = {c.modality for c in load_suite() if run._shrunk(c).params != c.params}
    assert shrunk <= set(screen.MEDIA_LANES), shrunk


def test_the_canary_plants_are_decided_before_any_race(monkeypatch):
    from harness import canary, reasons
    _stored(monkeypatch, {"case-00": 0.5})
    for plant in canary.PLANTS:
        if plant.lane == "stt":
            assert screen_race.plan(plant.lane, ["case-00"], 6, conn=object()) is None
    gguf = next(p for p in canary.PLANTS if p.lane == "code")
    got = screen.outcome(1, None, candidate=gguf.name, stderr_class=reasons.LOAD_FAILED_RUNTIME)
    assert got[0] == "declined" and "screen_futility" not in got[3]
    race = _race(_plan(_incumbent(), cap=12), lambda c: False)
    assert screen.outcome(0, {"k": {"passed": 0, "total": race.cases, screen_race.KEY: race.record()}},
                          candidate="k")[3] != "limit:screen_futility>0.05"


def test_a_declined_race_is_the_whole_verdict():
    from harness import reasons
    race = _race(_plan(_incumbent(), cap=12), lambda c: int(c[-2:]) % 4 == 0)
    got = screen.outcome(0, _summary(race), candidate="k")
    rec = race.record()
    said = (f"2 case(s) passed a screen; raced {rec['cases']} case(s) against the incumbent's stored cells: "
            f"gained {rec['gained']:g}, lost {rec['lost']:g}, P(beats it by 0.1) {rec['posterior']:.3f}, under 0.05")
    assert got == screen.Verdict("declined", said, reasons.LIMIT, "limit:screen_futility>0.05", reasons.CONTENT_FAILED)


def test_a_passed_race_and_an_unraced_screen_are_the_candidates_to_measure():
    from harness import reasons
    race = _race(_plan(_incumbent(0.3)), lambda c: True)
    raced = screen.outcome(0, _summary(race, 1), candidate="k")
    assert (raced.reason, raced.until, raced.failure_class) == (reasons.CANDIDATE, "", "")
    assert screen.outcome(0, {"k": {"passed": 1, "total": 6}}, candidate="k") == screen.Verdict(
        "screened", "1 case(s) passed a screen", reasons.CANDIDATE)


def test_the_race_read_is_the_named_candidates_under_its_key():
    worse = _race(_plan(_incumbent(), cap=12), lambda c: int(c[-2:]) % 4 == 0)
    better = _race(_plan(_incumbent(0.3)), lambda c: True)
    both = {"a/worse": {"passed": 2, **{screen_race.KEY: worse.record()}},
            "b/better": {"passed": 2, **{screen_race.KEY: better.record()}}}
    assert screen.outcome(0, both, candidate="spec:worse", key="a/worse")[0] == "declined"
    assert screen.outcome(0, both, candidate="spec:better", key="b/better")[0] == "screened"
    assert screen.outcome(0, {"a/worse": both["a/worse"]}, candidate="")[0] == "declined"
    assert screen.outcome(0, {"a/worse": both["a/worse"]}, candidate="x", key="a/worse")[0] == "declined"
