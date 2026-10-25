"""An engine's wall clock per case is a registered knob, derived from its slowest finished case on this machine (#708)."""
import pytest

from evals import core
from evals import run as R
from evals.core import Case, Receipt
from evals.runners.chain import ChainRunner
from evals.runners.process import ProcessRunner, timed_out
from evals.runners.trace import TraceRunner
from harness import engine_timeout as et
from harness import engines, knobs, reasons, runs, screen
from harness import memory_store as ms
from tests import test_knob_receipt, test_limit_hit_1193
from tests.test_knob_receipt import quiet_receipt  # noqa: F401

_SEQ = iter(range(1, 10_000))


@pytest.fixture
def conn():
    c = ms.connect()
    yield c
    c.close()


def record(conn, lane, candidate, seconds, failure_class="", here=True):
    rows = [{"candidate": candidate, "case_id": f"c{i}", "passed": not failure_class, "seconds": s,
             "failure_class": failure_class} for i, s in enumerate(seconds)]
    run_id = runs.record(conn, f"runs/r{next(_SEQ)}-{lane}",
                         {"receipt": {"modality": lane}, "specs": {candidate: candidate}, "rows": rows},
                         at=1_000.0 + next(_SEQ))
    if here:
        conn.execute("UPDATE runs SET machine_id = ? WHERE id = ?", (ms.remember_machine(conn), run_id))
        conn.commit()
    return run_id


def test_an_engine_timeout_limit_is_a_registered_knob_limit():
    for lane in knobs.KNOBS["engine_timeout"].lanes:
        assert knobs.limit(f"engine_timeout_s.{lane}", 900.0, "s") == f"engine_timeout_s.{lane}>900"
    assert timed_out("video", 21600.0).limit == "engine_timeout_s.video>21600"
    assert test_limit_hit_1193.AWAITING == {}


def test_an_engine_with_enough_finished_cases_runs_at_the_margin_times_its_slowest(conn):
    record(conn, "image", "mflux/z-image-turbo-q8", [10.0 * i for i in range(1, et.MIN_CASES + 1)])
    got = et.basis(conn, "image", "mflux/qwen-image-q4", 900.0)
    assert got["seconds"] == et.MARGIN * 10.0 * et.MIN_CASES
    assert (got["from"], got["cases"], got["ceiling"]) == ("measured", et.MIN_CASES, 900.0)


def test_an_engine_with_too_few_finished_cases_keeps_its_own_ceiling(conn):
    record(conn, "image", "mflux/z-image-turbo-q8", [100.0] * (et.MIN_CASES - 1))
    record(conn, "music", "acestep/acestep-v15-turbo", [100.0] * et.MIN_CASES)
    record(conn, "image", "mflux/z-image-turbo-q8", [100.0] * et.MIN_CASES, here=False)
    got = et.basis(conn, "image", "mflux/z-image-turbo-q8", 900.0)
    assert (got["seconds"], got["from"]) == (900.0, "ceiling")


def test_a_timed_out_case_does_not_raise_the_clock_it_was_cut_by(conn):
    record(conn, "image", "mflux/a", [50.0] * et.MIN_CASES)
    record(conn, "image", "mflux/a", [900.0], failure_class=reasons.TIMEOUT)
    assert et.basis(conn, "image", "mflux/a", 900.0)["seconds"] == et.MARGIN * 50.0


def test_the_derived_timeout_never_goes_below_the_floor(conn):
    record(conn, "pii", "pii-regex/patterns", [0.01] * et.MIN_CASES)
    assert et.basis(conn, "pii", "pii-regex/patterns", 60.0)["seconds"] == et.FLOOR_S
    assert et.derive(et.MIN_CASES, 0.01, 60.0, margin=0) == 60.0


