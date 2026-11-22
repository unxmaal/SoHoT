"""`soh morning --days N`: comparisons finished and jobs failed with a harness error, a line a local day, read from the store. #2111."""
import json
from datetime import datetime, timedelta

import pytest

from harness import cli, machine, morning
from harness import memory_store as ms
from harness.commands import morning as morning_cmd

OTHER = {"hw_model": "Other1,1", "os": "Linux", "arch": "x86_64", "host": "b-host"}
NOON = datetime(2026, 11, 20, 12, 0, 0)
NOW = NOON.timestamp()


def _at(days_ago: int, hour: int = 12) -> float:
    return (NOON.replace(hour=hour) - timedelta(days=days_ago)).timestamp()


def _verdict(conn, mid, outcome: str, at: float, tier: str = "adopt") -> None:
    conn.execute("INSERT INTO verdicts (machine_id, proposal_id, outcome, tier, detail, decided_at) "
                 "VALUES (?, NULL, ?, ?, '', ?)", (mid, outcome, tier, at))


def _job(conn, mid, state: str, reason: str, rc, finished, created: float | None = None) -> None:
    conn.execute("INSERT INTO jobs (machine_id, title, argv, state, reason, rc, created_at, finished_at) "
                 "VALUES (?, 'j', '[]', ?, ?, ?, ?, ?)", (mid, state, reason, rc, created or finished, finished))


@pytest.fixture
def store():
    conn = ms.connect()
    me = ms.remember_machine(conn)
    other = ms.remember_machine(conn, {**OTHER, "fingerprint": machine.fingerprint(*OTHER.values())})
    yield conn, me, other
    conn.close()


def test_each_day_counts_its_finished_comparisons_by_outcome(store):
    conn, me, _ = store
    _verdict(conn, me, "declined", _at(0, 1))
    _verdict(conn, me, "declined", _at(0, 23))
    _verdict(conn, me, "adopted", _at(0))
    _verdict(conn, me, "declined", _at(1, 23))
    got = morning.days(conn, NOW, 3)
    assert [r["day"] for r in got] == ["2026-11-20", "2026-11-19", "2026-11-18"]
    assert [r["finished"] for r in got] == [{"adopted": 1, "declined": 2}, {"declined": 1}, {}]


def test_a_verdict_of_another_tier_machine_or_day_is_not_a_finished_comparison(store):
    conn, me, other = store
    _verdict(conn, me, "screened", _at(0), tier="screen")
    _verdict(conn, other, "adopted", _at(0))
    _verdict(conn, me, "adopted", _at(2))
    assert [r["finished"] for r in morning.days(conn, NOW, 2)] == [{}, {}]


def test_each_day_counts_its_jobs_failed_with_a_harness_error_by_reason(store):
    conn, me, _ = store
    _job(conn, me, "failed", "exited", 1, _at(0))
    _job(conn, me, "failed", "exited", 1, _at(0, 3))
    _job(conn, me, "failed", "interrupted", None, None, created=_at(1))
    _job(conn, me, "failed", "expired", 75, _at(1))
    got = morning.days(conn, NOW, 2)
    assert [r["failed"] for r in got] == [{"exited rc 1": 2}, {"expired rc 75": 1, "interrupted": 1}]


def test_a_job_that_never_fits_ended_well_ran_elsewhere_or_earlier_is_no_harness_error(store):
    conn, me, other = store
    _job(conn, me, "failed", "never_fits", None, _at(0))
    _job(conn, me, "done", "exited", 0, _at(0))
    _job(conn, me, "cancelled", "cancel", None, _at(0))
    _job(conn, other, "failed", "exited", 1, _at(0))
    _job(conn, me, "failed", "exited", 1, _at(1))
    assert morning.days(conn, NOW, 1) == [{"day": "2026-11-20", "finished": {}, "failed": {}}]


def test_the_lines_say_each_days_totals_and_what_they_are_made_of():
    lines = morning_cmd.day_lines([{"day": "2026-11-20", "finished": {"declined": 2, "adopted": 1}, "failed": {}},
                                   {"day": "2026-11-19", "finished": {}, "failed": {"exited rc 1": 4}}])
    assert lines == ["2026-11-20  comparisons finished 3 (adopted 1, declined 2); jobs failed with a harness error 0",
                     "2026-11-19  comparisons finished 0; jobs failed with a harness error 4 (exited rc 1 4)"]


def test_the_command_reads_the_store_and_writes_nothing_to_it(store, capsys):
    conn, me, _ = store
    now = datetime.now().timestamp()
    _verdict(conn, me, "adopted", now)
    _job(conn, me, "failed", "exited", 2, now)
    conn.commit()
    before = [conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("verdicts", "jobs", "meta")]
    assert cli.main(["morning", "--days", "2", "--json"]) == 0
    got = json.loads(capsys.readouterr().out)
    assert [r["day"] for r in got["days"]][0] == datetime.now().strftime("%Y-%m-%d")
    assert got["days"][0]["finished"] == {"adopted": 1} and got["days"][0]["failed"] == {"exited rc 2": 1}
    assert [conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("verdicts", "jobs", "meta")] == before
