"""A paired run in weed-out order: cases by expected discordant cells per second, futility on the cases left, adopt only on full coverage. #1439."""
import json
import random
import sqlite3
import types
from pathlib import Path

import pytest

from evals import run as evals_run
from evals import watch
from evals.core import Case
from harness import adopt, holdout, looks, power, weedout, weedout_replay
from harness.commands import measure as measure_cmd

INC, CH = "inc", "ch"
CASES = tuple(f"c{i:02d}" for i in range(40))
SPLIT = holdout.Split("code", (), CASES, False)


def _pair(cells: dict) -> list[dict]:
    out = []
    for c, (i, ch) in cells.items():
        out += [{"case_id": c, "candidate": INC, "passed": i, "seconds": 1.0, "metrics": {}},
                {"case_id": c, "candidate": CH, "passed": ch, "seconds": 1.0, "metrics": {}}]
    return out


def _plan(rates: dict, ordered: bool = True, effect: float = 0.1) -> dict:
    plan = {"repeat": 1, "cells": len(CASES), "cases": len(CASES), "effect": effect,
            "odds": power._cell_odds([rates[c] for c in CASES], effect)}
    if ordered:
        plan.update(weedout.planned(CASES, rates, {}, effect))
    return plan


def test_cases_go_by_expected_discordant_cells_per_second():
    rates = {"easy": 1.0, "hard": 0.0, "mixed": 0.5, "slow-mixed": 0.5}
    secs = {"easy": 2.0, "hard": 5.0, "mixed": 50.0, "slow-mixed": 500.0}
    assert weedout.order(list(rates), rates, secs, 0.1) == ["hard", "mixed", "slow-mixed", "easy"]
    assert weedout.score(1.0, 0.1) == 0.0 and weedout.score(0.0, 0.1) == pytest.approx(0.1)


def test_an_untimed_case_costs_the_typical_one_and_a_near_zero_timing_does_not_lead_alone():
    rates = {"a": 0.5, "b": 0.5, "c": 0.5}
    assert weedout.order(["a", "b", "c"], rates, {"a": 10.0, "b": 1.0}, 0.1) == ["b", "c", "a"]
    assert weedout.order(["a", "b", "c"], rates, {"a": 2.0, "b": 2.0, "c": 2.0}, 0.1) == ["a", "b", "c"]
    assert weedout.order(["b", "a"], {"a": 0.5, "b": 0.0}, {"a": 3.0, "b": 0.0}, 0.1) == ["a", "b"]


def _case(cid: str) -> Case:
    return Case(id=cid, modality="code", prompt="p")


def test_the_run_takes_cases_in_the_order_file_each_repeat_a_pass_and_unnamed_cases_last(tmp_path):
    path = weedout.write(tmp_path, ["b", "a"])
    cases = [_case(x) for x in ("a#1", "a#2", "b#1", "b#2", "z#1", "c#1")]
    assert [c.id for c in evals_run.ordered(cases, path)] == ["b#1", "a#1", "z#1", "c#1", "b#2", "a#2"]
    assert evals_run.ordered(cases, None) is cases
    with pytest.raises(SystemExit):
        evals_run.ordered(cases, tmp_path / "missing.json")


def test_order_is_an_evals_run_flag():
    args = evals_run.parse_args(["--modality", "code", "--order", "o.json"])
    assert args.order == "o.json"


def test_an_ordered_run_never_adopts_before_every_case_has_a_cell_and_spends_no_alpha_there():
    rates = {c: 0.5 for c in CASES}
    rows = _pair({c: (False, True) for c in CASES[:20]})
    plain, verdict = looks.look(rows, lane="code", inc_key=INC, ch_key=CH, split=SPLIT, plan=_plan(rates, False),
                                alpha=0.05, spent_before=0.0, n=1)
    assert plain.decision == "success" and verdict.adopt
    held, verdict = looks.look(rows, lane="code", inc_key=INC, ch_key=CH, split=SPLIT, plan=_plan(rates),
                               alpha=0.05, spent_before=0.0, n=1)
    assert held.decision == "continue" and verdict is None
    assert held.spent == 0.0 and held.nominal == 0.0 and "20 more case(s)" in held.text


