"""The stt canary plants on today's holdout: a pair it no longer separates is invalid, not a miss. #1531."""
import json
import subprocess
from pathlib import Path

import pytest

from harness import adopt, canary, candidates, holdout, power, screen
from harness import memory_store as ms

FIX = Path(__file__).parent / "fixtures" / "stt_1531"
ROWS = [json.loads(line) for line in (FIX / "rows.jsonl").read_text(encoding="utf-8").splitlines()]
SIDES = json.loads((FIX / "split.json").read_text(encoding="utf-8"))
SPLIT = holdout.Split("stt", tuple(SIDES["dev"]), tuple(SIDES["holdout"]), False)
V3, BIG = "mlx-community/parakeet-tdt-0.6b-v3", "mlx-community/parakeet-tdt-1.1b"
# The live store has never measured it: only the canary's isolated homes have.
NEVER_STORED = "parakeet-tdt-1.1b"
OLD_WORSE = canary.Plant("stt-known-worse", "stt", V3, ("declined", "adopt", "candidate"), incumbent=BIG,
                         requires="separates")
OLD_BETTER = canary.Plant("stt-known-better", "stt", BIG, ("measured", "adopt", ""), incumbent=V3,
                          requires="separates")


def _key(name: str) -> str:
    return name.rsplit("/", 1)[-1]


def _rows(*keys) -> list[dict]:
    return [{"case_id": r["case_id"], "candidate": r["candidate"], "passed": r["wer"] <= 0.2,
             "metrics": {"wer": r["wer"]}, "seconds": 0.1, "repeat_index": 1}
            for r in ROWS if r["candidate"] in keys]


def _gate(plant):
    """The plant's verdict as `soh measure` reaches it: a plan on the incumbent's stored draws, the gate, then confirm."""
    inc, ch = _key(plant.incumbent), _key(plant.challenger)
    rows = _rows(inc, ch)
    draws, _ = power.draws_from([] if inc == NEVER_STORED else _rows(inc), inc, "stt")
    rates, seen = power.rates_from(draws, SPLIT.holdout)
    plan = power.plan([rates[c] for c in SPLIT.holdout], power.effect_for("stt"), stochastic=False,
                      observed=seen, alpha=adopt.ALPHA, unmeasured=not any(draws.values()),
                      rho=power.icc([list(draws.values())]))
    v = adopt.decide("stt", adopt._summary(rows, inc), adopt._summary(rows, ch), rows, split=SPLIT, plan=plan)
    return adopt.confirm(v, rows, SPLIT)


def _plants():
    return [p for p in canary.PLANTS if p.lane == "stt"]


def test_the_old_pair_reproduces_both_misses_on_its_stored_rows():
    worse, better = _gate(OLD_WORSE), _gate(OLD_BETTER)
    assert (adopt.outcome_of(worse), worse.failure_class) == (("declined", "limit"), "underpowered"), worse.why
    assert "no stored draws" in worse.why
    assert (adopt.outcome_of(better), better.failure_class) == (("declined", "limit"), "lane_too_small"), better.why
    assert "5 lost against 10 gained" in better.why


@pytest.mark.parametrize("plant", _plants(), ids=lambda p: p.name)
def test_each_stt_plant_reaches_its_verdict_on_its_pairs_stored_rows(plant):
    want, _, want_reason = plant.expect
    outcome, reason = adopt.outcome_of(_gate(plant))
    assert outcome == want and (not want_reason or reason == want_reason), _gate(plant).why


def _measured(conn, plant):
    rid = conn.execute("INSERT INTO runs (path, lane, tier, generated_at, recorded_at) "
                       "VALUES ('adopt-stt', 'stt', 'measure', 1, 0)").lastrowid
    seq = 0
    for name in (plant.incumbent, plant.challenger):
        cid = candidates.ensure(conn, screen.candidate_for("stt", name), lane="stt")
        for r in _rows(_key(name)):
            conn.execute("INSERT INTO results (run_id, seq, candidate_id, candidate, case_id, passed, metrics) "
                         "VALUES (?,?,?,?,?,?,?)", (rid, seq, cid, r["candidate"], r["case_id"], int(r["passed"]),
                                                    json.dumps(r["metrics"])))
            seq += 1


def _child(plant, verdict):
    """A spend that measures the pair's stored rows into the isolated store and records the gate's verdict."""
    def run(argv, env=None, **kw):
        if argv[3:5] == ["canary", "spend"]:
            conn = ms.connect(Path(env["LOCALHARNESS_HOME"]) / "discovery.db")
            try:
                _measured(conn, plant)
                ms.record(conn, ms.Seen(name=plant.challenger, source="t", lane="stt"))
                ms.decide(conn, plant.challenger, verdict[0], tier="adopt", detail=f"stt: {verdict[2]}",
                          reason=verdict[1], failure_class=verdict[3])
                conn.commit()
            finally:
                conn.close()
        return subprocess.CompletedProcess(argv, 0)
    return run


def test_a_pair_todays_holdout_does_not_separate_is_invalid_not_a_miss(monkeypatch, _home):
    monkeypatch.setattr(holdout, "for_lane", lambda lane, *a, **k: SPLIT)
    v = _gate(OLD_BETTER)
    r = canary.run([OLD_BETTER], run=_child(OLD_BETTER, ("declined", "limit", v.why, v.failure_class)))
    p = r["plants"][0]
    assert not p["ok"] and "does not separate" in p["invalid"] and "10 gained, 5 lost" in p["invalid"], p
    assert "invalid on this machine" in canary.morning_line()


def test_a_separated_pair_the_gate_calls_underpowered_is_still_a_miss(monkeypatch, _home):
    monkeypatch.setattr(holdout, "for_lane", lambda lane, *a, **k: SPLIT)
    plant = next(p for p in _plants() if p.name == "stt-known-better")
    r = canary.run([plant], run=_child(plant, ("declined", "limit", "underpowered: power 0.10", "underpowered")))
    p = r["plants"][0]
    assert not p["ok"] and p["invalid"] == "", p
    assert "missed their expected verdicts" in canary.morning_line()


def test_the_separation_check_reads_the_holdout_not_every_case():
    conn = ms.connect()
    try:
        _measured(conn, OLD_BETTER)
        old = canary.apart(conn, OLD_BETTER, SPLIT)
        whole = canary.apart(conn, OLD_BETTER, holdout.Split("stt", (), tuple(SIDES["dev"] + SIDES["holdout"]), False))
    finally:
        conn.close()
    assert "10 gained, 5 lost" in old and whole == "", (old, whole)


def test_soh_canary_check_judges_a_pair_on_todays_holdout():
    conn = ms.connect()
    try:
        _measured(conn, OLD_BETTER)
        got = canary.separable(conn, OLD_BETTER, SPLIT)
    finally:
        conn.close()
    assert not got["ok"] and "5 lost against 10 gained" in got["why"], got
