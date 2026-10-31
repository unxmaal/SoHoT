"""A machine-wide day clearance lets any job run past the watchdog's day limits and night starts until that day's end, and each skip is recorded. #1112."""
import json
import sys
from datetime import datetime

import pytest

from harness import cli, day_clear, morning
from harness import memory_store as ms
from harness import watchdog as wd
from harness import workqueue as wq
from harness.commands import morning as morning_cmd
from tests.test_watchdog import EVAL, NIGHT, NOON, Fake, Hand, P, ids, run

SAID = "owner: clear to run jobs all day"


@pytest.fixture(autouse=True)
def _day_8_to_21(monkeypatch):
    monkeypatch.setattr(wd, "DAY_START_HOUR", 8)
    monkeypatch.setattr(wd, "DAY_END_HOUR", 21)


def at(day, hour, minute=0):
    return datetime(2026, 10, day, hour, minute).timestamp()


class Cleared(Fake):
    def __init__(self, *a, clearance=None, **k):
        super().__init__(*a, **k)
        self._clearance = clearance

    def clearance(self, conn, now):
        return self._clearance


def clearance(until=None):
    return {"id": 1, "said": SAID, "cleared_at": NOON - 3600, "revoked_at": None,
            "until": day_clear.day_end(NOON) if until is None else until}


#: The GPU lock, held by job 0134's evals.run. #1370.
GPU = {"kind": "eval", "pid": 510, "pgid": 510}


def two_jobs(tmp_path, elapsed, c=None, progress=()):
    """Queue jobs 0134 (group 500, its evals.run holding the GPU lock) and 0135 (group 600, another command)."""
    return Cleared(tmp_path, procs=[P(500, 400, 500, elapsed, "uv run python -m evals.run --modality repo"),
                                    P(510, 500, 510, elapsed, EVAL),
                                    P(600, 400, 600, elapsed, "uv run soh something")],
                   jobs={"0134": 500, "0135": 600}, progress=progress, clearance=c, lock=GPU)


def judged(fake, now):
    found, _ = wd.judge(wd.observe(fake, None, now))
    return found


def test_a_clearance_lets_every_job_past_both_day_limits_and_names_each_skip(tmp_path):
    found = judged(two_jobs(tmp_path, max(d for _, d in wd.long_run_limits().values()) + 60, clearance()), NOON)
    assert ids(found, "daytime_gpu") == [] and ids(found, "long_run") == []
    skips = [(f.subject.key, f.evidence["skipped"]) for f in found if f.criterion == "day_clear"]
    assert sorted(skips) == [("job 0134", "daytime_gpu"), ("job 0134", "long_run"), ("job 0135", "long_run")]
    assert all(f.evidence["said"] == SAID for f in found if f.criterion == "day_clear")


def test_without_a_clearance_the_day_limit_pauses_the_gpu_holder_only(tmp_path):
    found = judged(two_jobs(tmp_path, wd.DAYTIME_GPU_S + 60), NOON)
    assert ids(found, "daytime_gpu") == ["job 0134"] and ids(found, "day_clear") == []


def test_a_clearance_never_lifts_the_night_limit(tmp_path):
    found = judged(two_jobs(tmp_path, max(n for n, _ in wd.long_run_limits().values()) + 60, clearance(until=NIGHT + 3600)), NIGHT)
    assert ids(found, "long_run") == ["job 0134", "job 0135"] and ids(found, "day_clear") == []


def test_a_stuck_job_is_still_caught_under_a_clearance(tmp_path):
    stuck = run(510, last=NOON - wd.STALL_S - 60, now=NOON)
    found = judged(two_jobs(tmp_path, wd.DAYTIME_GPU_S + 60, clearance(), progress=[stuck]), NOON)
    assert ids(found, "no_progress") == ["eval pgid 510"] and ids(found, "daytime_gpu") == []


def test_the_store_clearance_expires_at_day_end_and_revoke_ends_it(tmp_path):
    conn = ms.connect()
    got = day_clear.clear(conn, SAID, now=at(22, 11, 30))
    assert datetime.fromtimestamp(got["until"]) == datetime(2026, 10, 22, 21)
    assert day_clear.active(conn, at(22, 20, 59))["said"] == SAID
    assert day_clear.active(conn, at(22, 21)) is None and day_clear.active(conn, at(23, 12)) is None
    assert day_clear.revoke(conn, now=at(22, 12))["revoked_at"] == at(22, 12)
    assert day_clear.active(conn, at(22, 12, 1)) is None and day_clear.revoke(conn, now=at(22, 12, 2)) is None
    with pytest.raises(ValueError, match="day hours ended"):
        day_clear.clear(conn, SAID, now=at(22, 21, 30))
    with pytest.raises(ValueError, match="who gave it"):
        day_clear.clear(conn, "  ", now=at(22, 11))


def test_a_wake_reads_the_store_clearance_records_each_skip_and_at_most_notifies(tmp_path):
    conn = ms.connect()
    fake = Fake(tmp_path, procs=[P(500, 400, 500, wd.DAYTIME_GPU_S + 60, "uv run soh a")], jobs={"0134": 500},
                lock={"kind": "external", "pid": 500, "pgid": 500})
    day_clear.clear(conn, SAID, now=NOON - 60)
    hand = Hand()
    for i in range(wd.ESCALATE_AFTER + 2):
        wd.wake(conn, fake, hand, act=True, now=NOON + i * 300, say=lambda *_: None)
    rows = [dict(r) for r in conn.execute("SELECT * FROM watchdog_actions ORDER BY id")]
    assert {r["criterion"] for r in rows} == {"day_clear"} and len(rows) == wd.ESCALATE_AFTER + 2
    assert [r["action"] for r in rows] == [wd.NOTE] * wd.ESCALATE_AFTER + [wd.NOTIFY] * 2
    assert json.loads(rows[0]["evidence"])["said"] == SAID
    day_clear.revoke(conn, now=NOON + 3000)
    wd.wake(conn, fake, hand, act=True, now=NOON + 3300, say=lambda *_: None)
    last = dict(conn.execute("SELECT * FROM watchdog_actions ORDER BY id DESC LIMIT 1").fetchone())
    assert (last["criterion"], last["action"]) == ("daytime_gpu", wd.NOTIFY), "nothing to pause through: told"


