"""A run's pause says its kind beside its why; every reader decides on the kind, not the sentence's words. #1943."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from evals import watch
from harness import inventory_time as it
from harness import job_procs
from harness import memory_store as ms
from harness.commands import measure as measure_cmd
from tests.test_inventory_time_1152 import H, T0, _built, home  # noqa: F401
from tests.test_pause_813 import Ticking, _args, _run, clock, quiet  # noqa: F401
from tests.test_resume_813 import Eval, _measure, _pauses, _rows, _sweep, world  # noqa: F401

REWORDED = "the slice is over"
FT = "a-decision-read-back-out-of-a-sentence-the-code-wrote"


def _reworded(monkeypatch):
    """Every Stop sentence gets words put before it, as a later release might write them."""
    real = watch.Stop.__init__
    monkeypatch.setattr(watch.Stop, "__init__", lambda self, why, *a, **k: real(self, f"{REWORDED}: {why}", *a, **k))


# --- evals.run writes the kind and ends a queue item on it ------------------------

def test_a_stop_time_pause_writes_its_kind_and_keeps_the_old_sentence(monkeypatch, tmp_path, quiet, clock):
    out = tmp_path / "run"
    assert _run(monkeypatch, Ticking(clock), _args(out, stop_at=clock.now + 45.0)) == watch.PAUSED
    got = watch.read_progress(out)
    assert got[watch.PAUSE_KIND] == watch.STOP_TIME
    # An older release reads only the sentence, so it is unchanged.
    assert got["why"].startswith(watch.AT_STOP_TIME)


def test_a_reworded_stop_time_pause_still_ends_its_queue_item(monkeypatch, tmp_path, quiet, clock):
    _reworded(monkeypatch)
    ended = []
    monkeypatch.setattr(job_procs, "item_ended", lambda *a, **k: ended.append(1))
    out = tmp_path / "run"
    assert _run(monkeypatch, Ticking(clock), _args(out, stop_at=clock.now + 45.0, queue_item=True)) == watch.PAUSED
    got = watch.read_progress(out)
    assert got["why"].startswith(REWORDED) and got[watch.PAUSE_KIND] == watch.STOP_TIME
    assert ended == [1]


def test_a_reworded_request_writes_requested_and_ends_no_queue_item(monkeypatch, tmp_path, quiet, clock):
    _reworded(monkeypatch)
    ended = []
    monkeypatch.setattr(job_procs, "item_ended", lambda *a, **k: ended.append(1))
    out = tmp_path / "run"
    runner = Ticking(clock, on_case=lambda n: n == 2 and (out / watch.PAUSE_FILE).touch())
    assert _run(monkeypatch, runner, _args(out, queue_item=True, stop_at=clock.now + 1e6)) == watch.PAUSED
    assert watch.read_progress(out)[watch.PAUSE_KIND] == watch.REQUESTED and ended == []


def test_each_stop_carries_its_kind():
    assert watch.Stop("x").kind == watch.REQUESTED
    assert watch.Stop("x", watch.STOP_TIME).kind == watch.STOP_TIME
    assert watch.Deferred("x", "memory").kind == watch.DEFERRED
    assert watch.Silent("x").kind == watch.SILENT_KIND


# --- progress.json: the kind, else an older release's sentence ----------------------

@pytest.mark.gauntlet(FT, site="evals/watch.py:pause_kind:why")
def test_the_kind_decides_and_an_older_progress_falls_back_to_its_sentence():
    assert watch.pause_kind({"why": "paused on request", watch.PAUSE_KIND: watch.STOP_TIME}) == watch.STOP_TIME
    assert watch.pause_kind({"why": f"{watch.AT_STOP_TIME}, 3 left", watch.PAUSE_KIND: ""}) == ""
    assert watch.pause_kind({"why": f"{watch.AT_STOP_TIME}, 3 case(s) left"}) == watch.STOP_TIME
    assert watch.pause_kind({"why": "paused on request (memory): x"}) == watch.DEFERRED
    assert watch.pause_kind({"why": "paused on request, 3 case(s) left"}) == watch.REQUESTED
    assert watch.pause_kind({}) == ""


def _between(out, kind, why):
    (out / watch.PROGRESS).write_text(json.dumps({"why": why, watch.PAUSE_KIND: kind}), encoding="utf-8")
    proc = SimpleNamespace(returncode=watch.PAUSED, timed_out=False)
    return measure_cmd._between_looks(proc, out, last=False, before=-1, idle=0)


def test_the_next_look_slice_runs_on_a_stop_time_kind_whatever_the_sentence(tmp_path):
    assert _between(tmp_path, watch.STOP_TIME, REWORDED)
    assert not _between(tmp_path, watch.REQUESTED, f"{watch.AT_STOP_TIME}, 3 case(s) left")


# --- the measure step: a request halts or squeezes the sweep ------------------------

def _paused_by(monkeypatch, kind, reason):
    fake = Eval(rows=_rows(5))

    def requested(argv, **kw):
        got = fake(argv, **kw)
        out = Path(argv[argv.index("--out") + 1])
        p = json.loads((out / watch.PROGRESS).read_text(encoding="utf-8"))
        (out / watch.PROGRESS).write_text(json.dumps({**p, "why": REWORDED, watch.PAUSE_KIND: kind}),
                                          encoding="utf-8")
        watch.ask_pause(out, reason)
        return got
    monkeypatch.setattr(measure_cmd, "_launch", requested)
    sweep = _sweep()
    _measure(sweep)
    return sweep


def test_a_reworded_request_still_halts_or_squeezes_the_sweep(monkeypatch, world):
    assert _paused_by(monkeypatch, watch.REQUESTED, "daytime_gpu").halted.startswith("paused at")
    assert _paused_by(monkeypatch, watch.DEFERRED, "memory").squeezed.startswith("paused at")
    neither = _paused_by(monkeypatch, watch.STOP_TIME, "daytime_gpu")
    assert neither.halted == "" and neither.squeezed == ""


def test_the_stored_pause_keeps_its_kind_on_its_look(monkeypatch, world):
    _paused_by(monkeypatch, watch.REQUESTED, "daytime_gpu")
    conn = world()
    try:
        (p,) = _pauses(conn)
    finally:
        conn.close()
    assert json.loads(p["looks"])[-1][watch.PAUSE_KIND] == watch.REQUESTED
    assert it._stop_time(p) is False


# --- the time account: a stop-time pause before #1509 is a day limit ----------------

def _plant_pause(conn, at, why, looks):
    conn.execute("INSERT INTO paused_runs (lane, incumbent, challenger, out, looks, state, why, machine_id, "
                 "paused_at) VALUES ('code', 'a', 'b', 'o', ?, 'done', ?, ?, ?)",
                 (json.dumps(looks), why, ms.remember_machine(conn), at))
    conn.commit()


def test_the_time_account_reads_a_stored_pause_by_its_kind_and_an_older_one_by_its_sentence(home):
    conn = ms.connect()
    try:
        _plant_pause(conn, T0 + 2 * H + 60, REWORDED, [{watch.PAUSE_KIND: watch.STOP_TIME}])
        _plant_pause(conn, T0 + 4 * H + 60, "paused at its stop time, 3 case(s) left", [])
    finally:
        conn.close()
    assert _built(home)["blocked"]["by_reason"].get("day_limit") == 2


@pytest.mark.gauntlet(FT, site="harness/inventory_time.py:_stop_time:why")
def test_a_stored_kind_outweighs_a_sentence_that_says_stop_time():
    at = it.CUTOVER_1509 - 2 * H
    hours = [{"hour": int(at // H) * H, "category": it.MEASUREMENT}]
    paused = [{"paused_at": at, "why": "said stop time, but asked",
               "looks": json.dumps([{watch.PAUSE_KIND: watch.REQUESTED}])}]
    assert "day_limit" not in it.blocked(hours, paused=paused)["by_reason"]


def test_a_stop_time_pause_after_1509_is_a_look_slice_not_a_day_limit():
    at = it.CUTOVER_1509 + 2 * H
    hours = [{"hour": int(at // H) * H, "category": it.MEASUREMENT}]
    paused = [{"paused_at": at, "why": REWORDED, "looks": json.dumps([{watch.PAUSE_KIND: watch.STOP_TIME}])}]
    assert "day_limit" not in it.blocked(hours, paused=paused)["by_reason"]
    before = [{**paused[0], "paused_at": it.CUTOVER_1509 - 2 * H}]
    hours = [{"hour": int((it.CUTOVER_1509 - 2 * H) // H) * H, "category": it.MEASUREMENT}]
    assert it.blocked(hours, paused=before)["by_reason"].get("day_limit") == 1
