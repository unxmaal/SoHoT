"""The local merge gate: a verdict on the tree it tested, posted as a commit status the deploy guard accepts. #2110."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from harness import deploy_guard as g
from harness import merge_gate as mg
from harness import paths, resources, store
from harness import workqueue as wq

SEAM = "seam='^harness/store[a-z_]*\\.py'\n"


def _git(cwd, *args) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True).stdout.strip()


def _write(work: Path, files: dict) -> None:
    for rel, text in files.items():
        (work / rel).parent.mkdir(parents=True, exist_ok=True)
        (work / rel).write_text(text, encoding="utf-8", newline="\n")
    _git(work, "add", "-A")


class Hub:
    """gh over a dict: the open pull requests, and each commit's statuses newest first."""

    def __init__(self):
        self.prs, self.statuses = [], {}

    def __call__(self, argv):
        if argv[:2] == ["pr", "list"]:
            return json.dumps(self.prs)
        if argv[:2] == ["run", "list"]:
            return "[]"
        assert argv[0] == "api", argv
        if "-X" in argv:
            fields = dict(a.split("=", 1) for a in argv[4:] if a != "-f")
            self.statuses.setdefault(argv[3].rsplit("/", 1)[1], []).insert(0, fields)
            return "{}"
        return json.dumps(self.statuses.get(argv[1].split("/commits/")[1].split("/")[0], []))

    def said(self, sha) -> list[tuple[str, str]]:
        return [(s["state"], s["description"]) for s in reversed(self.statuses.get(sha, []))]

    def stamp(self, sha, state, tree, context=g.GATE):
        self.statuses.setdefault(sha, []).insert(0, {"state": state, "context": context,
                                                     "description": f"{g.stamp(tree)} on 0123456789ab: said"})


@pytest.fixture
def world(tmp_path):
    """origin with main at A, a clone to work in and one to judge from; pr() opens one, squash() merges onto main."""
    origin, work, live = tmp_path / "origin.git", tmp_path / "work", tmp_path / "live"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    subprocess.run(["git", "clone", "-q", str(origin), str(work)], check=True)
    _git(work, "config", "user.email", "t@example.invalid")
    _git(work, "config", "user.name", "t")
    _write(work, {"a": "\n"})
    _git(work, "commit", "-q", "-m", "first")
    _write(work, {"a": "a\n", ".github/workflows/ci.yml": f"          {SEAM}"})
    _git(work, "commit", "-q", "-m", "second")
    _git(work, "push", "-q", "origin", "HEAD:main")
    subprocess.run(["git", "clone", "-q", str(origin), str(live)], check=True)
    hub = Hub()

    def pr(n: int, files: dict, on: str = "", **more) -> str:
        _git(work, "checkout", "-q", "--detach", on or _git(work, "rev-parse", "HEAD"))
        _write(work, files)
        _git(work, "commit", "-q", "-m", f"pr {n}")
        head = _git(work, "rev-parse", "HEAD")
        _git(work, "push", "-q", "origin", f"{head}:refs/pull/{n}/head")
        hub.prs.append({"number": n, "headRefOid": head, "isCrossRepository": False, "isDraft": False, **more})
        return head

    def squash(subject: str, files: dict) -> str:
        _git(work, "fetch", "-q", "origin", "main")
        _git(work, "checkout", "-q", "--detach", "origin/main")
        _write(work, files)
        _git(work, "commit", "-q", "-m", subject)
        _git(work, "push", "-q", "origin", "HEAD:main")
        _git(live, "fetch", "-q", "origin", "main")
        return _git(work, "rev-parse", "HEAD")

    return {"work": work, "live": live, "base": _git(work, "rev-parse", "HEAD"), "pr": pr, "squash": squash, "hub": hub,
            "tree": lambda sha: _git(work, "rev-parse", f"{sha}^{{tree}}")}


