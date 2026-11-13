"""The read path: a checked local digest of a log, its planted-failure control, and the A/B on recorded CI logs. #1690."""
import gzip
import json
import sys

import pytest

from evals import digest_ab
from harness import ask, delegate, digest, ledger, purpose

PRE = "check-macos\tUNKNOWN STEP\t2026-11-08T06:16:58.8260710Z "
LOG_LINES = [
    "............F.....s......EF...... [ 40%]",
    "..........................XFAIL... [100%]",
    "==================================== ERRORS ====================================",
    "______________ ERROR at setup of test_the_store_opens_once ______________",
    "E       sqlite3.OperationalError: database is locked",
    "tests/test_store.py:12: OperationalError",
    "=================================== FAILURES ===================================",
    "_______________ test_a_full_read_soon_after_a_digest_is_a_redo ________________",
    "[gw1] darwin -- Python 3.12.10 /work/.venv/bin/python",
    "    def test_a_full_read_soon_after_a_digest_is_a_redo(tmp_path):",
    ">       assert got['redos'] == 1",
    "E       assert 0 == 1",
    "tests/test_ask_paths_1335.py:300: AssertionError",
    "__________________ TestRoute.test_the_lane_routes_by_spec[code] __________________",
    "E       KeyError: 'code'",
    "E         more detail",
    "harness/route.py:44: KeyError",
    "tests/test_route.py::test_the_lane_routes_by_spec PASSED",
    "=========================== short test summary info ============================",
    "SKIPPED [1] tests/test_x.py:3: needs ffmpeg",
    "FAILED tests/test_other.py::test_a_summary_only_failure - assert False",
    "=== 3 failed, 2000 passed, 12 skipped, 1 error in 300.12s (0:05:00) ===",
    "make: *** [Makefile:14: test] Error 1",
    "\x1b[31m##[error]Process completed with exit code 2.\x1b[0m",
]
LOG = "\n".join(PRE + ln for ln in LOG_LINES) + "\n"
TESTS = {"test_the_store_opens_once", "test_a_full_read_soon_after_a_digest_is_a_redo",
         "test_the_lane_routes_by_spec[code]", "test_a_summary_only_failure"}


def _keys(items, kind):
    return {i.key for i in items if i.kind == kind}


def _answer(text):
    """A local model that answers every part with `text`, as delegate.complete returns."""
    def complete(lane, prompt, **kw):
        complete.seen.append(kw.get("tag"))
        return {"text": text, "spec": "s", "model": "m", "prompt_tokens": 100, "completion_tokens": 10}
    complete.seen = []
    return complete


@pytest.fixture
def log(tmp_path):
    p = tmp_path / "logs" / "check.log"
    p.parent.mkdir()
    p.write_text(LOG, encoding="utf-8", newline="\n")
    return p


# ---- what the check requires ----------------------------------------------------

def test_the_check_finds_every_failing_test_error_count_and_exit_behind_ci_prefixes():
    items = digest.must(LOG)
    assert _keys(items, "test") == TESTS
    assert _keys(items, "exception") == {"sqlite3.OperationalError: database is locked", "assert 0 == 1",
                                         "KeyError: 'code'"}
    assert _keys(items, "count") == {"3 failed", "1 error"}
    assert _keys(items, "exit") == {"make: *** [Makefile:14: test] Error 1",
                                    "##[error]Process completed with exit code 2."}


def test_passing_skipped_and_xfail_lines_are_not_failures():
    items = digest.must("tests/a.py::test_ok PASSED\ntests/b.py::test_x XFAIL\nSKIPPED [1] tests/c.py:1: no\n"
                        "=== 10 passed, 2 skipped in 1.0s ===\nexit code 0\n")
    assert items == []


def test_a_failing_test_is_kept_only_by_its_own_whole_name():
    [item] = [i for i in digest.must(LOG) if i.key == "test_the_store_opens_once"]
    assert digest.missing("test_the_store_opens_once_more failed", [item]) == [item]
    assert digest.missing("tests/test_store.py::test_the_store_opens_once", [item]) == []


# ---- the digest -------------------------------------------------------------------

