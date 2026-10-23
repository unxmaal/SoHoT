"""Repo cases are told there are no tools, sessions are asked as quotations, tool-call replies get their own class. #1129."""
import dataclasses
import hashlib
import json
from pathlib import Path

import pytest

from evals import repo
from evals.core import load_cases
from evals.runners.repo import RepoRunner
from evals.session_cut import HEAD
from harness import completion, identity, reasons
from tests.test_repo_claude_905 import claude  # noqa: F401
from tests.test_repo_lane import BUGGY, DARWIN, FIXED, _diff, _here, upstream  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
CASES = load_cases(ROOT / "evals" / "cases" / "repo")
#: The system_sha every repo run before #1129 records (runs 472 and 557 among them).
OLD_SYSTEM_SHA = "b2f319c893bb6405"
SESSION = ("## user\nfix add\n\n## assistant\nLet me look.\n\n## tool Bash\n$ cat pkg/mod.py\n"
           "[40 bytes of output not shown]\n\n## assistant\nadd subtracts.")
TOOL_REPLY = ("I'll start by exploring the repository structure.<tool_call>\n<function=command>\n"
              "<parameter=command>\ncd /testbed && ls\n</parameter>\n</function>\n</tool_call>")


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _unquote(asked: str) -> str:
    body = asked[len(repo.QUOTE_HEAD):-len(repo.QUOTE_END)]
    return "\n".join(line[2:] if line.startswith("> ") else "" for line in body.splitlines())


def test_the_old_exams_cases_are_asked_byte_identically():
    old = [c for c in CASES if c.id in repo.LEGACY]
    assert len(old) == len(repo.LEGACY) == 39
    for c in old:
        asked = repo.as_asked(c)
        assert asked.prompt == c.prompt
        assert _sha(asked.params["system"]) == OLD_SYSTEM_SHA


def test_every_other_case_is_told_it_has_no_tools():
    new = [c for c in CASES if c.id not in repo.LEGACY]
    assert len(new) == 89
    for c in new:
        system = repo.as_asked(c).params["system"]
        assert "no tools" in system and "one unified diff" in system
        assert _sha(system) != OLD_SYSTEM_SHA


def test_a_session_is_asked_as_a_quotation_that_loses_nothing():
    sessions = [c for c in CASES if c.params.get("variant") == repo.SESSION_VARIANT]
    assert len(sessions) == 25
    for c in sessions:
        asked = repo.as_asked(c).prompt
        assert asked.startswith(repo.QUOTE_HEAD) and asked.endswith(repo.QUOTE_END)
        assert not [line for line in asked.splitlines() if line.startswith("## ")], c.id
        assert _unquote(asked) == c.prompt[len(HEAD):].strip("\n")
    spec = next(c for c in CASES if c.id not in repo.LEGACY and c.params.get("variant") == "spec")
    assert repo.as_asked(spec).prompt == spec.prompt


def test_only_the_new_cases_request_digests_move(monkeypatch):
    old = [c for c in CASES if c.id in repo.LEGACY][:3] + [c for c in CASES if c.id not in repo.LEGACY][:3]
    now = identity.case_digests("llamacpp:x", old, 32768)
    monkeypatch.setitem(completion.SYSTEM, "repo", repo.LEGACY_SYSTEM)
    monkeypatch.setattr(repo, "quoted", lambda prompt: prompt)
    before = identity.case_digests("llamacpp:x", old, 32768)
    assert [now[c.id] == before[c.id] for c in old] == [True] * 3 + [False] * 3


def _session_case(upstream, **params):
    return dataclasses.replace(upstream, id="mcm-engine-pr1-request", prompt=HEAD + SESSION,
                               params={**upstream.params, "variant": repo.SESSION_VARIANT, **params})


def _sent(monkeypatch, reply):
    """A RepoRunner whose fake model records each request's system prompt and user message."""
    sent = []

    def answer(prompt, **kw):
        sent.append({"system": kw.get("system"), "prompt": prompt})
        return completion.Completion(reply, {}, [])
    monkeypatch.setattr(completion, "complete_full", answer)
    r = RepoRunner("http://unused", "fake")
    r.attempt = lambda params: repo.Attempt.open(params, env=_here)
    return r, sent


def test_the_model_is_sent_the_no_tools_system_and_the_quoted_session(upstream, monkeypatch):
    r, sent = _sent(monkeypatch, TOOL_REPLY)
    r.run(_session_case(upstream))
    assert sent[0]["system"] == completion.SYSTEM["repo"]
    assert sent[0]["prompt"].startswith(repo.QUOTE_HEAD) and "\n> ## tool Bash\n" in sent[0]["prompt"]
    assert "def add(a, b)" in sent[0]["prompt"] and sent[0]["prompt"].endswith(repo.REPLY)
    r.run(dataclasses.replace(upstream, id="sohot-363-spec"))
    assert sent[1]["system"] == repo.LEGACY_SYSTEM and sent[1]["prompt"].startswith(upstream.prompt)


@pytest.mark.parametrize("reply, cls", [
    (TOOL_REPLY, reasons.TOOL_CALL),
    ("I would change add to use +.", reasons.INVALID_PATCH),
    (TOOL_REPLY + "\n```diff\n" + _diff("def nothing():\n    pass\n", "def nothing():\n    return 1\n") + "```",
     reasons.INVALID_PATCH),
])
def test_a_reply_that_only_calls_tools_is_its_own_class(upstream, monkeypatch, reply, cls):
    r, _ = _sent(monkeypatch, reply)
    row = r.run(_session_case(upstream))
    assert not row.passed and row.failure_class == cls, row.detail
    assert reasons.CLASSES[reasons.TOOL_CALL] == reasons.CLASSES[reasons.INVALID_PATCH]


@DARWIN
def test_the_fix_of_a_tool_call_case_grades_the_same_under_either_prompt(upstream, monkeypatch):
    fix = f"```diff\n{_diff(BUGGY, FIXED)}```"
    grades = []
    for case in (_session_case(upstream), dataclasses.replace(upstream, id="sohot-363-spec")):
        r, sent = _sent(monkeypatch, fix)
        row = r.run(case)
        grades.append((row.passed, row.failure_class, json.loads(row.output)["grade"]))
    assert grades[0] == grades[1] and grades[0][0] is True


def test_claude_code_is_given_the_same_system_prompt_per_case(upstream, claude):
    from tests.test_repo_claude_905 import _runner
    for case, system in ((_session_case(upstream), completion.SYSTEM["repo"]),
                         (dataclasses.replace(upstream, id="sohot-363-spec"), repo.LEGACY_SYSTEM)):
        _runner(claude, "no diff").run(case)
        argv = json.loads((claude / "argv.json").read_text(encoding="utf-8"))
        assert argv[argv.index("--system-prompt") + 1] == system


def test_the_cause_table_reads_the_runners_tool_call_class():
    from evals.analysis import repo_failures as F
    row = {"passed": False, "failure_class": reasons.TOOL_CALL, "detail": "the reply holds no diff"}
    assert F.cause(row, {"reply": TOOL_REPLY, "diff": ""}) == "tool_call"
    assert reasons.TOOL_CALL in F.TALLY
