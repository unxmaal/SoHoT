"""#1149: the weekly adversarial review files only findings it reproduced at the SHA and found in no open or recent issue."""
from __future__ import annotations

import json
import os
import plistlib
import re
import subprocess
import sys
from pathlib import Path

import pytest

import shells
from harness import cli, paths, review

REPO = Path(__file__).resolve().parents[1]

REPRO = '''import threading

from waits import wait_for


def test_wait_for_gives_up():
    out = []

    def go():
        try:
            wait_for(lambda: False)
        except TimeoutError:
            out.append("gave up")

    t = threading.Thread(target=go, daemon=True)
    t.start()
    t.join(5)
    assert out == ["gave up"], "wait_for never returned on a condition that never holds"
'''


def finding(**kw) -> dict:
    """The report a finder makes about the planted wait; the line is wherever the fixture puts it."""
    text = review.FIXTURES["planted"]["waits.py"]
    line = text.splitlines().index("    while not ready():") + 1
    got = {"title": "wait_for never gives up on a condition that never holds", "file": "waits.py",
           "line": line, "quote": "while not ready():", "symbol": "wait_for",
           "claim": "wait_for polls with no deadline, so a condition that never holds blocks its caller forever.",
           "repro": {"kind": "test", "body": REPRO}}
    got.update(kw)
    return got


