"""Serving preempts measurement: a delegation takes a lease and a running eval yields to it between cases. #1556."""
import threading
import time

import pytest

from evals import run as R
from evals import watch
from harness import delegate, exclusive, pressure, serve_lease
from harness import memory_store as ms
from harness import watchdog as wd
from harness import workqueue as wq
from tests.test_interleave_816 import CH, INC, Named, _pair, _paired
from tests.test_mcp_delegate import fake  # noqa: F401
from tests.test_pause_813 import _args, clock, quiet  # noqa: F401


def _until(cond, what, limit=20.0):
    end = time.monotonic() + limit
    while not cond():
        if time.monotonic() > end:
            raise AssertionError(f"never: {what}")
        time.sleep(0.01)


@pytest.fixture
def held(monkeypatch):
    """This process holds the machine for an eval, as evals.run does under exclusive.held."""
    monkeypatch.setenv(exclusive.HELD_ENV, "1")


@pytest.fixture
def polls(monkeypatch, clock):
    """Each poll of a yielding eval moves the fake clock POLL_S; `on` runs at every poll."""
    seen = {"n": 0, "on": None}

    def tick(seconds):
        seen["n"] += 1
        clock.now += seconds
        if seen["on"]:
            seen["on"](seen["n"])
        time.sleep(0.005)
    monkeypatch.setattr(watch, "sleep", tick)
    return seen


def _lease_mid_case(runners, key, at_case):
    """A delegation arrives while `key` is in its `at_case`-th case: it waits, answers, and goes idle."""
    runner = runners[key]
    gen = runner.generate
    taken = {}

    def generate(case):
        got = gen(case)
        if len(runner.ran) == at_case:
            taken["lease"] = serve_lease.Lease("code", "a code delegation")
            taken["lease"].idle()
        return got
    runner.generate = generate
    return taken


def test_a_paired_run_that_yields_keeps_its_pairs_and_order_and_its_case_seconds(
        monkeypatch, tmp_path, quiet, clock, held, polls):
    plain_runners, plain_log = _pair(monkeypatch, clock)
    plain = tmp_path / "plain"
    assert R._execute(_args(plain, candidates=f"{INC},{CH}", stop_at=clock.now + 59.0)) == watch.PAUSED
    _, plain_rows = watch.read(plain)

    runners, log = _pair(monkeypatch, clock)
    taken = _lease_mid_case(runners, INC, 2)
    polls["on"] = lambda n: n == 6 and taken["lease"].drop()
    out = tmp_path / "yielded"
    # The slice stops on the run's own time, so a yield inside it leaves the same cases to run.
    assert R._execute(_args(out, candidates=f"{INC},{CH}", stop_at=clock.now + 59.0)) == watch.PAUSED
    _, rows = watch.read(out)
    assert log == plain_log == [INC, CH] * 3
    assert [(r["candidate"], r["case_id"]) for r in rows] == [(r["candidate"], r["case_id"]) for r in plain_rows]
    assert _paired(rows) == _paired(plain_rows) == 3
    # Every case took its own model time; the yield is in none of them.
    assert [r["wall_s"] for r in rows] == [10.0] * 6
    got = watch.read_progress(out)
    assert got["serving_yields"]["count"] == 1
    assert got["serving_yields"]["seconds"] == polls["n"] * serve_lease.POLL_S
    # Cases finished after the yield, so none of it is still owed against no_progress.
    assert got["serving_yields"]["since_case_s"] == 0.0
    # The router may have swapped both models out while it yielded: each warms again outside any case.
    assert runners[INC].warms == runners[CH].warms == 2
    assert plain_runners[INC].warms == 1


def test_a_run_not_holding_the_machine_never_yields(monkeypatch, tmp_path, quiet, clock, polls):
    runners, log = _pair(monkeypatch, clock)
    _lease_mid_case(runners, INC, 1)
    R._execute(_args(tmp_path / "run", candidates=f"{INC},{CH}", stop_at=clock.now + 39.0))
    assert polls["n"] == 0 and log == [INC, CH] * 2


