"""Held-out split, the adopt gate's power, and lane saturation. #479."""
import json
from fractions import Fraction
from math import comb

import pytest

from evals.core import Case
from harness import adopt, holdout, power, reasons


def _cases(n, lane="code", tag=""):
    return [Case(id=f"case-{i:02d}", modality=lane, prompt=f"prompt {i}{tag}")
            for i in range(n)]


# --- the split -------------------------------------------------------------

def test_the_split_is_deterministic_and_ignores_input_order():
    cases = _cases(20)
    a = holdout.assign("code", cases)
    b = holdout.assign("code", list(reversed(cases)))
    assert (a.dev, a.holdout) == (b.dev, b.holdout)
    assert set(a.dev) | set(a.holdout) == {c.id for c in cases}
    assert not set(a.dev) & set(a.holdout)
    assert a.version == holdout.VERSION and not a.too_small


def test_about_thirty_percent_is_held_out_and_never_fewer_than_three():
    for n in (6, 10, 15, 24, 40):
        got = holdout.assign("code", _cases(n))
        assert len(got.holdout) >= holdout.MIN_HOLDOUT
        assert len(got.dev) >= holdout.MIN_DEV
        assert abs(len(got.holdout) - n * holdout.FRACTION) <= max(3, 0.15 * n)


def test_an_edit_moves_only_the_edited_case():
    """Assignment is by content digest: an unchanged case keeps its side."""
    cases = _cases(40)
    before = holdout.assign("code", cases)
    edited = [Case(id=c.id, modality=c.modality, prompt=c.prompt + " v2")
              if c.id == "case-07" else c for c in cases]
    after = holdout.assign("code", edited)
    for c in cases:
        if c.id != "case-07":
            assert before.side(c.id) == after.side(c.id), c.id


def test_the_content_decides_not_the_name_alone():
    """Rewriting every prompt reshuffles the split; the ids alone would not."""
    a = holdout.assign("code", _cases(40))
    b = holdout.assign("code", _cases(40, tag=" rewritten"))
    assert a.holdout != b.holdout


def test_a_lane_too_small_to_split_says_so_and_holds_out_everything():
    got = holdout.assign("svg", _cases(3, "svg"))
    assert got.too_small
    assert set(got.holdout) == {"case-00", "case-01", "case-02"}
    assert "too small" in got.caveat


def test_repeat_suffixes_map_to_their_case():
    split = holdout.assign("code", _cases(20))
    first = split.holdout[0]
    assert split.side(f"{first}#3") == "holdout"
    assert split.side("nope#1") == ""


def test_the_shipped_lanes_split_where_they_can():
    decide = holdout.for_lane("decide")
    assert not decide.too_small and len(decide.holdout) >= 3
    assert holdout.for_lane("svg").too_small


# --- the adopt gate decides on holdout only --------------------------------

def _split():
    return holdout.Split("code", dev=("d1", "d2", "d3", "d4"),
                      holdout=("h1", "h2", "h3"), too_small=False)


def _rows(cells):
    """cells: case -> list of (incumbent passed, challenger passed) per repeat."""
    out = []
    for case, pairs in cells.items():
        for k, (i, c) in enumerate(pairs, 1):
            out.append({"candidate": "inc", "case_id": f"{case}#{k}", "passed": i,
                        "seconds": 1.0, "metrics": {}})
            out.append({"candidate": "ch", "case_id": f"{case}#{k}", "passed": c,
                        "seconds": 1.0, "metrics": {}})
    return out


def _summary(name, rows):
    mine = [r for r in rows if r["candidate"] == name]
    rate = sum(r["passed"] for r in mine) / len(mine)
    return {"candidate": name, "pass_rate": rate, "median_s": 1.0, "metrics": {}}


def test_a_win_on_dev_alone_is_not_adopted():
    rows = _rows({**{d: [(False, True)] * 4 for d in _split().dev},
                  **{h: [(True, True)] * 4 for h in _split().holdout}})
    got = adopt.decide("code", _summary("inc", rows), _summary("ch", rows),
                       rows, split=_split())
    assert not got.adopt
    assert "dev" in got.why and "16 gained" in got.why


