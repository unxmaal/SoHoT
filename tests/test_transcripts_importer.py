"""Claude Code session requests linked to their merged commits, redacted, as repo cases. #1095."""
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from evals import redact, session_cut
from evals.core import load_cases
from evals.importers import history
from evals.importers import transcripts as tr
from harness import privacy

ROOT = Path(__file__).resolve().parents[1]
T0 = 1_760_000_000
FIX_LINE = '    return "the widget answer is two now"'
REQUEST = ("The importer drops every candidate when gh is down; make a gh failure raise instead, and "
           "mail someone.else@example.org the result")
#: The identity every test here redacts against, never the machine running it.
KNOWN = redact.Known(accounts=("zorblat",))


def _iso(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).isoformat().replace("+00:00", "Z")


def _human(text, t, pid):
    return {"type": "user", "promptId": pid, "timestamp": _iso(t), "origin": {"kind": "human"},
            "userType": "external", "message": {"role": "user", "content": text}}


def _bash(command, output, t, pid, n):
    return _tool("Bash", {"command": command}, output, t, pid, n)


def _tool(name, args, output, t, pid, n):
    use = {"type": "assistant", "timestamp": _iso(t), "message": {"content": [
        {"type": "tool_use", "id": f"tu{n}", "name": name, "input": args}]}}
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
def world(tmp_path, monkeypatch):
    """A checkout of acme/widget with a feature commit, its squash on main, and a session that printed the first."""
    monkeypatch.setattr(tr, "MIN_CUT_BYTES", 0)
    monkeypatch.setattr(tr, "admit", lambda case, env=None: None)
    monkeypatch.setattr(redact, "known_here", lambda *a, **k: KNOWN)
    monkeypatch.setattr(privacy, "names", lambda root: list(KNOWN.names))
    repos = tmp_path / "github"
    w = repos / "acme" / "widget"
    w.mkdir(parents=True)
    _git(w, "init", "-q", "-b", "main")
    _git(w, "remote", "add", "origin", "git@github.com:acme/widget.git")
    base = _commit(w, {"uv.lock": "x\n", "pkg/mod.py": "def f():\n    return 1\n",
                       "tests/test_mod.py": "from pkg.mod import f\n"}, "base", T0 - 100)
    _git(w, "checkout", "-q", "-b", "feat")
    feature = _commit(w, {"pkg/mod.py": f"def f():\n{FIX_LINE}\n",
                          "tests/test_mod.py": "from pkg.mod import f\ndef test_f():\n    assert f() == 2\n"},
                      "feat", T0 + 50)
    _git(w, "checkout", "-q", "main")
    _git(w, "merge", "-q", "--squash", "feat")
    squash = _commit(w, {}, "Fix f (#7)", T0 + 500)
    old = _commit(w, {"README": "old\n"}, "unrelated", T0 - 90_000)
    projects = tmp_path / "projects" / "-home-proj"
    main = projects / "s1.jsonl"
    mod = str(w / "pkg" / "mod.py")
    _write(main, [_human(REQUEST, T0, "p1"),
                  {"type": "assistant", "timestamp": _iso(T0 + 10), "message": {"content": [
                      {"type": "text", "text": "Reading the module first."}]}},
                  *_tool("Read", {"file_path": mod}, "def f():\n    return 1\n", T0 + 20, "p1", 10),
                  *_tool("Edit", {"file_path": mod, "old_string": "    return 1", "new_string": FIX_LINE}, "ok",
                         T0 + 30, "p1", 11),
                  {"type": "assistant", "timestamp": _iso(T0 + 40), "message": {"content": [
                      {"type": "text", "text": "AFTER THE EDIT, never in a prompt."}]}},
                  *_bash("git -C x commit -m feat", f"[feat {feature[:7]}] feat\n 2 files changed", T0 + 60, "p1", 1),
                  *_bash("git log --oneline -3", f"{old[:7]} unrelated", T0 + 61, "p1", 2),
                  *_bash("git commit -m z", f"{old[:7]} printed but far older than this commit", T0 + 62, "p1", 3),
                  _human("merge it", T0 + 1000, "p2")])
    index = {"private": False, "prs": {7: ("MERGED", squash)}, "by_commit": {feature: [7]}}
    return {"tmp": tmp_path, "repos": repos, "repo": w, "projects": projects.parent, "main": main,
            "base": base, "feature": feature, "squash": squash, "old": old, "index": index}


