"""The watchdog's time limits: the day end is its own, daytime_gpu judges the GPU lock's holder, a length limit pauses and never stops, long_run is per job kind. #1369-#1373."""
import json

import pytest

from harness import heartbeat, knobs
from harness import memory_store as ms
from harness import watchdog as wd
from tests.test_watchdog import EVAL, NIGHT, NOON, Fake, Hand, P, ids, run


def judged(fake, now):
    return wd.judge(wd.observe(fake, None, now))[0]


def two_jobs(tmp_path, elapsed, lock=None, progress=()):
    """Job 0007 (group 500) runs an evals.run (group 510); job 0008 (group 600) runs a helper (group 620) under it."""
    return Fake(tmp_path, procs=[P(500, 400, 500, elapsed, "uv run soh adopt --lane code --challenger x"),
                                 P(510, 500, 510, elapsed, "uv run python -m evals.run --modality code"),
                                 P(511, 510, 510, elapsed, EVAL),
                                 P(600, 400, 600, elapsed, "uv run python -m evals.analysis.demand replay"),
                                 P(620, 600, 620, elapsed, "uv run python helper.py")],
                jobs={"0007": 500, "0008": 600}, lock=lock, progress=progress)


def wakes(conn, fake, n, now=NOON):
    hand = Hand()
    for i in range(n):
        wd.wake(conn, fake, hand, act=True, now=now + i * 300, say=lambda *_: None)
    return hand, [dict(r) for r in conn.execute("SELECT * FROM watchdog_actions ORDER BY id")]


# --- #1369 the day end is the watchdog's own -------------------------------------------------------

def test_the_default_discover_hours_fall_outside_the_watchdog_day():
    day = range(wd.DAY_START_HOUR, wd.DAY_END_HOUR)
    assert heartbeat._default_hours() and all(h % 24 not in day for h in heartbeat._default_hours())


def test_moving_the_day_end_does_not_move_the_discover_hours(monkeypatch):
    before = heartbeat.discover_hours()
    monkeypatch.setattr(wd, "DAY_END_HOUR", 19)
    assert heartbeat.discover_hours() == before
    assert "DISCOVER_HOURS" in knobs.KNOBS["watchdog_day_end_hour"].note
    assert "fires at it" not in knobs.KNOBS["watchdog_day_end_hour"].note


# --- #1370 daytime_gpu judges the job that holds the GPU lock -----------------------------------------

def test_daytime_gpu_judges_only_the_job_whose_eval_holds_the_gpu_lock(tmp_path):
    held = {"kind": "eval", "pid": 511, "pgid": 510}
    assert ids(judged(two_jobs(tmp_path, wd.DAYTIME_GPU_S + 60, lock=held), NOON), "daytime_gpu") == ["job 0007"]
    assert ids(judged(two_jobs(tmp_path, wd.DAYTIME_GPU_S + 60, lock={}), NOON), "daytime_gpu") == []


def test_a_lock_held_by_any_descendant_of_a_job_is_that_job_s(tmp_path):
    held = {"kind": "external", "pid": 620, "pgid": 620}
    assert ids(judged(two_jobs(tmp_path, wd.DAYTIME_GPU_S + 60, lock=held), NOON), "daytime_gpu") == ["job 0008"]


def test_a_lock_held_by_something_not_ours_trips_no_job(tmp_path):
    held = {"kind": "image", "pid": 77, "pgid": 77}
    assert ids(judged(two_jobs(tmp_path, wd.DAYTIME_GPU_S + 60, lock=held), NOON), "daytime_gpu") == []


@pytest.mark.parametrize("lock", [None, {"kind": "unknown"}])
def test_an_unknown_holder_judges_every_job_as_before(tmp_path, lock):
    fake = two_jobs(tmp_path, wd.DAYTIME_GPU_S + 60)
    fake._lock = lock
    found = judged(fake, NOON)
    assert ids(found, "daytime_gpu") == ["job 0007", "job 0008"]
    assert all("cannot be told" in f.evidence["gpu"] for f in found if f.criterion == "daytime_gpu")


# --- #1371 a length limit pauses and never stops -------------------------------------------------------

def test_no_length_or_day_limit_ever_stops_a_job():
    for cid in ("long_run", "daytime_gpu", "day_clear"):
        c = wd.BY_ID[cid]
        assert wd.STOP not in (c.action, c.escalation), cid


def test_a_day_job_with_no_progress_file_is_notified_about_on_every_trip_and_never_stopped(tmp_path):
    conn = ms.connect()
    fake = two_jobs(tmp_path, wd.DAYTIME_GPU_S + 60, lock={"kind": "eval", "pid": 511, "pgid": 510})
    hand, rows = wakes(conn, fake, wd.ESCALATE_AFTER + 2)
    mine = [r for r in rows if r["criterion"] == "daytime_gpu"]
    assert [r["action"] for r in mine] == [wd.NOTIFY] * (wd.ESCALATE_AFTER + 2)
    assert [json.loads(r["evidence"]).get("unpausable") for r in mine if not r["escalated"]] == \
        [wd.UNPAUSABLE] * wd.ESCALATE_AFTER
    assert wd.STOP not in {a for a, _ in hand.done} and wd.PAUSE not in {a for a, _ in hand.done}


