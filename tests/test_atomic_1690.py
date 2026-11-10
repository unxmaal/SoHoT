"""Atomic subtasks on the repo lane: Claude's plan and hidden check, whole-function local units, fresh retries,
the vacuous-check control, and the three arms scored against the full hidden suite. #1690."""
import ast
import dataclasses
import json

import pytest

from evals import atomic

SRC = '''"""A module."""
import os


def keep():
    return 1


@decorated
def target(a, b=2):
    return a


class Box:
    size = 3

    def open(self):
        return False

    def close(self):
        return True


TAIL = 7
'''


def _sub(symbol="target", path="pkg/mod.py", kind="function", contract=("def target(a, b=2):",)):
    return atomic.Subtask(path=path, kind=kind, symbol=symbol, spec="return a plus b", contract=list(contract))


def test_a_function_is_replaced_whole_and_everything_else_is_kept():
    got = atomic.splice(SRC, _sub(), "def target(a, b=2):\n    return a + b\n")
    assert "return a + b" in got and "@decorated" not in got
    assert got.split("def target")[0] == SRC.split("@decorated")[0]
    assert got.endswith("TAIL = 7\n") and "def keep():\n    return 1" in got
    ast.parse(got)


def test_a_method_is_replaced_and_a_dedented_unit_is_indented_to_its_class():
    got = atomic.splice(SRC, _sub("Box.open", contract=["def open(self):"]), "def open(self):\n    return True\n")
    tree = ast.parse(got)
    box = next(n for n in tree.body if isinstance(n, ast.ClassDef))
    assert [n.name for n in box.body if isinstance(n, ast.FunctionDef)] == ["open", "close"]
    assert "    def open(self):\n        return True\n" in got


def test_a_missing_function_or_method_is_added_and_a_missing_class_is_refused():
    got = atomic.splice(SRC, _sub("fresh", contract=["def fresh():"]), "def fresh():\n    return 9\n")
    assert got.rstrip().endswith("def fresh():\n    return 9") and "TAIL = 7" in got
    got = atomic.splice(SRC, _sub("Box.wipe", contract=["def wipe(self):"]), "def wipe(self):\n    return 0\n")
    box = next(n for n in ast.parse(got).body if isinstance(n, ast.ClassDef))
    assert [n.name for n in box.body if isinstance(n, ast.FunctionDef)] == ["open", "close", "wipe"]
    with pytest.raises(atomic.UnitError, match="no class Crate"):
        atomic.splice(SRC, _sub("Crate.wipe", contract=["def wipe(self):"]), "def wipe(self):\n    return 0\n")


def test_a_unit_that_defines_something_else_or_does_not_parse_is_refused():
    with pytest.raises(atomic.UnitError, match="target"):
        atomic.splice(SRC, _sub(), "def other(a, b=2):\n    return a\n")
    with pytest.raises(atomic.UnitError, match="parse"):
        atomic.splice(SRC, _sub(), "def target(a, b=2):\nreturn a\n")


def test_a_whole_file_unit_replaces_the_file_or_creates_it():
    sub = _sub("", path="pkg/new.py", kind="file", contract=["def made():"])
    assert atomic.splice(None, sub, "def made():\n    return 1\n") == "def made():\n    return 1\n"
    with pytest.raises(atomic.UnitError, match="parse"):
        atomic.splice(SRC, sub, "def made(:\n")


def test_the_unit_is_the_last_python_block_of_the_reply():
    reply = "think\n```python\ndef a():\n    pass\n```\nthen\n```python\ndef target(a, b=2):\n    return a\n```\nok"
    assert atomic.extract_unit(reply) == "def target(a, b=2):\n    return a\n"
    assert atomic.extract_unit("def target(a):\n    return a\n") == "def target(a):\n    return a\n"
    assert atomic.extract_unit("I cannot do that.") == ""
    indented = "```python\n    @staticmethod\n    def open(self):\n        return True\n```"
    unit = atomic.extract_unit(indented)
    sub = _sub("Box.open", contract=["def open(self):"])
    assert atomic.contract_ok(unit, sub) == "", "a method written as it sits in its class is the same method"
    assert "    @staticmethod\n    def open(self):\n        return True\n" in atomic.splice(SRC, sub, unit)