class Suite:
    """What the gate would run, recorded; `fails` names the step that returns 1, `plan` is the mutation listing."""

    def __init__(self, fails: str = "", plan: str = ""):
        self.fails, self.plan, self.ran, self.seen = fails, plan, [], []

    def __call__(self, argv, cwd, env, capture=False):
        step = " ".join(argv)
        self.ran.append(step)
        self.seen.append((Path(cwd), dict(env), sorted(p.name for p in Path(cwd).iterdir() if p.name != ".git"),
                          _git(cwd, "log", "-1", "--format=%P")))
        return (1 if self.fails and self.fails in step else 0), (self.plan if capture else "")


def _pass(world, suite=None, **kw):
    suite = suite or Suite()
    return mg.run_pass(world["live"], gh=world["hub"], run=suite, say=lambda m: None, **kw), suite


# --- the deploy guard ---

def test_a_passed_gate_on_the_pr_head_for_mains_tree_deploys_while_the_hosted_run_is_missing(world):
    head = world["pr"](7, {"x": "x\n"})
    sha = world["squash"]("add x (#7)", {"x": "x\n"})
    world["hub"].stamp(head, "success", world["tree"](sha))
    ok, why, by = g.judge(sha, world["hub"], repo=world["live"])
    assert ok and by == g.BY_GATE, why
    assert g.GATE in why and head[:12] in why


def test_a_status_from_an_older_base_is_not_accepted(world):
    """The gate passed #7 merged onto A; #6 landed first, so main's commit for #7 holds a tree nobody tested."""
    head = world["pr"](7, {"x": "x\n"}, world["base"])
    on_a = world["tree"](head)
    world["squash"]("add y (#6)", {"y": "y\n"})
    sha = world["squash"]("add x (#7)", {"x": "x\n"})
    world["hub"].stamp(head, "success", on_a)
    assert g.gated(sha, world["hub"], world["live"])[0] == g.NONE
    ok, why, by = g.judge(sha, world["hub"], repo=world["live"])
    assert not ok and by == "", why


def test_a_failed_gate_refuses_a_tree_though_main_has_no_failed_run(world):
    head = world["pr"](7, {"x": "x\n"})
    sha = world["squash"]("add x (#7)", {"x": "x\n"})
    world["hub"].stamp(head, "failure", world["tree"](sha))
    ok, why, _ = g.judge(sha, world["hub"], repo=world["live"])
    assert not ok and "failure" in why


@pytest.mark.parametrize("state, context", [("pending", g.GATE), ("error", g.GATE), ("skipped", g.GATE), ("", g.GATE),
                                            ("success", "check-macos"), (None, None)])
def test_a_pending_skipped_missing_or_foreign_status_never_reads_as_passed(world, state, context):
    head = world["pr"](7, {"x": "x\n"})
    sha = world["squash"]("add x (#7)", {"x": "x\n"})
    if context:
        world["hub"].stamp(head, state, world["tree"](sha), context)
    assert g.gated(sha, world["hub"], world["live"])[0] != g.PASSED
    assert g.judge(sha, world["hub"], repo=world["live"])[0] is False


def test_the_newest_status_for_the_tree_decides(world):
    head = world["pr"](7, {"x": "x\n"})
    sha = world["squash"]("add x (#7)", {"x": "x\n"})
    world["hub"].stamp(head, "success", world["tree"](sha))
    world["hub"].stamp(head, "failure", world["tree"](sha))
    assert g.judge(sha, world["hub"], repo=world["live"])[0] is False
    world["hub"].stamp(head, "success", world["tree"](sha))
    assert g.judge(sha, world["hub"], repo=world["live"])[2] == g.BY_GATE


def test_a_status_on_main_itself_deploys_a_commit_no_pull_request_names(world):
    sha = world["squash"]("pushed by hand", {"z": "z\n"})
    assert g.judge(sha, world["hub"], repo=world["live"])[0] is False
    world["hub"].stamp(sha, "success", world["tree"](sha))
    assert g.judge(sha, world["hub"], repo=world["live"])[2] == g.BY_GATE


