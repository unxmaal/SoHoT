"""Claude Code session requests linked to their merged commits, redacted, as repo cases. #1095."""
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from evals import redact
from evals.core import load_cases
from evals.importers import history
from evals.importers import transcripts as tr

ROOT = Path(__file__).resolve().parents[1]
T0 = 1_760_000_000
REQUEST = ("The importer drops every candidate when gh is down; make a gh failure raise instead, and "
           "mail someone.else@example.org the result")


def _iso(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).isoformat().replace("+00:00", "Z")


def _human(text, t, pid):
    return {"type": "user", "promptId": pid, "timestamp": _iso(t), "origin": {"kind": "human"},
            "userType": "external", "message": {"role": "user", "content": text}}


def _bash(command, output, t, pid, n):
    use = {"type": "assistant", "timestamp": _iso(t), "message": {"content": [
        {"type": "tool_use", "id": f"tu{n}", "name": "Bash", "input": {"command": command}}]}}
    res = {"type": "user", "promptId": pid, "timestamp": _iso(t), "message": {"content": [
        {"type": "tool_result", "tool_use_id": f"tu{n}", "content": output}]}}
    return [use, res]


def _write(path: Path, recs) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in recs), encoding="utf-8")


def _git(path, *args, at=None):
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"}
    if at is not None:
        env |= {"GIT_AUTHOR_DATE": f"@{int(at)} +0000", "GIT_COMMITTER_DATE": f"@{int(at)} +0000"}
    return subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True, text=True,
                          env=env).stdout.strip()


def _commit(path, files: dict, msg: str, at: float) -> str:
    for rel, body in files.items():
        (path / rel).parent.mkdir(parents=True, exist_ok=True)
        (path / rel).write_text(body, encoding="utf-8")
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "-m", msg, at=at)
    return _git(path, "rev-parse", "HEAD")


@pytest.fixture
def world(tmp_path):
    """A checkout of acme/widget with a feature commit, its squash on main, and a session that printed the first."""
    repos = tmp_path / "github"
    w = repos / "acme" / "widget"
    w.mkdir(parents=True)
    _git(w, "init", "-q", "-b", "main")
    _git(w, "remote", "add", "origin", "git@github.com:acme/widget.git")
    base = _commit(w, {"uv.lock": "x\n", "pkg/mod.py": "def f():\n    return 1\n",
                       "tests/test_mod.py": "from pkg.mod import f\n"}, "base", T0 - 100)
    _git(w, "checkout", "-q", "-b", "feat")
    feature = _commit(w, {"pkg/mod.py": "def f():\n    return 2\n",
                          "tests/test_mod.py": "from pkg.mod import f\ndef test_f():\n    assert f() == 2\n"},
                      "feat", T0 + 50)
    _git(w, "checkout", "-q", "main")
    _git(w, "merge", "-q", "--squash", "feat")
    squash = _commit(w, {}, "Fix f (#7)", T0 + 500)
    old = _commit(w, {"README": "old\n"}, "unrelated", T0 - 90_000)
    projects = tmp_path / "projects" / "-home-proj"
    main = projects / "s1.jsonl"
    _write(main, [_human(REQUEST, T0, "p1"),
                  *_bash("git -C x commit -m feat", f"[feat {feature[:7]}] feat\n 2 files changed", T0 + 60, "p1", 1),
                  *_bash("git log --oneline -3", f"{old[:7]} unrelated", T0 + 61, "p1", 2),
                  *_bash("git commit -m z", f"{old[:7]} printed but far older than this commit", T0 + 62, "p1", 3),
                  _human("merge it", T0 + 1000, "p2")])
    index = {"private": False, "prs": {7: ("MERGED", squash)}, "by_commit": {feature: [7]}}
    return {"tmp": tmp_path, "repos": repos, "repo": w, "projects": projects.parent, "main": main,
            "base": base, "feature": feature, "squash": squash, "old": old, "index": index}