def plain(argv, work, timeout):
    """run_sandboxed's contract without the macOS sandbox, so the gate runs on every platform."""
    try:
        p = subprocess.run(argv, cwd=work, capture_output=True, text=True, timeout=timeout,
                           env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    except subprocess.TimeoutExpired as exc:
        return -9, str(exc.stdout or ""), True
    return p.returncode, (p.stdout + p.stderr)[-2000:], False


class Model:
    """A scripted `claude -p`: each finder reports `findings`, the refuter answers `verdict`."""

    def __init__(self, findings=None, verdict='{"verdict": "confirmed", "why": "the test hangs on main"}',
                 tokens=1000):
        self.findings = [finding()] if findings is None else findings
        self.verdict, self.tokens, self.calls = verdict, tokens, []

    def __call__(self, prompt, cwd, role):
        self.calls.append({"role": role, "cwd": Path(cwd), "prompt": prompt})
        usage = {"input_tokens": self.tokens // 2, "output_tokens": self.tokens // 4,
                 "cache_read_input_tokens": self.tokens // 8, "cache_creation_input_tokens": self.tokens // 8}
        if role.startswith("find"):
            text = "Here is what I found.\n```json\n" + json.dumps({"findings": self.findings}) + "\n```\n"
        else:
            text = self.verdict
        return {"text": text, "usage": usage}


class GH:
    """A faked `gh`: lists what it is given and records every create; it never reaches GitHub."""

    def __init__(self, open_issues=(), closed=()):
        self.open, self.closed, self.calls = list(open_issues), list(closed), []

    def __call__(self, argv):
        self.calls.append(list(argv))
        out = ""
        if argv[:2] == ["issue", "list"]:
            out = json.dumps(self.closed if "closed" in argv else self.open)
        elif argv[:2] == ["label", "list"]:
            out = json.dumps([{"name": review.LABEL}])
        elif argv[:2] == ["issue", "create"]:
            out = "https://github.com/unxmaal/SoHoT/issues/9999\n"
        return subprocess.CompletedProcess(["gh", *argv], 0, out, "")

    def created(self):
        return [c for c in self.calls if c[:2] == ["issue", "create"]]


def go(tmp_path, kind="planted", model=None, gh=None, file=True, environ=None, **kw):
    source = review.fixture(kind, tmp_path / f"fixture-{kind}")
    model, gh = model or Model(), gh or GH()
    environ = {review.FILE_ENV: "1"} if environ is None else environ
    r = review.run(source, ref="HEAD", fetch=False, dimensions=("efficiency",), file=file, ask=model,
                   gh=gh, repro=plain, environ=environ, wait=False, say=lambda *a: None, **kw)
    return r, model, gh


def fates(r):
    return [c["fate"] for c in r["candidates"]]


def test_a_planted_defect_is_found_verified_and_filed(tmp_path):
    r, model, gh = go(tmp_path)
    assert fates(r) == ["filed"], r["candidates"]
    made = gh.created()
    assert len(made) == 1
    argv = made[0]
    assert argv[argv.index("--label") + 1] == review.LABEL
    body = argv[argv.index("--body") + 1]
    fp = r["candidates"][0]["fingerprint"]
    assert f"{review.FINGERPRINT} {fp}" in body
    assert "def test_wait_for_gives_up" in body and "Prior art checked" in body
    assert r["candidates"][0]["issue"] == 9999 and r["filed"] == [9999]
    # The finder and the reproduction ran in different fresh worktrees, both under the review home, then went away.
    find_cwd = next(c["cwd"] for c in model.calls if c["role"].startswith("find"))
    refute_cwd = next(c["cwd"] for c in model.calls if c["role"] == "refute")
    assert find_cwd != refute_cwd
    assert (paths.home() / "review" / "work").resolve() in find_cwd.parents
    assert not find_cwd.exists() and not refute_cwd.exists()


def test_the_clean_fixture_files_nothing(tmp_path):
    r, _, gh = go(tmp_path, kind="clean")
    assert fates(r) == ["unreproduced"], r["candidates"]
    assert gh.created() == []
    assert r["known_answer"] == "clean"


def test_a_duplicate_of_an_open_issue_is_suppressed(tmp_path):
    fp = review.fingerprint("waits.py", "while   not ready():")
    gh = GH(open_issues=[{"number": 42, "title": "something", "state": "OPEN",
                          "body": f"older report\n{review.FINGERPRINT} {fp}\n"}])
    r, _, gh = go(tmp_path, gh=gh)
    assert fates(r) == ["duplicate"]
    assert r["candidates"][0]["issue"] == 42
    assert gh.created() == []


def test_a_duplicate_named_by_file_and_symbol_is_suppressed(tmp_path):
    gh = GH(closed=[{"number": 7, "title": "wait_for in waits.py hangs", "state": "CLOSED", "body": "x"}])
    r, _, gh = go(tmp_path, gh=gh)
    assert fates(r) == ["duplicate"] and r["candidates"][0]["issue"] == 7
    assert gh.created() == []
    closed = next(c for c in gh.calls if c[:2] == ["issue", "list"] and "closed" in c)
    assert any(a.startswith("closed:>=") for a in closed), closed


def test_a_second_report_of_the_same_line_in_one_run_is_a_duplicate(tmp_path):
    r, _, gh = go(tmp_path, model=Model(findings=[finding(), finding(line=finding()["line"] + 1, title="again")]))
    assert fates(r) == ["filed", "duplicate"]
    assert len(gh.created()) == 1


@pytest.mark.parametrize("verdict", ['{"verdict": "refuted", "why": "it has a deadline"}',
                                     "I think it is probably fine", '{"verdict": "Confirmed?"}'])
def test_a_refuted_finding_is_not_filed(tmp_path, verdict):
    r, _, gh = go(tmp_path, model=Model(verdict=verdict))
    assert fates(r) == ["refuted"]
    assert gh.created() == []


def test_a_harness_failure_is_not_recorded_as_a_verdict_on_the_finding(tmp_path):
    def no_sandbox(argv, work, timeout):
        raise RuntimeError("grading needs /usr/bin/sandbox-exec (macOS); this host has none")

    source = review.fixture("planted", tmp_path / "fx")
    r = review.run(source, ref="HEAD", fetch=False, dimensions=("efficiency",), file=True, ask=Model(), gh=GH(),
                   repro=no_sandbox, environ={review.FILE_ENV: "1"}, wait=False, say=lambda *a: None)
    assert fates(r) == ["unverifiable"] and "sandbox-exec" in r["candidates"][0]["why"]

    class Silent(Model):
        def __call__(self, prompt, cwd, role):
            if role == "refute":
                raise review.CallFailed("refute: Not logged in", {"input_tokens": 5})
            return super().__call__(prompt, cwd, role)

    r, _, gh = go(tmp_path / "silent", model=Silent())
    assert fates(r) == ["unverified"] and "Not logged in" in r["candidates"][0]["why"]
    assert gh.created() == [] and r["tokens"] == 1005


def test_a_finder_that_fails_is_an_error_of_the_run_not_a_finding(tmp_path):
    class Down(Model):
        def __call__(self, prompt, cwd, role):
            raise review.CallFailed("find:efficiency: stopped at 30 turns", {"output_tokens": 7},
                                    "review_turns>30")

    r, _, _ = go(tmp_path, model=Down())
    assert r["candidates"] == [] and "30 turns" in r["errors"]["efficiency"]
    assert "review_turns>30" in r["limits"] and r["tokens"] == 7


def test_a_misquoted_finding_is_not_filed(tmp_path):
    model = Model(findings=[finding(quote="while True:")])
    r, _, gh = go(tmp_path, model=model)
    assert fates(r) == ["unquoted"]
    assert [c["role"] for c in model.calls] == ["find:efficiency"]
    assert gh.created() == []


def test_a_symbol_not_in_the_quote_is_unquoted(tmp_path):
    r, _, _ = go(tmp_path, model=Model(findings=[finding(symbol="poll_forever")]))
    assert fates(r) == ["unquoted"]


def test_a_collection_error_is_not_a_reproduction(tmp_path):
    broken = REPRO.replace("from waits import wait_for", "from waits import no_such_name")
    r, _, gh = go(tmp_path, model=Model(findings=[finding(repro={"kind": "test", "body": broken})]))
    assert fates(r) == ["unreproduced"]
    assert "exit 2" in r["candidates"][0]["why"]
    assert gh.created() == []


def test_a_command_reproduces_only_when_its_output_holds_the_text(tmp_path):
    cmd = {"kind": "command", "argv": ["python", "-c", "import waits, inspect; print(inspect.getsource(waits))"]}
    r, _, _ = go(tmp_path, model=Model(findings=[finding(repro={**cmd, "expect": "deadline_s"})]))
    assert fates(r) == ["unreproduced"]
    r, _, _ = go(tmp_path / "again", model=Model(findings=[finding(repro={**cmd, "expect": "time.sleep(poll_s)"})]))
    assert fates(r) == ["filed"]


def test_a_malformed_finding_is_dropped(tmp_path):
    r, _, gh = go(tmp_path, model=Model(findings=[{"title": "no file"}, finding(file="../escape.py")]))
    assert fates(r) == ["malformed", "malformed"]
    assert gh.created() == []


def test_the_token_budget_stops_further_calls(tmp_path, monkeypatch):
    monkeypatch.setattr(review, "TOKEN_BUDGET", 1500)
    model = Model(tokens=1000)
    source = review.fixture("planted", tmp_path / "fx")
    r = review.run(source, ref="HEAD", fetch=False, dimensions=("rot", "efficiency", "tests"), file=False,
                   ask=model, gh=GH(), repro=plain, environ={}, wait=False, say=lambda *a: None)
    # rot's finder (1000) and its refuter (1000) spend the budget; nothing else starts.
    assert [c["role"] for c in model.calls] == ["find:rot", "refute"]
    assert "review_token_budget>1500" in r["limits"]
    assert r["tokens"] == 2000


def test_findings_past_the_cap_are_recorded_not_filed(tmp_path, monkeypatch):
    monkeypatch.setattr(review, "MAX_FINDINGS", 1)
    other = finding(title="wait_for sleeps a fixed poll", quote="time.sleep(poll_s)",
                    line=review.FIXTURES["planted"]["waits.py"].splitlines().index("        time.sleep(poll_s)") + 1)
    r, _, gh = go(tmp_path, model=Model(findings=[finding(), other]))
    assert fates(r) == ["filed", "capped"]
    assert len(gh.created()) == 1
    assert "review_max_findings>1" in r["limits"]


def test_a_body_that_fails_redaction_is_withheld(tmp_path):
    leak = finding(claim=f"wait_for blocks forever; seen from {Path.home()}/projects/x when it hung.")
    r, _, gh = go(tmp_path, model=Model(findings=[leak]))
    assert fates(r) == ["withheld"]
    assert "path" in r["candidates"][0]["why"]
    assert gh.created() == []


def test_the_review_s_own_sha_and_fingerprint_never_withhold_a_body():
    # A 17-digit run inside a SHA reads as an id to redact.detect.
    sha, fp = "abc63273636968742284" + "f" * 20, review.fingerprint("waits.py", "while not ready():")
    body = f"found at {sha[:12]}: {review.REPO_URL}/blob/{sha}/waits.py#L7\n{review.FINGERPRINT} {fp}\n"
    assert review.leaked(body, sha, fp) == {}
    assert review.leaked(body + f"seen in {Path.home()}/x\n", sha, fp) == {"path": 1}


@pytest.mark.parametrize("file,environ", [(True, {}), (False, {review.FILE_ENV: "1"}), (True, {review.FILE_ENV: "0"})])
def test_filing_needs_both_the_flag_and_the_switch(tmp_path, file, environ):
    r, _, gh = go(tmp_path, file=file, environ=environ)
    assert fates(r) == ["would file"]
    assert gh.created() == []
    assert r["mode"] == "dry"


def test_the_review_uses_the_subscription_login_and_reports_tokens(tmp_path):
    seen = {}

    def execute(argv, **kw):
        seen.update(argv=argv, **kw)
        body = {"type": "result", "subtype": "success", "is_error": False, "result": "hello",
                "total_cost_usd": 1.23,
                "usage": {"input_tokens": 10, "output_tokens": 20, "cache_read_input_tokens": 30,
                          "cache_creation_input_tokens": 40}}
        return subprocess.CompletedProcess(argv, 0, json.dumps(body), "")

    environ = {"PATH": "/usr/bin", "HOME": "/h", "ANTHROPIC_API_KEY": "sk-ant-api-x", "ANTHROPIC_AUTH_TOKEN": "t",
               "ANTHROPIC_BASE_URL": "http://127.0.0.1:4000", "ANTHROPIC_MODEL": "local"}
    got = review.claude_ask("look", tmp_path, "find:rot", execute=execute, environ=environ)
    for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "ANTHROPIC_MODEL"):
        assert name not in seen["env"]
    argv = seen["argv"]
    assert argv[:2] == ["claude", "-p"] and argv[argv.index("--model") + 1] == review.MODEL
    assert argv[argv.index("--tools") + 1] == "Read,Glob,Grep"
    assert "--bare" not in argv, "--bare reads no OAuth login, so it would need an API key"
    assert seen["input"] == "look" and "look" not in argv
    assert got == {"text": "hello", "usage": {"input_tokens": 10, "output_tokens": 20,
                                              "cache_read_input_tokens": 30, "cache_creation_input_tokens": 40}}
    r, _, _ = go(tmp_path / "run")
    assert r["tokens"] == 2000 and r["calls"][0]["tokens"]["total"] == 1000
    assert "cost" not in json.dumps(r)


def test_a_failed_call_spends_nothing_and_reports_why(tmp_path):
    def execute(argv, **kw):
        return subprocess.CompletedProcess(argv, 1, "", "Not logged in")

    with pytest.raises(review.CallFailed, match="Not logged in"):
        review.claude_ask("look", tmp_path, "find:rot", execute=execute, environ={})


def test_the_kill_switch_stops_a_run(monkeypatch):
    monkeypatch.setattr(review, "claude_ask", lambda *a, **k: pytest.fail("a claude -p call started"))
    assert cli.main(["review", "off"]) == 0
    assert review.is_off()
    assert cli.main(["review", "run"]) == 0
    assert cli.main(["review", "on"]) == 0
    assert not review.is_off()


def test_the_kill_switch_stops_a_run_started_by_any_caller(tmp_path):
    review.switch(False)
    model = Model()
    r, _, gh = go(tmp_path, model=model)
    assert r["off"] is True and model.calls == [] and gh.calls == []


def receipt(days_ago, filed, now):
    return review.write({"started": now - days_ago * 86400, "finished": now - days_ago * 86400, "sha": "a" * 40,
                         "source": "repo", "mode": "file",
                         "candidates": [{"dimension": d, "fate": "filed", "issue": n} for n, d in filed]})


def test_a_low_precision_dimension_is_switched_off(tmp_path):
    now = 1_800_000_000.0
    receipt(35, [(101, "rot"), (102, "rot"), (103, "efficiency")], now)
    receipt(14, [(104, "rot"), (105, "rot")], now)
    states = [{"number": 101, "state": "CLOSED", "stateReason": "COMPLETED"},
              {"number": 102, "state": "CLOSED", "stateReason": "NOT_PLANNED"},
              {"number": 103, "state": "CLOSED", "stateReason": "NOT_PLANNED"},
              {"number": 104, "state": "CLOSED", "stateReason": "NOT_PLANNED"},
              {"number": 105, "state": "CLOSED", "stateReason": "NOT_PLANNED"}]
    gh = GH(open_issues=states)
    s = review.stats(gh=gh, now=now)
    assert s["rot"] == {"filed": 4, "completed": 1, "not_planned": 3, "open": 0, "precision": 0.25,
                        "weeks": 5.0, "off": True, "held_by": ""}
    assert s["efficiency"]["off"] is False, "one closed issue is too few to judge"
    assert s["efficiency"]["held_by"] == "review_min_closed"
    model = Model()
    source = review.fixture("planted", tmp_path / "fx")
    r = review.run(source, ref="HEAD", fetch=False, dimensions=("rot", "efficiency"), file=False, ask=model,
                   gh=gh, repro=plain, environ={}, wait=False, say=lambda *a: None, now=lambda: now)
    assert "rot" in r["switched_off"]
    assert [c["role"] for c in model.calls if c["role"].startswith("find")] == ["find:efficiency"]


def test_a_young_dimension_is_not_judged(tmp_path):
    now = 1_800_000_000.0
    receipt(7, [(101, "rot"), (102, "rot"), (103, "rot")], now)
    gh = GH(open_issues=[{"number": n, "state": "CLOSED", "stateReason": "NOT_PLANNED"} for n in (101, 102, 103)])
    got = review.stats(gh=gh, now=now)["rot"]
    assert got["off"] is False and got["held_by"] == "review_precision_weeks"


def test_a_fixture_run_says_whether_it_found_the_planted_answer(tmp_path):
    r, _, gh = go(tmp_path, file=False)
    assert r["known_answer"] == "found" and gh.created() == []
    r, _, _ = go(tmp_path / "miss", file=False, model=Model(findings=[]))
    assert r["known_answer"] == "missed"


def test_the_finder_is_told_what_changed_since_the_last_review(tmp_path):
    source = review.fixture("planted", tmp_path / "fx")
    first = review.run(source, ref="HEAD", fetch=False, dimensions=("gauntlet",), file=False, ask=Model(findings=[]),
                       gh=GH(), repro=plain, environ={}, wait=False, say=lambda *a: None)
    (source / "later.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(source), "add", "-A"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(source), "commit", "-qm", "later"], check=True, capture_output=True)
    model = Model(findings=[])
    second = review.run(source, ref="HEAD", fetch=False, dimensions=("gauntlet",), file=False, ask=model,
                        gh=GH(), repro=plain, environ={}, wait=False, say=lambda *a: None, since=first["sha"])
    assert second["since"] == first["sha"]
    assert "later.py" in model.calls[0]["prompt"] and "waits.py" not in model.calls[0]["prompt"]


def test_a_fixture_run_from_the_command_line_never_files(monkeypatch):
    gh = GH()
    monkeypatch.setenv(review.FILE_ENV, "1")
    monkeypatch.setattr(review, "gh_run", gh)
    monkeypatch.setattr(review, "claude_ask", Model())
    monkeypatch.setattr("evals.repo.run_sandboxed", plain)
    assert cli.main(["review", "run", "--fixture", "planted", "--file"]) == 0
    assert gh.created() == []
    (r,) = review.receipts()
    assert r["mode"] == "dry" and r["known_answer"] == "found" and r["source"] == "fixture:planted"


@pytest.mark.skipif(sys.platform != "darwin", reason="the reproduction sandbox is macOS sandbox-exec")
def test_the_real_sandbox_reproduces_the_plant_and_not_the_clean_fixture(tmp_path):
    for kind, want in (("planted", "would file"), ("clean", "unreproduced")):
        source = review.fixture(kind, tmp_path / kind)
        r = review.run(source, ref="HEAD", fetch=False, dimensions=("efficiency",), file=False, ask=Model(),
                       gh=GH(), environ={}, wait=False, say=lambda *a: None)
        assert fates(r) == [want], r["candidates"]


@pytest.mark.skipif(sys.platform != "darwin", reason="launchd is macOS-only")
def test_the_review_unit_runs_weekly_outside_the_sweep_window(tmp_path):
    gen = REPO / "scripts" / "launchd.sh"
    env = {**os.environ, "LOCALHARNESS_HOME": str(tmp_path / "home"), "LH_ROLE": "scheduler"}
    out = tmp_path / "units"
    got = subprocess.run([shells.BASH, str(gen), "generate", str(out)], capture_output=True, text=True, env=env)
    assert got.returncode == 0, got.stderr
    unit = plistlib.loads((out / "com.unxmaal.localharness.review.plist").read_bytes())
    assert unit["ProgramArguments"][1].endswith("scripts/serve-review.sh")
    (when,) = unit["StartCalendarInterval"]
    assert set(when) == {"Weekday", "Hour", "Minute"}
    assert 3 < when["Hour"] < 21, "the sweep window is 21:00 to 03:00"
    node = tmp_path / "node"
    got = subprocess.run([shells.BASH, str(gen), "generate", str(node)], capture_output=True, text=True,
                         env={**env, "LOCALHARNESS_HOME": str(tmp_path / "nodehome"), "LH_ROLE": "node"})
    assert got.returncode == 0, got.stderr
    assert not (node / "com.unxmaal.localharness.review.plist").exists()
    script = (REPO / "scripts" / "serve-review.sh").read_text(encoding="utf-8")
    assert re.search(r"soh review run --file\b", script)
