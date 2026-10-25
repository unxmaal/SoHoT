"""#775: a loop waiting behind a healthy lock holder reads running, from the holder's declared deadline or its beats."""
import contextlib
import json
import math
import time

import pytest

from evals import watch
from harness import completion, exclusive, gateway_switch, ramp, throughput
from harness import heartbeat as hb
from harness import sweep_check as sc
from tests.test_cli_rubric import home  # noqa: F401
from tests.test_sweep_check_1062 import AT_22, START, beat, judge, unit

WAITING = "waiting for eval for 1s (pid 7) to finish"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv(exclusive.HELD_ENV, raising=False)


def _holder(**record):
    exclusive.holder_path().write_text(json.dumps({"kind": "eval", "pid": 7, "since": START, **record}),
                                       encoding="utf-8")


def _declared(monkeypatch):
    """exclusive.held that records what each holder declares, and holds nothing."""
    seen = []

    @contextlib.contextmanager
    def held(kind, announce=None, **kw):
        seen.append({"kind": kind, **kw})
        yield False
    monkeypatch.setattr(exclusive, "held", held)
    return seen


def test_the_sweep_check_reads_a_loop_behind_a_beating_holder_as_running():
    # The 2026-10-24 02:00 shape: the loop waited 1h 47m behind a queued evals.run that was still working.
    b = {**beat(updated=AT_22 - 6420), "waiting": WAITING}
    _holder(beat=AT_22 - 60)
    assert judge(unit("running"), b)["verdict"] == sc.RUNNING
    _holder(beat=AT_22 - 6420)
    assert judge(unit("running"), b)["verdict"] == sc.STALLED


def test_the_heartbeat_reads_a_loop_behind_a_beating_holder_as_running(monkeypatch):
    clock = {"t": 1_000_000.0}
    monkeypatch.setattr(hb, "clock", lambda: clock["t"])
    hb.start(lane="repo", total=10)
    hb.beat("measure", step=10, candidate="org/model")
    hb.expect(None, waiting=WAITING)
    clock["t"] += hb.STALL_S + 600
    _holder(beat=clock["t"] - 60)
    assert hb.status(hb.read(), alive=lambda pid: True) == "running"
    _holder(beat=clock["t"] - hb.STALL_S - 1)
    assert hb.status(hb.read(), alive=lambda pid: True) == "stalled"


def test_a_loop_that_is_not_waiting_ignores_the_holders_beat(monkeypatch):
    clock = {"t": 1_000_000.0}
    monkeypatch.setattr(hb, "clock", lambda: clock["t"])
    hb.start(lane="repo", total=10)
    hb.beat("measure", step=10, candidate="org/model")
    clock["t"] += hb.STALL_S + 600
    _holder(beat=clock["t"] - 60)
    assert hb.status(hb.read(), alive=lambda pid: True) == "stalled"


def test_every_case_an_eval_finishes_beats_its_lock(tmp_path):
    progress = watch.Progress(tmp_path, watch.Watch(), {}, 2, 0)
    with exclusive.held("eval"):
        assert "beat" not in exclusive.holder()
        before = time.time()
        progress.case_done()
        assert exclusive.holder()["beat"] >= before


def test_a_child_of_the_holder_beats_its_parents_record(monkeypatch):
    with exclusive.held("eval"):
        exclusive.holder_path().write_text(json.dumps({"kind": "eval", "pid": 1, "since": START}),
                                           encoding="utf-8")
        exclusive.beat()
        assert exclusive.holder()["pid"] == 1 and exclusive.holder()["beat"] > START


def test_a_process_that_holds_no_lock_leaves_another_holders_record_alone():
    _holder()
    exclusive.beat()
    assert "beat" not in exclusive.holder()


def test_a_beat_after_the_holder_let_go_writes_no_record(monkeypatch):
    monkeypatch.setenv(exclusive.HELD_ENV, "1")
    exclusive.beat()
    assert exclusive.holder() == {}