def test_an_ordered_run_adopts_through_alpha_spending_once_every_case_has_a_cell():
    rates = {c: 0.5 for c in CASES}
    rows = _pair({c: ((False, True) if i < 20 else (True, True)) for i, c in enumerate(CASES)})
    got, verdict = looks.look(rows, lane="code", inc_key=INC, ch_key=CH, split=SPLIT, plan=_plan(rates),
                              alpha=0.05, spent_before=0.0, n=2)
    assert got.decision == "success" and verdict.adopt and got.spent == pytest.approx(0.05)


def test_futility_reads_the_odds_of_the_cases_still_to_run_not_the_holdout_average():
    # Half the cases have room to gain, half the incumbent always passes; the room was spent first.
    rates = {c: (0.0 if i < 20 else 1.0) for i, c in enumerate(CASES)}
    rows = _pair({c: ((False, True) if i < 2 else (True, False) if i < 4 else (False, False))
                  for i, c in enumerate(CASES[:20])})
    plain, _ = looks.look(rows, lane="code", inc_key=INC, ch_key=CH, split=SPLIT,
                          plan=_plan(rates, False, effect=0.5), alpha=0.05, spent_before=0.0, n=1)
    assert plain.decision == "continue" and plain.cp >= looks.FUTILITY_CP
    ordered, verdict = looks.look(rows, lane="code", inc_key=INC, ch_key=CH, split=SPLIT,
                                  plan=_plan(rates, effect=0.5), alpha=0.05, spent_before=0.0, n=1)
    assert ordered.decision == "futility" and ordered.cp < looks.FUTILITY_CP
    assert verdict is not None and not verdict.adopt


def test_a_challenger_ahead_on_an_ordered_run_is_never_stopped():
    rates = {c: (0.0 if i < 20 else 1.0) for i, c in enumerate(CASES)}
    rows = _pair({c: ((False, True) if i < 3 else (False, False)) for i, c in enumerate(CASES[:20])})
    got, _ = looks.look(rows, lane="code", inc_key=INC, ch_key=CH, split=SPLIT, plan=_plan(rates, effect=0.5),
                        alpha=0.05, spent_before=0.0, n=1)
    assert got.decision == "continue"


def test_cells_left_count_a_case_until_both_candidates_ran_every_repeat():
    rows = [{"case_id": "a#1", "candidate": INC}, {"case_id": "a#1", "candidate": CH},
            {"case_id": "a#2", "candidate": INC}, {"case_id": "b#1", "candidate": CH}]
    assert weedout.left(rows, INC, CH, ["a", "b", "c"], 2) == {"a": 1, "b": 2, "c": 2}
    assert weedout.rest_odds({"a": 1.0, "b": 0.0}, {"a": 1, "b": 1}, 0.1) == pytest.approx((0.05, 0.0))
    assert weedout.rest_odds({}, {}, 0.1) == (0.0, 0.0)


def _brute(gained, lost, remaining, gain, lose, alpha):
    disc = gain + lose
    if remaining <= 0 or disc <= 0:
        return 1.0 if looks._wins(gained, lost, alpha) else 0.0
    r = gain / disc
    return min(1.0, sum(power._pmf(remaining, m, disc) * sum(
        power._pmf(m, k, r) for k in range(m + 1) if looks._wins(gained + k, lost + m - k, alpha))
        for m in range(remaining + 1) if power._pmf(remaining, m, disc) >= 1e-12))


