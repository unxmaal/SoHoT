"""An eval asks a lane-model at the least reply budget its stored runs show keeps its passes (#1352)."""
import json

import pytest

from evals import core
from evals import run as R
from harness import cli, completion, knobs, reasons, reply_cap, runs
from harness import memory_store as ms
from harness.commands import measure

LANE = "repo"
BUDGET = completion.budget(LANE)
_SEQ = iter(range(1, 10_000))
_REAL_CONNECT = ms.connect


@pytest.fixture
def db(tmp_path):
    return tmp_path / "d.db"


@pytest.fixture
def conn(db):
    c = ms.connect(db)
    yield c
    c.close()


def _row(spec, i, passed, tokens=None, never_ran=False):
    fc = reasons.REFUSED_BY_GATEWAY if never_ran else ("" if passed else reasons.CONTENT_FAILED)
    return {"candidate": spec, "case_id": f"c{i}", "passed": passed, "seconds": (tokens or 100) / 50.0,
            "failure_class": fc, "limit": "", "metrics": {"completion_tokens": tokens} if tokens else {}}


def record(conn, spec, rows, budget=BUDGET, sampling=None, harness=""):
    receipt = {"modality": LANE, "max_tokens": budget, "budget_ladder": [],
               "sampling": {LANE: sampling or {}}, **({"harness": harness} if harness else {})}
    return runs.record(conn, f"runs/r{next(_SEQ)}-{LANE}",
                       {"receipt": receipt, "specs": {spec: spec}, "rows": rows}, at=1_000.0)


def exam(spec, passing, n=108, tokens=500):
    return [_row(spec, i, i in passing, tokens) for i in range(n)]


def known(conn, spec="known"):
    """Twenty quick passes and two replies that ran on to 30000 tokens and failed: a cap at 4096 saves their time."""
    record(conn, spec, [_row(spec, i, True, 100) for i in range(20)] + [_row(spec, 20 + i, False, 30000) for i in range(2)])


def qwopus(conn, spec="qwopus"):
    """The 2026-10-23 sweep's shape: 2000 and 4000 never ran, 8000 and 16384 pass 9, 32768 passes 6."""
    for b in (2000, 4000):
        record(conn, spec, [_row(spec, i, False, never_ran=True) for i in range(108)], budget=b)
    record(conn, spec, exam(spec, set(range(9)), tokens=2000), budget=8000)
    record(conn, spec, exam(spec, set(range(9)), tokens=4000), budget=16384)
    record(conn, spec, exam(spec, set(range(6)), tokens=8000), budget=32768)


def test_a_sweep_caps_at_the_smallest_budget_within_noise_of_the_best(conn):
    qwopus(conn)
    got = reply_cap.derive(conn, LANE)["models"]["qwopus"]
    assert got["from"] == "sweep" and got["cap"] == 8000 and got["best"] == 8000
    assert got["passes"] == {"8000": 9, "16384": 9, "32768": 6} and got["cases"] == 108


def test_a_budget_that_passes_clearly_fewer_is_not_within_noise(conn):
    record(conn, "m", exam("m", {0}), budget=4000)
    record(conn, "m", exam("m", set(range(12))), budget=8000)
    got = reply_cap.derive(conn, LANE)["models"]["m"]
    assert got["cap"] == 8000 and got["passes"]["4000"] == 1


def test_a_smaller_budget_within_noise_wins_over_a_best_that_passes_one_more(conn):
    record(conn, "m", exam("m", set(range(9))), budget=8000)
    record(conn, "m", exam("m", set(range(10))), budget=32768)
    got = reply_cap.derive(conn, LANE)["models"]["m"]
    assert (got["best"], got["cap"]) == (32768, 8000)


def test_the_sign_test_counts_only_cases_one_budget_passes():
    best = {i: i < 9 for i in range(108)}
    assert reply_cap.within_noise(best, {i: i < 6 for i in range(108)}, 1.96)
    assert not reply_cap.within_noise(best, {i: False for i in range(108)}, 1.96)
    assert reply_cap.within_noise(best, dict(best), 1.96)


def test_a_sweep_whose_best_passes_too_few_sets_nothing(conn):
    record(conn, "m", exam("m", set()), budget=4000)
    record(conn, "m", exam("m", set(range(reply_cap.MIN_PASSES - 1))), budget=8000)
    assert "m" not in reply_cap.derive(conn, LANE)["models"]


def test_runs_with_other_sampling_are_not_one_sweep(conn):
    record(conn, "m", exam("m", set()), budget=4000, sampling={"temperature": 1.0})
    record(conn, "m", exam("m", set(range(12))), budget=8000)
    got = reply_cap.derive(conn, LANE)["models"].get("m")
    assert got is None or got["from"] != "sweep"


def test_tokens_cap_is_the_quantile_plus_margin_in_whole_steps(conn):
    record(conn, "m", [_row("m", i, True, 100 * (i + 1)) for i in range(20)] + [_row("m", 20, False, 30000)])
    got = reply_cap.derive(conn, LANE)["models"]["m"]
    assert got["from"] == "tokens" and got["tokens"] == 1900 and got["passes"] == 20
    assert got["cap"] == 4096