def test_a_file_that_is_not_python_is_taken_verbatim_from_any_fenced_block():
    yml = "jobs:\n  check:\n    runs-on: macos-15\n"
    reply = f"Here it is:\n```yaml\n{yml}```\n"
    unit = atomic.extract_unit(reply, python=False)
    sub = _sub("", path=".github/workflows/ci.yml", kind="file", contract=[])
    assert unit == yml and atomic.contract_ok(unit, sub) == ""
    assert atomic.splice("jobs: {}\n", sub, "  indented: kept\n") == "  indented: kept\n"
    assert atomic.extract_unit("no block at all", python=False) == ""
    md = {**PLAN, "subtasks": [{"path": "README.md", "kind": "function", "symbol": "x", "spec": "s", "contract": []}]}
    with pytest.raises(atomic.PlanError, match="Python"):
        atomic.parse_plan(json.dumps(md), ["README.md"])


def test_the_visible_contract_holds_names_and_parameters():
    sub = _sub(contract=["def target(a, b=2):", "def helper(x):"])
    assert atomic.contract_ok("def target(a, b=2):\n    return a\n\n\ndef helper(x):\n    return x\n", sub) == ""
    assert "helper" in atomic.contract_ok("def target(a, b=2):\n    return a\n", sub)
    assert "b" in atomic.contract_ok("def target(a):\n    return a\n\n\ndef helper(x):\n    return x\n", sub)
    assert "async" not in atomic.contract_ok("async def target(a, b=2):\n    return a\n\n\ndef helper(x):\n    pass\n",
                                             sub)
    two = "class A:\n    def __init__(self, config):\n        pass\n\n\nclass B:\n    def __init__(self, config, key):\n        pass\n"
    init = _sub("", path="pkg/mod.py", kind="file", contract=["def __init__(self, config):"])
    assert atomic.contract_ok(two, init) == "", "any def of that name may hold the contract, not only the last"
    init.contract = ["def __init__(self, other):"]
    assert "other" in atomic.contract_ok(two, init)


PLAN = {"subtasks": [{"path": "pkg/mod.py", "kind": "function", "symbol": "target", "spec": "add",
                      "contract": ["def target(a, b=2):"]}],
        "check": "from pkg.mod import target\n\n\ndef test_adds():\n    assert target(1) == 3\n"}


def test_a_plan_is_read_from_a_json_reply_and_held_to_the_case_files():
    plan = atomic.parse_plan("Here:\n```json\n" + json.dumps(PLAN) + "\n```", ["pkg/mod.py"])
    assert plan.subtasks[0].symbol == "target" and "def test_adds" in plan.check and not plan.escalate
    assert atomic.parse_plan(json.dumps({"escalate": "spans four modules"}), []).escalate == "spans four modules"
    bad = {**PLAN, "subtasks": [{**PLAN["subtasks"][0], "path": "other.py"}]}
    with pytest.raises(atomic.PlanError, match="other.py"):
        atomic.parse_plan(json.dumps(bad), ["pkg/mod.py"])
    tests = {**PLAN, "subtasks": [{**PLAN["subtasks"][0], "path": "tests/test_mod.py", "kind": "file"}]}
    with pytest.raises(atomic.PlanError, match="test"):
        atomic.parse_plan(json.dumps(tests), ["tests/test_mod.py"])
    with pytest.raises(atomic.PlanError, match="check"):
        atomic.parse_plan(json.dumps({**PLAN, "check": "x = 1\n"}), ["pkg/mod.py"])
    with pytest.raises(atomic.PlanError, match="symbol"):
        atomic.parse_plan(json.dumps({**PLAN, "subtasks": [{**PLAN["subtasks"][0], "symbol": ""}]}), ["pkg/mod.py"])
    with pytest.raises(atomic.PlanError, match="JSON"):
        atomic.parse_plan("no plan here", ["pkg/mod.py"])