def test_conditional_power_sums_only_the_winning_tail_of_each_count():
    rng = random.Random(1439)
    for _ in range(60):
        a = (rng.randint(0, 15), rng.randint(0, 15), rng.randint(0, 40), rng.random() * 0.4, rng.random() * 0.4,
             rng.choice([0.05, 0.003125]))
        assert looks.conditional_power(*a) == pytest.approx(_brute(*a), abs=1e-12)


def test_a_paired_measure_asks_evals_run_for_its_order(tmp_path):
    plan = power.Plan(1, 0.5, 10, 10, 0.1, 0.05, 0.8, 16, False, True, 0, "", side="holdout",
                      order=("b", "a"), rates={"a": 1.0, "b": 0.5})
    argv = measure_cmd._argv("code", plan, tmp_path, "inc-spec", "org/x")
    assert argv[argv.index("--order") + 1] == str(tmp_path / weedout.ORDER_FILE)
    bare = measure_cmd._argv("code", power.Plan(1, 0.5, 10, 10, 0.1, 0.05, 0.8, 16, False, True, 0, ""),
                             tmp_path, "inc-spec", "org/x")
    assert "--order" not in bare


def test_a_measure_plan_orders_the_cases_it_runs_from_the_incumbents_draws(store_run):
    import argparse
    run = [*holdout.for_lane("music").holdout, *holdout.for_lane("music").dev]
    always, mixed = run[0], run[1]
    by = {c: ([1, 1, 1, 1] if c == always else [1, 0, 1, 0]) for c in run}
    rows = [{"case_id": f"{c}#{k}", "candidate": "inc", "passed": ok, "seconds": 5.0, "peak_kb": 0, "detail": ""}
            for c, oks in by.items() for k, ok in enumerate(oks, 1)]
    store_run("20261007-000000-adopt-music", "music", rows=rows)
    _, plan = measure_cmd._plan(argparse.Namespace(repeat=None, effect=0.4, power_budget_min=power.BUDGET_MIN),
                                "music", "inc")
    assert set(plan.order) == set(run) and plan.order[-1] == always and plan.rates[always] == 1.0
    assert plan.rates[mixed] == 0.5


def test_the_run_reads_its_order_flag_when_it_picks_its_cases(tmp_path, monkeypatch):
    monkeypatch.setattr(evals_run, "load_selected", lambda args: [_case("a"), _case("b"), _case("c")])
    path = weedout.write(tmp_path, ["c", "a"])
    _, _, cases = evals_run._plan(evals_run.parse_args(["--modality", "code", "--repeat", "1", "--order", str(path)]))
    assert [c.id for c in cases] == ["c", "a", "b"]


def test_a_resumed_plan_keeps_its_order():
    stored = power.Plan(1, 0.5, 10, 10, 0.1, 0.05, 0.8, 16, False, True, 0, "", order=("b", "a"),
                        rates={"a": 1.0, "b": 0.5}).as_dict()
    stored = json.loads(json.dumps(stored))
    fresh = power.Plan(1, 0.9, 10, 10, 0.1, 0.05, 0.8, 16, False, True, 0, "", budget_s=600.0)
    got = measure_cmd._resumed_plan(stored, fresh)
    assert got.order == ("b", "a") and got.rates == {"a": 1.0, "b": 0.5}


def test_a_confirmation_slice_that_cannot_reach_the_gate_records_a_keep(tmp_path, monkeypatch):
    out = tmp_path / "confirm"
    ident = {"modality": "code", "candidates": ["inc-spec", "org/x"], "repeat": 1, "split": "dev"}
    out.mkdir()
    ckpt = watch.Checkpoint(out, ident, keep=False)
    rates = {c: (0.0 if i < 20 else 1.0) for i, c in enumerate(CASES)}
    for r in _pair({c: ((True, False) if i < 6 else (False, False)) for i, c in enumerate(CASES[:20])}):
        ckpt.add({**r, "candidate": "inc-key" if r["candidate"] == INC else "ch-key"}, 1.0)
    (out / watch.PROGRESS).write_text(json.dumps({"specs": {"inc-key": "inc-spec", "ch-key": "org/x"}}),
                                      encoding="utf-8")
    plan = {**weedout.planned(CASES, rates, {}, 0.5), "cells": list(CASES), "repeat": 1, "effect": 0.5,
            "incumbent": "inc-spec", "challenger": "org/x"}
    got = measure_cmd._confirm_look("code", out, plan, 7)
    assert got is not None and not got.adopt and "futility" in got.why and "verdict 7" in got.why
    ahead = {**plan, "cells": list(CASES)}
    for r in _pair({c: (False, True) for c in CASES[20:30]}):
        ckpt.add({**r, "candidate": "inc-key" if r["candidate"] == INC else "ch-key"}, 1.0)
    assert measure_cmd._confirm_look("code", out, ahead, 7) is None