def test_a_win_on_holdout_is_adopted_and_dev_is_reported_beside_it():
    """The incumbent passes half its draws of every case, so repeats are
    independent evidence; a deterministic three-case win is not (#591)."""
    rows = _rows({**{d: [(True, True)] * 4 for d in _split().dev},
                  **{h: [(False, True), (True, True)] * 2 for h in _split().holdout}})
    got = adopt.decide("code", _summary("inc", rows), _summary("ch", rows),
                       rows, split=_split())
    assert got.adopt
    assert "6 gained against 0 lost" in got.why
    assert "dev: 0 gained, 0 lost" in got.why
    assert got.evidence["split"]["version"] == holdout.VERSION


def test_a_lane_too_small_adopts_on_all_cases_with_the_caveat_recorded():
    small = holdout.Split("svg", dev=("a", "b", "c"), holdout=("a", "b", "c"),
                          too_small=True)
    rows = _rows({c: [(False, True), (True, True), (False, True)]
                  for c in ("a", "b", "c")})
    got = adopt.decide("svg", _summary("inc", rows), _summary("ch", rows),
                       rows, split=small)
    assert got.adopt
    assert "too small" in got.why
    assert got.evidence["split"]["too_small"] is True


# --- power -----------------------------------------------------------------

def _tail(n, p, k):
    """P(Binomial(n, p) >= k), exactly."""
    p = Fraction(p)
    return float(sum(comb(n, i) * p ** i * (1 - p) ** (n - i)
                     for i in range(k, n + 1)))


def test_a_certain_flip_needs_six_cells_for_the_sign_test():
    """Every cell gained: the two-sided sign test first rejects at six cells."""
    assert power.power([0.0], effect=1.0, repeat=5) == 0.0
    assert power.power([0.0], effect=1.0, repeat=6) == pytest.approx(1.0)


def test_the_svg_receipt_was_underpowered_at_repeat_three():
    """The svg receipt's shape: no cell can be lost, so the gate rejects only
    at six or more gains, a binomial tail computed exactly below."""
    rates = [5 / 9] * 3
    effect = 4 / 9
    assert power.power(rates, effect, repeat=3) == pytest.approx(
        _tail(9, Fraction(4, 9), 6), abs=1e-9)
    assert power.power(rates, effect, repeat=3) == pytest.approx(0.1574, abs=1e-3)
    assert power.power(rates, effect, repeat=8) == pytest.approx(
        _tail(24, Fraction(4, 9), 6), abs=1e-9)


def test_lost_cells_count_against_the_challenger():
    """p=0.5, q=0.7: gained 0.35, lost 0.15. Six cells reject only if all six
    are gains (two-sided p=0.031); five of six is p=0.22. P = 0.35^6."""
    assert power.power([0.5], effect=0.2, repeat=6) == pytest.approx(0.35 ** 6)


def test_the_plan_takes_the_smallest_repeat_that_reaches_the_target():
    got = power.plan([5 / 9] * 3, effect=4 / 9, stochastic=True, rho=0.0)
    assert got.repeat > 3
    assert got.power >= power.TARGET
    assert power.power([5 / 9] * 3, 4 / 9, got.repeat - 1) < power.TARGET
    assert not got.capped


def test_the_plan_is_capped_and_says_so():
    got = power.plan([0.97] * 3, effect=0.2, stochastic=True, cap=10, rho=0.0)
    assert got.capped and got.repeat == 10
    assert got.power < power.TARGET
    assert got.as_dict()["cap"] == 10


def test_repeat_adds_no_cells_in_a_deterministic_lane():
    got = power.plan([0.5] * 4, effect=0.2, stochastic=False)
    assert got.repeat == 1 and got.cells == 4
    assert "more cases" in got.why


def test_incumbent_rates_come_from_stored_runs(store_run):
    from harness import memory_store as ms
    rows = [{"case_id": f"{c}#{k}", "candidate": "inc", "passed": ok,
             "seconds": 1.0, "peak_kb": 0, "detail": ""}
            for c, oks in (("a", [1, 1, 0, 0]), ("b", [1, 1, 1, 1]))
            for k, ok in enumerate(oks, 1)]
    store_run("20261006-000000-code", "code", rows=rows)
    conn = ms.connect()
    try:
        rates, seen = power.incumbent_rates(conn, "code", "inc", ["a", "b", "c"])
    finally:
        conn.close()
    assert rates["a"] == 0.5 and rates["b"] == 1.0 and rates["c"] in (0.5, 1.0)
    assert seen == 8


