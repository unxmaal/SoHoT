"""The importer and demand-census limits record a limit_cuts row when they bind, and only then (#1087)."""
from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace

import httpx
import pytest

from evals import importers
from evals.analysis import demand as d
from evals.analysis.demand import replay as rp
from evals.importers import history, leetcode, librispeech, squad2, squad2_extract
from evals.importers import transcripts as tr
from harness import cuts
from tests import test_demand_census_1151 as census_t, test_history_importer as history_t
from tests import test_transcripts_importer as tr_t
from tests.test_demand_census_1151 import root as census_root  # noqa: F401
from tests.test_demand_replay_1161 import world as replay_world  # noqa: F401
from tests.test_demand_replay_1161 import KNOWN, _judges, _packets
from tests.test_transcripts_importer import world as tr_world  # noqa: F401


def _spooled() -> list[dict]:
    path = cuts._spool_path()
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


def _knobs(but=()) -> list[str]:
    return [r["knob"] for r in _spooled() if r["knob"] not in but]


def _history_survey(tmp_path, src=None, **kw):
    src = src or history_t._repo(tmp_path, history_t.FIXED, history_t.ADD_TEST)
    return history.survey(str(src), "main", 20, tmp_path / "log.txt", get_issue=lambda n: history_t.ISSUE, **kw)


def test_a_fix_screened_out_as_too_big_is_a_cut_of_the_size_limit_that_refused_it(tmp_path, monkeypatch):
    src = history_t._repo(tmp_path, history_t.FIXED, history_t.ADD_TEST)
    _history_survey(tmp_path, src, run=False)
    assert _spooled() == []
    monkeypatch.setattr(history, "MAX_LINES", 0)
    got = _history_survey(tmp_path, src, run=False)
    assert got["dropped"] == {"too_big": 1}
    assert [(r["knob"], r["dropped"]) for r in _spooled()] == [("history_max_lines", 1)]


def test_a_probe_dropped_as_timeout_is_one_cut_at_the_timeout_it_ran_under(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "probe", lambda *a, **k: {"drop": "timeout"})
    got = _history_survey(tmp_path, timeout=7)
    assert got["dropped"] == {"timeout": 1}
    assert [(r["knob"], r["value"], r["dropped"]) for r in _spooled()] == [
        ("evals/importers/history.py:TIMEOUT_S", 7.0, 1)]


def test_both_size_limits_record_only_the_candidates_each_one_refused():
    small = {"source_files": ["a.py"], "lines": 1}
    history.record_cuts([small, {**small, "lines": history.MAX_LINES + 1},
                         {"source_files": [f"{i}.py" for i in range(history.MAX_SOURCE_FILES + 1)], "lines": 1}],
                        0, history.TIMEOUT_S)
    assert sorted((r["knob"], r["dropped"]) for r in _spooled()) == [("history_max_lines", 1),
                                                                    ("history_max_source_files", 1)]


def _tr_survey(world, **kw):
    return tr_t._survey(world, **kw)


def test_commit_evidence_outside_the_window_is_a_cut_of_the_side_it_fell_on(tr_world, monkeypatch):
    _tr_survey(tr_world, run=False)
    assert set(_knobs()) == {"transcripts_commit_before"}
    cuts._spool_path().unlink()
    monkeypatch.setattr(tr, "COMMIT_BEFORE_S", 10 ** 9)
    _tr_survey(tr_world, run=False)
    assert _spooled() == []
    real = tr.resolve
    monkeypatch.setattr(tr, "resolve", lambda repos, shas: {
        k: [(r, sha, t + 10 ** 6) for r, sha, t in v] for k, v in real(repos, shas).items()})
    _tr_survey(tr_world, run=False)
    assert set(_knobs()) == {"transcripts_commit_after"}


WINDOW = ("transcripts_commit_before",)


def test_a_cut_shorter_than_the_floor_is_a_cut_of_the_floor(tr_world, monkeypatch):
    monkeypatch.setattr(tr, "MIN_CUT_BYTES", 10 ** 9)
    got = _tr_survey(tr_world, run=False)
    assert got["projects"]["widget"]["dropped"] == {"cut_too_short": 1}
    assert [(r["knob"], r["dropped"]) for r in _spooled() if r["knob"] not in WINDOW] == [
        ("transcripts_min_cut_bytes", 1)]


def test_a_transcript_task_too_big_or_timed_out_records_the_history_limit(tr_world, monkeypatch):
    monkeypatch.setattr(history, "MAX_SOURCE_FILES", 0)
    _tr_survey(tr_world, run=False)
    assert _knobs(WINDOW) == ["history_max_source_files"]
    cuts._spool_path().unlink()
    monkeypatch.setattr(history, "MAX_SOURCE_FILES", 8)
    monkeypatch.setattr(history, "probe", lambda *a, **k: {"drop": "timeout"})
    _tr_survey(tr_world)
    assert _knobs(WINDOW) == ["evals/importers/history.py:TIMEOUT_S"]


