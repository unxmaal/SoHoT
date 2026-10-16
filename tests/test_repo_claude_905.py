"""The repo lane takes a claude-code candidate for its one patch-only call, built-in tools off. #905."""
import json
import os
import sys

import pytest

from evals import repo, run
from evals.runners.repo import ClaudeRepoRunner
from harness import reasons
from tests.test_repo_lane import BUGGY, FIXED, _diff, _here, upstream  # noqa: F401

FAKE = """#!{python}
import json, sys
from pathlib import Path
here = Path(__file__).parent
(here / "argv.json").write_text(json.dumps(sys.argv[1:]))
(here / "stdin.txt").write_text(sys.stdin.read())
reply = (here / "reply.txt").read_text()
print(json.dumps({{"type": "stream_event", "event": {{"delta": {{"type": "text_delta", "text": "x"}}}}}}))
print(json.dumps({{"type": "result", "result": reply, "is_error": False, "total_cost_usd": 0.0421,
                  "usage": {{"output_tokens": 50}}}}))
"""


@pytest.fixture
def claude(tmp_path):
    """A fake `claude` executable: records argv and stdin, answers with reply.txt as stream-json."""
    d = tmp_path / "fakeclaude"
    d.mkdir()
    exe = d / "claude"
    exe.write_text(FAKE.format(python=sys.executable), encoding="utf-8")
    exe.chmod(0o755)
    return d


def _runner(claude, reply):
    (claude / "reply.txt").write_text(reply, encoding="utf-8")
    r = ClaudeRepoRunner("claude-opus-5-5", binary=str(claude / "claude"))
    r.attempt = lambda params: repo.Attempt.open(params, env=_here)
    return r


def test_the_repo_lane_builds_a_claude_runner_for_a_claude_code_candidate():
    r = run._repo_runner("claude-code:claude-opus-5-5", "", 0)
    assert isinstance(r, ClaudeRepoRunner) and r.model == "claude-opus-5-5"
    with pytest.raises(SystemExit, match="needs a model"):
        run._repo_runner("claude-code:", "", 0)


def test_a_claude_reply_is_parsed_as_a_diff_and_graded_with_its_cost(upstream, claude):
    row = _runner(claude, f"Here is the fix.\n```diff\n{_diff(BUGGY, FIXED)}```\n").run(upstream)
    assert row.passed and row.metrics["resolved"] == 1 and row.metrics["patch_applied"] == 1
    assert row.metrics["cost_usd"] == 0.0421 and row.metrics["completion_tokens"] == 50
    assert row.candidate == "claude-code:claude-opus-5-5"
    asked = (claude / "stdin.txt").read_text(encoding="utf-8")
    assert "def add(a, b)" in asked and "test_add_hidden_marker" not in asked


def test_the_call_has_every_built_in_tool_mcp_server_and_setting_source_off(upstream, claude):
    _runner(claude, "no diff").run(upstream)
    argv = json.loads((claude / "argv.json").read_text(encoding="utf-8"))
    assert argv[-2:] == ["--tools", ""]
    assert "--strict-mcp-config" in argv and "--mcp-config" not in argv
    assert argv[argv.index("--setting-sources") + 1] == ""
    from harness import completion
    assert argv[argv.index("--system-prompt") + 1] == completion.SYSTEM["repo"]


def test_a_claude_reply_with_no_usable_diff_is_the_candidates_failure(upstream, claude):
    row = _runner(claude, "I would change add to use +.").run(upstream)
    assert not row.passed and row.failure_class == reasons.INVALID_PATCH


def test_a_missing_claude_binary_is_a_failed_row_not_a_crash(upstream, tmp_path):
    r = ClaudeRepoRunner("m", binary=os.fspath(tmp_path / "absent"))
    r.attempt = lambda params: repo.Attempt.open(params, env=_here)
    row = r.run(upstream)
    assert not row.passed and "could not run" in row.detail