class FakeWorkspace:
    """A checkout whose check, pass_to_pass and full-suite outcomes are planted per attempt."""

    def __init__(self, base_passes=False, reference_passes=True, outcomes=()):
        self.base_passes, self.reference_passes = base_passes, reference_passes
        self.outcomes = list(outcomes)
        self.tried = []

    def read(self, path):
        return SRC if path == "pkg/mod.py" else None

    def check_at(self, which, check):
        return self.base_passes if which == "base" else self.reference_passes

    def attempt(self, files, check):
        self.tried.append(files)
        return self.outcomes.pop(0)


def _local(*replies):
    """A local model answering in turn, as delegate.complete returns."""
    queue = list(replies)

    def complete(lane, prompt, **kw):
        complete.prompts.append(prompt)
        complete.kw.append(kw)
        return {"text": queue.pop(0), "model": "m", "prompt_tokens": 100, "completion_tokens": 20}
    complete.prompts, complete.kw = [], []
    return complete


GOOD = "```python\ndef target(a, b=2):\n    return a + b\n```"
WRONG_NAME = "```python\ndef nope(a, b=2):\n    return a + b\n```"
PASS = {"check": True, "p2p": True, "full": True}
FAIL = {"check": False, "p2p": True, "full": False}


def test_a_check_that_passes_on_the_unchanged_code_is_caught_and_nothing_local_runs():
    plan = atomic.parse_plan(json.dumps(PLAN), ["pkg/mod.py"])
    local = _local()
    got = atomic.run_case(plan, FakeWorkspace(base_passes=True), local)
    assert got["final"] == "cloud" and got["vacuous"] and local.prompts == [] and got["attempts"] == []


def test_a_failed_attempt_is_retried_fresh_and_a_gated_one_is_kept():
    plan = atomic.parse_plan(json.dumps(PLAN), ["pkg/mod.py"])
    local = _local(WRONG_NAME, GOOD)
    ws = FakeWorkspace(outcomes=[PASS])
    got = atomic.run_case(plan, ws, local)
    assert got["final"] == "local" and got["solved"] and not got["false_accept"]
    assert len(got["attempts"]) == 2 and "target" in got["attempts"][0]["why"]
    assert got["attempts"][0]["calls"][-1]["tail"].endswith("return a + b\n```"), "a failed reply's tail is kept"
    assert local.prompts[0] == local.prompts[1], "a retry is fresh: the same prompt, no failure fed back"
    assert all(plan.check not in p and "test_adds" not in p for p in local.prompts), "the check stays hidden"
    assert "return a + b" in ws.tried[0]["pkg/mod.py"]
    assert got["local_tokens"] == 240 and all(not k.get("delegated") and k.get("tag") is None for k in local.kw)


def test_three_gate_failures_escalate_and_a_gate_pass_the_suite_fails_is_a_false_accept():
    plan = atomic.parse_plan(json.dumps(PLAN), ["pkg/mod.py"])
    got = atomic.run_case(plan, FakeWorkspace(outcomes=[FAIL, FAIL, FAIL]), _local(GOOD, GOOD, GOOD))
    assert got["final"] == "cloud" and len(got["attempts"]) == atomic.ATTEMPTS and not got["false_accept"]
    got = atomic.run_case(plan, FakeWorkspace(outcomes=[{"check": True, "p2p": True, "full": False}]), _local(GOOD))
    assert got["final"] == "local" and got["false_accept"] and not got["solved"]
    broke = {"check": True, "p2p": False, "full": False}
    got = atomic.run_case(plan, FakeWorkspace(outcomes=[broke] * 3), _local(GOOD, GOOD, GOOD))
    assert got["final"] == "cloud", "a unit that breaks pass_to_pass is never kept, whatever the check says"


def test_a_planner_escalation_or_a_bad_plan_goes_to_the_cloud():
    got = atomic.run_case(atomic.Plan([], "", escalate="too wide"), FakeWorkspace(), _local())
    assert got["final"] == "cloud" and got["escalate"] == "too wide"


