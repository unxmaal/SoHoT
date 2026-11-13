"""Atomic subtasks on the repo lane: Claude writes specs and hidden checks, the local model writes one function or file per subtask, fresh retries, cloud on failure. #1690."""
from __future__ import annotations

import ast
import json
import re
import subprocess
import textwrap
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

#: Fresh local attempts per case before it goes to the cloud: each regenerates every subtask from the same prompt.
ATTEMPTS = 3
KINDS = ("function", "file")
#: Where the hidden check runs from the repository root; the grader's install_tests removes it before the full suite.
CHECK_PATH = "tests/test_atomic_check.py"
CLOUD_MODEL = "claude-opus-5-5"
LOCAL_RUN, CLOUD_RUN = 571, 572
PLAN_TIMEOUT_S = 900.0
LOCAL_MAX_TOKENS = 16384
#: Below this reply budget a whole function with its reasoning does not fit; the attempt fails instead.
MIN_REPLY_TOKENS = 2048
_FITS = re.compile(r"max_tokens must be 1\.\.(\d+)")
#: Characters of a failed reply kept in its record, so a failure can be told from a grader defect afterwards.
REPLY_TAIL = 400
ARMS = ("cloud-only", "routed", "atomic")

PLAN_SYSTEM = ("You plan a code change for a smaller model that writes one function or one file at a time and never "
               "sees the tests. Reply with one JSON object and nothing else.")
PLAN_ASK = """Split the change into atomic subtasks for a smaller local model. Each subtask is one of:
- "function": write or rewrite one top-level function (symbol "name") or one method (symbol "Class.name") in a file \
listed above. The model returns that whole function and nothing else; it replaces the old one or is added. Imports \
it needs go inside its body.
- "file": write one whole file: a file to create, or a listed file whose change is not confined to functions \
(module constants, imports, new classes). Prefer "function" for long files.
Each subtask has: "path"; "kind"; "symbol" ("" for a file); "spec": everything the implementer needs, since it \
cannot see the issue, the other subtasks' code or any test (behaviour, edge cases, exact messages and names, the \
helpers it may call); "contract": the exact `def` line, with parameters, of every function its output must define.
Never make a subtask of a test file.
Then "check": one pytest file, run from the repository root as tests/test_atomic_check.py, that tests the finished \
change against the issue. It must fail on the code as given above and pass once the change is right. The \
implementer never sees it, so test behaviour the specs state, not wording they leave open.
Reply with one JSON object: {"subtasks": [{"path": "...", "kind": "function", "symbol": "...", "spec": "...", \
"contract": ["def ...(...):"]}], "check": "..."}
If the change cannot be split this way, reply {"escalate": "<why>"}."""
LOCAL_SYSTEM = "You write Python to a spec. Reply with exactly one fenced python code block and nothing after it."

_BLOCK = re.compile(r"```(?:python|py|python3)?[^\n]*\n(.*?)```", re.S)
_JSON_BLOCK = re.compile(r"```(?:json)?[^\n]*\n(.*?)```", re.S)
_ANY_BLOCK = re.compile(r"```[^\n]*\n(.*?)```", re.S)


class PlanError(ValueError):
    """The planner's reply is not a usable plan; the case goes to the cloud."""


class UnitError(ValueError):
    """A local unit cannot go into its file; the attempt fails."""


class CloudError(RuntimeError):
    """claude -p gave no usable answer."""


@dataclass
class Subtask:
    path: str
    kind: str
    symbol: str
    spec: str
    contract: list = field(default_factory=list)


@dataclass
class Plan:
    subtasks: list
    check: str
    escalate: str = ""


def _defs(tree) -> dict:
    return {n.name: n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def _params(node) -> list:
    a = node.args
    names = [x.arg for x in (*a.posonlyargs, *a.args)]
    names += [f"*{a.vararg.arg}"] if a.vararg else []
    names += [x.arg for x in a.kwonlyargs]
    return names + ([f"**{a.kwarg.arg}"] if a.kwarg else [])


def _contract_def(line: str):
    try:
        tree = ast.parse(line.strip() + "\n    ...\n")
    except SyntaxError:
        return None
    node = tree.body[0] if tree.body else None
    return node if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) else None