def test_a_gate_lookup_that_breaks_leaves_the_hosted_verdict_standing(world):
    sha = world["squash"]("add x (#7)", {"x": "x\n"})
    def gh(argv):
        if argv[0] == "api":
            raise g.GhError("no statuses")
        return json.dumps([{"databaseId": 1, "headSha": sha, "status": "completed", "conclusion": "failure", "url": "u"}]
                          if argv[:2] == ["run", "list"] else {"jobs": [{"name": g.JOB, "conclusion": "failure"}]})
    ok, why, _ = g.judge(sha, gh, repo=world["live"])
    assert not ok and "check-macos concluded failure" in why


# --- the gate ---

def test_a_head_whose_suite_fails_gets_a_failing_status_and_the_guard_refuses_its_tree(world):
    head = world["pr"](7, {"x": "x\n"})
    rows, suite = _pass(world, Suite(fails="make PYTEST_N=6 check"), only=7)
    assert [r["state"] for r in rows] == [mg.FAILURE]
    said = world["hub"].said(head)
    assert [s for s, _ in said] == ["pending", "pending", "failure"]
    assert said[-1][1].split(": ", 1)[1].startswith("make check failed, log ") and said[-1][1].startswith(g.stamp(rows[0]["tree"]) + " on ")
    assert all(s["context"] == g.GATE for s in world["hub"].statuses[head])
    assert suite.ran == ["make PYTEST_N=6 check"]
    sha = world["squash"]("add x (#7)", {"x": "x\n"})
    assert g.judge(sha, world["hub"], repo=world["live"])[0] is False


def test_a_passing_suite_posts_success_on_the_merged_tree_and_the_guard_deploys_the_squash(world):
    head = world["pr"](7, {"x": "x\n"})
    rows, _ = _pass(world, only=7)
    assert rows[0]["state"] == mg.SUCCESS and world["hub"].said(head)[-1][0] == "success"
    assert len(world["hub"].said(head)[-1][1]) <= mg.DESCRIPTION_MAX
    sha = world["squash"]("add x (#7)", {"x": "x\n"})
    assert rows[0]["tree"] == world["tree"](sha)
    assert g.judge(sha, world["hub"], repo=world["live"])[2] == g.BY_GATE


def test_the_suite_runs_in_a_clean_worktree_at_the_head_merged_onto_current_main(world, monkeypatch):
    head = world["pr"](7, {"x": "x\n"}, world["base"])
    main = world["squash"]("add y (#6)", {"y": "y\n"})
    monkeypatch.setenv(wq.JOB_ENV, "12")
    rows, suite = _pass(world, only=7)
    cwd, env, files, parents = suite.seen[0]
    assert files == [".github", "a", "x", "y"] and parents.split() == [main, head]
    assert rows[0]["base"] == main and rows[0]["tree"] not in (world["tree"](head), world["tree"](main))
    assert env[store.BACKEND_ENV] == "sqlite" and wq.JOB_ENV not in env
    assert Path(env[paths.ENV_VAR]) != paths.home() and mg.root() in Path(env[paths.ENV_VAR]).parents
    assert not cwd.exists() and str(cwd) not in _git(world["live"], "worktree", "list")


def test_main_moving_under_a_judged_head_tests_it_again_and_a_settled_tree_is_left_alone(world):
    head = world["pr"](7, {"x": "x\n"})
    first, _ = _pass(world, only=7)
    again, suite = _pass(world, only=7)
    assert again == [] and suite.ran == [] and len(world["hub"].said(head)) == 3
    world["squash"]("add y (#6)", {"y": "y\n"})
    moved, suite = _pass(world, only=7)
    assert suite.ran and moved[0]["tree"] != first[0]["tree"]
    assert [s for s, _ in world["hub"].said(head)][3:] == ["pending", "pending", "success"]
    forced, suite = _pass(world, only=7, again=True)
    assert suite.ran and forced[0]["tree"] == moved[0]["tree"]