def _row(passed, applied=True, p2p_broken=False, tok=(10, 5, 0, 0)):
    return {"passed": passed, "applied": applied, "p2p_broken": p2p_broken, "failure_class": "",
            "tokens": dict(zip(("input", "output", "cache_write", "cache_read"), tok))}


def test_the_three_arms_count_solves_false_accepts_and_tokens_the_same_way():
    local = {"a": _row(True, tok=(1000, 100, 0, 0)), "b": _row(False, tok=(1000, 100, 0, 0)),
             "c": _row(False, applied=False, tok=(1000, 100, 0, 0))}
    cloud = {"a": _row(True, tok=(2, 300, 3000, 50)), "b": _row(True, tok=(2, 300, 3000, 50)),
             "c": _row(False, tok=(2, 300, 3000, 50))}
    records = {"a": {"final": "local", "solved": True, "false_accept": False, "local_tokens": 500,
                     "plan_tokens": {"input": 2, "output": 400, "cache_write": 1000, "cache_read": 9}},
               "b": {"final": "local", "solved": False, "false_accept": True, "local_tokens": 700,
                     "plan_tokens": {"input": 2, "output": 400, "cache_write": 1000, "cache_read": 9}},
               "c": {"final": "cloud", "solved": False, "false_accept": False, "local_tokens": 900,
                     "plan_tokens": {"input": 2, "output": 400, "cache_write": 1000, "cache_read": 9}}}
    rep = atomic.arms(records, local, cloud)
    one, routed, at = rep["cloud-only"], rep["routed"], rep["atomic"]
    assert (one["solved"], one["n"], one["local_tokens"], one["cloud_tokens"], one["cloud_calls"]) == (2, 3, 0, 9906, 3)
    assert one["false_accepts"] == 1, "c applied, held pass_to_pass and was wrong"
    assert (routed["solved"], routed["false_accepts"], routed["cloud_calls"]) == (1, 2, 1)
    assert (routed["local_tokens"], routed["cloud_tokens"]) == (3300, 3302)
    assert (at["solved"], at["false_accepts"], at["cloud_calls"]) == (1, 2, 4)
    assert at["plan_tokens"] == 3 * 1402 and at["cloud_tokens"] == 3 * 1402 + 3302 and at["local_tokens"] == 2100
    assert at["local_false_accepts"] == 1 and routed["local_false_accepts"] == 1 and one["local_false_accepts"] == 0
    text = "\n".join(atomic.report(records, local, cloud)["lines"])
    assert "atomic" in text and "routed" in text and "cloud-only" in text


def test_the_plan_call_counts_input_output_and_cache_writes_from_claude_p():
    body = {"type": "result", "result": json.dumps(PLAN), "is_error": False,
            "usage": {"input_tokens": 3, "output_tokens": 800, "cache_creation_input_tokens": 4000,
                      "cache_read_input_tokens": 12000}}

    def run(argv, **kw):
        run.argv, run.input = argv, kw.get("input")

        class Done:
            returncode, stdout, stderr = 0, json.dumps(body), ""
        return Done()
    got = atomic.ask_claude("plan this", "claude-opus-5-5", run=run)
    assert got["text"] == json.dumps(PLAN) and run.input == "plan this"
    assert got["tokens"] == {"input": 3, "output": 800, "cache_write": 4000, "cache_read": 12000}
    assert atomic.counted(got["tokens"]) == 4803
    assert run.argv[:4] == ["claude", "-p", "--model", "claude-opus-5-5"] and run.argv[-2:] == ["--tools", ""]


def test_the_command_refuses_while_another_run_holds_the_machine(monkeypatch, tmp_path, capsys):
    from harness import cli, delegate
    monkeypatch.setattr(delegate, "busy", lambda: "eval run 900 (pid 1)")
    rc = cli.main(["atomic", "--out", str(tmp_path / "o"), "--case", "sohot-363-spec"])
    said = capsys.readouterr()
    assert rc == 2 and "eval run 900" in said.out + said.err