def _plan_json(text: str) -> dict:
    tries = [text.strip(), *(m.group(1) for m in _JSON_BLOCK.finditer(text or ""))]
    if "{" in (text or ""):
        tries.append(text[text.index("{"):text.rindex("}") + 1])
    for t in tries:
        try:
            got = json.loads(t)
        except ValueError:
            continue
        if isinstance(got, dict):
            return got
    raise PlanError("no JSON plan in the reply")


def parse_plan(text: str, allowed) -> Plan:
    """The planner's subtasks and hidden check, each subtask held to a non-test file of the case."""
    from evals.repo import is_test_path
    got = _plan_json(text)
    if str(got.get("escalate") or "").strip():
        return Plan([], "", escalate=str(got["escalate"]).strip())
    subs = []
    for s in got.get("subtasks") or []:
        path, kind, symbol = str(s.get("path") or ""), str(s.get("kind") or ""), str(s.get("symbol") or "").strip()
        if is_test_path(path):
            raise PlanError(f"{path} is a test file; the hidden tests replace test files")
        if path not in allowed:
            raise PlanError(f"{path} is not a file of this case")
        if kind not in KINDS:
            raise PlanError(f"{path}: kind {kind!r} is not one of {', '.join(KINDS)}")
        if kind == "function" and not is_python(path):
            raise PlanError(f"{path}: a function subtask needs a Python file")
        if kind == "function" and not symbol:
            raise PlanError(f"{path}: a function subtask needs its symbol")
        contract = [str(c) for c in (s.get("contract") or [])]
        bad = [c for c in contract if _contract_def(c) is None]
        if bad:
            raise PlanError(f"{path}: contract lines that are not def lines: {bad}")
        subs.append(Subtask(path, kind, symbol, str(s.get("spec") or ""), contract))
    if not subs:
        raise PlanError("the plan has no subtasks")
    check = str(got.get("check") or "")
    try:
        tests = [n for n in _defs(ast.parse(check)) if n.startswith("test")]
    except SyntaxError as exc:
        raise PlanError(f"the check does not parse: {exc}") from exc
    if not tests:
        raise PlanError("the check defines no test function")
    return Plan(subs, check)


def is_python(path: str) -> bool:
    return path.endswith(".py")


def extract_unit(reply: str, python: bool = True) -> str:
    """The last python block of the reply, or the whole reply when it parses as code that defines something."""
    if not python:
        blocks = _ANY_BLOCK.findall(reply or "")
        return blocks[-1].strip("\n") + "\n" if blocks else ""
    blocks = _BLOCK.findall(reply or "")
    if blocks:
        return textwrap.dedent(blocks[-1]).strip("\n") + "\n"
    text = textwrap.dedent(reply or "").strip("\n")
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return ""
    return text + "\n" if _defs(tree) else ""


def contract_ok(unit: str, sub: Subtask) -> str:
    """"" when the unit defines every contract def with its parameters, else why not. The local model sees this."""
    if not is_python(sub.path):
        return ""
    try:
        tree = ast.parse(unit)
    except SyntaxError as exc:
        return f"the reply does not parse: {exc.msg} (line {exc.lineno})"
    have: dict = {}
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            have.setdefault(n.name, []).append(_params(n))
    for line in sub.contract:
        want = _contract_def(line)
        if want.name not in have:
            return f"the reply defines no {want.name}"
        need = _params(want)
        if need not in have[want.name]:
            got = have[want.name][0]
            return f"{want.name} takes ({', '.join(got)}), the contract says ({', '.join(need)})"
    return ""


def _indent(text: str, n: int) -> str:
    pad = " " * n
    return "".join(pad + ln if ln.strip() else ln for ln in text.splitlines(keepends=True))


