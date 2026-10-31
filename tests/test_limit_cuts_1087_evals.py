"""The evals limits record a limit_cuts row when they bind, and none when they do not (#1087)."""
from __future__ import annotations

import argparse
import json
import subprocess
import threading
import time

import httpx
import pytest

from harness import completion, cuts, reasons


def _spooled() -> list[tuple]:
    path = cuts._spool_path()
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    return [(r["knob"], r["kept"], r["dropped"]) for r in map(json.loads, lines)]


def _knobs() -> list[str]:
    return [k for k, _, _ in _spooled()]


def _expired(*a, **kw):
    raise subprocess.TimeoutExpired(a[0] if a else "cmd", kw.get("timeout") or 1)


def _done(stdout="true"):
    return lambda *a, **kw: subprocess.CompletedProcess(a[0] if a else [], 0, stdout=stdout, stderr="")


def test_a_git_probe_that_times_out_on_a_claims_export_is_a_cut(tmp_path, monkeypatch):
    from evals import claims_import
    monkeypatch.setattr(claims_import.subprocess, "run", _done())
    assert claims_import._in_git(tmp_path) is True
    assert _spooled() == []
    monkeypatch.setattr(claims_import.subprocess, "run", _expired)
    assert claims_import._in_git(tmp_path) is False
    assert _spooled() == [("evals/claims_import.py:_in_git->subprocess.run(timeout)", 0, 1)]


def test_a_receipt_probe_that_times_out_is_a_cut(monkeypatch):
    from evals import environment
    monkeypatch.setattr(environment.subprocess, "run", _done("x"))
    assert environment._sh("git", "status") == "x"
    assert _spooled() == []
    monkeypatch.setattr(environment.subprocess, "run", _expired)
    assert environment._sh("git", "status") == ""
    assert _spooled() == [("evals/environment.py:_sh->subprocess.run(timeout)", 0, 1)]


def test_a_git_archive_of_the_repo_cases_that_times_out_is_a_cut(tmp_path, monkeypatch):
    from evals import repo_report
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: subprocess.CompletedProcess(a[0], 1, b"", b""))
    assert repo_report.cases_at("abc", tmp_path) == []
    assert _spooled() == []
    monkeypatch.setattr(subprocess, "run", _expired)
    assert repo_report.cases_at("abc", tmp_path) == []
    assert _spooled() == [("evals/repo_report.py:cases_at->subprocess.run(timeout)", 0, 1)]


def test_a_decide_corpus_read_that_times_out_is_a_cut_and_a_refused_connect_is_not(monkeypatch):
    from evals import decide_corpus as dc
    monkeypatch.setattr(time, "sleep", lambda s: None)
    raised = iter([httpx.ConnectError("refused"), httpx.ReadTimeout("slow")])

    def get(url, **kw):
        for exc in raised:
            raise exc
        return httpx.Response(200, request=httpx.Request("GET", url))
    monkeypatch.setattr(httpx, "get", get)
    assert dc._get("http://x/y").status_code == 200
    assert _spooled() == [("evals/decide_corpus.py:_get->httpx.get(timeout)", 0, 1)]


def test_manifest_rows_past_the_read_limit_are_a_cut_only_when_enough_was_never_found(monkeypatch):
    from evals import decide_corpus as dc
    monkeypatch.setattr(dc, "hf_row", lambda *a: {"i": a[-1]})
    ids = [f"r-{i}" for i in range(5)]
    assert len(dc._indexed(ids, "d", "c", "s", lambda got: len(got) == 2, limit=3)) == 2
    assert len(dc._indexed(ids, "d", "c", "s", lambda got: False, limit=5)) == 5
    assert _spooled() == []
    assert len(dc._indexed(ids, "d", "c", "s", lambda got: False, limit=3)) == 3
    assert _spooled() == [("evals/decide_corpus.py:_indexed(limit)", 3, 2)]


def test_helpsteer_rows_too_long_to_rate_are_a_cut_on_the_recorded_pick_only():
    from evals import decide_corpus as dc
    rows = {"a": {"prompt": "p1", "response": "short"},
            "b": {"prompt": "p2", "response": "x" * dc.MAX_CHARS},
            "c": {"prompt": "p3", "response": "short"}}
    assert dc.pick_rate(list(rows), rows, n=5) == ["a", "c"]
    assert dc.pick_rate(["a", "c"], rows, n=5, record=True) == ["a", "c"]
    assert _spooled() == []
    assert dc.pick_rate(list(rows), rows, n=5, record=True) == ["a", "c"]
    assert _spooled() == [("evals/decide_corpus.py:MAX_CHARS", 2, 1)]


