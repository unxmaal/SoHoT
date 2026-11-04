"""`soh morning` says why a wanted lane got no measure run: no challenger waiting, no reverify queued, or what was. #1533."""
from __future__ import annotations

from datetime import datetime

import pytest

from harness import lanes, morning, reverify
from harness import memory_store as ms
from harness.commands import morning as morning_cmd

NOW = datetime(2026, 11, 4, 6, 30).timestamp()
SINCE = NOW - 18 * 3600
NIGHT = datetime(2026, 11, 3, 21, 0).timestamp()


def _store():
    conn = ms.connect()
    conn.execute("INSERT INTO runs (path, lane, tier, recorded_at) VALUES ('r-image','image','measure',?)", (NIGHT + 600,))
    conn.execute("INSERT INTO runs (path, lane, tier, recorded_at) VALUES ('r-agent','agent','measure',?)",
                 (datetime(2026, 11, 2, 0, 37).timestamp(),))
    cur = conn.execute("INSERT INTO proposals (name, lane, first_seen, last_seen, state) "
                       "VALUES ('org/Decider-4B','decide',?,?,'screened')", (NIGHT, NIGHT))
    v = conn.execute("INSERT INTO verdicts (proposal_id, outcome, tier, detail, decided_at) VALUES (?,'screened','screen','',?)",
                     (cur.lastrowid, NIGHT + 60)).lastrowid
    conn.execute("UPDATE proposals SET state_verdict_id = ? WHERE id = ?", (v, cur.lastrowid))
    conn.execute("INSERT INTO jobs (id, created_at) VALUES (230, ?)", (NIGHT + 900,))
    conn.execute("INSERT INTO reverifications (lane, spec, job_id, queued_at) VALUES ('music','m',230,?)", (NIGHT + 900,))
    conn.commit()
    return conn


def test_a_lane_with_nothing_due_says_so_and_a_measured_lane_is_left_out():
    got = {i["lane"]: i for i in morning.idle_lanes(_store(), SINCE)}
    assert "image" not in got
    assert set(got) <= set(lanes.WANTED) and "agent" in got
    days = reverify.days_for(ms.connect(), "agent")
    assert got["agent"]["line"] == ("agent: no measure run; no challenger waiting; no reverify queued "
                                    f"(last measured 11-02 00:37, an age trigger after {days:g}d)")
    assert got["decide"]["waiting"] == 1 and "1 challenger(s) waiting" in got["decide"]["line"]
    assert "reverify job 230 queued 11-03 21:15, not settled" in got["music"]["line"]
    assert "never measured here" in got["video"]["line"]


@pytest.mark.gauntlet("state-is-whichever-row-came-last", site="harness/morning.py:idle_lanes")
def test_the_newest_reverify_by_its_queue_time_is_the_one_said_not_the_last_inserted():
    conn = _store()
    conn.execute("INSERT INTO jobs (id, created_at) VALUES (229, ?)", (NIGHT + 300,))
    conn.execute("INSERT INTO reverifications (lane, spec, job_id, queued_at, outcome) VALUES ('music','m',229,?,'passed')",
                 (NIGHT + 300,))
    conn.commit()
    got = {i["lane"]: i for i in morning.idle_lanes(conn, SINCE)}
    assert got["music"]["reverify_job"] == 230


def test_the_report_prints_each_idle_lane():
    conn = _store()
    r = {"idle": morning.idle_lanes(conn, SINCE)}
    text = "\n".join(morning_cmd.idle_lines(r))
    assert text.startswith("idle      ") and "agent: no measure run; no challenger waiting" in text