def splice(source: str | None, sub: Subtask, unit: str) -> str:
    """The file with the unit in place: a whole file, or one function or method replaced or added."""
    if not is_python(sub.path):
        return unit
    unit = textwrap.dedent(unit).strip("\n") + "\n"
    try:
        tree = ast.parse(unit)
    except SyntaxError as exc:
        raise UnitError(f"the reply does not parse: {exc.msg} (line {exc.lineno})") from exc
    if sub.kind == "file":
        return unit
    cls, _, name = sub.symbol.rpartition(".")
    if not any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name for n in tree.body):
        raise UnitError(f"the reply defines no function {name} at its top level")
    if source is None:
        if cls:
            raise UnitError(f"no class {cls} in {sub.path}: the file does not exist")
        return unit
    lines = source.splitlines(keepends=True)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    body, owner = ast.parse(source).body, None
    if cls:
        owner = next((n for n in body if isinstance(n, ast.ClassDef) and n.name == cls), None)
        if owner is None:
            raise UnitError(f"no class {cls} in {sub.path}")
        body = owner.body
    old = next((n for n in body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name), None)
    if old is not None:
        start = min([old.lineno, *(d.lineno for d in old.decorator_list)]) - 1
        lines[start:old.end_lineno] = [_indent(unit, old.col_offset)]
    elif owner is not None:
        lines[owner.end_lineno:owner.end_lineno] = ["\n", _indent(unit, body[0].col_offset)]
    else:
        lines += ["\n", "\n", unit]
    out = "".join(lines)
    try:
        ast.parse(out)
    except SyntaxError as exc:
        raise UnitError(f"the spliced file does not parse: {exc.msg} (line {exc.lineno})") from exc
    return out


def subtask_prompt(sub: Subtask, text: str | None, others=()) -> str:
    """What the local model sees: its spec, its visible contract, the file at base, the others' contracts. Never the check."""
    what = "the whole file" if sub.kind == "file" else (
        f"the whole method {sub.symbol.rpartition('.')[2]} of class {sub.symbol.rpartition('.')[0]}"
        if "." in sub.symbol else f"the whole function {sub.symbol}")
    parts = [f"Write {what} for {sub.path}.", f"Spec:\n{sub.spec.strip()}"]
    if sub.contract:
        parts.append("Contract: your code must define these, with exactly these parameters:\n" + "\n".join(sub.contract))
    rest = [c for o in others if o is not sub for c in o.contract]
    if rest:
        parts.append("Other parts of the same change, written separately, that you may call:\n" + "\n".join(rest))
    fence = "python" if is_python(sub.path) else ""
    parts.append(f"{sub.path} as it is now:\n```{fence}\n{text}```" if text is not None
                 else f"{sub.path} does not exist yet.")
    parts.append(f"Reply with one ```{fence} block holding only {what}"
                 + (", decorators included." if sub.kind == "function" else "."))
    return "\n\n".join(parts)


def _local_tokens(got: dict) -> int:
    return int(got.get("prompt_tokens") or 0) + int(got.get("completion_tokens") or 0)


def ask_local(complete, lane: str, prompt: str, model: str | None = None) -> tuple[dict, str]:
    """(reply, "") or ({}, why): a reply budget over what the served context leaves is retried once at that cap."""
    from harness import completion, cuts, delegate, reasons
    budget = LOCAL_MAX_TOKENS
    while True:
        try:
            return complete(lane, prompt, system=LOCAL_SYSTEM, max_tokens=budget, delegated=False, model=model), ""
        except delegate.Refused as exc:
            m = _FITS.search(str(exc))
            if m and int(m.group(1)) < MIN_REPLY_TOKENS:
                cuts.cut("atomic_min_reply_tokens", "a subtask prompt leaving too small a reply budget", kept=0,
                         dropped=1)
            if not m or not MIN_REPLY_TOKENS <= int(m.group(1)) < budget:
                return {}, f"refused: {exc}"
            cuts.cut("atomic_local_max_tokens", "a subtask reply budget cut to the served context", value=budget)
            budget = int(m.group(1))
        except completion.CompletionError as exc:
            if exc.failure_class == reasons.TOKEN_BUDGET_EXHAUSTED:
                cuts.cut("atomic_local_max_tokens", "a subtask reply cut at its budget", kept=0, dropped=1, value=budget)
            return {}, f"no reply: {exc}"


