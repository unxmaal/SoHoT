"""The morning brief is this machine's night: another machine's verdicts, runs, reverifications, pauses and watchdog rows are not counted as its own (#1932)."""
import json

import pytest

from harness import lanes, machine, morning, sweep_check
from harness import memory_store as ms
from harness.commands import morning as morning_cmd
from tests.test_morning_867 import NIGHT, NOW, SINCE, _beat, _gh, _git, deploy_dir  # noqa: F401

OTHER = {"hw_model": "Other1,1", "os": "Linux", "arch": "x86_64", "host": "b-host"}


def _lanes() -> tuple[str, str, str]:
    free = [lane for lane in lanes.WANTED if not lanes.parked(lane)[0]]
    return free[0], free[1], free[2]


def _night(conn, mid, lane: str, tier_outcome: str, at: float, rv_lane: str, rv_job: int) -> None:
    conn.execute("INSERT INTO verdicts (machine_id, proposal_id, outcome, tier, detail, decided_at) "
                 "VALUES (?, NULL, ?, 'screen', '', ?)", (mid, tier_outcome, at))
    conn.execute("INSERT INTO verdicts (machine_id, proposal_id, outcome, tier, detail, decided_at) "
                 "VALUES (?, NULL, ?, 'adopt', '', ?)", (mid, tier_outcome, at))
    conn.execute("INSERT INTO runs (machine_id, path, lane, tier, recorded_at) VALUES (?, ?, ?, 'measure', ?)",
                 (mid, f"r-{lane}-{mid}", lane, at))
    conn.execute("INSERT INTO paused_runs (machine_id, lane, incumbent, challenger, out, done, total, state, paused_at) "
                 "VALUES (?, ?, 'inc', ?, 'o', 1, 2, 'paused', ?)", (mid, lane, f"chal-{mid}", at))
    conn.execute("INSERT INTO watchdog_actions (machine_id, at, criterion, subject, action, escalated, dry_run, outcome) "
                 "VALUES (?, ?, 'overrun', ?, 'stop', 1, 0, 'group term')", (mid, at, f"eval pgid {mid}"))
    conn.execute("INSERT INTO watchdog_actions (machine_id, at, criterion, subject, action, escalated, dry_run, "
                 "evidence, outcome, notified) VALUES (?, ?, ?, 'sweep', 'note', 0, 0, ?, 'noted', 0)",
                 (mid, at, sweep_check.CRITERION, json.dumps({"verdict": "running", "line": f"check {mid}"})))
    conn.execute("INSERT INTO jobs (id, created_at) VALUES (?, ?)", (rv_job, at))
    conn.execute("INSERT INTO reverifications (machine_id, lane, spec, job_id, queued_at) VALUES (?, ?, 'm', ?, ?)",
                 (mid, rv_lane, rv_job, at))


@pytest.fixture
def two():
    conn = ms.connect()
    me = ms.remember_machine(conn)
    other = ms.remember_machine(conn, {**OTHER, "fingerprint": machine.fingerprint(*OTHER.values())})
    mine, theirs, idle = _lanes()
    _night(conn, me, mine, "screened", NIGHT + 60, idle, 301)
    _night(conn, other, theirs, "broken", NIGHT + 120, theirs, 302)
    conn.commit()
    return conn, me, other, (mine, theirs, idle)


def test_the_tallies_are_this_machines_verdicts(two):
    conn, *_ = two
    s = morning.sweep(conn, SINCE, None)
    assert s["screened"] == {"screened": 1}
    assert s["settled"]["verdicts"] == {"screened": 1}


def test_another_machines_run_is_named_by_its_machine_not_counted_as_this_ones(two):
    conn, me, other, (mine, theirs, _) = two
    m = morning.sweep(conn, SINCE, None)["measured"]
    assert [(r["lane"], r["machine_id"]) for r in m["runs"]] == [(mine, me)]
    assert [(r["lane"], r["machine_id"]) for r in m["elsewhere"]] == [(theirs, other)]
    assert morning.machine_name(m["elsewhere"][0]) == f"machine {other} (Other1,1)"


def test_pauses_stops_and_sweep_checks_are_this_machines(two):
    conn, me, *_ = two
    s = morning.sweep(conn, SINCE, None)
    assert [p["challenger"] for p in s["paused"]] == [f"chal-{me}"]
    assert [w["subject"] for w in s["stopped"]] == [f"eval pgid {me}"]
    assert [w["subject"] for w in morning.watchdog(conn, SINCE)] == [f"eval pgid {me}"]
    assert [c["line"] for c in morning.sweep_checks(conn, SINCE)] == [f"check {me}"]


def test_a_lane_another_machine_measured_is_idle_here_and_its_reverify_is_not_said(two):
    conn, _, _, (mine, theirs, idle) = two
    got = {i["lane"]: i for i in morning.idle_lanes(conn, SINCE)}
    assert mine not in got
    assert "never measured here" in got[theirs]["line"] and got[theirs]["reverify_job"] is None
    assert got[idle]["reverify_job"] == 301


def test_the_brief_says_this_machines_count_and_names_the_others_runs(two, deploy_dir):
    conn, _, other, (mine, theirs, _) = two
    r = morning.gather(conn, NOW, SINCE, beat=_beat(), gh=_gh(), git=_git(), where=deploy_dir, lanes=lambda c: [])
    text = "\n".join(morning_cmd.render(r))
    assert f"measured  1 run(s): {mine}; " in text
    assert f"elsewhere 1: {theirs} on machine {other} (Other1,1)" in text


def test_an_unstamped_run_is_no_machines_and_is_named_so():
    assert morning.machine_name({"machine_id": None}) == "no recorded machine"