def test_the_cap_never_exceeds_the_lanes_budget(conn):
    record(conn, "m", [_row("m", i, True, 30000) for i in range(10)])
    assert reply_cap.entry(reply_cap.derive(conn, LANE), "m")["cap"] == BUDGET
    record(conn, "s", exam("s", set(range(9)), tokens=12000), budget=49152)
    record(conn, "s", exam("s", set(range(9)), tokens=20000), budget=65536)
    assert reply_cap.entry(reply_cap.derive(conn, LANE), "s")["cap"] == BUDGET


def test_too_few_passes_at_the_whole_budget_set_no_cap(conn):
    record(conn, "m", [_row("m", i, i < reply_cap.MIN_PASSES - 1, 100) for i in range(40)])
    assert "m" not in reply_cap.derive(conn, LANE)["models"]


def test_a_laddered_run_is_no_point_of_a_sweep(conn):
    record(conn, "m", exam("m", set(range(12))), budget=8000)
    lad = {"modality": LANE, "max_tokens": 65536, "budget_ladder": [4000, 65536], "sampling": {LANE: {}}}
    runs.record(conn, f"runs/r{next(_SEQ)}-{LANE}", {"receipt": lad, "specs": {"m": "m"},
                                                     "rows": exam("m", set(range(12)))}, at=1_000.0)
    got = reply_cap.derive(conn, LANE)["models"]["m"]
    assert got["from"] == "tokens"


def test_a_capped_run_never_lowers_its_own_cap(conn):
    record(conn, "m", [_row("m", i, True, 100) for i in range(20)], budget=4096)
    assert reply_cap.entry(reply_cap.derive(conn, LANE), "m") == {"cap": BUDGET, "from": "budget", "model": "m"}


def test_a_cap_that_saves_too_little_keeps_the_lanes_budget(conn):
    record(conn, "m", [_row("m", i, True, 100) for i in range(20)])
    got = reply_cap.entry(reply_cap.derive(conn, LANE), "m")
    assert (got["cap"], got["from"], got["derived"]["cap"]) == (BUDGET, "budget", 4096)
    assert "under 0.1" in reply_cap.said(got)
    known(conn, "k")
    k = reply_cap.entry(reply_cap.derive(conn, LANE), "k")
    assert k["cap"] == 4096 and k["saved_share"] >= reply_cap.MIN_SAVED


def test_rows_of_another_harness_are_left_out(conn):
    record(conn, "m", [_row("m", i, True, 100) for i in range(20)], harness="repair")
    assert reply_cap.derive(conn, LANE)["models"] == {}


def test_a_model_with_no_evidence_runs_at_the_lanes_budget_and_a_pair_shares_the_larger(conn):
    known(conn)
    assert reply_cap.cap_for(conn, LANE, ["known,temperature=0.2"])[0] == 4096
    budget, caps = reply_cap.cap_for(conn, LANE, ["known", "newcomer"])
    assert budget == BUDGET and caps["newcomer"]["from"] == "budget" and caps["known"]["cap"] == 4096


def test_evals_run_asks_at_the_cap_unless_told_otherwise(conn, db, monkeypatch):
    known(conn)
    monkeypatch.setattr(ms, "connect", lambda *a, **k: _REAL_CONNECT(db))
    budget, caps = R.reply_budget(LANE, None, ["known"])
    assert budget == 4096 and caps["known"]["from"] == "tokens"
    assert R.reply_budget(LANE, 32768, ["known"]) == (32768, {})
    assert R.reply_budget(LANE, None, ["known"], harness="repair") == (BUDGET, {})
    assert R.run_budget(LANE, None) == BUDGET
    assert measure._settings(LANE, "known", "") == (4096, ())
    assert measure._settings(LANE, "known", "newcomer") == (BUDGET, ())


def test_the_receipt_keeps_each_keys_cap_and_old_receipts_read_without_one():
    cap = {"cap": 8000, "from": "sweep", "model": "qwopus"}
    r = core.Receipt(modality=LANE, case_ids=("c0",), repeat=1, sampling={}, gateway="g", max_tokens=8000,
                     reply_cap={"qwopus": cap})
    assert core.Receipt.from_dict(json.loads(json.dumps(r.as_dict()))).reply_cap == {"qwopus": cap}
    bare = core.Receipt(modality=LANE, case_ids=("c0",), repeat=1, sampling={}, gateway="g", max_tokens=8000)
    assert "reply_cap" not in bare.as_dict()
    assert R.reply_caps({"key": "qwopus,temperature=0.0"}, {"qwopus": cap}) == {"key": cap}


def test_the_caps_knobs_are_registered_at_their_defaults():
    for name, value in (("reply_cap_quantile", reply_cap.QUANTILE), ("reply_cap_margin", reply_cap.MARGIN),
                        ("reply_cap_min_passes", reply_cap.MIN_PASSES), ("reply_cap_noise_z", reply_cap.NOISE_Z),
                        ("reply_cap_min_saved", reply_cap.MIN_SAVED)):
        k = knobs.KNOBS[name]
        assert k.default() == value and value in k.values and "#1352" in k.note


def test_soh_knobs_reply_caps_prints_each_lane_models_derivation(conn, tmp_path, capsys):
    qwopus(conn)
    conn.commit()
    copy = tmp_path / "copy.db"
    conn.execute(f"VACUUM INTO '{copy}'")
    assert cli.main(["knobs", "reply-caps", "--json", "--store", str(copy)]) == 0
    out = json.loads(capsys.readouterr().out)
    got = [r for r in out["caps"] if r["lane"] == LANE and r["model"] == "qwopus"]
    assert got and got[0]["cap"] == 8000 and got[0]["from"] == "sweep"