def run_case(plan: Plan, ws, complete, attempts: int = ATTEMPTS, lane: str = "code", model: str | None = None) -> dict:
    """One case: the vacuous-check control, then up to `attempts` fresh local attempts gated on the hidden check."""
    rec = {"final": "cloud", "escalate": plan.escalate, "subtasks": len(plan.subtasks), "vacuous": False,
           "reference_passes": None, "attempts": [], "local_tokens": 0, "solved": False, "false_accept": False}
    if plan.escalate:
        return rec
    if ws.check_at("base", plan.check):
        rec["vacuous"] = True
        return rec
    rec["reference_passes"] = ws.check_at("reference", plan.check)
    base = {s.path: ws.read(s.path) for s in plan.subtasks}
    prompts = [subtask_prompt(s, base[s.path], plan.subtasks) for s in plan.subtasks]
    for _ in range(attempts):
        files, why, calls = {}, "", []
        for sub, prompt in zip(plan.subtasks, prompts):
            started = time.perf_counter()
            got, why = ask_local(complete, lane, prompt, model)
            rec["local_tokens"] += _local_tokens(got)
            calls.append({"tokens": _local_tokens(got), "seconds": round(time.perf_counter() - started, 1),
                          "model": got.get("model") or ""})
            unit = extract_unit(got.get("text") or "", is_python(sub.path))
            why = why or (contract_ok(unit, sub) if unit else "the reply holds no python block")
            if not why:
                try:
                    files[sub.path] = splice(files.get(sub.path, base[sub.path]), sub, unit)
                except UnitError as exc:
                    why = str(exc)
            if why:
                why = f"{sub.path} {sub.symbol}: {why}".replace("  ", " ")
                calls[-1]["tail"] = (got.get("text") or "")[-REPLY_TAIL:]
                break
        att = {"why": why, "calls": calls}
        rec["attempts"].append(att)
        if why:
            continue
        att.update(ws.attempt(files, plan.check))
        att["gate"] = bool(att["check"] and att["p2p"])
        if att["gate"]:
            rec.update(final="local", solved=bool(att["full"]), false_accept=not att["full"])
            break
    if rec["final"] == "cloud":
        from harness import cuts
        cuts.cut("atomic_attempts", "a case whose fresh local attempts all failed, sent to the cloud", kept=0, dropped=1)
    return rec


class RepoWorkspace:
    """A case's checkout at base: the check run alone, and a local attempt run under the check and the full suite."""

    def __init__(self, params: dict):
        from evals import repo
        self.repo, self.p = repo, params
        self.att = repo.Attempt.open(params)
        self.task = self.att.task

    def close(self) -> None:
        self.att.close()

    def _reset(self) -> None:
        self.repo._git(["reset", "--hard", "--quiet"], cwd=self.task, check=False)
        self.repo._git(["clean", "-fdq"], cwd=self.task, check=False)

    def read(self, path: str) -> str | None:
        f = self.task / path
        return f.read_text(encoding="utf-8") if f.is_file() else None

    def plan_prompt(self, issue: str) -> str:
        new = self.p.get("new_files") or ()
        create = f"Files to create (they do not exist at the commit to fix): {', '.join(new)}\n\n" if new else ""
        return (f"{issue.strip()}\n\nThe relevant files at the commit to fix:\n\n"
                f"{self.repo.context_block(self.task, self.p['context_files'])}\n\n{create}{PLAN_ASK}")

    def _check(self, check: str) -> bool:
        f = self.task / CHECK_PATH
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(check, encoding="utf-8")
        xml = self.task / self.repo.HARNESS_DIR / "check.xml"
        xml.parent.mkdir(parents=True, exist_ok=True)
        xml.unlink(missing_ok=True)
        rc, _, late = self.repo.run_sandboxed(
            [str(self.att.python), "-m", "pytest", "-p", "no:cacheprovider", "-q", "-o", "addopts=",
             *(self.p.get("pytest_args") or ()), f"--junitxml={xml}", CHECK_PATH], self.task, self.repo.TEST_TIMEOUT_S)
        f.unlink(missing_ok=True)
        if late or not xml.is_file():
            return False
        ok, bad = self.repo._junit_ids(xml)
        return rc == 0 and bool(ok) and not bad

    def check_at(self, which: str, check: str) -> bool:
        self._reset()
        try:
            if which == "reference":
                diff = self.repo.reference_diff(self.att.mirror, self.p["base"], self.p["fix"])
                if not self.repo.apply(self.task, diff)[0]:
                    return False
            return self._check(check)
        finally:
            self._reset()

    def attempt(self, files: dict, check: str) -> dict:
        self._reset()
        try:
            for path, text in files.items():
                f = self.task / path
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_text(text, encoding="utf-8")
            passed = self._check(check)
            p = self.p
            self.repo.install_tests(self.att.mirror, self.task, p["base"], p["fix"])
            g = self.repo.grade(self.task, self.att.python, p["fail_to_pass"], p.get("pass_to_pass") or [],
                                p.get("pytest_args") or ())
            return {"check": passed, "p2p": "pass_to_pass broken" not in g.detail, "full": bool(g.resolved),
                    "detail": g.detail[:300]}
        finally:
            self._reset()


