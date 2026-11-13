"""watchdog_actions readers decide on result, notified, job_id and run_dir, never on the outcome sentence. #1778."""
import json

import pytest

from harness import contention, paused_jobs
from harness import memory_store as ms
from harness import watchdog as wd, watchdog_hands, watchdog_observe
from harness.memory_store.migrations import v102
from tests.test_limit_cuts_1087_harness_tz import _knobs
from tests.test_watchdog import NIGHT, Fake, Notifier, P, _fallbacks, _rows, run


def _eval(out, command="", pgid=41):
    return wd.Subject("eval", f"eval pgid {pgid}", "test", pid=pgid, pgid=pgid, command=command,
                      progress=run(pgid, tmp=out) if out is not None and not command else None)


def _stop(conn, subject, outcome, dry_run=False, criterion="overrun"):
    wd.record(conn, wd.Finding(criterion, subject, {}), wd.STOP, True, dry_run, outcome, NIGHT)


def test_an_overrun_stop_is_found_by_its_run_dir_whatever_its_sentence_says(tmp_path):
    out = tmp_path / "run"
    conn = ms.connect()
    try:
        _stop(conn, _eval(out), wd.Said("halted the evaluation at once", wd.ACTED))
        assert wd.overrun_stopped(conn, out)
        assert not wd.overrun_stopped(conn, tmp_path / "other")
    finally:
        conn.close()


@pytest.mark.parametrize("said", [wd.Said("group 41: term", wd.REFUSED), wd.Said("group 41: term", wd.FAILED)])
def test_a_stop_that_did_not_act_is_no_overrun_however_it_reads(tmp_path, said):
    out = tmp_path / "run"
    conn = ms.connect()
    try:
        _stop(conn, _eval(out), said)
        _stop(conn, _eval(out), wd.Said("group 41: term"), dry_run=True)
        _stop(conn, _eval(out), wd.Said("group 41: term"), criterion="no_progress")
        assert not wd.overrun_stopped(conn, out)
    finally:
        conn.close()


def test_a_stop_the_hands_refused_is_no_overrun(tmp_path):
    out = tmp_path / "run"
    conn = ms.connect()
    try:
        s = _eval(out)
        s.pgid = None
        got = watchdog_hands.Hands().do(wd.STOP, wd.Finding("overrun", s, {}))
        _stop(conn, s, got)
        assert got.result == wd.REFUSED and not wd.overrun_stopped(conn, out)
    finally:
        conn.close()


@pytest.mark.parametrize("spell", ["--out {} --resume", "--out={} --resume", "--out {}"])
@pytest.mark.parametrize("name", ["run-café", "run\\back", "run with/../run"])
def test_an_overrun_stop_with_no_progress_file_is_found_by_its_out_argument(tmp_path, spell, name):
    out = tmp_path / name
    out.mkdir(parents=True, exist_ok=True)
    conn = ms.connect()
    try:
        _stop(conn, _eval(None, command="uv run python -m evals.run " + spell.format(out)), wd.Said("stopped"))
        assert wd.overrun_stopped(conn, out)
    finally:
        conn.close()


def test_a_notification_is_held_by_the_notified_flag_whatever_its_sentence_says(tmp_path, monkeypatch, shown_live):
    monkeypatch.setattr(wd, "ESCALATE_AFTER", 99)
    monkeypatch.setattr(wd, "NOTIFIED", "put on the desktop")
    monkeypatch.setattr(wd, "HELD", "kept back")
    conn = ms.connect()
    hand = Notifier()
    fake = Fake(tmp_path, fallbacks=_fallbacks("a"))
    for i in range(3):
        wd.wake(conn, fake, hand, act=True, now=NIGHT + i * 300, say=lambda *_: None)
    rows = _rows(conn)
    assert len(hand.calls) == 1
    assert [(r["result"], r["notified"]) for r in rows] == [(wd.ACTED, 1), (wd.WITHHELD, 0), (wd.WITHHELD, 0)]
    assert rows[0]["outcome"].startswith("put on the desktop") and rows[1]["outcome"].startswith("kept back")
    assert _knobs().count("watchdog_notify_every") == 2


def test_a_failed_notification_does_not_hold_even_when_it_reads_as_shown(tmp_path, monkeypatch):
    monkeypatch.setattr(wd, "ESCALATE_AFTER", 99)
    conn = ms.connect()
    shown = []

    class Hand(watchdog_hands.Hands):
        def notify(self, f):
            shown.append(f.subject.key)
            return wd.Said(f"{wd.NOTIFIED}: it was not", wd.FAILED)
    fake = Fake(tmp_path, fallbacks=_fallbacks("a"))
    for i in range(2):
        wd.wake(conn, fake, Hand(run=None, environ={}), act=True, now=NIGHT + i * 300, say=lambda *_: None)
    assert len(shown) == 2