def test_a_digest_that_left_a_failing_test_out_gets_it_back_from_the_check(log):
    got = digest.run([str(log)], roots=[ask.Root(log.parent)],
                     complete=_answer("E       assert 0 == 1\nFAILED tests/test_other.py::test_a_summary_only_failure"))
    headed_only = {"test_a_full_read_soon_after_a_digest_is_a_redo", "test_the_lane_routes_by_spec[code]"}
    assert got["check"]["control"] is True and set(got["check"]["missing"]) == headed_only
    added = got["text"].split("check added (the digest left these out):", 1)[1]
    assert all(f"FAILED {n}" in added for n in ("test_a_full_read_soon_after_a_digest_is_a_redo",
                                                 "TestRoute.test_the_lane_routes_by_spec[code]"))
    assert got["answer"] in got["text"] and digest.missing(got["text"], digest.must(LOG)) == []


def test_the_digest_points_at_the_raw_file_and_is_shorter_than_it(log):
    got = digest.run([str(log)], roots=[ask.Root(log.parent)], complete=_answer("none"))
    assert f"raw: {log.resolve()} ({LOG.count(chr(10)) + 1} lines" in got["text"]
    assert got["raw_tokens"] == digest.tokens(LOG)
    assert got["digest_tokens"] == digest.tokens(got["text"])


def test_the_control_is_caught_and_fails_when_the_digest_already_names_the_plant():
    assert digest.control(LOG, "nothing here") is True
    assert digest.control(LOG, f"FAILED {digest.CONTROL}") is False


def test_a_digest_whose_control_misses_says_read_the_raw_file(log, monkeypatch):
    monkeypatch.setattr(digest, "control", lambda text, d: False)
    got = digest.run([str(log)], roots=[ask.Root(log.parent)], complete=_answer("none"))
    assert "CONTROL MISSED" in got["text"] and "read the raw file" in got["text"]


def test_a_lane_that_refuses_leaves_the_scan_and_the_check(log):
    def busy(lane, prompt, **kw):
        raise delegate.Refused("the machine is busy")
    got = digest.run([str(log)], roots=[ask.Root(log.parent)], complete=busy)
    assert got["call_id"] == "" and "the machine is busy" in got["unmodelled"]
    assert "no model: the extract lane did not answer" in got["text"]
    assert digest.missing(got["text"], digest.must(LOG)) == []


def test_the_check_caps_what_it_adds_and_records_the_cut(tmp_path, monkeypatch):
    from harness import cuts
    seen = []
    monkeypatch.setattr(cuts, "cut", lambda name, *a, **kw: seen.append(name))
    monkeypatch.setattr(digest, "CHECK_ITEMS", 2)
    p = tmp_path / "many.log"
    p.write_text("".join(f"____ test_n{i} ____\nE   AssertionError: {i}\n" for i in range(5)), encoding="utf-8")
    got = digest.run([str(p)], roots=[ask.Root(tmp_path)], model=False)
    assert got["check"]["added"] == 2 and "and 3 more; read the raw file" in got["text"]
    assert "harness/digest.py:CHECK_ITEMS" in seen


def test_a_long_exception_line_is_checked_by_its_first_characters_and_leaves_a_cut(monkeypatch):
    from harness import cuts
    seen = []
    monkeypatch.setattr(cuts, "cut", lambda name, *a, **kw: seen.append((name, kw.get("dropped"))))
    long = "AssertionError: " + "x" * 200
    [_, exc] = digest.must(f"____ test_long ____\nE   {long}\n")
    assert exc.key == long[:digest.KEY_CHARS] and digest.missing(long[:digest.KEY_CHARS] + "yz", [exc]) == []
    assert ("harness/digest.py:KEY_CHARS", 1) in seen


# ---- the scan reads CI logs; eval traffic is not internal work (#1701) -----------

def test_the_failure_scan_finds_an_exception_line_behind_a_ci_prefix():
    assert "E       KeyError: 'code'" in ask.failure_lines(LOG)


def test_an_undelegated_call_inside_an_eval_is_tagged_eval(log, monkeypatch):
    monkeypatch.setenv(purpose.ENV, purpose.EVAL)
    assert delegate.tag_of(False) == purpose.EVAL and delegate.tag_of(True) == purpose.WORK
    complete = _answer("none")
    ask.ask([str(log)], "what failed?", roots=[ask.Root(log.parent)], complete=complete)
    assert set(complete.seen) == {purpose.EVAL}


def test_an_undelegated_call_outside_a_measurement_stays_internal(monkeypatch):
    monkeypatch.delenv(purpose.ENV, raising=False)
    assert delegate.tag_of(False) == purpose.INTERNAL
    monkeypatch.setenv(purpose.ENV, purpose.WATCHDOG)
    assert delegate.tag_of(False) == purpose.INTERNAL


# ---- the CLI and local_complete ------------------------------------------------------

