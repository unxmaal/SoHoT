"""`soh inventory weight`: planted parts reach their expected verdicts, and the store is only ever read. #1148."""
import hashlib
import json
import plistlib
import sqlite3

import pytest

from harness import cli, inventory_weight as iw, live_audit, paths
from harness import memory_store as ms

T0 = 1791964800
DAY = 86400


def _run(conn, lane, digest, rows, path):
    rid = conn.execute("INSERT INTO runs (path, lane, tier, cases_digest, recorded_at) VALUES (?, ?, 'measure', ?, ?)",
                       (path, lane, digest, T0)).lastrowid
    for seq, (cand, case, passed, secs) in enumerate(rows):
        conn.execute("INSERT INTO results (run_id, seq, candidate, case_id, passed, seconds) VALUES (?,?,?,?,?,?)",
                     (rid, seq, cand, case, int(passed), secs))


@pytest.fixture
def store():
    conn = ms.connect()
    rows = []
    for m in ("m1", "m2", "m3"):
        rows += [(f"llamacpp:{m}", "easy", True, 10.0), (f"llamacpp:{m}", "split", m != "m3", 5.0)]
    rows += [("llamacpp:m1", "lonely", True, 1.0), ("llamacpp:m2", "lonely", True, 1.0)]
    _run(conn, "code", "exam", rows, "r1")
    _run(conn, "code", "old-exam", [("llamacpp:m1", "split", False, 100.0), ("llamacpp:m1", "easy", False, 100.0)],
         "r0")
    conn.commit()
    yield conn
    conn.close()


def _cases(conn, min_models=3):
    src = iw.gather_cases(conn, exam_of=lambda lane, split, repeat: (frozenset({"easy", "split", "lonely"}), "exam"))
    return {r["name"]: r for r in iw.score_cases(src, min_models)}


def test_a_case_every_fixture_model_passes_is_flagged(store):
    got = _cases(store)["code/easy"]
    assert got["flagged"] and got["evidence"] == 0 and got["direction"] == "all-pass", "an old exam's draw is not judged"
    assert got["rank"] == got["cost"] == 130.0


def test_a_case_that_splits_the_models_is_not_flagged(store):
    got = _cases(store)["code/split"]
    assert not got["flagged"] and got["evidence"] == 1 and got["rank"] == 0
    assert got["cost"] == 115.0, "an earlier exam's rows still count toward what the case has cost"


def test_a_case_seen_by_fewer_models_than_the_knob_is_not_flagged(store):
    assert not _cases(store)["code/lonely"]["flagged"]
    assert _cases(store, min_models=2)["code/lonely"]["flagged"]


JUNIT = """<testsuites><testsuite>
<testcase classname="tests.test_a" name="test_fast" time="0.1"/>
<testcase classname="tests.test_a" name="test_slow[x]" time="5.0"/>
<testcase classname="tests.test_a" name="test_slow[y]" time="4.0"/>
<testcase classname="tests.test_b" name="test_once_broke" time="20.0"/>
<testcase classname="tests.test_c.TestK" name="test_m" time="8.0"/>
</testsuite></testsuites>"""


def _tests(tmp_path, failures, mutation=None):
    p = tmp_path / "junit.xml"
    p.write_text(JUNIT, encoding="utf-8")
    times = iw.junit_times(p)
    return times, {r["name"]: r for r in iw.score_tests(times, failures, mutation=mutation, slow_share=0.5)}


def test_junit_names_a_test_function_once_over_its_parameters_and_keeps_its_class(tmp_path):
    times, _ = _tests(tmp_path, [])
    assert times == {"tests/test_a.py::test_fast": 0.1, "tests/test_a.py::test_slow": 9.0,
                     "tests/test_b.py::test_once_broke": 20.0, "tests/test_c.py::TestK.test_m": 8.0}


def test_a_test_that_once_failed_on_main_is_never_flagged(tmp_path):
    _, got = _tests(tmp_path, [{"id": "7", "main": True, "at": "2026-10-01", "failed": ["tests/test_b.py::test_once_broke"]}])
    r = got["tests/test_b.py::test_once_broke"]
    assert r["load_bearing"] and not r["flagged"] and r["rank"] == 0 and "1 main" in r["work"]