class _Eval:
    """evals.run in a thread, its case `gate_at` held open until the test lets it finish."""

    def __init__(self, monkeypatch, tmp_path, clock, gate_at=2, plan_s=None):
        self.runners, self.log = _pair(monkeypatch, clock)
        self.go, self.inside = threading.Event(), threading.Event()
        runner = self.runners[INC]
        gen = runner.generate

        def generate(case):
            if len(runner.ran) + 1 == gate_at:
                self.inside.set()
                assert self.go.wait(30)
            return gen(case)
        runner.generate = generate
        self.out = tmp_path / "run"
        args = _args(self.out, candidates=f"{INC},{CH}", stop_at=clock.now + 59.0,
                     plan_s=plan_s and [plan_s, plan_s])
        self.rc = None
        self.thread = threading.Thread(target=lambda: setattr(self, "rc", R._execute(args)), daemon=True)

    def __enter__(self):
        self.thread.start()
        assert self.inside.wait(30)
        return self

    def __exit__(self, *exc):
        self.go.set()
        self.thread.join(30)


def _delegating(monkeypatch, eval_):
    """busy() names the eval while its thread runs; the lane model is not resident."""
    monkeypatch.setattr(delegate, "busy", lambda: "eval for 1s (pid 1)" if eval_.thread.is_alive() else "")
    monkeypatch.setattr(delegate, "loaded", lambda where, **k: False)
    monkeypatch.setattr(exclusive, "holder", lambda: {})
    monkeypatch.setattr(pressure, "sample", lambda *a, **k: pressure.Pressure(level=pressure.NORMAL))


def test_a_delegation_takes_the_lease_the_eval_yields_after_its_case_and_resumes_after_the_grace(
        fake, monkeypatch, tmp_path, quiet, clock, held, polls):  # noqa: F811
    monkeypatch.setattr(serve_lease, "GRACE_S", 0.3)
    answered = {}
    from harness import completion
    sent = completion.complete_full

    def answer(*a, **k):
        ev.log.append("ANSWER")
        return sent(*a, **k)
    monkeypatch.setattr(completion, "complete_full", answer)
    with _Eval(monkeypatch, tmp_path, clock) as ev:
        _delegating(monkeypatch, ev)
        asked = threading.Thread(target=lambda: answered.update(
            delegate.complete("code", "write add", delegated=True)))
        asked.start()
        _until(lambda: serve_lease.holders(), "the delegation takes the lease")
        assert serve_lease.holders()[0]["state"] == serve_lease.WAITING
        # Nothing loads under the case in flight.
        assert fake.seen == []
        ev.go.set()
        asked.join(30)
        assert answered["text"] and len(fake.seen) == 1
        assert answered["serve_wait_s"] > 0
        ev.thread.join(30)
    # The eval finished its case, answered nothing beside a case, and took up the paired order where it stopped.
    assert ev.log == [INC, CH, INC, "ANSWER", CH, INC, CH]
    assert ev.rc == watch.PAUSED
    _, rows = watch.read(ev.out)
    assert len(rows) == 6 and [r["wall_s"] for r in rows] == [10.0] * 6
    assert watch.read_progress(ev.out)["serving_yields"]["count"] == 1
    conn = ms.connect()
    try:
        waits = [dict(r) for r in conn.execute("SELECT lane, outcome, waited_s FROM serve_waits")]
    finally:
        conn.close()
    assert [(w["lane"], w["outcome"]) for w in waits] == [("code", serve_lease.ANSWERED)]
    assert waits[0]["waited_s"] > 0


def _serve_waits():
    conn = ms.connect()
    try:
        return [dict(r) for r in conn.execute("SELECT lane, outcome, cut, in_flight, call_id FROM serve_waits")]
    finally:
        conn.close()


def test_a_case_that_cannot_be_cut_refuses_the_delegation_naming_the_holder_and_the_case_and_the_eval_keeps_it(
        fake, monkeypatch, tmp_path, quiet, clock, held, polls):  # noqa: F811
    monkeypatch.setattr(serve_lease, "CUT_WAIT_S", 0.3)
    # Planned far under what the held case takes, it is past its plan: the delegation asks for a cut at once.
    with _Eval(monkeypatch, tmp_path, clock, plan_s=0.01) as ev:
        _delegating(monkeypatch, ev)
        with pytest.raises(delegate.Refused) as got:
            delegate.complete("code", "write add", delegated=True)
        why = str(got.value)
        assert "busy with eval for 1s (pid 1)" in why
        assert f"of {INC}" in why and "past its plan" in why and "asked to cut that case" in why
        assert fake.seen == [] and serve_lease.holders() == []
    # This runner never streams, so nothing was cut: the case finished and kept its row.
    assert ev.rc == watch.PAUSED and polls["n"] == 0
    assert len(watch.read(ev.out)[1]) == 6
    assert watch.read_progress(ev.out)["serving_yields"]["cut"] == []
    assert [(w["outcome"], w["cut"]) for w in _serve_waits()] == [(serve_lease.REFUSED, 1)]