def test_soh_digest_prints_the_checked_digest(log, monkeypatch, capsys):
    from harness import cli
    monkeypatch.chdir(log.parent)
    (log.parent / ".git").mkdir()
    assert cli.main(["digest", "--no-model", "check.log", "--json"]) == 0
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["check"]["control"] and out["check"]["items"] == len(digest.must(LOG))


def test_soh_digest_run_logs_a_command_and_exits_with_its_code(tmp_path, monkeypatch, capsys):
    from harness import cli
    monkeypatch.chdir(tmp_path)
    out = tmp_path / "out" / "run.log"
    code = "import sys; print('_____ test_it_breaks _____'); print('E   ValueError: no'); sys.exit(3)"
    assert cli.main(["digest", "--no-model", "--run", "--out", str(out), "--", sys.executable, "-c", code]) == 3
    assert "test_it_breaks" in out.read_text(encoding="utf-8")
    said = capsys.readouterr().out
    assert "FAILED test_it_breaks" in said and "command exit 3" in said


def test_local_complete_mode_digest_runs_the_same_checked_digest(log, monkeypatch):
    from harness import local_tools
    monkeypatch.setenv(ask.ROOTS_ENV, str(log.parent))
    monkeypatch.setattr(delegate, "complete", _answer("none"))
    monkeypatch.setattr("harness.delegations.note", lambda got, call_id, **kw: {**got, "call_id": "c1"})
    got = local_tools.complete(paths=[str(log)], mode="digest")
    assert got["check"]["control"] and "check added" in got["text"] and got["call_id"] == "c1"
    with pytest.raises(ValueError, match="pass them in `paths`"):
        local_tools.complete(prompt="x", mode="digest")


# ---- the A/B on recorded logs ---------------------------------------------------------

def _fetcher(logs):
    return lambda run: logs[run].encode("utf-8")


def test_build_records_a_log_only_when_headers_and_progress_marks_agree(tmp_path):
    bad = LOG.replace("..EF..", "..EFF..")
    got = digest_ab.build([1, 2], tmp_path, fetch=_fetcher({1: LOG, 2: bad}))
    manifest = json.loads((tmp_path / digest_ab.MANIFEST).read_text(encoding="utf-8"))
    assert [e["run"] for e in got] == [1] and manifest["refused"][0]["run"] == 2
    assert set(got[0]["tests"]) == TESTS


def test_a_recorded_log_that_changed_is_refused(tmp_path):
    digest_ab.build([1], tmp_path / "set", fetch=_fetcher({1: LOG}))
    f = tmp_path / "set" / "logs" / "1.log.gz"
    f.write_bytes(gzip.compress(LOG.replace("Error 1", "Error 9").encode("utf-8")))
    with pytest.raises(ValueError, match="sha256"):
        digest_ab.materialize(tmp_path / "out", tmp_path / "set")


def test_the_ab_counts_tokens_recall_per_arm_and_the_ratio_by_the_1688_rule(tmp_path):
    digest_ab.build([1], tmp_path / "set", fetch=_fetcher({1: LOG}))
    rep = digest_ab.run(tmp_path / "out", complete=_answer("FAILED tests/test_other.py::test_a_summary_only_failure"),
                        set_dir=tmp_path / "set")
    [row] = [json.loads(ln) for ln in (tmp_path / "out" / "results.jsonl").read_text(encoding="utf-8").splitlines()]
    assert row["tests"] == 4 and row["tests_model"] == 1 and row["tests_checked"] == 4
    assert rep["tests_checked"]["recall"] == 1.0 and rep["tests_model"]["recall"] == 0.25
    assert rep["raw_tokens"] == digest.tokens(LOG) and rep["control"] == 1
    want = ledger.local_vs_cloud([(purpose.WORK, "extract", row["local_tokens"], 0)],
                                 {"input": rep["digest_tokens"], "output": row["digest_call"]})
    assert rep["digest_arm"] == want and rep["ratio"] == want["local"] / want["cloud"]
    assert any("target 3.0:1" in ln for ln in rep["lines"])


def test_the_committed_set_is_intact_and_its_gold_has_two_readings(tmp_path):
    rows = digest_ab.materialize(tmp_path)
    assert len(rows) >= 24 and sum(len(r["tests"]) for r in rows) >= 50
    for r in rows:
        text = open(r["path"], encoding="utf-8", errors="replace").read()
        assert digest_ab.gold(text) == {"tests": r["tests"], "exits": r["exits"]}, r["id"]
        if r["tests"]:
            assert digest_ab.progress_failures(text) == digest_ab.headers(text), r["id"]