def test_a_confirmation_too_small_to_power_its_effect_stops_as_lane_too_small_not_a_loss(tmp_path, monkeypatch):
    from harness import reasons
    out = tmp_path / "confirm"
    out.mkdir()
    ckpt = watch.Checkpoint(out, {"modality": "code", "candidates": ["inc-spec", "org/x"], "repeat": 1,
                                  "split": "dev"}, keep=False)
    few = CASES[:8]
    rates = {c: (0.0 if i < 4 else 1.0) for i, c in enumerate(few)}
    for r in _pair({c: ((True, False) if i < 2 else (False, False)) for i, c in enumerate(few[:4])}):
        ckpt.add({**r, "candidate": "inc-key" if r["candidate"] == INC else "ch-key"}, 1.0)
    (out / watch.PROGRESS).write_text(json.dumps({"specs": {"inc-key": "inc-spec", "ch-key": "org/x"}}),
                                      encoding="utf-8")
    monkeypatch.setattr(power, "effect_for", lambda lane: 0.06)
    pw = power.plan([rates[c] for c in few], 0.06, repeat=1, observed=40, unmeasured=False)
    assert pw.power < pw.target and (pw.cases_needed or 0) > len(few)
    plan = {**weedout.planned(few, rates, {}, 0.06), "cells": list(few), "repeat": 1, "effect": 0.06,
            "power": pw.as_dict(), "incumbent": "inc-spec", "challenger": "org/x"}
    got = measure_cmd._confirm_look("code", out, plan, 7)
    assert got is not None and not got.adopt
    assert got.failure_class == reasons.LANE_TOO_SMALL and got.until.startswith("cases:code>")


def test_the_confirmation_plan_carries_the_power_its_cells_could_have(tmp_path, monkeypatch):
    monkeypatch.setattr(power, "served_profile", lambda conn, lane, spec: ({"d1": [1, 1], "d2": [0, 1]}, None))
    monkeypatch.setattr(weedout, "seconds_of", lambda conn, lane, spec: {"d1": 2.0, "d2": 30.0})

    class Conn:
        def close(self):
            pass
    from harness import memory_store as ms
    monkeypatch.setattr(ms, "connect", lambda *a, **k: Conn())
    split = holdout.Split("code", ("d1", "d2", "d3"), ("h1",), False)
    got = measure_cmd._confirm_order("code", "inc-spec", split, 1, frozenset({"d3"}))
    assert got["cells"] == ["d1", "d2"] and set(got["order"]) == {"d1", "d2", "d3"}
    assert got["power"]["cases"] == 2 and 0.0 <= got["power"]["power"] <= 1.0 and not got["power"]["unmeasured"]