def _endless():
    """A reply that reasons forever, one token a chunk, as llama-server streams it."""
    import json
    for _ in range(20000):
        yield "data: " + json.dumps({"choices": [{"delta": {"reasoning_content": "x"}}]})
        time.sleep(0.002)
    raise AssertionError("the stream was never cut")


def test_a_streaming_case_past_the_bound_is_cut_run_again_after_the_yield_and_never_charged(
        fake, monkeypatch, tmp_path, quiet, clock, held, polls):  # noqa: F811
    from harness import completion
    monkeypatch.setattr(serve_lease, "WAIT_S", 0.3)
    monkeypatch.setattr(serve_lease, "GRACE_S", 0.3)
    runners, log = _pair(monkeypatch, clock)
    runner, inside, tried = runners[INC], threading.Event(), []
    gen = runner.generate

    def generate(case):
        if len(runner.ran) == 1 and not tried:
            tried.append(case.id)
            inside.set()
            completion.assemble(_endless(), time.perf_counter(), 600.0)
        return gen(case)
    runner.generate = generate
    sent = completion.complete_full

    def answer(*a, **k):
        log.append("ANSWER")
        return sent(*a, **k)
    monkeypatch.setattr(completion, "complete_full", answer)
    out = tmp_path / "run"
    result = {}
    thread = threading.Thread(target=lambda: result.update(rc=R._execute(
        _args(out, candidates=f"{INC},{CH}", stop_at=clock.now + 59.0))), daemon=True)
    thread.start()
    assert inside.wait(30)
    ev = type("E", (), {"thread": thread})
    _delegating(monkeypatch, ev)
    got = delegate.complete("code", "write add", delegated=True)
    thread.join(30)
    assert got["text"] and got["serve_wait_s"] > 0
    # The cut case left no row and no log line; it ran again, whole, after the delegation answered.
    assert log == [INC, CH, "ANSWER", INC, CH, INC, CH]
    _, rows = watch.read(out)
    assert [(r["candidate"], r["case_id"]) for r in rows][2] == (INC, tried[0])
    assert [r["wall_s"] for r in rows] == [10.0] * 6 and all(r["passed"] is not None for r in rows)
    assert not any(r.get("failure_class") == "harness_error" for r in rows)
    cut = watch.read_progress(out)["serving_yields"]["cut"]
    assert [(c["candidate"], c["case"]) for c in cut] == [(INC, tried[0])]
    waits = _serve_waits()
    assert [(w["outcome"], w["cut"]) for w in waits] == [(serve_lease.ANSWERED, 1)]
    assert waits[0]["call_id"] == got["call_id"]


def test_a_stream_is_cut_when_its_predicate_says_so():
    from harness import completion
    seen = []
    with completion.cutting(lambda: len(seen) > 3), pytest.raises(completion.ServingCut) as got:
        completion.assemble((seen.append(1) or line for line in _endless()), time.perf_counter(), 600.0)
    assert got.value.failure_class == "harness_error" and len(seen) == 4


def test_a_resident_model_answers_at_once_beside_the_case_in_flight_and_both_are_flagged(
        fake, monkeypatch, tmp_path, quiet, clock, held, polls):  # noqa: F811
    monkeypatch.setattr(serve_lease, "GRACE_S", 0.3)
    with _Eval(monkeypatch, tmp_path, clock) as ev:
        _delegating(monkeypatch, ev)
        monkeypatch.setattr(delegate, "loaded", lambda where, **k: True)
        got = delegate.complete("code", "write add", delegated=True)
        assert got["text"] and "serve_wait_s" not in got
        assert f"of {INC}" in got["co_tenant"]
    _, rows = watch.read(ev.out)
    shared = [i for i, r in enumerate(rows) if (r.get("metrics") or {}).get("co_tenancy")]
    assert shared == [2]
    assert any("answered beside this case" in w for w in rows[2]["warnings"])
    assert [w["outcome"] for w in _serve_waits()] == [serve_lease.BESIDE]