def test_a_fork_or_a_draft_is_never_run(world):
    world["pr"](7, {"x": "x\n"}, isCrossRepository=True)
    world["pr"](8, {"w": "w\n"}, world["base"], isDraft=True)
    world["hub"].prs.append({"number": 9, "headRefOid": world["base"]})
    world["hub"].stamp(world["base"], "success", world["tree"](world["base"]))
    rows, suite = _pass(world)
    assert rows == [] and suite.ran == []
    for n in (7, 8, 9):
        suite = Suite()
        with pytest.raises(mg.GateError, match="not an open, non-draft pull request"):
            mg.run_pass(world["live"], only=n, gh=world["hub"], run=suite)
        assert suite.ran == []


def test_a_head_that_conflicts_with_main_gets_a_failing_status_without_a_run(world):
    head = world["pr"](7, {"a": "mine\n"}, world["base"])
    world["squash"]("theirs (#6)", {"a": "theirs\n"})
    rows, suite = _pass(world, only=7)
    assert suite.ran == [] and rows[0]["state"] == mg.FAILURE
    assert world["hub"].said(head) == [("failure", world["hub"].said(head)[0][1])]
    assert "does not merge onto main" in world["hub"].said(head)[0][1]
    assert _pass(world, only=7)[0] == []


def test_main_tip_is_tested_when_no_verdict_names_its_tree_and_not_when_its_pull_request_was_gated(world):
    head = world["pr"](7, {"x": "x\n"})
    _pass(world, only=7)
    sha = world["squash"]("add x (#7)", {"x": "x\n"})
    world["hub"].prs.clear()
    rows, suite = _pass(world)
    assert rows == [] and suite.ran == [] and sha not in world["hub"].statuses
    tip = world["squash"]("pushed by hand", {"z": "z\n"})
    rows, suite = _pass(world)
    assert [r["head"] for r in rows] == [tip] and suite.ran and world["hub"].said(tip)[-1][0] == "success"
    assert g.judge(tip, world["hub"], repo=world["live"])[2] == g.BY_GATE
    assert head not in [r["head"] for r in rows]


def test_a_run_that_cannot_start_posts_an_error_and_is_tried_again(world):
    head = world["pr"](7, {"x": "x\n"})
    def broken(argv, cwd, env, capture=False):
        raise OSError("no make on PATH")
    rows = mg.run_pass(world["live"], only=7, gh=world["hub"], run=broken, say=lambda m: None)
    assert rows[0]["state"] == mg.ERROR and world["hub"].said(head)[-1] == ("error", world["hub"].said(head)[-1][1])
    assert "no make on PATH" in world["hub"].said(head)[-1][1]
    rows, suite = _pass(world, only=7)
    assert suite.ran and rows[0]["state"] == mg.SUCCESS


def test_a_pass_beside_a_running_one_does_nothing(world):
    world["pr"](7, {"x": "x\n"})
    inner = []
    class Nested(Suite):
        def __call__(self, argv, cwd, env, capture=False):
            said = []
            inner.append((mg.run_pass(world["live"], only=7, gh=world["hub"], run=Suite(fails="make"), say=said.append), said))
            return super().__call__(argv, cwd, env, capture)
    rows, _ = _pass(world, Nested(), only=7)
    assert rows[0]["state"] == mg.SUCCESS
    assert inner[0] == ([], ["another merge gate pass is running"])


