"""A frontier model through headless Claude Code. #359."""
import json

import pytest

from evals import run
from evals.core import Case
from evals.runners.base import RunnerError
from evals.runners.claude_code import ClaudeCodeRunner
from harness import completion


def case():
    return Case(id="add", modality="code", prompt="Write add(a, b).",
                assertions={"checks": ["add(2, 3) == 5"]})


class Proc:
    def __init__(self, body, rc=0, stderr=""):
        self.stdout = body if isinstance(body, str) else json.dumps(body)
        self.returncode, self.stderr = rc, stderr


def fake(body, rc=0, seen=None):
    def run_(argv, **kw):
        if seen is not None:
            seen.update(argv=argv, kw=kw)
        return Proc(body, rc)
    return run_


def test_the_lane_prompt_replaces_claude_codes_own_and_tools_are_off():
    seen = {}
    r = ClaudeCodeRunner("claude-opus-5-5", execute=fake({"result": "x"}, seen=seen))
    r.generate(case())
    argv = seen["argv"]
    assert argv[argv.index("--system-prompt") + 1] == completion.SYSTEM["code"]
    assert argv[-2:] == ["--tools", ""], "--tools last, or it swallows the prompt"
    assert "--bare" not in argv, "--bare skips the subscription login"
    assert argv[argv.index("--model") + 1] == "claude-opus-5-5"
    assert seen["kw"]["cwd"], "runs in an empty directory, not this repo"


def test_the_answer_and_its_throughput_come_back():
    r = ClaudeCodeRunner("m", execute=fake({"result": "def add(a, b): return a + b",
                                        "usage": {"output_tokens": 20}}))
    text, peak = r.generate(case())
    assert "def add" in text and peak == 0
    assert r.extra_metrics()["completion_tokens"] == 20


@pytest.mark.parametrize("body,rc", [
    ({"is_error": True, "result": "Not logged in"}, 1),
    ({"result": "   "}, 0),
    ("Error: Input must be provided", 1),
])
def test_a_failure_is_a_failed_row_not_a_crash(body, rc):
    with pytest.raises(RunnerError):
        ClaudeCodeRunner("m", execute=fake(body, rc)).generate(case())


def test_the_candidate_kind_runs_every_text_lane():
    assert run.kind_of("claude-code:claude-opus-5-5") == run.CLAUDE_CODE_PREFIX
    cases = [Case(id=m, modality=m, prompt="p") for m in ("code", "web", "image")]
    got = {c.modality for c in run.cases_for("claude-code:claude-opus-5-5", cases)}
    assert got == {"code", "web"}


def test_the_runner_reports_its_spec_as_the_candidate():
    r = run.build_runner("claude-code:claude-opus-5-5", "http://gw", None)
    assert isinstance(r, ClaudeCodeRunner) and r.candidate == "claude-code:claude-opus-5-5"


def test_the_runner_keeps_the_base_run_method():
    """Storing the subprocess function as `self.run` shadowed BaseRunner.run,
    and the first real case died with 'Case' object is not iterable."""
    r = ClaudeCodeRunner("m", execute=fake({"result": "def add(a, b): return a + b"}))
    row = r.run(case())
    assert row.candidate == "claude-code:m" and row.passed, row.detail


def test_one_empty_result_is_retried_and_recorded():
    """#366: 1 in 45 calls came back empty and never reproduced."""
    bodies = iter([{"result": ""}, {"result": "def add(a, b): return a + b",
                                    "usage": {"output_tokens": 9}}])
    r = ClaudeCodeRunner("m", execute=lambda argv, **kw: Proc(next(bodies)))
    text, _ = r.generate(case())
    assert "def add" in text and r.extra_metrics()["retries"] == 1


def test_empty_twice_is_the_models_answer():
    r = ClaudeCodeRunner("m", execute=fake({"result": ""}))
    with pytest.raises(RunnerError, match="twice"):
        r.generate(case())