def test_a_day_job_with_a_progress_file_is_paused_then_notified_about(tmp_path):
    conn = ms.connect()
    fake = two_jobs(tmp_path, wd.DAYTIME_GPU_S + 60, lock={"kind": "eval", "pid": 511, "pgid": 510},
                    progress=[run(511, now=NOON, tmp=tmp_path)])
    hand, rows = wakes(conn, fake, wd.ESCALATE_AFTER + 1)
    mine = [(r["action"], r["escalated"]) for r in rows if r["criterion"] == "daytime_gpu"]
    assert mine == [(wd.PAUSE, 0)] * wd.ESCALATE_AFTER + [(wd.NOTIFY, 1)]


def test_a_dry_run_says_it_would_notify_when_there_is_nothing_to_pause(tmp_path):
    conn = ms.connect()
    fake = two_jobs(tmp_path, wd.DAYTIME_GPU_S + 60, lock={"kind": "eval", "pid": 511, "pgid": 510})
    said = []
    wd.wake(conn, fake, Hand(), act=False, now=NOON, say=said.append)
    assert any(line.startswith("[dry-run] would notify job 0007: daytime_gpu") for line in said)


# --- #1373 long_run notifies, then pauses ------------------------------------------------------------

def test_long_run_notifies_then_pauses_through_the_progress_file_and_never_stops(tmp_path):
    conn = ms.connect()
    fake = two_jobs(tmp_path, wd.LONG_RUN_ADOPT_S + 60, progress=[run(511, now=NIGHT, tmp=tmp_path)])
    hand, rows = wakes(conn, fake, wd.ESCALATE_AFTER + 1, now=NIGHT)
    mine = [(r["action"], r["escalated"]) for r in rows if r["criterion"] == "long_run" and r["subject"] == "job 0007"]
    assert mine == [(wd.NOTIFY, 0)] * wd.ESCALATE_AFTER + [(wd.PAUSE, 1)]
    other = [r["action"] for r in rows if r["criterion"] == "long_run" and r["subject"] == "job 0008"]
    assert other == [wd.NOTIFY] * (wd.ESCALATE_AFTER + 1), "nothing to pause through: told, and it runs on"
    assert wd.STOP not in {a for a, _ in hand.done}


# --- #1372 a limit per job kind -----------------------------------------------------------------------

@pytest.mark.parametrize("kind, command", [
    ("confirm", "/x/.venv/bin/python -m harness.cli adopt --confirm 15807"),
    ("adopt", "uv run soh adopt --lane code --challenger llamacpp:x"),
    ("eval", "uv run python -m evals.run --modality pii --candidates pii-regex"),
    ("other", "uv run soh benchmarks --probe sohot-code"),
])
def test_a_job_s_kind_is_read_from_its_command(kind, command):
    assert wd.kind_of(wd.Subject("job", "job 1", "t", command=command)) == kind


def test_the_discover_agent_is_a_sweep_and_an_unowned_eval_an_eval():
    assert wd.kind_of(wd.Subject("discover", "discover pid 1", "t", command="/bin/bash serve-discover.sh")) == "sweep"
    assert wd.kind_of(wd.Subject("eval", "eval pgid 1", "t", command="python helper.py")) == "eval"


SUBJECTS = {"sweep": wd.Subject("discover", "d", "t", command="/bin/bash serve-discover.sh"),
            "confirm": wd.Subject("job", "j", "t", command="soh adopt --confirm 1"),
            "adopt": wd.Subject("job", "j", "t", command="soh adopt --lane code"),
            "eval": wd.Subject("eval", "e", "t", command="x"),
            "other": wd.Subject("job", "j", "t", command="soh fetch")}


@pytest.mark.parametrize("kind", wd.KINDS)
@pytest.mark.parametrize("day, want", [(False, 8 * 3600.0), (True, 2 * 3600.0)])
def test_every_kind_has_a_registered_knob_per_limit_defaulting_to_8_h_at_night_and_2_h_by_day(kind, day, want):
    name, value = wd.long_run_limit(SUBJECTS[kind], day)
    k = knobs.KNOBS[name]
    assert value == want == k.default() and k.unit == "s" and k.limit == name and want in k.values
    assert "store 2026-10-30" in k.note and name in wd.BY_ID["long_run"].knobs


def test_raising_one_kind_s_limit_lets_that_kind_run_on_while_another_still_trips(tmp_path, monkeypatch):
    elapsed = wd.LONG_RUN_ADOPT_S + 60
    monkeypatch.setattr(wd, "LONG_RUN_ADOPT_S", 12 * 3600.0)
    found = judged(two_jobs(tmp_path, elapsed), NIGHT)
    assert ids(found, "long_run") == ["job 0008"]
    f = next(f for f in found if f.criterion == "long_run")
    assert f.evidence["kind"] == "other" and f.evidence["limit"] == f"watchdog_long_run_other>{wd.LONG_RUN_OTHER_S:g}"


def test_a_clearance_lets_off_each_job_by_its_own_kind_s_day_limit(tmp_path, monkeypatch):
    from tests.test_day_clear_1112 import Cleared, clearance
    monkeypatch.setattr(wd, "LONG_RUN_DAY_ADOPT_S", 4 * 3600.0)
    base = two_jobs(tmp_path, wd.LONG_RUN_DAY_OTHER_S + 60)
    fake = Cleared(tmp_path, procs=base.procs, jobs=base.jobs, lock={}, clearance=clearance())
    skips = [(f.subject.key, f.evidence["skipped"]) for f in judged(fake, NOON) if f.criterion == "day_clear"]
    assert skips == [("job 0008", "long_run")]