def _check_row(*checks: str) -> dict:
    body = "".join(f"    {c}\n" for c in checks)
    return {"test": f"def check(candidate):\n{body}", "entry_point": "Solution().f"}


def test_leetcode_checks_past_either_limit_are_one_cut_per_import(monkeypatch):
    few = _check_row(*(f"assert candidate({i}) == {i}" for i in range(3)))
    assert len(leetcode.checks_of(few)) == 3
    leetcode.converted()
    assert _spooled() == []
    long = "assert candidate(" + "1" * leetcode.MAX_CHECK_CHARS + ") == 1"
    many = _check_row(long, *(f"assert candidate({i}) == {i}" for i in range(leetcode.MAX_CHECKS + 2)))
    got = leetcode.checks_of(many)
    assert len(got) == leetcode.MAX_CHECKS and all(len(c) <= leetcode.MAX_CHECK_CHARS for c in got)
    leetcode.checks_of(many)
    leetcode.converted()
    assert sorted((r["knob"], r["dropped"]) for r in _spooled()) == [
        ("evals/importers/leetcode.py:MAX_CHECKS", 4), ("evals/importers/leetcode.py:MAX_CHECK_CHARS", 2)]


def test_an_import_run_reports_its_cuts_after_converting_every_row(monkeypatch, tmp_path):
    called = []
    mod = SimpleNamespace(LANE="code", LICENSE=next(iter(importers.ALLOWED_LICENSES)), fetch=list, convert=lambda r: None,
                          converted=lambda: called.append(1))
    monkeypatch.setattr(importers, "module", lambda name: mod)
    importers.run("x", root=tmp_path, rows=[{}, {}])
    assert called == [1]


def _timeout(*a, **k):
    raise httpx.ReadTimeout("slow")


SITES = ("evals/importers/leetcode.py:_get->httpx.get(timeout)",
         "evals/importers/squad2.py:load->httpx.get(timeout)",
         "evals/importers/librispeech.py:_get->httpx.get(timeout)",
         "evals/importers/librispeech.py:audio_getter.get->httpx.get(timeout)",
         "evals/importers/librispeech.py:build_manifest->httpx.get(timeout)")


@pytest.mark.parametrize("site", SITES)
def test_a_download_past_its_timeout_is_a_cut_of_that_call_and_still_raises(site, monkeypatch, tmp_path):
    monkeypatch.setattr(httpx, "get", _timeout)
    monkeypatch.setattr(librispeech, "_src", lambda row: "https://example.invalid/clip.flac")
    pages = iter([[{"row_idx": 0, "row": {"id": "u1", "text": "one two three four"}}], []])
    calls = {SITES[0]: lambda: leetcode._get("https://example.invalid/x"),
             SITES[1]: lambda: squad2.load(tmp_path),
             SITES[2]: lambda: librispeech._get({}),
             SITES[3]: lambda: (monkeypatch.setattr(librispeech, "_page", lambda o, n: [
                 {"row_idx": 0, "row": {}}]), librispeech.audio_getter()(0)),
             SITES[4]: lambda: (monkeypatch.setattr(librispeech, "_page", lambda o, n: next(pages)),
                                librispeech.build_manifest(tmp_path / "cache", n=1))}
    with pytest.raises(httpx.ReadTimeout):
        calls[site]()
    assert _knobs() == [site]


def test_a_download_that_fails_otherwise_is_no_cut(monkeypatch):
    def refused(*a, **k):
        raise httpx.ConnectError("refused")
    monkeypatch.setattr(httpx, "get", refused)
    with pytest.raises(httpx.ConnectError):
        leetcode._get("https://example.invalid/x")
    assert _spooled() == []


def _squad(*answers_per_para: str) -> dict:
    paras = [{"context": f"The answer here is {a}.", "qas": [{"id": f"q{i}", "question": "what?",
                                                               "answers": [{"text": a}], "is_impossible": False}]}
             for i, a in enumerate(answers_per_para)]
    return {"data": [{"title": "t", "paragraphs": paras}]}


def test_a_paragraph_whose_answers_are_too_long_is_a_cut_of_the_word_limit():
    assert len(squad2_extract.select(_squad("blue", "red"), n=5)) == 2
    assert _spooled() == []
    long = " ".join(["word"] * (squad2_extract.MAX_WORDS + 1))
    assert len(squad2_extract.select(_squad("blue", long), n=5)) == 1
    assert [(r["knob"], r["dropped"]) for r in _spooled()] == [("evals/importers/squad2_extract.py:MAX_WORDS", 1)]