def _job_pause(conn, key, job_id, criterion=contention.CRITERION):
    s = wd.Subject("job", key, "test", pid=9, pgid=9, job_id=job_id)
    wd.record(conn, wd.Finding(criterion, s, {}), wd.PAUSE, False, False, wd.Said("pause file written"), NIGHT)


def test_contention_finds_the_paused_job_by_its_id_not_its_label():
    conn = ms.connect()
    try:
        _job_pause(conn, "queue job #7 (batch)", 7)
        _job_pause(conn, "job 0008", 9)
        assert contention.paused_for(conn, {"id": "0007", "started": None})
        assert not contention.paused_for(conn, {"id": "0008", "started": None})
    finally:
        conn.close()


def test_a_paused_job_names_its_watchdog_cause_by_its_id_not_its_label():
    conn = ms.connect()
    try:
        _job_pause(conn, "queue job #7", 7, criterion="memory_stuck")
        _job_pause(conn, "job 0007", 8, criterion="long_run")
        assert paused_jobs._said(conn, {"id": "0007", "started": None}) == "memory_stuck"
    finally:
        conn.close()


def test_the_job_subject_carries_its_id_from_the_worker_pid_file(tmp_path):
    fake = Fake(tmp_path, procs=[P(700, 1, 700, 60, "soh-batch-job")], jobs={"0042": 700},
                rows={"0042": {"state": "running"}})
    world = watchdog_observe.observe(fake, None, NIGHT)
    assert [(s.key, s.job_id) for s in world.top if s.kind == "job"] == [("job 0042", 42)]


def _legacy(conn, subject, action, dry_run, outcome, evidence):
    conn.execute("INSERT INTO watchdog_actions (at, criterion, subject, action, escalated, dry_run, evidence, outcome) "
                 "VALUES (0, 'c', ?, ?, 0, ?, ?, ?)", (subject, action, dry_run, json.dumps(evidence), outcome))


@pytest.mark.gauntlet("a-shared-store-query-with-no-scope-or-a-scope-with-its-own-idea-of-null", site="harness/memory_store/migrations/v102.py:data:watchdog_actions")
def test_the_migration_reads_each_earlier_rows_fields_from_its_text_once(tmp_path):
    out = tmp_path / "run"
    conn = ms.connect()
    try:
        _legacy(conn, "eval pgid 5", "stop", 0, "group 5: term", {"pgid": 5, "command": f"x --out {out} --resume"})
        _legacy(conn, "job 0012", "pause", 0, "pause file written: p; notified: memory_stuck: job 0012", {"pgid": 12})
        _legacy(conn, "eval pgid 6", "stop", 0, "refused: eval pgid 6 has no process group", {"pgid": None})
        _legacy(conn, "gateway", "notify", 0, "notify held: shown 60s ago", {})
        _legacy(conn, "gateway", "file", 0, "not filed: LH_WATCHDOG_FILE is not 1", {})
        _legacy(conn, "gateway", "restart", 0, "restart of gateway failed rc 1: x", {})
        _legacy(conn, "gateway", "notify", 0, "notify unavailable: no desktop notifier on linux", {})
        _legacy(conn, "gateway", "notify", 1, "dry-run", {})
        v102.data(conn)
        got = [tuple(r[k] for k in ("result", "notified", "job_id", "pgid", "run_dir")) for r in _rows(conn)]
        assert got == [(wd.ACTED, 0, None, 5, wd.canon(out)), (wd.ACTED, 1, 12, 12, ""), (wd.REFUSED, 0, None, None, ""),
                       (wd.WITHHELD, 0, None, None, ""), (wd.REFUSED, 0, None, None, ""), (wd.FAILED, 0, None, None, ""),
                       (wd.UNAVAILABLE, 0, None, None, ""), (wd.DRY, 0, None, None, "")]
        assert set(v102._result(o, d) for o, d in [("noted", 0), ("x", 1)]) <= set(wd.RESULTS)
        conn.execute("UPDATE watchdog_actions SET outcome = 'refused: reworded'")
        v102.data(conn)
        assert [r["result"] for r in _rows(conn)][0] == wd.ACTED
    finally:
        conn.close()