def _survey(world, **kw):
    return tr.survey(world["projects"], [world["repos"]], world["tmp"] / "log",
                     known=KNOWN,
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


def test_a_project_dir_spelled_from_a_home_path_is_written_without_its_account(world):
    world["projects"].joinpath("-home-proj").rename(world["projects"] / "-Users-someone-proj")
    got = _survey(world, run=False)
    assert list(got["transcripts"]) == ["-Users-USER-proj"]


def test_a_session_recorded_on_windows_links_its_request_too(world):
    recs = [json.loads(line) for line in world["main"].read_text(encoding="utf-8").splitlines()]
    paths = []
    for rec in recs:
        for block in rec["message"]["content"] if isinstance(rec["message"]["content"], list) else []:
            if "file_path" in block.get("input", {}):
                block["input"]["file_path"] = "C:" + block["input"]["file_path"].replace("/", "\\")
                paths.append(block["input"]["file_path"])
    assert len(paths) == 2 and all(p.endswith("\\pkg\\mod.py") for p in paths)
    _write(world["main"], recs)
    got = _survey(world, run=False)
    assert [p["fix"] for p in got["pending"]] == [world["squash"]]


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
    prompt = task["prompt"]
    assert prompt.startswith(session_cut.HEAD) and "<EMAIL_1>" in prompt and "The importer drops" in prompt
    assert "Reading the module first." in prompt and "## tool Read" in prompt and "return 1" in prompt
    assert "AFTER THE EDIT" not in prompt and "## tool Edit" not in prompt
    assert session_cut.leaks(prompt, [FIX_LINE.strip()]) == []
    prov = task["provenance"]
    assert prov["session"] == tr.session_hash("s1") and prov["evidence"] == "commit"
    assert prov["redactions"]["email"] == 1 and prov["cut"]["stream"] == "main"
    case = tr.convert(task).case
    assert case["params"]["variant"] == "request" and case["params"]["fix"] == world["squash"]
    assert case["attribution"]["session"] == tr.session_hash("s1") and "s1" not in json.dumps(case)


def _recs(world):
    return [json.loads(line) for line in world["main"].read_text(encoding="utf-8").splitlines()]


def test_a_task_no_edit_in_its_request_touched_has_no_cut(world):
    _write(world["main"], [r for r in _recs(world)
                           if not any(b.get("name") == "Edit" for b in (r.get("message") or {}).get("content") or []
                                      if isinstance(b, dict))])
    got = _survey(world, run=False)
    assert got["projects"]["widget"]["dropped"] == {"no_edit": 1} and not got["pending"]


def test_a_cut_that_already_shows_a_fix_line_is_dropped_as_a_leak(world):
    recs = _recs(world)
    recs[0]["message"]["content"] = REQUEST + "\nchange it to:\n" + FIX_LINE
    _write(world["main"], recs)
    got = _survey(world, run=False)
    assert got["projects"]["widget"]["dropped"] == {"leak": 1} and not got["pending"]


def test_a_cut_with_a_name_like_word_is_dropped_and_the_word_reported(world):
    recs = _recs(world)
    recs[0]["message"]["content"] = REQUEST + ". Ask Zorvanna, she reported it."
    _write(world["main"], recs)
    got = _survey(world, run=False)
    assert got["projects"]["widget"]["dropped"] == {"name_guard": 1} and list(got["flagged"]) == ["Zorvanna"] and got["flagged"]["Zorvanna"][0] == 1


def test_a_subagent_that_makes_the_first_edit_is_the_cut_and_opens_with_the_request(world, monkeypatch):
    recs = [r for r in _recs(world)
            if not any(b.get("name") == "Edit" for b in (r.get("message") or {}).get("content") or []
                       if isinstance(b, dict))]
    _write(world["main"], recs)
    sub = world["main"].parent / "s1" / "subagents" / "agent-1.jsonl"
    mod = str(world["repo"] / "pkg" / "mod.py")
    _write(sub, [{"type": "user", "promptId": "p1", "timestamp": _iso(T0 + 5), "isSidechain": True,
                  "message": {"content": "Implement the gh failure change in pkg/mod.py"}},
                 *_tool("Grep", {"pattern": "def f"}, "pkg/mod.py:1:def f():", T0 + 15, None, 20),
                 *_tool("Write", {"file_path": mod, "content": f"def f():\n{FIX_LINE}\n"}, "ok", T0 + 25, None, 21)])
    monkeypatch.setattr(history, "probe", lambda *a, **k: {
        "fail_to_pass": ["tests/test_mod.py::test_f"], "pass_to_pass": [], "test_s": 0.1})
    (task,) = _survey(world)["tasks"]
    prompt = task["prompt"]
    assert task["provenance"]["cut"]["stream"] == "subagent"
    assert prompt.index("The importer drops") < prompt.index("Implement the gh failure") < prompt.index("## tool Grep")
    assert FIX_LINE.strip() not in prompt


def test_a_request_resolved_in_two_merged_tasks_drops_the_one_whose_cut_heads_toward_the_other(world):
    w = world["repo"]
    other = _commit(w, {"pkg/mod.py": "def f():\n    return 3\n",
                        "tests/test_mod.py": "from pkg.mod import f\ndef test_f():\n    assert f() == 3\n"},
                    "direct on main", T0 + 600)
    recs = [json.loads(line) for line in world["main"].read_text(encoding="utf-8").splitlines()]
    recs[-1:-1] = _bash("git commit -m y", f"[main {other[:8]}] y", T0 + 610, "p1", 9)
    _write(world["main"], recs)
    got = _survey(world, run=False)
    assert [p["fix"] for p in got["pending"]] == [world["squash"]]
    assert got["projects"]["widget"]["dropped"] == {"mismatch": 1}


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
    with pytest.raises(ValueError, match="refused.*1 name-like"):
        tr.convert({**task, "prompt": task["prompt"] + " thanks to @quillfeather"})


def test_the_table_names_every_project():
    got = {"transcripts": {"-p": {"sessions": 2, "requests": 9}},
           "projects": {"widget": {"sessions": 1, "requests_linked": 3, "tasks": 1,
                                   "dropped": {"too_big": 1, "no_flip": 1}}}, "tasks": [{}]}
    lines = tr.report(got)
    assert "-p 2 sessions 9 requests" in lines[0]
    assert any(line.startswith("widget") and "no_flip 1, too_big 1" in line for line in lines)


#: A fixed planted account and name, so the clean check reads the same on every machine; the machine's own account
#: counts only where an account leaks, in a home path or a project slug, since a CI runner's account ("runner") is
#: also a word these cases use.
PLANTED = redact.Known(accounts=("zorblat",), names=("Quentavious",))


def _left(values: str) -> dict:
    import re
    got = dict(redact.detect(values, PLANTED))
    for acct in redact.known_here().accounts:
        if re.search(rf"(?:Users|home)[/\\-]{re.escape(acct)}(?![A-Za-z0-9])", values, re.I):
            got["account"] = got.get("account", 0) + 1
    return got


def test_the_clean_check_catches_a_planted_account_and_this_machines_in_a_path():
    import getpass
    assert _left("all clean here") == {}
    assert _left("see -Users-zorblat-projects/x") == {"account": 1}
    assert _left(f"see <PATH_HOME>/.claude/projects/-Users-{getpass.getuser()}-projects") == {"account": 1}
    assert _left(f"the {getpass.getuser()} word alone") == {}


COMMITTED = sorted((ROOT / "evals" / "cases" / "repo" / "transcripts").glob("*.yaml"))
LOADED = {Path(c.source).name: c for c in load_cases(COMMITTED[0].parent)} if COMMITTED else {}


def test_the_committed_manifest_matches_revision_and_the_cases():
    got = tr.manifest()
    assert tr.revision(got) == tr.REVISION
    assert {t["id"] for t in got["tasks"]} == {p.stem for p in COMMITTED}


@pytest.mark.parametrize("path", COMMITTED, ids=[p.stem for p in COMMITTED])
def test_every_committed_case_is_clean_and_loads(path):
    import yaml
    text = path.read_text(encoding="utf-8")
    values = tr.strings(yaml.safe_load(text))
    assert _left(values) == {} and redact.name_like(values) == []
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
    recs += _tool("Read", {"file_path": str(w / "pkg" / "mod.py")}, "def f():\n    return 1\n", T0 + 1940, "p3", 29)
    recs += _tool("Edit", {"file_path": str(w / "pkg" / "mod.py"), "old_string": "1", "new_string": "4"}, "ok",
                  T0 + 1950, "p3", 30)
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


@pytest.mark.parametrize("path", COMMITTED, ids=[p.stem for p in COMMITTED])
def test_no_committed_cut_holds_a_line_its_fix_adds(path):
    case = LOADED[path.name]
    p = case.params
    if p["source_repo"] != history.REPO_URL:
        pytest.skip("only this checkout's own history is at hand")
    files = sorted({*p["context_files"], *(p.get("new_files") or [])})
    try:
        diff = _git(ROOT, "diff", "--no-renames", p["base"], p["fix"], "--", *files)
        base = {f: _git(ROOT, "show", f"{p['base']}:{f}") for f in p["context_files"]}
    except subprocess.CalledProcessError:
        pytest.skip("a shallow checkout lacks the commits")
    assert session_cut.leaks(case.prompt, session_cut.added_lines(diff, base)) == []


def test_a_repo_whose_sessions_read_a_chat_archive_is_never_imported(world, monkeypatch):
    monkeypatch.setattr(tr, "THIRD_PARTY_DATA", ("widget",))
    got = _survey(world, run=False)
    assert got["projects"]["widget"]["dropped"] == {"third_party_data": 1} and not got["pending"]


def test_a_cut_that_is_the_request_and_little_else_is_dropped(world, monkeypatch):
    monkeypatch.setattr(tr, "MIN_CUT_BYTES", 10 ** 6)
    got = _survey(world, run=False)
    assert got["projects"]["widget"]["dropped"] == {"cut_too_short": 1} and not got["pending"]


def test_a_case_excluded_by_hand_is_dropped(world, monkeypatch):
    monkeypatch.setattr(tr, "EXCLUDED", {"widget-pr7-request": "private"})
    got = _survey(world, run=False)
    assert got["projects"]["widget"]["dropped"] == {"excluded": 1} and not got["pending"]


def test_a_fix_names_the_issues_its_title_ends_with_or_its_body_closes():
    assert tr.fix_issues("Pin the venvs when a pin moves (#1037) (#1042)") == [1037, 1042]
    assert tr.fix_issues("Size the listing (#1079, #1080) (#1081)", "See #947 too.") == [1079, 1080, 1081]
    assert tr.fix_issues("Interleave case by case (#862)", "body\n\nCloses #816\n") == [816, 862]
    assert tr.fix_issues("Merge pull request #138 from acme/fix/136-bodies",
                         "fix(search): keep bodies inline (#136)\n\nmore about #120") == [136]
    assert tr.fix_issues("unrelated") == []


def _sub(world, n, spawn, recs, at):
    path = world["main"].parent / "s1" / "subagents" / f"agent-{n}.jsonl"
    _write(path, [{"type": "user", "promptId": "p1", "timestamp": _iso(at), "isSidechain": True,
                   "message": {"content": spawn}}, *recs])
    return path


def _two_tasks(world, fixed_by_sub: bool):
    """One request that spawns two subagents: #9's edits pkg/mod.py first through a heredoc; #6's is the merged fix."""
    w = world["repo"]
    fix = _commit(w, {"pkg/mod.py": 'def f():\n    return "the widget answer is three now"\n',
                      "tests/test_mod.py": "from pkg.mod import f\ndef test_f():\n    assert f()\n"}, "Fix f (#6) (#7)",
                  T0 + 500)
    world["index"]["prs"][7] = ("MERGED", fix)
    keep = [r for r in _recs(world) if not any(b.get("name") in ("Edit", "Bash") for b in
                                               (r.get("message") or {}).get("content") or [] if isinstance(b, dict))]
    pr_url = "https://github.com/acme/widget/pull/7"
    if not fixed_by_sub:
        keep[-1:-1] = _bash("gh pr create --fill", pr_url, T0 + 400, "p1", 40)
    _write(world["main"], keep)
    heredoc = "python3 - <<'EOF'\nfrom pathlib import Path\np = Path('pkg/mod.py')\np.write_text('x')\nEOF"
    _sub(world, 1, "Implement issue #9: rename f's helper", [
        *_tool("Read", {"file_path": str(w / "pkg" / "mod.py")}, "def f():\n    return 1\n", T0 + 12, None, 50),
        *_bash(heredoc, "", T0 + 14, None, 51)], T0 + 10)
    _sub(world, 2, "Implement issue #6: make f answer two" if fixed_by_sub else "Tidy the docs", [
        *_tool("Read", {"file_path": str(w / "pkg" / "mod.py")}, "def f():\n    return 1\n", T0 + 30, None, 60),
        *_tool("Edit", {"file_path": str(w / "pkg" / "mod.py"), "old_string": "    return 1", "new_string": FIX_LINE},
               "ok", T0 + 40, None, 61),
        *([*_bash("gh pr create --fill", pr_url, T0 + 300, None, 62)] if fixed_by_sub else [])], T0 + 20)


def test_a_request_that_spawns_two_tasks_cuts_the_one_that_opened_the_fixs_pr(world, monkeypatch):
    _two_tasks(world, fixed_by_sub=True)
    monkeypatch.setattr(history, "probe", lambda *a, **k: {
        "fail_to_pass": ["tests/test_mod.py::test_f"], "pass_to_pass": [], "test_s": 0.1})
    (task,) = _survey(world)["tasks"]
    assert task["provenance"]["cut"] == {"stream": "subagent", "events": 4, "bytes": task["provenance"]["cut"]["bytes"]}
    assert "Implement issue #6" in task["prompt"] and "issue #9" not in task["prompt"]


def test_a_cut_that_heads_toward_another_task_is_dropped_as_a_mismatch(world):
    _two_tasks(world, fixed_by_sub=False)
    got = _survey(world, run=False)
    assert got["projects"]["widget"]["dropped"] == {"mismatch": 1} and not got["pending"]


def test_a_task_already_in_the_manifest_keeps_its_bytes_when_a_screen_would_now_drop_it(world, monkeypatch):
    monkeypatch.setattr(history, "probe", lambda *a, **k: {
        "fail_to_pass": ["tests/test_mod.py::test_f"], "pass_to_pass": [], "test_s": 0.1})
    first = _survey(world)
    monkeypatch.setattr(tr, "MIN_CUT_BYTES", 10 ** 6)
    stale = {"tasks": [{**first["tasks"][0], "prompt": "the audited prompt"}]}
    assert _survey(world, keep=stale)["tasks"] == stale["tasks"]


#: The 13 cases #1136 retired as request/fix mismatches, with the issue each fix closes.
MISMATCHED = {"mcm-engine-pr138-request": [136], "mcm-engine-pr184-request": [177], "sohot-pr1029-request": [1025],
              "sohot-pr1033-request": [1027], "sohot-pr1035-request": [1030], "sohot-pr1038-request": [1032],
              "sohot-pr1042-request": [1037], "sohot-pr1046-request": [1045], "sohot-pr1051-request": [1049],
              "sohot-pr1054-request": [1053], "sohot-pr933-request": [928], "sohot-pr957-request": [954],
              "sohot-pr966-request": [964]}
#: The manifest as committed before #1136 retired them.
BEFORE_1136 = "a31a032b"


def test_the_mismatch_screen_drops_every_case_1136_retired_as_one_and_keeps_named_ones():
    try:
        rows = {t["id"]: t for t in json.loads(_git(ROOT, "show", f"{BEFORE_1136}:evals/importers/transcripts.json"))["tasks"]}
    except subprocess.CalledProcessError:
        pytest.skip("a shallow checkout lacks the commits")
    files = lambda t: [*t["context_files"], *t["new_files"]]  # noqa: E731
    for tid, issues in MISMATCHED.items():
        t = rows[tid]
        if t["slug"] == "sohot":
            subject, body = _git(ROOT, "show", "-s", "--format=%s%x00%b", t["fix"]).split("\0", 1)
            assert set(tr.fix_issues(subject, body)) - {t["pr"]} == set(issues), tid
        assert not session_cut.on_task(t["prompt"], issues, files(t)), tid
    for tid, issues in {"sohot-pr1081-request": [1079, 1080], "sohot-pr1101-request": [1099],
                        "sohot-pr1003-request": [1002], "mcm-engine-pr162-request": [156]}.items():
        assert session_cut.on_task(rows[tid]["prompt"], issues, files(rows[tid])), tid


def test_a_second_fix_from_one_subagent_whose_first_is_already_at_its_base_is_a_mismatch(world):
    _two_tasks(world, fixed_by_sub=True)
    w = world["repo"]
    later = _commit(w, {"pkg/mod.py": 'def f():\n    return "the widget answer is four by now"\n',
                        "tests/test_mod.py": "from pkg.mod import f\ndef test_f():\n    assert 'four' in f()\n"},
                    "Follow up on f (#6) (#8)", T0 + 900)
    world["index"]["prs"][8] = ("MERGED", later)
    sub = world["main"].parent / "s1" / "subagents" / "agent-2.jsonl"
    recs = [json.loads(line) for line in sub.read_text(encoding="utf-8").splitlines()]
    recs += _bash("gh pr create --fill", "https://github.com/acme/widget/pull/8", T0 + 800, None, 63)
    _write(sub, recs)
    got = _survey(world, run=False)
    assert [p["id"] for p in got["pending"]] == ["widget-pr7-request"]
    assert got["projects"]["widget"]["dropped"] == {"mismatch": 1}


def test_a_second_fix_from_one_subagent_cut_after_its_first_landed_is_kept(world):
    _two_tasks(world, fixed_by_sub=True)
    w = world["repo"]
    _commit(w, {"pkg/other.py": "def g():\n    return 0\n"}, "add g", T0 + 850)
    later = _commit(w, {"pkg/other.py": "def g():\n    return 'g is one now and says so'\n",
                        "tests/test_other.py": "from pkg.other import g\ndef test_g():\n    assert g()\n"},
                    "Give g a value (#6) (#8)", T0 + 900)
    world["index"]["prs"][8] = ("MERGED", later)
    sub = world["main"].parent / "s1" / "subagents" / "agent-2.jsonl"
    recs = [json.loads(line) for line in sub.read_text(encoding="utf-8").splitlines()]
    other = str(w / "pkg" / "other.py")
    recs += [*_tool("Read", {"file_path": other}, "def g():\n    return 0\n", T0 + 860, None, 64),
             *_tool("Edit", {"file_path": other, "old_string": "0", "new_string": "1"}, "ok", T0 + 870, None, 65),
             *_bash("gh pr create --fill", "https://github.com/acme/widget/pull/8", T0 + 880, None, 66)]
    _write(sub, recs)
    got = _survey(world, run=False)
    assert sorted(p["id"] for p in got["pending"]) == ["widget-pr7-request", "widget-pr8-request"]