def test_the_census_scan_records_each_window_gap_slack_and_fit_limit_that_bound(census_root, monkeypatch):
    d.scan(census_root, census_t.NOW)
    got = {r["knob"]: r["dropped"] for r in _spooled()}
    assert got == {"demand_days": 2, "demand_idle_gap": 1, "demand_cost_slack": 2, "demand_min_final": got.get(
        "demand_min_final")} and got["demand_min_final"] > 0
    cuts._spool_path().unlink()
    for name in ("IDLE_GAP_S", "COST_SLACK_S"):
        monkeypatch.setattr(d, name, 10 ** 9)
    d.scan(census_root, census_t.NOW, days=40)
    assert _knobs() == ["demand_min_final"]


def test_the_output_fit_skipped_for_too_few_final_counts_is_a_cut_only_with_partials_to_estimate():
    final = [d.Msg(out=10, final=True, visible=i, signature=0) for i in range(d.MIN_FINAL - 1)]
    d.output_model(final)
    assert _spooled() == []
    d.output_model(final + [d.Msg(out=3, final=False)])
    assert [(r["knob"], r["kept"], r["dropped"]) for r in _spooled()] == [("demand_min_final", d.MIN_FINAL - 1, 1)]


def _unit(i: int, project: str, tokens: int) -> d.Unit:
    u = d.Unit(f"k{project}{i}", "main", "s", "main", float(i), tokens_out_recorded=tokens)
    u.project = project
    return u


def test_the_floor_is_a_cut_only_when_it_moves_draws_off_proportional_shares():
    even = [_unit(i, p, 100) for p in ("a", "b") for i in range(5)]
    d.draw(even, n=4)
    assert _spooled() == []
    skewed = [_unit(i, "a", 9000) for i in range(5)] + [_unit(i, "b", 1) for i in range(5)]
    d.draw(skewed, n=4, floor=0)
    assert _spooled() == []
    d.draw(skewed, n=4)
    assert [(r["knob"], r["dropped"]) for r in _spooled()] == [("demand_floor", 1)]


def test_packet_caps_record_what_they_cut_from_the_labellers_view(census_root, tmp_path, monkeypatch):
    packet_knobs = {"demand_request_cap", "demand_result_cap", "demand_step_cap", "demand_steps"}
    d.census(tmp_path / "a", census_root, census_t.NOW, n=4, known=census_t.KNOWN)
    assert not packet_knobs & set(_knobs())
    cuts._spool_path().unlink()
    for name, value in (("REQUEST_CAP", 5), ("RESULT_CAP", 2), ("STEP_CAP", 4), ("STEPS", 1)):
        monkeypatch.setattr(d, name, value)
    frame = d.census(tmp_path / "b", census_root, census_t.NOW, n=4, known=census_t.KNOWN)
    assert packet_knobs <= set(_knobs())
    packets = [json.loads(line) for line in (tmp_path / "b" / "packets-a.jsonl").read_text(encoding="utf-8").splitlines()]
    assert frame["n"] == len(packets) and all(len(p["steps"]) <= 1 and all(len(s) <= 4 for s in p["steps"])
                                              for p in packets)


def test_a_long_step_is_cut_only_in_the_packet(census_root):
    units, _ = d.scan(census_root, census_t.NOW)
    step = d._step("Bash", {"command": "x" * (d.STEP_CAP * 2)})
    assert len(step) > d.STEP_CAP
    u = units[0]
    u.steps = [step]
    p = d.packet(u, "P1", census_t.KNOWN)
    assert p["steps"] == [step[:d.STEP_CAP]]


def test_a_replay_result_past_its_cap_is_a_cut_in_prepare_and_in_wrong_plants(replay_world, monkeypatch):
    _packets(replay_world)
    assert "replay_result_cap" not in _knobs()
    monkeypatch.setattr(rp, "RESULT_CAP", 4)
    (replay_world["out"] / "packets.jsonl").unlink()
    ps = list(_packets(replay_world).values())
    assert _knobs() == ["replay_result_cap"]
    cuts._spool_path().unlink()
    rp.calibrate(replay_world["out"], ps, _judges(True), known=KNOWN)
    assert [(r["knob"], r["dropped"]) for r in _spooled()] == [("replay_result_cap", len(ps))]


def test_a_judge_call_past_its_timeout_is_a_cut_and_the_timeout_still_raises():
    def ok(argv, **kw):
        return SimpleNamespace(stdout=json.dumps({"type": "result", "result": "fine"}), returncode=0)

    def slow(argv, **kw):
        raise subprocess.TimeoutExpired(argv, kw["timeout"])
    rp.claude("p", "s", execute=ok)
    assert _spooled() == []
    with pytest.raises(subprocess.TimeoutExpired):
        rp.claude("p", "s", execute=slow, timeout=3)
    assert [(r["knob"], r["value"]) for r in _spooled()] == [("replay_judge_timeout", 3.0)]