def test_an_eval_run_records_each_engine_runner_timeout_and_its_basis_on_the_receipt(conn, tmp_path):
    record(conn, "image", "mflux/z-image-turbo-q8", [40.0] * et.MIN_CASES)
    process = ProcessRunner(engines.resolve("mflux:z-image-turbo"), tmp_path)
    chain = ChainRunner(engines.resolve("mflux:z-image-turbo"), "upscale-seedvr2", tmp_path)
    got = R.engine_timeouts("image", [("mflux:z-image-turbo", process, []), ("x", chain, [])])
    assert process.timeout == et.MARGIN * 40.0 and chain.timeout == chain.ceiling == 1800.0
    assert got[process.candidate]["seconds"] == process.timeout
    assert got[chain.candidate]["from"] == "ceiling"
    raw = Receipt(modality="image", case_ids=("a",), repeat=1, sampling={}, gateway="g",
                  engine_timeout=got).as_dict()
    back = Receipt.from_dict(raw)
    assert back.engine_timeout == got
    other = Receipt.from_dict({**raw, "engine_timeout": {}})
    assert core.comparable(back, other)[0], "the clock each engine ran at is provenance, not an axis"


class Clocked(test_knob_receipt.Answers):
    ceiling = timeout = 77.0


def test_a_run_writes_its_engine_clocks_into_the_receipt(tmp_path, monkeypatch, quiet_receipt):
    import argparse
    import json
    monkeypatch.setattr(R, "build_runner", lambda *a, **k: Clocked())
    args = argparse.Namespace(
        screen=False, repeat=1, adherence="", cases=str(test_knob_receipt.ROOT / "evals" / "cases"),
        modality="code", candidates="org/x", from_winners=False, gateway="http://gw.test",
        out=str(tmp_path / "out"), split="all", max_tokens=None)
    R._execute(args)
    data = json.loads((tmp_path / "out" / "results.json").read_text(encoding="utf-8"))
    assert data["receipt"]["engine_timeout"]["org/x"]["seconds"] == 77.0
    assert data["receipt"]["engine_timeout"]["org/x"]["from"] == "ceiling"


def test_a_trace_runner_runs_at_the_timeout_set_on_it(tmp_path, monkeypatch):
    from evals.runners import trace
    seen = {}

    def expired(argv, timeout=None, **_):
        import subprocess
        seen["timeout"] = timeout
        raise subprocess.TimeoutExpired(argv, timeout)
    monkeypatch.setattr(trace.proc, "run", expired)
    r = TraceRunner(engines.resolve("mflux:z-image-turbo"), tmp_path)
    r.timeout = 120.0
    row = r.run(Case(id="c", modality="svg", prompt="a fox"))
    assert seen["timeout"] == 120.0 and row.limit == "engine_timeout_s.svg>120"


def test_a_screen_deadline_follows_the_derived_engine_timeout(conn):
    from evals.run import SCREEN_CASES
    assert screen.deadline_s("mflux:z-image-turbo") == SCREEN_CASES * 900.0
    record(conn, "image", "mflux/z-image-turbo-q8", [30.0] * et.MIN_CASES)
    assert screen.deadline_s("mflux:z-image-turbo") == SCREEN_CASES * et.MARGIN * 30.0


def test_the_backtest_counts_the_cases_a_margin_would_have_cut(conn):
    record(conn, "image", "mflux/a", [100.0] * et.MIN_CASES + [350.0, 600.0])
    (got,) = et.backtest(conn, margins=(2.0, 3.0, 5.0, 10.0))
    assert (got["lane"], got["engine"], got["cases"], got["slowest"]) == ("image", "mflux", et.MIN_CASES + 2, 600.0)
    assert got["cut"] == {2.0: 1, 3.0: 1, 5.0: 0, 10.0: 0}


def test_the_margin_is_an_exam_knob_a_run_can_set():
    assert knobs.settings("image")["engine_timeout"] == et.MARGIN
    assert knobs.settings("image", {"engine_timeout": 5.0})["engine_timeout"] == 5.0
    with knobs.rebind({"engine_timeout": 5.0}):
        assert et.derive(et.MIN_CASES, 100.0, 900.0) == 500.0
    assert et.derive(et.MIN_CASES, 100.0, 900.0) == et.MARGIN * 100.0