def lock_holders(lock: Path, run=subprocess.run) -> str:
    """The pids lsof finds holding the live generation.lock open, "" when none; a scratch home cannot see that lock."""
    try:
        got = run(["lsof", "-t", str(lock)], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        return f"lsof failed on {lock}: {exc}"
    pids = " ".join((got.stdout or "").split())
    return f"pid {pids} holding {lock}" if pids else ""


def seed_home(live: Path, scratch: Path) -> list:
    """The machine's built case environments linked into a scratch home; its interactive plan is read where it is (#1711)."""
    out = []
    # Built case environments are reused, not rebuilt: grading runs them sandboxed, writing nothing outside the task.
    envs = Path(live) / "repo-cache" / "envs"
    for env in sorted(envs.iterdir()) if envs.is_dir() and Path(live).resolve() != Path(scratch).resolve() else ():
        link = Path(scratch) / "repo-cache" / "envs" / env.name
        if (env / ".built").is_file() and not link.exists():
            link.parent.mkdir(parents=True, exist_ok=True)
            link.symlink_to(env, target_is_directory=True)
            out.append(f"envs/{env.name}")
    return out


def counted(tokens: dict) -> int:
    """Cloud tokens under the #1688 rule: input, output and cache writes; cache reads are not counted."""
    from harness import ledger
    return sum(int(tokens.get(k) or 0) for k in ledger.CLOUD_COUNTED)


def ask_claude(prompt: str, model: str = CLOUD_MODEL, run=subprocess.run, timeout: float = PLAN_TIMEOUT_S) -> dict:
    """One headless claude -p call on the subscription, tools off: its text and token usage."""
    from evals.runners.claude_code import result_of
    argv = ["claude", "-p", "--model", model, "--output-format", "json", "--no-session-persistence",
            "--strict-mcp-config", "--setting-sources", "", "--system-prompt", PLAN_SYSTEM, "--tools", ""]
    from harness import cuts
    started = time.perf_counter()
    with cuts.timeout("atomic_plan_timeout_s", "a claude -p planning call", value=timeout):
        got = run(argv, input=prompt, capture_output=True, text=True, timeout=timeout)
    try:
        body = result_of(got.stdout or "")
    except ValueError as exc:
        raise CloudError(f"claude -p exited {got.returncode}: {(got.stderr or '')[-300:]}") from exc
    if body.get("is_error"):
        raise CloudError(f"claude -p: {str(body.get('result'))[:300]}")
    u = body.get("usage") or {}
    tokens = {"input": int(u.get("input_tokens") or 0), "output": int(u.get("output_tokens") or 0),
              "cache_write": int(u.get("cache_creation_input_tokens") or 0),
              "cache_read": int(u.get("cache_read_input_tokens") or 0)}
    return {"text": str(body.get("result") or ""), "tokens": tokens, "seconds": round(time.perf_counter() - started, 1),
            "model": model}


def stored(conn, run_id: int) -> dict:
    """repo_routing's rows of a stored run, each with its tokens: local prompt/completion, cloud with cache writes."""
    from evals import repo_routing
    rows = repo_routing.load(conn, run_id)
    for case, rep, metrics in conn.execute("SELECT case_id, repeat_index, metrics FROM results WHERE run_id = ?",
                                           (int(run_id),)):
        if case in rows and (rep or 1) == 1:
            m = json.loads(metrics or "{}")
            rows[case]["tokens"] = {"input": int(m.get("prompt_tokens") or 0),
                                    "output": int(m.get("completion_tokens") or 0),
                                    "cache_write": int(m.get("cache_creation_tokens") or 0),
                                    "cache_read": int(m.get("cache_read_tokens") or 0)}
    return rows


def _gated(row: dict) -> bool:
    return row["applied"] and not row["p2p_broken"]


def arms(records: dict, local: dict, cloud: dict) -> dict:
    """cloud-only, routed (#891's gate-visible cascade) and atomic; a false accept is a gated answer the full suite fails."""
    ks = sorted(k for k in records if k in local and k in cloud and "error" not in records[k])
    zero = {"n": len(ks), "solved": 0, "false_accepts": 0, "local_false_accepts": 0, "local_kept": 0,
            "local_tokens": 0, "cloud_tokens": 0, "plan_tokens": 0, "cloud_calls": 0}
    out = {a: dict(zero) for a in ARMS}

    def to_cloud(acc, k):
        acc["cloud_calls"] += 1
        acc["cloud_tokens"] += counted(cloud[k]["tokens"])
        acc["solved"] += cloud[k]["passed"]
        acc["false_accepts"] += _gated(cloud[k]) and not cloud[k]["passed"]

    def kept(acc, ok):
        acc["local_kept"] += 1
        acc["solved"] += ok
        acc["false_accepts"] += not ok
        acc["local_false_accepts"] += not ok
    for k in ks:
        to_cloud(out["cloud-only"], k)
        r = out["routed"]
        r["local_tokens"] += local[k]["tokens"]["input"] + local[k]["tokens"]["output"]
        if _gated(local[k]):
            kept(r, local[k]["passed"])
        else:
            to_cloud(r, k)
        a, rec = out["atomic"], records[k]
        a["local_tokens"] += rec.get("local_tokens") or 0
        plan = counted(rec.get("plan_tokens") or {})
        a["plan_tokens"] += plan
        a["cloud_tokens"] += plan
        a["cloud_calls"] += 1
        if rec["final"] == "local":
            kept(a, bool(rec["solved"]))
        else:
            to_cloud(a, k)
    for acc in out.values():
        acc["ratio"] = round(acc["local_tokens"] / acc["cloud_tokens"], 3) if acc["cloud_tokens"] else None
    return out


def diagnostics(records: dict) -> dict:
    recs = [r for r in records.values() if "error" not in r]
    ran = [r for r in recs if not r.get("escalate") and not r.get("vacuous")]
    tries = [a for r in ran for a in r.get("attempts") or []]
    return {"cases": len(recs), "errors": len(records) - len(recs),
            "planner_escalated": sum(1 for r in recs if r.get("escalate")),
            "vacuous_checks": sum(1 for r in recs if r.get("vacuous")),
            "check_rejects_reference": sum(1 for r in ran if r.get("reference_passes") is False),
            "local_tried": len(ran), "attempts": len(tries),
            "contract_or_splice_failures": sum(1 for a in tries if a["why"]),
            "gate_passes": sum(1 for r in ran if r["final"] == "local"),
            "any_attempt_full_pass": sum(1 for r in ran if any(a.get("full") for a in r.get("attempts") or [])),
            "local_seconds": round(sum(c["seconds"] for a in tries for c in a["calls"]), 1),
            "plan_seconds": round(sum(r.get("plan_seconds") or 0 for r in recs), 1)}


def lines(rep: dict) -> list:
    from harness import intervals, ledger
    d = rep["diagnostics"]
    out = [f"{d['cases']} cases ({d['errors']} could not be set up); planner escalated {d['planner_escalated']}, "
           f"vacuous checks caught {d['vacuous_checks']} (they pass on the unchanged code), checks that reject the "
           f"reference fix {d['check_rejects_reference']} of {d['local_tried']} tried locally",
           f"local: {d['attempts']} attempts, {d['contract_or_splice_failures']} failed the contract or splice, "
           f"{d['gate_passes']} cases passed the gate, {d['any_attempt_full_pass']} had an attempt pass the full "
           f"suite; {d['local_seconds']:.0f}s local, {d['plan_seconds']:.0f}s planning",
           f"{'arm':11s} {'solved':>16s} {'false acc':>9s} {'local FA':>8s} {'kept':>5s} {'cloud':>6s} "
           f"{'local tok':>10s} {'cloud tok':>10s} {'plan tok':>9s} {'local:cloud':>11s}"]
    for name in ARMS:
        a = rep["arms"][name]
        lo, hi = intervals.wilson(a["solved"], a["n"]) if a["n"] else (0.0, 0.0)
        out.append(f"{name:11s} {a['solved']:>3d}/{a['n']:<3d} [{lo:.2f},{hi:.2f}] {a['false_accepts']:>9d} "
                   f"{a['local_false_accepts']:>8d} {a['local_kept']:>5d} {a['cloud_calls']:>6d} "
                   f"{a['local_tokens']:>10,} {a['cloud_tokens']:>10,} {a['plan_tokens']:>9,} "
                   f"{ledger._as_ratio(a['ratio']):>11s}")
    return out


def report(records: dict, local: dict, cloud: dict) -> dict:
    rep = {"arms": arms(records, local, cloud), "diagnostics": diagnostics(records)}
    every = arms({k: {"final": "cloud"} for k in local if k in cloud}, local, cloud)
    rep["stored"] = {a: every[a] for a in ARMS[:2]}
    rep["lines"] = lines(rep) + [
        f"every stored case: {a} {s['solved']}/{s['n']}, {s['false_accepts']} false accepts, {s['cloud_calls']} cloud "
        f"calls, {s['local_tokens']:,} local / {s['cloud_tokens']:,} cloud tokens" for a, s in rep["stored"].items()]
    return rep


def run(out: Path, cases, *, local: dict, cloud: dict, model: str = CLOUD_MODEL, attempts: int = ATTEMPTS,
        ask=ask_claude, complete=None, workspace=RepoWorkspace, busy=None, progress=None,
        local_model: str | None = None) -> dict:
    """Plan, check and run each case, keeping each plan and record under out so a rerun resumes and never re-asks."""
    from evals import repo
    if complete is None:
        from harness.delegate import complete
    out = Path(out)
    (out / "plans").mkdir(parents=True, exist_ok=True)
    (out / "cases").mkdir(parents=True, exist_ok=True)
    records = {}
    for case in cases:
        done = out / "cases" / f"{case.id}.json"
        if done.is_file():
            records[case.id] = json.loads(done.read_text(encoding="utf-8"))
            continue
        held = busy() if busy else ""
        if held:
            records["__stopped__"] = held
            break
        try:
            ws = workspace(case.params)
        except (repo.RepoEnvError, OSError, subprocess.SubprocessError) as exc:
            rec = {"error": str(exc)[:400]}
        else:
            try:
                rec = _one(case, ws, out, model, attempts, ask, complete, local_model)
            finally:
                ws.close()
        rec["case"] = case.id
        done.write_text(json.dumps(rec, indent=1) + "\n", encoding="utf-8")
        records[case.id] = rec
        if progress:
            progress(rec)
    stopped = records.pop("__stopped__", "")
    rep = report(records, local, cloud)
    rep["stopped"] = stopped
    (out / "report.json").write_text(json.dumps(rep, indent=1) + "\n", encoding="utf-8")
    return rep


def _one(case, ws, out: Path, model: str, attempts: int, ask, complete, local_model=None) -> dict:
    from evals import repo
    cached = out / "plans" / f"{case.id}.json"
    if cached.is_file():
        got = json.loads(cached.read_text(encoding="utf-8"))
    else:
        got = ask(ws.plan_prompt(repo.as_asked(case).prompt), model)
        cached.write_text(json.dumps(got, indent=1) + "\n", encoding="utf-8")
    p = case.params
    try:
        plan = parse_plan(got["text"], [*p["context_files"], *(p.get("new_files") or ())])
    except PlanError as exc:
        plan = Plan([], "", escalate=f"bad plan: {exc}")
    rec = run_case(plan, ws, complete, attempts, model=local_model)
    rec.update(plan_tokens=got["tokens"], plan_seconds=got.get("seconds") or 0.0,
               plan=[asdict(s) for s in plan.subtasks])
    return rec