def test_a_repo_git_step_that_times_out_is_a_cut(monkeypatch):
    from evals import repo
    monkeypatch.setattr(repo.subprocess, "run", _done(b""))
    repo._git(["status"])
    assert _spooled() == []
    monkeypatch.setattr(repo.subprocess, "run", _expired)
    with pytest.raises(subprocess.TimeoutExpired):
        repo._git(["status"])
    assert _spooled() == [("repo_git_timeout", 0, 1)]


def test_an_environment_build_that_times_out_is_a_cut(tmp_path, monkeypatch):
    from evals import repo
    task = tmp_path / "task"
    task.mkdir()
    (task / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    monkeypatch.setattr(repo, "cache_root", lambda: tmp_path / "cache")
    monkeypatch.setattr(repo.subprocess, "run", _expired)
    with pytest.raises(repo.RepoEnvError, match="timed out"):
        repo.prepare(task)
    assert _spooled() == [("repo_env_timeout", 0, 1)]


def test_documentation_hunks_left_out_are_a_cut_and_a_clean_apply_is_not(tmp_path):
    from evals import repo
    from tests.test_repo_doc_hunk_1107 import CODE, STALE_README, _case
    from tests.test_repo_lane import _here
    for name, diff, want in (("clean", CODE, []), ("stale", CODE + STALE_README, [("repo_doc_patterns", 1, 1)])):
        a = repo.Attempt.open(_case(tmp_path / name).params, env=_here)
        try:
            assert repo.apply_docs_aside(a.task, diff, lambda p: False)[0]
        finally:
            a.close()
        assert _spooled() == want


def test_a_screen_declined_short_of_the_outside_votes_is_a_cut_of_the_votes():
    from tests.test_repo_screen_1176 import _verdict
    assert _verdict([1, 1, 0, 0], [[0], [0], [1], [0]], votes=0)["verdict"] == "declined"
    assert _verdict([1, 1, 0, 0], [[0], [0], [1], [0]], votes=3)["verdict"] == "rerun"
    assert _spooled() == []
    assert _verdict([1, 1, 0, 0], [[0], [0], [1], [0]], votes=2)["verdict"] == "declined"
    assert _spooled() == [("screen_outside_votes", None, 1)]


def test_a_screen_declined_after_its_reruns_is_a_cut_of_the_repeats():
    from tests.test_repo_screen_1176 import _verdict
    tie = _verdict([1, 0, 0, 0], [[1, 1, 1, 1], [0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]], draws=4, votes=3)
    assert tie["verdict"] == "survives" and _spooled() == []
    v = _verdict([1, 1, 0, 0], [[0, 0, 0, 0], [0, 1, 0, 0], [1, 0, 0, 0], [0, 0, 0, 0]], draws=4, votes=3)
    assert v["verdict"] == "declined"
    assert _spooled() == [("screen_repeats", 4, 1)]


def test_a_warm_up_that_outlasts_the_gateway_wait_is_a_cut_and_one_that_recovers_is_not(monkeypatch):
    from evals import run
    from evals.runners.base import RunnerError
    from tests.test_router_down_1181 import Clock, Refusing, _connect_refused
    monkeypatch.setattr(run, "GATEWAY_DOWN_WAIT_S", 3.0)

    class Recovers(Refusing):
        def warm(self):
            if self.calls < 2:
                return super().warm()
            self.calls += 1
    clock = Clock()
    run.warm(Recovers(_connect_refused), clock=clock, sleep=clock.sleep)
    assert _spooled() == []
    clock = Clock()
    with pytest.raises(RunnerError):
        run.warm(Refusing(_connect_refused), clock=clock, sleep=clock.sleep)
    assert _spooled() == [("gateway_down_wait", 0, 1)]


def _events(n, body="x" * 40):
    from evals.session_cut import Event
    out = [Event(0.0, "user", body="the request")]
    for i in range(n):
        out += [Event(float(i), "call", name="Read", input={"file_path": f"f{i}"}, ref=f"c{i}"),
                Event(float(i), "result", name="Read", body=body, ref=f"c{i}")]
    return out


def test_a_transcript_cut_past_its_budget_is_a_cut_when_the_importer_names_the_knob():
    from evals import session_cut
    session_cut.render(_events(50), budget=10 ** 6, budget_knob="transcripts_cut_budget")
    session_cut.render(_events(50), budget=300)
    assert _spooled() == []
    session_cut.render(_events(50), budget=300, budget_knob="transcripts_cut_budget")
    [(knob, kept, dropped)] = _spooled()
    assert knob == "transcripts_cut_budget" and kept + dropped == 51 and dropped > 0


def test_tool_outputs_past_the_output_cap_are_one_cut_per_render():
    from evals import session_cut
    session_cut.render(_events(3), cap=100)
    assert _spooled() == []
    session_cut.render(_events(3, body="word " * 100), cap=100)
    assert _spooled() == [("transcripts_cut_output_cap", None, 3)]


def test_command_outputs_past_the_command_cap_alone_are_a_cut_of_it():
    from evals import session_cut
    from evals.session_cut import Event

    def bash(n):
        return [Event(0.0, "user", body="go"), Event(1.0, "call", name="Bash", input={"command": "make"}, ref="b"),
                Event(1.0, "result", name="Bash", body="y" * n, ref="b")]
    session_cut.render(bash(session_cut.COMMAND_CAP_BYTES), cap=session_cut.COMMAND_CAP_BYTES * 2)
    assert _spooled() == []
    session_cut.render(bash(session_cut.COMMAND_CAP_BYTES + 1), cap=session_cut.COMMAND_CAP_BYTES * 2)
    assert _spooled() == [("transcripts_cut_command_cap", None, 1)]


def test_added_fix_lines_too_short_to_count_as_a_leak_are_a_cut():
    from evals import session_cut
    long = "value = compute_the_total(items)"
    diff = f"+++ b/m.py\n+{long}\n+    \n+old_line_already_at_base_here\n"
    assert session_cut.added_lines(diff, {"m.py": "old_line_already_at_base_here"}) == [long]
    assert _spooled() == []
    assert session_cut.added_lines(diff + "+x = 1\n", {"m.py": ""}) == sorted([long, "old_line_already_at_base_here"])
    assert _spooled() == [("transcripts_leak_min_chars", 2, 1)]


def test_a_swebench_fetch_or_completion_that_times_out_is_a_cut(monkeypatch):
    from evals import swebench

    def slow(*a, **kw):
        raise httpx.ReadTimeout("slow")
    monkeypatch.setattr(httpx, "get", slow)
    monkeypatch.setattr(httpx, "post", slow)
    with pytest.raises(httpx.ReadTimeout):
        swebench._fetch("http://x/results.json")
    with pytest.raises(httpx.ReadTimeout):
        swebench.complete("http://x", "p", 8)
    assert _knobs() == ["swebench_fetch_timeout", "swebench_completion_timeout"]


def test_swellama_replies_stopped_at_n_predict_are_one_cut_per_predict(tmp_path):
    from evals import swebench
    from tests.test_swebench_922 import _run_dir
    prompts = tmp_path / "prompts.jsonl"
    swebench.write_jsonl(prompts, [{"instance_id": f"o__r-{i}", "text": "Fix it.\n"} for i in range(3)])
    stopped = iter([False, True, True])

    def post(url, payload):
        return {"content": "", "stopped_limit": next(stopped)}

    def args(run):
        return argparse.Namespace(run_dir=str(run), server="http://127.0.0.1:1", model="m", weights="w", quant="",
                                  prompts=str(prompts), max_tokens=123, limit=0)
    swebench.cmd_predict(args(_run_dir(tmp_path / "a", ["o__r-0"])), post=post, get=lambda u: {})
    assert _spooled() == []
    swebench.cmd_predict(args(_run_dir(tmp_path / "b", ["o__r-1", "o__r-2"])), post=post, get=lambda u: {})
    assert _spooled() == [("swebench_max_tokens", None, 2)]


def test_a_calibration_refused_agreement_is_a_cut_of_the_threshold_that_refused_it():
    from evals import swebench
    ids = [f"i{k}" for k in range(20)]
    same = {i: {"applied": True} for i in ids}
    swebench.paired(ids, same, same, "applied")
    assert _spooled() == []
    ours = {i: {"applied": k < 4} for k, i in enumerate(ids)}
    assert not swebench.paired(ids, ours, same, "applied")["agrees"]
    assert _knobs() == ["swebench_margin", "swebench_alpha"]


def test_claude_p_empty_after_its_retry_is_a_cut_of_the_retry():
    from evals.runners.base import RunnerError
    from evals.runners.claude_code import ClaudeCodeRunner
    from tests.test_claude_code_runner import Proc, case, fake
    bodies = iter([{"result": ""}, {"result": "def add(a, b): return a + b"}])
    ClaudeCodeRunner("m", execute=lambda argv, **kw: Proc(next(bodies))).generate(case())
    assert _spooled() == []
    with pytest.raises(RunnerError, match="twice"):
        ClaudeCodeRunner("m", execute=fake({"result": ""})).generate(case())
    assert _spooled() == [("evals/runners/claude_code.py:ClaudeCodeRunner._answer->self._once(retries)#2", 0, 1)]


class _Pipe:
    def __init__(self, gate):
        self.gate = gate

    def read(self):
        self.gate.wait(10)
        return ""

    def write(self, text):
        return len(text)

    def close(self):
        pass


def test_a_claude_p_pipe_reader_left_running_past_the_join_is_a_cut(monkeypatch):
    from evals.runners import claude_code
    gate = threading.Event()

    class Popen:
        def __init__(self, argv, **kw):
            self.stdin, self.stderr, self.stdout, self.returncode = _Pipe(threading.Event()), _Pipe(gate), iter(["{}"]), 0

        def wait(self):
            return 0

        def kill(self):
            pass
    gate.set()
    monkeypatch.setattr(claude_code.subprocess, "Popen", Popen)
    claude_code.stream_run(["claude"], cwd=".", input="", timeout=60)
    assert _spooled() == []
    gate.clear()
    try:
        claude_code.stream_run(["claude"], cwd=".", input="", timeout=60)
    finally:
        gate.set()
    assert _spooled() == [("evals/runners/claude_code.py:stream_run->t.join(timeout)", 1, 1)]


def test_an_omnisvg_run_past_its_timeout_is_a_cut(tmp_path, monkeypatch):
    from evals.runners import omnisvg
    from evals.runners.base import RunnerError
    from tests.test_evals_runner_omnisvg import WRITES_SVG, case, checkout
    monkeypatch.setattr(omnisvg, "cached", lambda repo, name: tmp_path)
    runner = omnisvg.OmniSVGRunner("4B", root=checkout(tmp_path, WRITES_SVG))
    assert runner.run(case()).passed
    assert _spooled() == []
    monkeypatch.setattr(omnisvg.proc, "run", _expired)
    with pytest.raises(RunnerError, match="exceeded"):
        runner.generate(case())
    assert _spooled() == [("evals/runners/omnisvg.py:TIMEOUT", 0, 1)]


def _repair(monkeypatch, replies):
    from evals.runners import repair
    from tests.test_evals_runner_repair import case

    def complete(prompt, **kw):
        got = next(replies)
        if isinstance(got, Exception):
            raise got
        return got, {"completion_tokens": 1}
    monkeypatch.setattr(repair.completion, "complete_with_usage", complete)
    return repair.RepairRunner("http://gw", "m", attempts=2), case()


def test_repair_attempts_run_out_on_a_failing_artifact_is_a_cut(monkeypatch):
    from tests.test_evals_runner_repair import BAD, GOOD
    runner, c = _repair(monkeypatch, iter([BAD, GOOD]))
    runner.generate(c)
    assert _spooled() == []
    runner, c = _repair(monkeypatch, iter([BAD, BAD]))
    runner.generate(c)
    assert _spooled() == [("evals/runners/repair.py:RepairRunner.__init__(attempts)", 2, None)]


def test_a_repair_attempt_that_times_out_is_a_cut_of_the_timeout(monkeypatch):
    from evals.runners.base import RunnerError
    from tests.test_evals_runner_repair import BAD
    runner, c = _repair(monkeypatch, iter([BAD, completion.CompletionError("busy", reasons.CONTENT_FAILED)]))
    with pytest.raises(RunnerError):
        runner.generate(c)
    assert _spooled() == []
    runner, c = _repair(monkeypatch, iter([BAD, completion.CompletionError("slow", reasons.TIMEOUT)]))
    with pytest.raises(RunnerError):
        runner.generate(c)
    assert _spooled() == [("evals/runners/repair.py:RepairRunner.__init__(timeout)", 1, 1)]
