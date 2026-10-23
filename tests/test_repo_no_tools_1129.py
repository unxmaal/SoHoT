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
#: The system prompt every repo run before #1129 sent; runs 472 and 557 record its sha.
OLD_SYSTEM = ("You fix issues in a software repository. You output one unified diff that git "
              "apply accepts, with a/ and b/ paths from the repository root, and nothing else.")
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


def _pre_1129(monkeypatch):
    """The request as it was before #1129: the old system prompt, the session unquoted."""
    monkeypatch.setitem(completion.SYSTEM, "repo", OLD_SYSTEM)
    monkeypatch.setattr(repo, "quoted", lambda prompt: prompt)


def test_every_case_is_told_it_has_no_tools():
    assert len(CASES) == 128 and _sha(OLD_SYSTEM) == OLD_SYSTEM_SHA
    for c in CASES:
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
    spec = next(c for c in CASES if c.params.get("variant") == "spec")
    assert repo.as_asked(spec).prompt == spec.prompt


def test_every_cases_request_digest_moves(monkeypatch):
    picked = [next(c for c in CASES if c.params.get("variant") == v) for v in ("spec", "symptom", "request")]
    now = identity.case_digests("llamacpp:x", picked, 32768)
    _pre_1129(monkeypatch)
    before = identity.case_digests("llamacpp:x", picked, 32768)
    assert [now[c.id] != before[c.id] for c in picked] == [True] * 3


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
    assert sent[1]["system"] == completion.SYSTEM["repo"] and sent[1]["prompt"].startswith(upstream.prompt)


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
    grades, systems = [], []
    for old in (False, True):
        if old:
            _pre_1129(monkeypatch)
        r, sent = _sent(monkeypatch, fix)
        row = r.run(_session_case(upstream))
        grades.append((row.passed, row.failure_class, json.loads(row.output)["grade"]))
        systems.append(sent[0]["system"])
    assert systems[1] == OLD_SYSTEM != systems[0]
    assert grades[0] == grades[1] and grades[0][0] is True


def test_claude_code_is_asked_the_same_system_prompt_and_quotation(upstream, claude):
    from tests.test_repo_claude_905 import _runner
    _runner(claude, "no diff").run(_session_case(upstream))
    argv = json.loads((claude / "argv.json").read_text(encoding="utf-8"))
    assert argv[argv.index("--system-prompt") + 1] == completion.SYSTEM["repo"]
    assert (claude / "stdin.txt").read_text(encoding="utf-8").startswith(repo.QUOTE_HEAD)


def test_the_cause_table_reads_the_runners_tool_call_class():
    from evals.analysis import repo_failures as F
    row = {"passed": False, "failure_class": reasons.TOOL_CALL, "detail": "the reply holds no diff"}
    assert F.cause(row, {"reply": TOOL_REPLY, "diff": ""}) == "tool_call"
    assert reasons.TOOL_CALL in F.TALLY


def test_a_session_cases_request_digest_covers_its_quotation(monkeypatch):
    session = next(c for c in CASES if c.params.get("variant") == repo.SESSION_VARIANT)
    now = identity.case_digests("llamacpp:x", [session], 32768)
    monkeypatch.setattr(repo, "quoted", lambda prompt: prompt)
    assert identity.case_digests("llamacpp:x", [session], 32768) != now