def test_the_report_holds_decide_and_extract_to_the_p95_target():
    from harness import delegations
    conn = ms.connect()
    try:
        now = time.time()
        for i in range(20):
            delegations.record(conn, f"d{i}", "decide", seconds=1.0, at=now)
            delegations.record(conn, f"e{i}", "extract", seconds=1.0, at=now)
            delegations.record(conn, f"c{i}", "code", seconds=50.0, at=now)
        # A few decide answers waited on an eval: their whole latency puts the p95 past the target.
        for i in range(2):
            conn.execute("INSERT INTO serve_waits (at, lane, holder, waited_s, outcome, call_id) "
                         "VALUES (?, 'decide', 'eval', 30.0, 'answered', ?)", (now, f"d{i}"))
        conn.commit()
        got = {w["lane"]: w for w in serve_lease.waits(conn, 3600)}
    finally:
        conn.close()
    assert got["decide"]["p95_s"] == 31.0 and got["decide"]["over_target"]
    assert got["extract"]["p95_s"] == 1.0 and not got["extract"]["over_target"]
    assert got["code"]["target_s"] is None and not got["code"]["over_target"]
    assert got["decide"]["waits"] == 2 and got["extract"]["waits"] == 0


def test_a_program_call_takes_no_lease(fake, monkeypatch):  # noqa: F811
    delegate.complete("code", "write add")
    assert serve_lease.holders() == []
    delegate.complete("code", "write add", delegated=True)
    assert [h["state"] for h in serve_lease.holders()] == [serve_lease.IDLE]


def test_a_lane_the_interactive_server_pins_takes_no_lease(fake, monkeypatch):  # noqa: F811
    from harness import interactive
    monkeypatch.setattr(interactive, "upstream", lambda where: (where.base, where.model))
    delegate.complete("code", "write add", delegated=True)
    assert serve_lease.holders() == []


def test_local_complete_over_paths_is_work_and_takes_the_lease(fake, monkeypatch):  # noqa: F811
    from harness import purpose
    # ask.ask and spans.ask_file tag their calls work for a delegation without making each one a delegations row.
    delegate.complete("code", "write add", tag=purpose.WORK)
    assert [h["state"] for h in serve_lease.holders()] == [serve_lease.IDLE]


def test_no_queued_job_starts_while_a_lease_is_held():
    sample = lambda: pressure.Pressure(level=pressure.NORMAL)  # noqa: E731
    assert wq.gate(sample)[0]
    lease = serve_lease.Lease("code", "a code delegation")
    ok, why = wq.gate(sample)
    assert not ok and "a code delegation" in why
    lease.idle()
    assert not wq.gate(sample)[0]
    lease.drop()
    assert wq.gate(sample)[0]


def test_an_idle_lease_lapses_after_its_grace():
    lease = serve_lease.Lease("code", "a code delegation")
    lease.idle()
    until = lease.record["until"]
    assert serve_lease.held(until - 1)
    assert serve_lease.held(until + 1) == "" and not lease.path.exists()


def _yielding(now, since, done_ago, yielded_before):
    return {"pid": 1, "started_at": now - 3 * 3600, "last_progress_at": now - done_ago,
            "planned_s_per_case": {"a": 10.0}, "done": 3, "total": 9,
            "serving_yields": {"count": 2, "seconds": yielded_before + 0.0, "since_case_s": yielded_before + 0.0,
                               "yielding_since": now - since, "to": "a code delegation"}}


def test_the_watchdog_never_counts_a_yield_against_no_progress_or_long_run():
    now = 2_000_000.0
    run = _yielding(now, since=wd.STALL_S, done_ago=wd.STALL_S + 60, yielded_before=120)
    s = wd.Subject("eval", "eval 1", "an evals.run", pid=1, elapsed_s=wd.LONG_RUN_EVAL_S + 600, progress=run)
    w = wd.World(now=now, top=[s], evals=[s])
    assert wd._no_progress(w) == []
    assert [f.criterion for f in wd._long_run(w)] == []
    # The same run with no yield is stalled, and past its limit.
    bare = {k: v for k, v in run.items() if k != "serving_yields"}
    s2 = wd.Subject("eval", "eval 1", "an evals.run", pid=1, elapsed_s=wd.LONG_RUN_EVAL_S + 600, progress=bare)
    w2 = wd.World(now=now, top=[s2], evals=[s2])
    assert [f.criterion for f in wd._no_progress(w2)] == ["no_progress"]
    assert [f.criterion for f in wd._long_run(w2)] == ["long_run"]


def test_a_yield_is_a_wait_no_measuring_scope_counts(monkeypatch, clock, polls):
    from harness import completion
    eye = watch.Watch(yielder=serve_lease.Yielder(""))
    lease = serve_lease.Lease("code", "a code delegation")
    polls["on"] = lambda n: n == 2 and lease.drop()
    with completion.measuring() as waits:
        assert eye.before("k", "c1") is True
    assert waits.within(kind=watch.SERVING_YIELD) > 0
    assert eye.before("k", "c2") is False