def test_a_slow_test_that_never_failed_is_flagged(tmp_path):
    _, got = _tests(tmp_path, [], mutation={"harness/x.py": ["tests/test_c.py"]})
    assert got["tests/test_b.py::test_once_broke"]["flagged"]
    assert got["tests/test_a.py::test_slow"]["flagged"]
    assert not got["tests/test_a.py::test_fast"]["flagged"], "fast tests are not in the slowest share"
    assert not got["tests/test_c.py::TestK.test_m"]["flagged"], "a test run against mutants may kill one"
    assert got["tests/test_c.py::TestK.test_m"]["evidence"] == 0.5


LOG = "\n".join([
    "check-macos\tmake check\t﻿2026-10-24T20:00:26.8697190Z ##[group]Run make check",
    "check-macos\tmake check\t2026-10-24T20:09:13.4578480Z =================================== FAILURES ===================",
    "check-macos\tmake check\t2026-10-24T20:09:13.4579500Z _ test_the_fetch_records_the_limit _",
    "check-macos\tmake check\t2026-10-24T20:09:13.4580610Z [gw0] darwin -- Python 3.12.10",
    "check-macos\tmake check\t2026-10-24T20:09:13.4599570Z >       assert set(got) == {'discover_top'}",
    "check-macos\tmake check\t2026-10-24T20:09:13.4601060Z tests/test_limit_trace_1087.py:164: AssertionError",
    "check-macos\tmake check\t2026-10-24T20:09:13.4602000Z ____ test_a_planted_bad_case[the reference fails one id] ____",
    "check-macos\tmake check\t2026-10-24T20:09:13.4603000Z harness/repo.py:12: in grade",
    "check-macos\tmake check\t2026-10-24T20:09:13.4603000Z tests/test_repo_lane.py:88: in test_a_planted_bad_case",
    "check-windows\tmake check\t2026-10-24T20:09:13.4604000Z ______ ERROR at setup of TestK.test_m ______",
    "check-windows\tmake check\t2026-10-24T20:09:13.4605000Z tests\\test_c.py:9: in fixture",
    "check-macos\tmake check\t2026-10-24T20:09:13.4606000Z 30.90s call     tests/test_slow.py::test_never_failed",
])


def test_a_failed_run_log_names_its_failed_tests():
    assert iw.failed_tests(LOG) == {"tests/test_limit_trace_1087.py::test_the_fetch_records_the_limit",
                                    "tests/test_repo_lane.py::test_a_planted_bad_case",
                                    "tests/test_c.py::TestK.test_m"}


AUDIT = """=== audit 2026-10-08T07:00:05Z ===
  ok   foreign_keys
  FAIL gateway_errors: 3: ...
=== audit 2026-10-09T07:00:04Z ===
  ok   foreign_keys
  warn gateway_errors: pinned
"""


def _checks(home, monkeypatch, failures=()):
    monkeypatch.setattr(live_audit, "CHECKS", live_audit.CHECKS + ("planted_never_fires",))
    (paths.logs()).mkdir(parents=True, exist_ok=True)
    (paths.logs() / "audit.log").write_text(AUDIT, encoding="utf-8")
    conn = ms.connect()
    conn.execute("INSERT INTO watchdog_actions (at, criterion, subject, action) VALUES (?, 'stale_mcp', 's', 'notify')",
                 (T0,))
    conn.commit()
    try:
        src = iw.gather_checks(conn, home, paths.REPO, None)
    finally:
        conn.close()
    return {r["name"]: r for r in iw.score_checks(src, list(failures), 40, 10.0, 288.0)}


def test_a_planted_check_that_never_fired_ranks_as_dead_weight(monkeypatch):
    got = _checks(paths.home(), monkeypatch)
    r = got["planted_never_fires"]
    assert r["flagged"] and not r["load_bearing"] and r["evidence"] == 0 and r["rank"] == r["cost"] == 2
    assert got["no_progress"]["flagged"] and got["no_progress"]["cost"] == 2880