def _survey(world, **kw):
    return tr.survey(world["projects"], [world["repos"]], world["tmp"] / "log",
                     known=redact.Known(accounts=("zorblat",)),
                     index_of=lambda r: world["index"], mirror_of=lambda r: world["repo"] / ".git", **kw)


def test_only_what_the_person_typed_is_a_request():
    assert tr.human_text(_human("do the thing", T0, "p")) == "do the thing"
    assert tr.human_text({**_human("x", T0, "p"), "origin": {"kind": "task-notification"}}) is None
    assert tr.human_text({**_human("x", T0, "p"), "isSidechain": True}) is None
    tool = _bash("ls", "out", T0, "p", 1)[1]
    assert tr.human_text(tool) is None
    old = {k: v for k, v in _human("typed before origin existed", T0, "p").items() if k != "origin"}
    assert tr.human_text(old) == "typed before origin existed"


def test_evidence_comes_only_from_the_command_that_wrote_it():
    assert tr.evidence_in("git commit -m x", "[b 1a2b3c4] x") == [("commit", "1a2b3c4")]
    assert tr.evidence_in("git -C '/a b' -c x=y commit -q", "[b 1a2b3c4] x") == [("commit", "1a2b3c4")]
    assert tr.evidence_in("git log --oneline", "1a2b3c4 x") == []
    url = "https://github.com/acme/widget/pull/12"
    assert tr.evidence_in("gh pr create --fill", url) == [("pr", "acme/widget#12")]
    assert tr.evidence_in("gh pr view 12", url) == []


def test_a_subagents_evidence_belongs_to_the_request_that_spawned_it(tmp_path):
    main = tmp_path / "p" / "s.jsonl"
    _write(main, [_human("first request with plenty of words in it to count", T0, "p1"),
                  _human("second request about something else entirely here", T0 + 100, "p2")])
    sub = main.parent / "s" / "subagents" / "agent-1.jsonl"
    _write(sub, [{"type": "user", "promptId": "p1", "timestamp": _iso(T0 + 200), "isSidechain": True,
                  "message": {"content": "do it"}},
                 *_bash("git commit -m x", "[b 1a2b3c4] x", T0 + 300, None, 1)])
    reqs, found, _ = tr.scan_session("s", "p", main, [sub])
    assert [r.prompt_id for r in reqs] == ["p1", "p2"]
    assert len(found) == 1 and found[0].at == T0 + 300
    assert tr.request_for(reqs, found[0].anchor).prompt_id == "p1"


def test_a_printed_feature_commit_links_its_request_to_the_merged_squash(world):
    got = _survey(world, run=False)
    assert [p["fix"] for p in got["pending"]] == [world["squash"]]
    assert got["pending"][0]["id"] == "widget-pr7-request"
    p = got["projects"]["widget"]
    assert p["sessions"] == 1 and p["requests_linked"] == 1 and p["dropped"] == {}
    assert got["transcripts"]["-home-proj"] == {"sessions": 1, "requests": 2}


def test_a_commit_older_than_the_window_is_not_evidence(world):
    got = _survey(world, run=False)
    assert world["old"] not in json.dumps(got)


def test_a_kept_task_carries_the_redacted_request_and_no_raw_text(world, monkeypatch):
    monkeypatch.setattr(history, "probe", lambda *a, **k: {
        "fail_to_pass": ["tests/test_mod.py::test_f"], "pass_to_pass": [], "test_s": 0.1})
    got = _survey(world)
    (task,) = got["tasks"]
    assert task["base"] == world["base"] and task["fix"] == world["squash"] and task["pr"] == 7
    assert task["repo"] == "https://github.com/acme/widget.git"
    assert "someone.else@example.org" not in json.dumps(got)
    assert "<EMAIL_1>" in task["prompt"] and task["prompt"].startswith("The importer drops")
    assert task["provenance"] == {"session": tr.session_hash("s1"), "evidence": "commit",
                                  "redactions": {"email": 1}}
    case = tr.convert(task).case
    assert case["params"]["variant"] == "request" and case["params"]["fix"] == world["squash"]
    assert case["attribution"]["session"] == tr.session_hash("s1") and "s1" not in json.dumps(case)