def test_each_ramp_step_beats_its_lock():
    beats = []
    ramp.run(step_gb=1.0, settle_s=0.0, cap_gb=3.0, allocate=lambda gb: None, release=lambda: None,
             sample=lambda: type("P", (), {"free_pct": 50, "level": 1, "swapouts": 0, "wired_gb": 1.0})(),
             sleep=lambda s: None, available=lambda: 10.0, beat=lambda: beats.append(1))
    assert len(beats) == 3


def test_the_throughput_sweep_declares_its_bound_and_beats_each_request(monkeypatch):
    seen = _declared(monkeypatch)
    beats = []
    monkeypatch.setattr(exclusive, "beat", lambda: beats.append(1))
    throughput.sweep("m", ["t"] * 5, levels=(1, 2, 4), timeout=10.0, post=lambda p: {"usage": {}})
    want = max(10.0, completion.LOAD_TIMEOUT_S) + sum(math.ceil(5 / L) * 10.0 * L for L in (1, 2, 4))
    assert seen == [{"kind": "eval", "deadline_s": want}]
    assert throughput.deadline_s(5, (1, 2, 4), 10.0) == want
    assert len(beats) == 1 + 3 * 5


def test_measure_throughput_declares_the_sweep_it_runs(monkeypatch, tmp_path):
    from harness import cli
    seen = _declared(monkeypatch)
    level = {"concurrency": 1, "per_hour": 1.0, "p50_s": 1.0, "p95_s": 1.0, "errors": 0, "completion_tokens": 1}
    monkeypatch.setattr(throughput, "sweep", lambda *a, **k: [level])
    texts = tmp_path / "t.jsonl"
    texts.write_text('{"text": "a"}\n{"text": "b"}\n', encoding="utf-8")
    a = cli.build_parser().parse_args(["throughput", "--model", "eval-7b", "--texts", str(texts), "--timeout", "30",
                                       "--n", "2", "--levels", "1,2"])
    a.func(a)
    assert seen and seen[0]["deadline_s"] == throughput.deadline_s(2, (1, 2), 30.0)


def test_a_rubric_run_declares_candidates_times_items_times_the_request_timeout(home, monkeypatch):
    from harness import cli, knobs
    from harness import rubric_eval as rv
    seen = _declared(monkeypatch)
    _, root = home
    rv.record_label(root, "a", "fact")
    rv.record_label(root, "b", "no-fact")
    timeout = knobs.resolve("harness/rubric_eval.py:evaluate(timeout)")

    def evaluate(r, text, model, gw, post=None, timeout=timeout):
        return rv.Verdict(True, "fact", '{"verdict":"fact"}', "", 0.1)
    monkeypatch.setattr(rv, "evaluate", evaluate)
    assert cli.main(["rubric", "run", "demo", "--candidates", "m1,m2"]) == 0
    assert seen[0]["deadline_s"] == 2 * 2 * timeout


def test_a_default_read_through_a_stand_in_without_that_parameter_is_the_sources(monkeypatch):
    from harness import knobs
    from harness import rubric_eval as rv
    want = knobs.resolve("harness/rubric_eval.py:evaluate(timeout)")
    monkeypatch.setattr(rv, "evaluate", lambda r, text, model, gw, post=None: None)
    assert knobs.resolve("harness/rubric_eval.py:evaluate(timeout)") == want == 300.0


def test_a_gateway_switch_declares_every_retry_of_wait_drain_and_serve(monkeypatch):
    seen = _declared(monkeypatch)
    monkeypatch.setattr(gateway_switch, "switch", lambda **kw: [])
    gateway_switch.main(["--max-wait-s", "600"])
    g = gateway_switch
    want = g.RETRIES * (600 + g.DRAIN_S + g.SERVE_WAIT_S) + sum(g.BACKOFF_S * 2 ** (k - 1) for k in range(1, g.RETRIES))
    assert seen == [{"kind": "external", "deadline_s": want}]
    assert want > hb.STALL_S