# --- an underpowered null is not "no better" -------------------------------

def test_an_underpowered_null_says_so():
    rows = _rows({h: [(False, True)] + [(True, True)] * 2 for h in _split().holdout})
    weak = power.plan([2 / 3] * 3, effect=0.2, stochastic=True, cap=3)
    got = adopt.decide("code", _summary("inc", rows), _summary("ch", rows),
                       rows, split=_split(), plan=weak)
    assert not got.adopt
    assert got.failure_class == reasons.UNDERPOWERED
    assert got.why.startswith("underpowered")
    assert got.evidence["power"]["power"] == pytest.approx(weak.power)


def test_a_powered_null_is_an_ordinary_loss():
    rows = _rows({h: [(False, True)] + [(True, True)] * 2 for h in _split().holdout})
    strong = power.Plan(repeat=3, power=0.95, cells=9, cases=3, effect=0.2,
                        alpha=0.05, target=0.8, cap=16, capped=False,
                        stochastic=True, observed=9, why="")
    got = adopt.decide("code", _summary("inc", rows), _summary("ch", rows),
                       rows, split=_split(), plan=strong)
    assert not got.adopt and got.failure_class == ""
    assert "not established" in got.why


def test_the_verdict_row_carries_the_split_version_and_the_power(tmp_path):
    from harness import memory_store as ms
    conn = ms.connect(tmp_path / "d.db")
    weak = power.plan([2 / 3] * 3, effect=0.2, stochastic=True, cap=3)
    verdict = adopt.Verdict("code", "q3-4b", "org/x", False, "underpowered: x",
                            failure_class=reasons.UNDERPOWERED,
                            evidence={"split": _split().as_dict(),
                                      "power": weak.as_dict()})
    vid = adopt.record(conn, verdict, spec="org/x")
    row = conn.execute("SELECT * FROM verdicts WHERE id = ?", (vid,)).fetchone()
    assert row["failure_class"] == reasons.UNDERPOWERED
    assert row["reason"] == reasons.LIMIT
    assert row["split_version"] == holdout.VERSION
    assert json.loads(row["power"])["power"] == pytest.approx(weak.power)


def test_a_run_records_its_split():
    from harness import memory_store as ms
    from harness import paths, runs
    conn = ms.connect()
    try:
        rid = runs.record(conn, paths.runs() / "20261006-000001-code", {
            "receipt": {"modality": "code", "split": "dev", "split_version": "1"},
            "rows": [{"case_id": "a", "candidate": "x", "passed": True,
                      "seconds": 1.0, "peak_kb": 0, "detail": ""}]})
        row = runs.get(conn, rid)
    finally:
        conn.close()
    assert (row["split"], row["split_version"]) == ("dev", "1")


# --- saturation ------------------------------------------------------------

def test_a_lane_whose_incumbent_passes_its_holdout_is_saturated(
        store_run, monkeypatch):
    from harness import report, winners
    monkeypatch.setattr(winners, "typed", lambda: {"svg": "local-large"})
    monkeypatch.setattr(adopt, "current", lambda conn, machine=None: {})
    ids = holdout.for_lane("svg").holdout
    store_run("20261006-000002-svg", "svg", rows=[
        {"case_id": f"{c}#{k}", "candidate": "local-large", "passed": True,
         "seconds": 1.0, "peak_kb": 0, "detail": ""}
        for c in ids for k in (1, 2)])
    from harness import memory_store as ms
    conn = ms.connect()
    try:
        svg = {l["lane"]: l for l in report.lanes_state(conn)}["svg"]
    finally:
        conn.close()
    assert svg["saturated"] is True
    assert svg["holdout_pass_rate"] == 1.0
    assert "saturated" in report._lane_rows([{**svg, "age_days": 0.1}], {})