def test_screens_drop_and_count_by_reason(world):
    main = world["main"]
    recs = [json.loads(line) for line in main.read_text(encoding="utf-8").splitlines()]
    recs[0]["message"]["content"] = "fix it"
    _write(main, recs)
    got = _survey(world, run=False)
    assert got["projects"]["widget"]["dropped"] == {"request_too_short": 1} and not got["pending"]


def test_a_request_resolved_in_two_merged_tasks_is_dropped(world):
    w = world["repo"]
    other = _commit(w, {"pkg/mod.py": "def f():\n    return 3\n",
                        "tests/test_mod.py": "from pkg.mod import f\ndef test_f():\n    assert f() == 3\n"},
                    "direct on main", T0 + 600)
    recs = [json.loads(line) for line in world["main"].read_text(encoding="utf-8").splitlines()]
    recs[-1:-1] = _bash("git commit -m y", f"[main {other[:8]}] y", T0 + 610, "p1", 9)
    _write(world["main"], recs)
    got = _survey(world, run=False)
    assert got["projects"]["widget"]["dropped"] == {"request_spans_tasks": 2}


def test_a_private_repo_is_never_a_case(world):
    world["index"]["private"] = True
    got = _survey(world, run=False)
    assert got["projects"]["widget"]["dropped"] == {"private_repo": 1} and not got["pending"]


def test_an_unmerged_pr_is_dropped(world):
    world["index"]["prs"][7] = ("CLOSED", "")
    got = _survey(world, run=False)
    assert got["projects"]["widget"]["dropped"] == {"pr_not_merged": 1}


def test_a_case_still_matching_a_detector_is_refused(world, monkeypatch):
    monkeypatch.setattr(history, "probe", lambda *a, **k: {
        "fail_to_pass": ["tests/test_mod.py::test_f"], "pass_to_pass": [], "test_s": 0.1})
    (task,) = _survey(world)["tasks"]
    with pytest.raises(ValueError, match="refused.*email"):
        tr.convert({**task, "prompt": task["prompt"] + " cc another@example.net"})
    with pytest.raises(ValueError, match="refused.*home-path"):
        tr.convert({**task, "prompt": task["prompt"] + " see /" + "Users/zorblat/x"})


def test_the_table_names_every_project():
    got = {"transcripts": {"-p": {"sessions": 2, "requests": 9}},
           "projects": {"widget": {"sessions": 1, "requests_linked": 3, "tasks": 1,
                                   "dropped": {"too_big": 1, "no_flip": 1}}}, "tasks": [{}]}
    lines = tr.report(got)
    assert "-p 2 sessions 9 requests" in lines[0]
    assert any(line.startswith("widget") and "no_flip 1, too_big 1" in line for line in lines)


COMMITTED = sorted((ROOT / "evals" / "cases" / "repo" / "transcripts").glob("*.yaml"))
LOADED = {Path(c.source).name: c for c in load_cases(COMMITTED[0].parent)} if COMMITTED else {}


def test_the_committed_manifest_matches_revision_and_the_cases():
    got = tr.manifest()
    assert tr.revision(got) == tr.REVISION
    assert {t["id"] for t in got["tasks"]} == {p.stem for p in COMMITTED}


@pytest.mark.parametrize("path", COMMITTED, ids=[p.stem for p in COMMITTED])
def test_every_committed_case_is_clean_and_loads(path):
    from harness import privacy
    text = path.read_text(encoding="utf-8")
    assert redact.detect(text, redact.known_here()) == {}
    assert privacy.scan(text, path.name) == []
    case = LOADED[path.name]
    assert case.params["variant"] == "request" and case.params["fail_to_pass"]