@pytest.mark.parametrize("files, fails, steps, said", [
    ({"x": "x\n"}, "", ["make PYTEST_N=6 check", "uv run python -m tests.gauntlet.mutation changed --base BASE"], ""),
    ({"harness/store_x.py": "x\n"}, "", ["make PYTEST_N=6 check", "make PYTEST_N=6 test-postgres",
                                         "uv run python -m tests.gauntlet.mutation changed --base BASE"], ""),
    ({"harness/store_x.py": "x\n"}, "test-postgres", ["make PYTEST_N=6 check", "make PYTEST_N=6 test-postgres"],
     "make test-postgres"),
    ({"x": "x\n"}, "mutation changed", ["make PYTEST_N=6 check",
                                        "uv run python -m tests.gauntlet.mutation changed --base BASE"], "the mutation plan"),
])
def test_a_store_change_adds_the_postgres_suite_and_each_failing_step_is_named(world, files, fails, steps, said):
    world["pr"](7, files)
    rows, suite = _pass(world, Suite(fails=fails), only=7)
    assert suite.ran == [s.replace("BASE", world["base"]) for s in steps]
    assert rows[0]["state"] == (mg.FAILURE if said else mg.SUCCESS)
    assert world["hub"].said(rows[0]["head"])[-1][1].split(": ", 1)[1].startswith(f"{said} failed" if said else "passed")


def test_each_changed_module_is_mutated_on_its_changed_functions_and_a_survivor_fails_the_verdict(world):
    plan = "harness/a.py\tf g\n\nharness/b.py\th\n"
    world["pr"](7, {"x": "x\n"})
    rows, suite = _pass(world, Suite(plan=plan), only=7)
    assert suite.ran[2:] == ["make mutation MUTATION_ARGS=--module harness/a.py --function f --function g",
                             "make mutation MUTATION_ARGS=--module harness/b.py --function h"]
    assert rows[0]["state"] == mg.SUCCESS
    rows, suite = _pass(world, Suite(plan=plan, fails="harness/b.py"), only=7, again=True)
    assert rows[0]["state"] == mg.FAILURE
    assert world["hub"].said(rows[0]["head"])[-1][1].split(": ", 1)[1].startswith("mutation of harness/b.py failed")


def test_a_tree_whose_ci_names_no_store_seam_runs_the_postgres_suite(world):
    world["pr"](7, {".github/workflows/ci.yml": "jobs: {}\n"})
    _, suite = _pass(world, only=7)
    assert "make PYTEST_N=6 test-postgres" in suite.ran


def test_a_step_past_its_limit_fails_instead_of_holding_the_gate(tmp_path, monkeypatch):
    monkeypatch.setattr(mg, "STEP_TIMEOUT_S", 0.5)
    rc, out = mg._run([sys.executable, "-c", "import time; time.sleep(60)"], tmp_path, mg._env(tmp_path / "home"))
    assert (rc, out) == (mg.TIMED_OUT, "")
    assert mg._run([sys.executable, "-c", "print('a\\tb')"], tmp_path, mg._env(tmp_path / "home"), capture=True) == (0, "a\tb\n")


def test_the_repositorys_own_ci_still_names_the_store_seam_the_gate_reads():
    assert mg._SEAM.search((Path(__file__).resolve().parents[1] / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))


# --- the queue ---

def test_a_moved_ref_queues_one_cpu_pass_and_an_unmoved_one_queues_nothing(world):
    refs = ["one"]
    def ask(src):
        return refs[0]
    job = mg.queue(world["live"], refs=ask)
    assert job["resource"] == resources.CPU and job["requested_by"] == mg.REQUESTER
    assert job["argv"][-3:] == ["merge-gate", "--repo", str(world["live"])]
    assert resources.of(job) == resources.CPU
    assert mg.queue(world["live"], refs=ask) is None
    refs[0] = "two"
    assert mg.queue(world["live"], refs=ask) is None, "one pass waits at a time"
    with wq._store() as c:
        c.execute("UPDATE jobs SET state = ? WHERE requested_by = ?", (wq.DONE, mg.REQUESTER))
        c.commit()
    assert mg.queue(world["live"], refs=ask)["id"] != job["id"]
    assert len([j for j in wq.jobs() if j["requested_by"] == mg.REQUESTER]) == 2