def test_a_check_with_a_recorded_catch_is_load_bearing(monkeypatch):
    scanner = "tests/test_portability.py::test_no_text_file_is_read_or_written_without_an_explicit_encoding"
    got = _checks(paths.home(), monkeypatch, [{"id": "9", "main": False, "failed": [scanner]}])
    for name in ("gateway_errors", "stale_mcp", scanner):
        assert got[name]["load_bearing"] and not got[name]["flagged"] and got[name]["rank"] == 0, name
    assert "fired 2 time(s)" in got["gateway_errors"]["work"]
    assert not got["foreign_keys"]["load_bearing"]


def test_the_deploy_guard_and_the_watchdog_are_load_bearing(monkeypatch):
    got = _checks(paths.home(), monkeypatch)
    for name in ("deploy_guard", "sweep_guard"):
        assert got[name]["load_bearing"] and not got[name]["flagged"] and "#" in got[name]["why"]
    idle = {"unit": "watchdog", "declared": True, "table": "watchdog_actions", "rows": {"n": 0}, "log": None,
            "wakes": 288.0, "readers": []}
    w = iw.score_units([idle, {**idle, "unit": "otel"}], 0, DAY)
    assert w[0]["load_bearing"] and not w[0]["flagged"] and "#814" in w[0]["why"]
    assert w[1]["flagged"] and not w[1]["load_bearing"]


@pytest.mark.gauntlet("a-fact-about-the-harness-recorded-as-a-verdict-on-the-subject",
                      site="harness/inventory_weight.py:ci_failures.one")
def test_a_failed_run_whose_log_cannot_be_read_is_reported_not_read_as_clean(tmp_path):
    class Got:
        def __init__(self, rc, out="", err=""):
            self.returncode, self.stdout, self.stderr = rc, out, err

    def run(argv, **kw):
        return Got(1, err="HTTP 410: logs expired") if argv[3] == "1" else Got(0, LOG)
    runs = [{"databaseId": 1, "conclusion": "failure", "headBranch": "main", "event": "push"},
            {"databaseId": 2, "conclusion": "failure", "headBranch": "x", "event": "pull_request"},
            {"databaseId": 3, "conclusion": "success", "headBranch": "main", "event": "push"}]
    got = iw.ci_failures(run, runs, tmp_path)
    assert [g["id"] for g in got] == ["1", "2"] and "410" in got[0]["why"] and got[1]["failed"]
    assert not (tmp_path / "1.json").exists(), "an unreadable log is not cached as a clean one"
    L = iw.build({"now": DAY, "since": 0, "ci": {"runs": runs, "failures": got}, "junit": {}})
    assert L["ci"]["unreadable"] == ["1"] and "1 failed run log(s) unreadable" in iw.render(L)


@pytest.mark.gauntlet("a-closed-table-fronting-an-open-set", site="harness/inventory_weight.py:UNIT_OUTPUTS")
def test_every_launchd_unit_declares_its_output():
    units = iw.services((paths.REPO / "scripts" / "launchd.sh").read_text(encoding="utf-8"))
    assert len(units) >= 19 and set(units) == set(iw.UNIT_OUTPUTS)
    for unit, (table, col, cond, words) in iw.UNIT_OUTPUTS.items():
        assert table or words, f"{unit}: names neither a table nor a word its readers would name"
    stray = iw.score_units([{"unit": "newcomer", "declared": False, "rows": None, "log": None, "readers": []}], 0, DAY)
    assert stray[0]["flagged"] and "no declared output" in stray[0]["work"]


def test_a_units_schedule_wakes_and_its_log_starts():
    assert iw.wakes_per_day({"StartCalendarInterval": [{"Minute": m} for m in range(0, 60, 5)]}) == 288
    assert iw.wakes_per_day({"StartCalendarInterval": {"Weekday": 6, "Hour": 4, "Minute": 0}}) == pytest.approx(1 / 7)
    assert iw.wakes_per_day({"KeepAlive": True}) is None
    log = "=== morning 2026-10-24T10:30:04Z ===\nx\n=== morning 2026-10-25T10:30:03Z ===\n"
    assert iw.log_runs(log, "morning", iw._iso("2026-10-25T00:00:00Z")) == 1
    assert iw.log_runs("no start lines", "morning", 0) is None


