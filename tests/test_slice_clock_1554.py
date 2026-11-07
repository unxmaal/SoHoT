"""A look slice counts from the lock, an empty slice is not the end of a run, and a resume takes its own budget. #1554, #1553."""
import contextlib
import json
import time

from evals import run as R
from evals import watch
from harness import exclusive, looks
from harness.commands import measure as measure_cmd
from tests.test_repo_looks_1353 import Slices, _measure, priced
from tests.test_resume_813 import _pauses, _rows, world  # noqa: F401

WAIT = 954.0


def _stop_seen(monkeypatch, argv, wait: float) -> tuple[float, float]:
    """(the stop time evals.run pauses at, when it held the machine) for `argv` after `wait` s behind the lock."""
    now = [time.time()]
    monkeypatch.setattr(watch, "clock", lambda: now[0])
    monkeypatch.setattr(R.env, "guard", lambda: None)

    @contextlib.contextmanager
    def held(kind, announce=None, deadline_s=None, **kw):
        now[0] += wait
        yield True

    monkeypatch.setattr(exclusive, "held", held)
    seen = []
    monkeypatch.setattr(R, "_execute", lambda args: seen.append(args.stop_at) or 0)
    R._main(R.parse_args(argv[argv.index("evals.run") + 1:]))
    return seen[0], now[0]


def _first_argv(monkeypatch, **kw):
    fake = Slices([_rows(6, gained=1, lost=1)])
    monkeypatch.setattr(measure_cmd, "_launch", fake)
    _measure(**kw)
    return fake.argvs[0]


def test_an_eval_that_waits_for_the_lock_still_gets_a_full_look_interval(monkeypatch, world):
    argv = _first_argv(monkeypatch)
    stop, holding = _stop_seen(monkeypatch, argv, WAIT)
    assert stop - holding >= looks.LOOK_INTERVAL_S - 1


def test_a_lock_wait_never_carries_a_slice_past_the_budget(monkeypatch, world):
    argv = _first_argv(monkeypatch, power_budget_min=60)
    after = time.time()
    stop, holding = _stop_seen(monkeypatch, argv, 3000.0)
    assert stop <= after + 3600 + 1 and stop - holding < looks.LOOK_INTERVAL_S


def test_a_slice_that_stops_on_time_with_no_new_rows_and_budget_left_takes_the_next_slice(monkeypatch, world):
    fake = Slices([[], _rows(6, gained=1, lost=1)])
    monkeypatch.setattr(measure_cmd, "_launch", fake)
    _measure()
    assert len(fake.argvs) >= 2 and "--resume" in fake.argvs[1]


def test_two_slices_in_a_row_with_no_new_rows_pause_and_say_so(monkeypatch, world):
    fake = Slices([_rows(6, gained=1, lost=1)])
    monkeypatch.setattr(measure_cmd, "_launch", fake)
    assert _measure() == watch.PAUSED
    assert len(fake.argvs) == 1 + measure_cmd.IDLE_SLICES
    conn = world()
    try:
        (p,) = _pauses(conn)
    finally:
        conn.close()
    assert p["state"] == "paused" and f"{measure_cmd.IDLE_SLICES} look slices in a row ran no case" in p["why"]


def test_a_resumed_run_stops_at_this_invocations_budget_not_the_stored_one(monkeypatch, world):
    priced(monkeypatch, 1.0)
    monkeypatch.setattr(measure_cmd, "_launch", Slices([_rows(6, gained=1, lost=1)]))
    _measure(power_budget_min=1)
    conn = world()
    try:
        (p,) = _pauses(conn)
    finally:
        conn.close()
    assert json.loads(p["plan"])["budget_s"] == 60
    fake = Slices([_rows(12, gained=1, lost=1)])
    monkeypatch.setattr(measure_cmd, "_launch", fake)
    before = time.time()
    _measure(power_budget_min=120)
    argv = fake.argvs[0]
    assert "--resume" in argv
    assert float(argv[argv.index("--stop-at") + 1]) >= before + 7200 - 2
    assert float(argv[argv.index("--stop-after") + 1]) == looks.LOOK_INTERVAL_S


def test_a_slice_shorter_than_one_planned_case_is_not_launched_and_says_why(monkeypatch, world, capsys):
    priced(monkeypatch, 300.0)
    fake = Slices([_rows(6, gained=1, lost=1)])
    monkeypatch.setattr(measure_cmd, "_launch", fake)
    assert _measure(power_budget_min=5) == 0
    assert fake.argvs == []
    assert "not launched, its slice ends in 300s, under one planned case of each side (600s)" in capsys.readouterr().out