@pytest.mark.gauntlet("state-is-whichever-row-came-last", site="harness/day_clear.py:active")
def test_a_second_clearance_is_revoked_with_the_first_and_shows_the_latest_text():
    conn = ms.connect()
    day_clear.clear(conn, "owner: morning", now=at(22, 9))
    day_clear.clear(conn, SAID, now=at(22, 10))
    assert day_clear.active(conn, at(22, 11))["said"] == SAID
    day_clear.revoke(conn, now=at(22, 12))
    assert day_clear.active(conn, at(22, 12, 1)) is None


def test_a_clearance_lifts_a_night_start_but_never_a_clock_time(tmp_path):
    conn = ms.connect()
    py = [sys.executable, "-c", "pass"]
    night = wq.add(py, title="night", not_before=at(22, 21), night=True, conn=conn)
    clock = wq.add(py, title="clock", not_before=at(22, 16, 45), conn=conn)
    assert wq.ready(conn, now=at(22, 12)) == []
    day_clear.clear(conn, SAID, now=at(22, 11))
    assert [j["id"] for j in wq.ready(conn, now=at(22, 12))] == [night["id"]]
    assert clock["night_gate"] is False and night["night_gate"] is True
    day_clear.revoke(conn, now=at(22, 12, 1))
    assert wq.ready(conn, now=at(22, 12, 2)) == []


def test_the_cli_clears_shows_and_revokes(capsys, monkeypatch):
    monkeypatch.setattr(day_clear.time, "time", lambda: at(22, 11, 30))
    monkeypatch.setattr(wq.time, "time", lambda: at(22, 11, 30))
    assert cli.main(["day", "status"]) == 0
    assert "no day clearance" in capsys.readouterr().out
    assert cli.main(["day", "clear", SAID, "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["clearance"]["said"] == SAID
    assert cli.main(["jobs", "list"]) == 0
    shown = capsys.readouterr()
    assert f"until 21:00: {SAID}" in shown.out + shown.err
    assert cli.main(["day", "revoke"]) == 0
    assert "revoked at 11:30" in capsys.readouterr().out
    assert cli.main(["day", "clear"]) != 0


def test_morning_shows_the_clearance_once_not_every_skip(tmp_path):
    conn = ms.connect()
    fake = Fake(tmp_path, procs=[P(500, 400, 500, wd.DAYTIME_GPU_S + 60, "uv run soh a")], jobs={"0134": 500},
                lock={"kind": "external", "pid": 500, "pgid": 500})
    day_clear.clear(conn, SAID, now=NOON - 60)
    for i in range(3):
        wd.wake(conn, fake, Hand(), act=True, now=NOON + i * 300, say=lambda *_: None)
    assert morning.watchdog(conn, NOON - 120) == []
    got = morning.clearances(conn, NOON - 120, NOON + 900)
    assert [(c["said"], c["skips"]) for c in got] == [(SAID, 3)]
    lines = [x for x in morning_cmd.render({**_report(), "clearances": got}) if x.startswith("cleared")]
    assert len(lines) == 1 and SAID in lines[0] and "3 day limit(s)" in lines[0]


def _report():
    return {"since": NOON, "sweep": {"loop": None, "screened": {}, "measured": {"runs": [], "verdicts": {}},
                                     "paused": [], "stopped": [], "settled": {"verdicts": {}, "adopted": []}},
            "watchdog": [], "ci": {"available": False, "why": "-"}, "ledger": None, "stale": [],
            "deploy": {"available": False, "why": "-"}}


OLD_JOBS = """
CREATE TABLE jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL DEFAULT '', kind TEXT NOT NULL DEFAULT 'command',
    output TEXT NOT NULL DEFAULT '', priority INTEGER NOT NULL DEFAULT 0, argv TEXT NOT NULL DEFAULT '[]',
    cwd TEXT NOT NULL DEFAULT '', state TEXT NOT NULL DEFAULT 'pending', created_at REAL NOT NULL,
    started_at REAL, finished_at REAL, rc INTEGER, log TEXT NOT NULL DEFAULT '', note TEXT NOT NULL DEFAULT '',
    requested_by TEXT NOT NULL DEFAULT '', machine_id INTEGER, not_before REAL);
"""


def test_a_schema_78_store_marks_pending_night_starts_and_leaves_clock_times(old_store):
    rows = "".join(f"INSERT INTO jobs (id, title, state, created_at, not_before) VALUES ({i}, '{t}', '{s}', 1.0, {nb});"
                   for i, t, s, nb in ((135, "night", "pending", at(22, 21)), (136, "clock", "pending", at(22, 23, 30)),
                                       (137, "done", "done", at(21, 21)), (138, "now", "pending", "NULL")))
    conn = ms.connect(old_store(78, rows, ddl=OLD_JOBS))
    try:
        got = {r["title"]: r["night_gate"] for r in conn.execute("SELECT title, night_gate FROM jobs")}
        assert got == {"night": 1, "clock": 0, "done": 0, "now": 0}
        assert conn.execute("SELECT COUNT(*) FROM day_clearances").fetchone()[0] == 0
    finally:
        conn.close()