def test_a_lane_with_room_is_not_saturated(store_run, monkeypatch):
    from harness import report, winners
    monkeypatch.setattr(winners, "typed", lambda: {"svg": "local-large"})
    monkeypatch.setattr(adopt, "current", lambda conn, machine=None: {})
    ids = holdout.for_lane("svg").holdout
    store_run("20261006-000003-svg", "svg", rows=[
        {"case_id": c, "candidate": "local-large", "passed": i == 0,
         "seconds": 1.0, "peak_kb": 0, "detail": ""} for i, c in enumerate(ids)])
    from harness import memory_store as ms
    conn = ms.connect()
    try:
        svg = {l["lane"]: l for l in report.lanes_state(conn)}["svg"]
    finally:
        conn.close()
    assert svg["saturated"] is False


def test_saturation_threshold():
    assert holdout.saturated(0.95) and not holdout.saturated(0.94)
    assert not holdout.saturated(None)


# --- who sees which side ---------------------------------------------------

def test_only_keeps_one_side_and_all_keeps_everything():
    cases = _cases(20)
    split = holdout.assign("code", cases)
    assert {c.id for c in holdout.only(cases, "dev")} == set(split.dev)
    assert {c.id for c in holdout.only(cases, "holdout")} == set(split.holdout)
    assert holdout.only(cases, "all") == cases


def test_the_screen_sees_only_dev_cases():
    from evals.run import screen_pool
    cases = _cases(20)
    split = holdout.assign("code", cases)
    picked = screen_pool(cases)
    assert picked and all(c.id in split.dev for c in picked)


def test_runs_on_different_sides_are_not_one_exam():
    from evals.core import Receipt, comparable
    a = Receipt("code", ("x",), 1, {}, "g", split="dev", split_version="1")
    b = Receipt("code", ("x",), 1, {}, "g", split="holdout", split_version="1")
    ok, why = comparable(a, b)
    assert not ok and "split" in why


def test_adopt_without_repeat_measures_at_the_planned_repeat(monkeypatch, tmp_path):
    import argparse
    import subprocess

    from harness import cli
    from harness import memory_store as ms
    from harness.commands import measure as measure_cmd

    seen = {}

    class Done:
        returncode = 0
        stderr = ""

    def fake_run(argv, **kw):
        seen["argv"] = argv
        return Done()

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(adopt, "default_for", lambda lane, fallback, conn=None: "q3-4b")
    monkeypatch.setattr(measure_cmd, "_receipt_at", lambda out: None)
    monkeypatch.setattr(power, "plan", lambda *a, **k: power.Plan(
        repeat=7, power=0.81, cells=21, cases=3, effect=0.2, alpha=0.05,
        target=0.8, cap=16, capped=False, stochastic=True, observed=0, why=""))
    real = ms.connect
    monkeypatch.setattr(ms, "connect", lambda *a, **k: real(tmp_path / "d.db"))
    cli._measure_and_adopt(argparse.Namespace(repeat=None, lane="svg"),
                           {"name": "q3-30b", "lane": "svg"})
    argv = seen["argv"]
    assert argv[argv.index("--repeat") + 1] == "7"


def test_the_adopt_and_discover_commands_default_to_the_planned_repeat():
    from harness import cli
    p = cli.build_parser()
    assert p.parse_args(["adopt", "--lane", "svg", "--challenger", "x"]).repeat is None
    assert p.parse_args(["discover", "--loop"]).repeat is None


def test_an_edited_case_file_is_drawn_again(tmp_path):
    lane = tmp_path / "code"
    lane.mkdir()
    for i in range(8):
        (lane / f"c{i}.yaml").write_text(
            f"id: c{i}\nmodality: code\nprompt: p{i}\nassert:\n  checks: ['x']\n",
            encoding="utf-8")
    before = holdout.for_lane("code", tmp_path)
    for i in range(8):
        (lane / f"c{i}.yaml").write_text(
            f"id: c{i}\nmodality: code\nprompt: q{i}\nassert:\n  checks: ['x']\n",
            encoding="utf-8")
    from evals.core import load_cases
    after = holdout.for_lane("code", tmp_path)
    assert after == holdout.assign("code", load_cases(tmp_path))
    assert before.holdout != after.holdout
    assert before == holdout.assign("code", [
        Case(id=c.id, modality="code", prompt=f"p{c.id[1:]}", assertions=c.assertions)
        for c in load_cases(tmp_path)])