def test_a_knob_whose_constant_changed_value_moved_and_one_never_touched_is_flagged():
    commits = iw.history("\n".join([
        "@@COMMIT aaa 100 add the limit (#5) (#6)", "diff --git a/harness/x.py b/harness/x.py", "+++ b/harness/x.py",
        "+LIMIT = 3", "+QUIET = 1", "+TABLE = {", '+    "code": 5,', "@@COMMIT bbb 200 raise it (#7)", "--- a/harness/x.py", "+++ b/harness/x.py",
        "-LIMIT = 3", "+LIMIT = 5", "@@COMMIT ccc 300 comment only", "+++ b/harness/x.py",
        "-QUIET = 1", "+QUIET = 1  # one-line note"]))
    assert iw.value_changes(commits, "harness/x.py:LIMIT") == 1
    assert iw.value_changes(commits, "harness/x.py:QUIET") == 0
    assert iw.value_changes(commits, "harness/x.py:f(timeout)") is None
    assert iw.value_changes(commits, "harness/x.py:TABLE") is None, "a value spread over lines cannot be compared"
    assert iw.first_added(commits, "harness/x.py", "QUIET")["issues"] == [5]
    got = {r["name"]: r for r in iw.score_knobs([
        {"name": "moved", "changes": 1}, {"name": "swept", "sweeps": 2, "changes": 0},
        {"name": "still", "changes": 0, "values": 1}])}
    assert not got["moved"]["flagged"] and not got["swept"]["flagged"]
    assert got["still"]["flagged"] and not got["still"]["load_bearing"] and got["still"]["info"]


#: SQLite's WAL index: a mode=ro reader of a WAL store maps it, and an empty -wal holds no write.
SIDECARS = ("-shm", "-wal")


def _snapshot(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file() and not p.name.endswith(SIDECARS)}


def test_the_command_opens_the_store_read_only_and_writes_nothing(store, tmp_path, monkeypatch, capsys):
    agents = tmp_path / "agents"
    agents.mkdir()
    (agents / "com.unxmaal.localharness.watchdog.plist").write_bytes(plistlib.dumps(
        {"StartCalendarInterval": [{"Minute": m} for m in range(0, 60, 5)]}))
    monkeypatch.setattr(iw, "agents_dir", lambda: agents)
    monkeypatch.setattr(iw, "_launchctl", lambda *a: None)
    monkeypatch.setattr(iw, "git_history", lambda run, root: [])
    store.close()
    home = paths.home()
    before = _snapshot(home)
    db = ms.db_path()
    db.chmod(0o444)
    real = sqlite3.connect
    opened = []

    def spy(target, *a, **kw):
        opened.append((str(target), kw.get("uri", False)))
        return real(target, *a, **kw)

    def refuse(*a, **kw):
        raise AssertionError("ms.connect would migrate and write the store")

    monkeypatch.setattr(sqlite3, "connect", spy)
    monkeypatch.setattr(ms, "connect", refuse)
    assert cli.main(["inventory", "weight", "--json", "--no-ci", "--kind", "cases", "--kind", "units",
                     "--kind", "knobs", "--kind", "checks"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] and set(out["kinds"]) == {"cases", "units", "knobs", "checks"}
    wd = next(r for r in out["kinds"]["units"]["rows"] if r["name"] == "watchdog")
    assert wd["cost"] == 288 and wd["load_bearing"]
    store_opens = [(t, uri) for t, uri in opened if db.name in t]
    assert store_opens and all(t.endswith("?mode=ro") and uri for t, uri in store_opens)
    assert _snapshot(home) == before
    wal = db.with_name(db.name + "-wal")
    assert not wal.exists() or wal.stat().st_size == 0