def test_a_confirmation_runs_in_look_slices_with_its_order(tmp_path, monkeypatch):
    seen = []

    def launch(argv, **kw):
        seen.append(argv)
        return types.SimpleNamespace(returncode=0, stderr="")
    monkeypatch.setattr(measure_cmd, "_launch", launch)
    monkeypatch.setattr(measure_cmd.paths, "home", lambda: tmp_path)
    split = holdout.Split("code", ("d1", "d2"), ("h1",), False)
    plan = {"order": ("d2", "d1"), "rates": {"d1": 1.0, "d2": 0.5}, "cells": ["d1", "d2"], "repeat": 1, "effect": 0.1}
    _, out = measure_cmd._confirm_run("code", "inc-spec", "org/x", "org/x", 1, split, None, 7, plan)
    argv = seen[-1]
    assert json.loads(Path(argv[argv.index("--order") + 1]).read_text(encoding="utf-8")) == ["d2", "d1"]
    assert "--stop-at" in argv and plan["incumbent"] == "inc-spec" and plan["challenger"] == "org/x"
    measure_cmd._confirm_run("code", "inc-spec", "org/x", "org/x", 1, split, None, 7, None)
    assert "--order" not in seen[-1] and "--stop-at" not in seen[-1]


def test_a_replayed_run_is_never_ordered_from_its_own_rows():
    rows = [{"candidate": INC, "run_id": 1, "base": "a", "seconds": 9.0, "judged": True, "draw": 0},
            {"candidate": INC, "run_id": 2, "base": "a", "seconds": 1.0, "judged": True, "draw": 1}]
    rates, secs = weedout_replay._history(rows, INC, ["a"], skip_run=1)
    assert rates == {"a": 1.0} and secs == {"a": 1.0}


def _store(tmp_path) -> sqlite3.Connection:
    conn = sqlite3.connect(tmp_path / "s.db")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        "CREATE TABLE runs (id INTEGER PRIMARY KEY, lane TEXT, tier TEXT, split TEXT, repeat_count INTEGER);"
        "CREATE TABLE results (id INTEGER PRIMARY KEY, run_id INTEGER, seq INTEGER, candidate TEXT, case_id TEXT,"
        " passed INTEGER, seconds REAL, metrics TEXT, failure_class TEXT);"
        "CREATE TABLE candidates (id INTEGER PRIMARY KEY, receipt_key TEXT);"
        "CREATE TABLE verdicts (id INTEGER PRIMARY KEY, run_id INTEGER, candidate_id INTEGER, tier TEXT);")
    return conn


def test_the_replay_orders_each_run_without_its_own_rows_and_keeps_every_verdict(tmp_path, monkeypatch):
    monkeypatch.setattr(holdout, "for_lane", lambda lane, root=None: SPLIT)
    conn = _store(tmp_path)
    rng = random.Random(7)
    rate = {c: (1.0 if i < 15 else 0.0 if i < 20 else 0.5) for i, c in enumerate(CASES)}
    for rid, other in ((1, "x"), (2, "y"), (3, "z")):
        conn.execute("INSERT INTO runs VALUES (?, 'code', 'measure', 'holdout', 1)", (rid,))
        seq = 0
        for c in CASES:
            for who, p in ((INC, rate[c]), (other, rate[c] - 0.3)):
                conn.execute("INSERT INTO results (run_id, seq, candidate, case_id, passed, seconds, metrics, "
                             "failure_class) VALUES (?, ?, ?, ?, ?, 600, '{}', '')",
                             (rid, seq, who, c, int(rng.random() < p)))
                seq += 1
    got = weedout_replay.replay(conn, "code")
    assert [x["inc"] for x in got] == [INC, INC, INC]
    assert all(x["weedout"].adopt == x["full"] for x in got)
    assert all(x["weedout"].cases <= x["cases"] for x in got)
    assert any(x["weedout"].how == "futility" for x in got)
    lines = weedout_replay.replay_lines(got)
    assert lines[-1].startswith("3 paired run(s): weed-out same verdict 3/3, adopts where full kept 0")
    sim = weedout_replay.simulate(conn, "code", INC, reps=5, blocks=2)
    assert set(sim) == set(weedout_replay.scenarios())
    assert all(sim[s]["full"]["cases"] == len(CASES) for s in sim)
    assert len(weedout_replay.simulate_lines(sim)) == len(sim)