def test_a_reply_budget_over_the_served_context_is_retried_at_its_cap_and_a_prompt_too_long_fails():
    from harness import completion, delegate

    def complete(lane, prompt, **kw):
        complete.budgets.append(kw["max_tokens"])
        if kw["max_tokens"] > complete.most:
            raise delegate.Refused(f"max_tokens must be 1..{complete.most} (the context), not {kw['max_tokens']}")
        return {"text": GOOD, "prompt_tokens": 1, "completion_tokens": 1}
    complete.budgets, complete.most = [], 9000
    got, why = atomic.ask_local(complete, "code", "p")
    assert why == "" and complete.budgets == [atomic.LOCAL_MAX_TOKENS, 9000]
    complete.budgets, complete.most = [], 100
    got, why = atomic.ask_local(complete, "code", "p")
    assert got == {} and why.startswith("refused") and complete.budgets == [atomic.LOCAL_MAX_TOKENS]

    def late(lane, prompt, **kw):
        raise completion.CompletionError("timed out", "timeout")
    assert atomic.ask_local(late, "code", "p")[1].startswith("no reply")


def test_the_live_lock_is_read_with_lsof_and_the_scratch_home_gets_the_interactive_plan(tmp_path):
    class Got:
        stdout = "4242\n77\n"
    lock = tmp_path / "generation.lock"
    assert atomic.lock_holders(lock, run=lambda argv, **kw: Got()) == f"pid 4242 77 holding {lock}"
    Got.stdout = ""
    assert atomic.lock_holders(lock, run=lambda argv, **kw: Got()) == ""
    live, scratch = tmp_path / "live", tmp_path / "scratch"
    live.mkdir()
    scratch.mkdir()
    (live / "interactive.json").write_text('{"lanes": {"code": {}}}', encoding="utf-8")
    built, half = live / "repo-cache" / "envs" / "abc", live / "repo-cache" / "envs" / "def"
    built.mkdir(parents=True)
    half.mkdir()
    (built / ".built").write_text("abc", encoding="utf-8")
    assert atomic.seed_home(live, scratch) == ["interactive.json", "envs/abc"]
    assert (scratch / "repo-cache" / "envs" / "abc").resolve() == built.resolve()
    assert not (scratch / "repo-cache" / "envs" / "def").exists(), "a half-built environment is not reused"
    assert (scratch / "interactive.json").read_text(encoding="utf-8") == '{"lanes": {"code": {}}}'


@dataclasses.dataclass
class Case:
    id: str
    prompt: str = "fix it"
    params: dict = dataclasses.field(default_factory=lambda: {"context_files": ["pkg/mod.py"], "variant": "spec"})


class PlanningWorkspace(FakeWorkspace):
    def __init__(self, params):
        super().__init__(outcomes=[PASS])

    def plan_prompt(self, issue):
        return f"{issue}\n\nplan"

    def close(self):
        pass


def test_a_run_keeps_each_plan_and_record_resumes_without_asking_again_and_stops_while_the_machine_is_held(tmp_path):
    asked = []

    def ask(prompt, model):
        asked.append(prompt)
        return {"text": json.dumps(PLAN), "tokens": {"input": 1, "output": 2, "cache_write": 3, "cache_read": 4}}
    rows = {"a": _row(True), "b": _row(False)}
    rep = atomic.run(tmp_path, [Case("a")], local=rows, cloud=rows, ask=ask, complete=_local(GOOD),
                     workspace=PlanningWorkspace)
    assert len(asked) == 1 and rep["arms"]["atomic"]["solved"] == 1 and (tmp_path / "plans" / "a.json").is_file()
    rep = atomic.run(tmp_path, [Case("a"), Case("b")], local=rows, cloud=rows, ask=ask, complete=_local(),
                     workspace=PlanningWorkspace, busy=lambda: "pid 9 holding generation.lock")
    assert len(asked) == 1 and rep["stopped"] == "pid 9 holding generation.lock" and rep["arms"]["atomic"]["n"] == 1