def test_no_checkout_or_a_node_queues_nothing_and_asks_nothing(world, tmp_path):
    def never(src):
        raise AssertionError("asked origin")
    assert mg.queue(tmp_path / "absent", refs=never) is None
    (paths.home() / "role").write_text("node\n", encoding="utf-8")
    assert mg.queue(world["live"], refs=never) is None
    assert wq.jobs() == []


def test_an_unmoved_ref_queues_nothing_after_its_pass_finished(world):
    assert mg.queue(world["live"], refs=lambda src: "one")
    with wq._store() as c:
        c.execute("UPDATE jobs SET state = ? WHERE requested_by = ?", (wq.DONE, mg.REQUESTER))
        c.commit()
    assert mg.queue(world["live"], refs=lambda src: "one") is None
    assert len(wq.jobs()) == 1


# --- the deploy poll ---

def _polled(monkeypatch, capsys, queue):
    from harness import deploy
    from harness.commands import deploy as cmd
    monkeypatch.setattr(deploy, "poll", lambda **kw: {"queued": None, "why": "nothing new", "superseded": [], "confirm": ""})
    monkeypatch.setattr(mg, "queue", queue)
    return cmd._poll(False, ""), capsys.readouterr().out


def test_the_deploy_poll_queues_the_gate(monkeypatch, capsys):
    rc, out = _polled(monkeypatch, capsys, lambda: {"id": "0042", "title": "merge gate"})
    assert rc == 0 and "queued 0042: merge gate" in out and "nothing queued: nothing new" in out


def test_a_gate_that_cannot_be_queued_never_stops_the_deploy_poll(monkeypatch, capsys):
    def broken():
        raise RuntimeError("store down")
    rc, out = _polled(monkeypatch, capsys, broken)
    assert rc == 0 and "merge gate not queued: store down" in out and "nothing queued: nothing new" in out


def test_a_head_later_in_the_pass_is_tested_on_the_main_that_moved_meanwhile(world):
    world["pr"](7, {"x": "x\n"}, world["base"])
    world["pr"](8, {"w": "w\n"}, world["base"])
    moved = []
    class Moving(Suite):
        def __call__(self, argv, cwd, env, capture=False):
            if not moved:
                moved.append(world["squash"]("add y (#6)", {"y": "y\n"}))
            return super().__call__(argv, cwd, env, capture)
    rows, _ = _pass(world, Moving())
    assert [r["base"] for r in rows[1:]] == [moved[0], moved[0]] and rows[0]["head"] == world["base"]
    assert all("y" in files for _, _, files, _ in _.seen[2:])


@pytest.mark.gauntlet("an-effect-reachable-from-a-run-that-is-not-the-live-deploy",
                      site="harness/merge_gate.py:run_pass:_gh")
def test_the_only_thing_a_pass_writes_to_github_is_the_gate_status_of_the_head_it_tested(world, monkeypatch):
    head = world["pr"](7, {"x": "x\n"})
    world["pr"](8, {"w": "w\n"}, world["base"])
    calls = []
    def gh(argv, cwd=None):
        calls.append((list(argv), cwd))
        return world["hub"](argv)
    monkeypatch.setattr(g, "_gh", gh)
    rows = mg.run_pass(world["live"], only=7, run=Suite(), say=lambda m: None)
    assert rows[0]["state"] == mg.SUCCESS and {cwd for _, cwd in calls} == {str(world["live"])}
    writes = [a for a, _ in calls if not (a[:2] == ["pr", "list"] or (a[0] == "api" and "-X" not in a))]
    assert len(writes) == 3 and len(calls) > 3
    for a in writes:
        assert a[:4] == ["api", "-X", "POST", f"repos/{{owner}}/{{repo}}/statuses/{head}"] and f"context={g.GATE}" in a