def test_a_claude_session_trailer_links_a_commit_no_tool_printed(world):
    w, url = world["repo"], "https://claude.ai/code/session_01" + "Abc" * 8
    _git(w, "checkout", "-q", "-b", "feat2", world["base"])
    trailed = _commit(w, {"pkg/mod.py": "def f():\n    return 4\n",
                          "tests/test_mod.py": "from pkg.mod import f\ndef test_f():\n    assert f() == 4\n"},
                      f"feat2\n\nClaude-Session: {url}", T0 + 2000)
    _git(w, "checkout", "-q", "main")
    world["index"]["prs"][8] = ("MERGED", trailed)
    world["index"]["by_commit"][trailed] = [8]
    recs = [json.loads(line) for line in world["main"].read_text(encoding="utf-8").splitlines()]
    recs.append({"type": "attachment", "attachment": {"type": "remote_session_change", "url": url}})
    recs.append(_human("now make f return four and keep its test honest about it please", T0 + 1900, "p3"))
    _write(world["main"], recs)
    got = _survey(world, run=False)
    assert {p["id"] for p in got["pending"]} == {"widget-pr7-request", "widget-pr8-request"}


def test_a_kept_task_skips_the_probe_and_survives_its_transcript(world, monkeypatch):
    monkeypatch.setattr(history, "probe", lambda *a, **k: {
        "fail_to_pass": ["tests/test_mod.py::test_f"], "pass_to_pass": [], "test_s": 0.1})
    first = _survey(world)
    monkeypatch.setattr(history, "probe", lambda *a, **k: pytest.fail("a kept task was probed again"))
    again = _survey(world, keep=first)
    assert again["tasks"] == first["tasks"]
    gone = {**first["tasks"][0], "id": "widget-pr99-request", "fix": "e" * 40}
    world["main"].unlink()
    assert _survey(world, keep={"tasks": [gone]})["tasks"] == [gone]


def test_a_request_case_takes_its_fix_tasks_holdout_side():
    from evals.core import Case
    from harness import holdout
    cases = [Case(id=f"t{i}-{v}", modality="repo", prompt="p", params={"fix": f"{i:040x}", "variant": v})
             for i in range(12) for v in ("spec", "request")]
    split = holdout.assign("repo", cases)
    for i in range(12):
        assert split.side(f"t{i}-spec") == split.side(f"t{i}-request")


@pytest.mark.gauntlet("one-default-tuned-for-one-member-applied-to-all", site="evals/importers/transcripts.py:survey(timeout)")
def test_the_survey_hands_its_timeout_to_every_probe(world, monkeypatch):
    seen = []
    monkeypatch.setattr(history, "probe", lambda mirror, c, log, timeout, env=None, src=None: seen.append(timeout) or {
        "drop": "timeout"})
    got = _survey(world, timeout=7)
    assert seen == [7] and got["projects"]["widget"]["dropped"] == {"timeout": 1}


def test_a_repo_with_a_history_source_is_probed_and_graded_its_way(world, monkeypatch):
    src = history.Repo("history_widget", "widget", "https://github.com/acme/widget.git", "acme/widget", "0" * 40,
                       pytest_args=("--import-mode=importlib",), extras=("dev",))
    monkeypatch.setattr(history, "repos", lambda: [src])
    seen = []
    monkeypatch.setattr(history, "probe", lambda *a, src=None, **k: seen.append(src) or {
        "fail_to_pass": ["tests/test_mod.py::test_f"], "pass_to_pass": [], "test_s": 0.1})
    (task,) = _survey(world)["tasks"]
    assert seen == [src]
    params = tr.convert(task).case["params"]
    assert params["pytest_args"] == ["--import-mode=importlib"] and params["extras"] == ["dev"]
    assert tr.source_for("https://github.com/acme/other.git", "other").markers == ""
