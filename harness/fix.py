"""soh fix: a cloud plan writes a failing test, a local model makes it pass, a runner-enforced gate decides (#2035)."""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

CLASSES = ("flaky_test", "scaffold_registration", "mechanical_split", "read_the_field")
OUT_OF_CLASS = "out_of_class"
#: Source files one plan may change.
MAX_FILES = 3
#: Counted cloud tokens (input, output, cache writes) one plan may spend.
PLAN_TOKEN_CAP = 20_000
PLAN_MODEL = "claude-opus-5-5"
PLAN_TOOLS = "Read,Grep,Glob"
PLAN_MAX_TURNS = 12
PLAN_TIMEOUT_S = 600.0
AGENT_ALIAS = "sohot-agent"
EXEC_TOOLS = "Read,Edit,Grep,Bash"
EXEC_MAX_TURNS = 30
EXEC_TIMEOUT_S = 600.0
#: Local attempts per issue: the first, then one fresh one told why the gate refused.
ATTEMPTS = 2
GATE_TIMEOUT_S = 240.0
#: Lines of a refused gate step's output handed to the next attempt and kept in the record.
TAIL_LINES = 40
LANE, PLAN_LANE, REPLAY_LANE = "fix", "fix-plan", "fix-replay"
#: Paths no plan may name: migrations, the deploy path, the store schema.
FORBIDDEN = re.compile(r"(^|/)migrations?/|memory_store/schema\.py$|deploy|^scripts/launchd\.sh$")
PYTEST = ("uv", "run", "--group", "mcp", "pytest", "-q", "-p", "no:cacheprovider")
CHECKS = (("make", "precheck"), ("make", "lint"))
#: pytest exit codes that mean the planned test ran, or tried to import what is not there yet, and failed.
FAILED_RCS = (1, 2)

PLAN_SYSTEM = f"""You plan one fix for a small local model that cannot interpret issues. Read only what you need \
with Read, Grep and Glob: the whole plan has a {PLAN_TOKEN_CAP:,}-token budget. Then answer with ONE JSON object \
and nothing else:
{{"class": "{'" | "'.join(CLASSES)}" | "{OUT_OF_CLASS}", "why": "one line",
"files": ["at most {MAX_FILES} repo-relative files to change, an existing test only when it is the defect"],
"test_path": "tests/test_<topic>_<issue>.py, a file that does not exist yet",
"test_code": "the complete pytest file",
"brief": "exact instructions: which function or line changes and to what"}}
Classes: flaky_test, a flaky or timing-bound test whose cause the issue names; scaffold_registration, a \
registration a scaffold creates plus the lines that fill it; mechanical_split, a split or rename with behaviour \
and tests unchanged; read_the_field, a parser of prose replaced by a stored value. Answer {OUT_OF_CLASS} when none \
fits, or the fix needs a migration, the deploy path, the store schema or more than {MAX_FILES} source files.
The test must fail on the code as it is and pass once the brief is done, with no network and no live store."""


class PlanError(ValueError):
    """The plan does not parse or names what no plan may."""


@dataclass(frozen=True)
class Plan:
    klass: str
    files: tuple[str, ...] = ()
    test_path: str = ""
    test_code: str = ""
    brief: str = ""
    why: str = ""


@dataclass
class Verdict:
    ok: bool
    stage: str
    why: str = ""
    output: str = ""


@dataclass
class Record:
    issue: int
    call_id: str
    klass: str = ""
    stage: str = ""
    why: str = ""
    resolved: bool = False
    plan_tokens: dict = field(default_factory=dict)
    local_tokens: dict = field(default_factory=dict)
    attempts: list = field(default_factory=list)
    plan: dict = field(default_factory=dict)
    seconds: float = 0.0


def new_call_id() -> str:
    return "fix-" + uuid.uuid4().hex


def _safe(path: str) -> bool:
    p = Path(path)
    return bool(path) and not p.is_absolute() and ".." not in p.parts


def _json_object(text: str) -> dict:
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    raw = m.group(1) if m else text[text.find("{"):text.rfind("}") + 1]
    try:
        got = json.loads(raw)
    except ValueError as exc:
        raise PlanError(f"the plan is not JSON: {exc}") from exc
    if not isinstance(got, dict):
        raise PlanError("the plan is not a JSON object")
    return got


def parse_plan(text: str) -> Plan:
    got = _json_object(text)
    klass = str(got.get("class") or "")
    if klass == OUT_OF_CLASS:
        return Plan(OUT_OF_CLASS, why=str(got.get("why") or ""))
    if klass not in CLASSES:
        raise PlanError(f"class {klass!r} is not one of {CLASSES + (OUT_OF_CLASS,)}")
    files = tuple(str(f) for f in got.get("files") or ())
    test_path, code = str(got.get("test_path") or ""), str(got.get("test_code") or "")
    if len(files) > MAX_FILES:
        from harness import cuts
        cuts.cut("fix_max_files", "a plan naming more source files than one plan may change", kept=0, dropped=1)
    if not files or len(files) > MAX_FILES:
        raise PlanError(f"a plan changes 1 to {MAX_FILES} files, not {len(files)}")
    bad = [f for f in files if not _safe(f) or f == test_path or FORBIDDEN.search(f)]
    if bad:
        raise PlanError(f"files no plan may change: {bad}")
    if not (_safe(test_path) and test_path.startswith("tests/") and Path(test_path).name.startswith("test_")
            and test_path.endswith(".py")):
        raise PlanError(f"the test path {test_path!r} is not tests/test_*.py")
    if not code.strip():
        raise PlanError("the plan has no test code")
    return Plan(klass, files, test_path, code, str(got.get("brief") or ""), str(got.get("why") or ""))


def run_cmd(argv, cwd: Path, timeout: float = GATE_TIMEOUT_S) -> tuple[int, str]:
    """rc and output; no bytecode is written, so an edit inside the same second is never judged by a stale .pyc."""
    from harness import cuts
    try:
        with cuts.timeout("fix_gate_timeout_s", f"soh fix: {' '.join(argv[:3])}", value=timeout):
            got = subprocess.run(list(argv), cwd=str(cwd), capture_output=True, text=True, timeout=timeout,
                                 env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    except subprocess.TimeoutExpired:
        return 124, f"{' '.join(argv)}: no exit in {timeout:.0f}s"
    except OSError as exc:
        return 127, f"{' '.join(argv)}: {exc}"
    return got.returncode, (got.stdout or "") + (got.stderr or "")


def tail(text: str, n: int = TAIL_LINES) -> str:
    return "\n".join((text or "").splitlines()[-n:])


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else ""


def changed_paths(ws: Path, run=run_cmd) -> set[str]:
    """Every path the working tree changed, added or removed since its commit, untracked files included."""
    rc, out = run(("git", "status", "--porcelain", "--untracked-files=all"), ws)
    if rc != 0:
        raise OSError(f"git status: {tail(out, 5)}")
    got = set()
    for line in out.splitlines():
        for part in line[3:].split(" -> "):
            got.add(part.strip().strip('"'))
    return got - {""}


def selected_tests(ws: Path, files) -> list[str]:
    """The test files that import a module the plan changes."""
    pats = []
    for f in files:
        if not f.endswith(".py"):
            continue
        mod = f[:-3].replace("/", ".")
        pkg, _, name = mod.rpartition(".")
        pats.append(re.compile(rf"^\s*(import {re.escape(mod)}\b|from {re.escape(mod)} import\b"
                               + (rf"|from {re.escape(pkg)} import (\([^)]*|[^\n]*)\b{re.escape(name)}\b" if pkg else "")
                               + ")", re.M))
    if not pats:
        return []
    out = []
    for p in sorted((ws / "tests").glob("test_*.py")):
        text = p.read_text(encoding="utf-8", errors="replace")
        if any(r.search(text) for r in pats):
            out.append(p.relative_to(ws).as_posix())
    return out


def at_base(ws: Path, plan: Plan, run=run_cmd, pytest=PYTEST) -> tuple[Verdict, str]:
    """Write the planned test and run it at base; it must fail there. Returns the verdict and the test's hash."""
    path = ws / plan.test_path
    if path.exists():
        return Verdict(False, "base", f"{plan.test_path} already exists at base"), ""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(plan.test_code, encoding="utf-8")
    digest = sha(path)
    rc, out = run((*pytest, plan.test_path), ws)
    if rc == 0:
        return Verdict(False, "base", "the planned test passes at base, so it proves nothing", tail(out)), digest
    if rc not in FAILED_RCS:
        return Verdict(False, "base", f"the planned test did not run at base (pytest exit {rc})", tail(out)), digest
    return Verdict(True, "base", f"fails at base (pytest exit {rc})"), digest


def after(ws: Path, plan: Plan, digest: str, run=run_cmd, pytest=PYTEST, checks=CHECKS,
          select=selected_tests) -> Verdict:
    """The gate on the local model's work, run by the runner: hash, scope, the test, then the checks."""
    now = sha(ws / plan.test_path)
    if now != digest:
        return Verdict(False, "hash", f"{plan.test_path} was {'removed' if not now else 'edited'} by the local step")
    try:
        changed = changed_paths(ws, run) - {plan.test_path}
    except OSError as exc:
        return Verdict(False, "scope", str(exc))
    outside = sorted(changed - set(plan.files))
    if outside:
        return Verdict(False, "scope", f"the diff touches unplanned files: {outside}")
    if not changed:
        return Verdict(False, "scope", "the local step changed nothing")
    rc, out = run((*pytest, plan.test_path), ws)
    if rc != 0:
        return Verdict(False, "test", f"the planned test still fails (pytest exit {rc})", tail(out))
    for argv in checks:
        rc, out = run(argv, ws)
        if rc != 0:
            return Verdict(False, " ".join(argv), f"{' '.join(argv)} exit {rc}", tail(out))
    tests = [t for t in select(ws, plan.files) if t != plan.test_path]
    if tests:
        rc, out = run((*pytest, *tests), ws)
        if rc != 0:
            return Verdict(False, "tests", f"selected tests exit {rc}: {' '.join(tests)}", tail(out))
    return Verdict(True, "ok", f"gate passed; {len(tests)} selected test files")


def exec_prompt(plan: Plan, refused: Verdict | None = None, pytest=PYTEST) -> str:
    text = (f"Make the failing test {plan.test_path} pass by changing only these files: {', '.join(plan.files)}.\n"
            f"Do not edit, move or delete {plan.test_path}, and do not create or change any other file.\n"
            f"What to change: {plan.brief}\nCheck with: {' '.join(pytest)} {plan.test_path}\n"
            "Stop as soon as it passes.")
    if refused is not None:
        text += f"\n\nA previous attempt was refused: {refused.why}\n{refused.output}"
    return text


def plan_prompt(issue: int, title: str, body: str) -> str:
    return f"Issue #{issue}: {title}\n\n{body}\n\nPlan the fix. Answer with the JSON object only."


def tokens_of(result: dict) -> dict:
    """input, output, cache_write, cache_read of a claude -p result, every model it called summed."""
    mu = result.get("modelUsage") or {}
    if mu:
        rows = list(mu.values())
        keys = {"input": "inputTokens", "output": "outputTokens", "cache_write": "cacheCreationInputTokens",
                "cache_read": "cacheReadInputTokens"}
        return {k: sum(int(r.get(v) or 0) for r in rows) for k, v in keys.items()}
    u = result.get("usage") or {}
    return {"input": int(u.get("input_tokens") or 0), "output": int(u.get("output_tokens") or 0),
            "cache_write": int(u.get("cache_creation_input_tokens") or 0),
            "cache_read": int(u.get("cache_read_input_tokens") or 0)}


def counted(tokens: dict) -> int:
    from harness import ledger
    return sum(int(tokens.get(k) or 0) for k in ledger.CLOUD_COUNTED)


def ask_plan(prompt: str, ws: Path, model: str = PLAN_MODEL, run=subprocess.run,
             timeout: float = PLAN_TIMEOUT_S) -> dict:
    """One claude -p call on the subscription in the workspace, read-only tools: its text and tokens."""
    from evals.runners.claude_code import result_of
    from harness import cuts, headless
    argv = ["claude", "-p", "--model", model, "--output-format", "json", "--strict-mcp-config",
            "--setting-sources", "", "--system-prompt", PLAN_SYSTEM, "--max-turns", str(PLAN_MAX_TURNS),
            "--tools", PLAN_TOOLS, "--allowedTools", PLAN_TOOLS]
    with cuts.timeout("fix_plan_timeout_s", "a soh fix planning call", value=timeout):
        got = run(argv, input=prompt, cwd=str(ws), env=headless.control_env(), capture_output=True, text=True,
                  timeout=timeout)
    try:
        body = result_of(got.stdout or "")
    except ValueError as exc:
        raise PlanError(f"claude -p exited {got.returncode}: {(got.stderr or '')[-300:]}") from exc
    if body.get("subtype") == "error_max_turns":
        cuts.cut("fix_plan_max_turns", "a soh fix planning call stopped at its turn limit", kept=0, dropped=1)
    return {"text": str(body.get("result") or ""), "tokens": tokens_of(body), "is_error": bool(body.get("is_error"))}


def headless_executor(alias: str, gateway: str, key: str, tag: str, run=subprocess.run,
                      timeout: float = EXEC_TIMEOUT_S):
    """The local step: claude -p on `alias` under `soh headless`'s profile, each request tagged with the call id."""
    from evals import headless as hl
    from harness import cuts, headless, purpose

    def execute(ws: Path, prompt: str, call_id: str) -> dict:
        env = headless.child_env(alias, gateway, key)
        env["ANTHROPIC_CUSTOM_HEADERS"] = (f"{purpose.HEADER}: {purpose.TAG_PREFIX}{tag},"
                                           f"{purpose.DELEGATION_PREFIX}{call_id}")
        argv = ["claude", "-p", "--model", alias, "--output-format", "stream-json", "--verbose",
                "--no-session-persistence", "--strict-mcp-config", "--setting-sources", "",
                "--max-turns", str(EXEC_MAX_TURNS), "--tools", EXEC_TOOLS, "--allowedTools", EXEC_TOOLS, "--bare"]
        started, limit, rc, stdout = time.time(), "", None, ""
        try:
            with cuts.timeout("fix_exec_timeout_s", "a soh fix local step", value=timeout):
                got = run(argv, cwd=str(ws), env=env, input=prompt, capture_output=True, text=True,
                          encoding="utf-8", timeout=timeout)
            rc, stdout = got.returncode, got.stdout or ""
        except subprocess.TimeoutExpired as exc:
            limit, out = f"timeout {timeout:.0f}s", exc.stdout or ""
            stdout = out.decode("utf-8", "replace") if isinstance(out, bytes) else out
        res = hl.parse_stream(stdout)["result"]
        if not limit and res.get("subtype") == "error_max_turns":
            cuts.cut("fix_exec_max_turns", "a soh fix local step stopped at its turn limit", kept=0, dropped=1)
            limit = f"max turns {EXEC_MAX_TURNS}"
        return {"exit": rc, "limit": limit, "turns": res.get("num_turns"), "tokens": tokens_of(res),
                "model_usage": sorted((res.get("modelUsage") or {}).keys()), "seconds": round(time.time() - started, 1),
                "start": started}
    return execute


def reset(ws: Path, plan: Plan, run=run_cmd) -> None:
    """Back to base for a fresh attempt: tracked files restored, untracked removed, the planned test rewritten."""
    run(("git", "checkout", "--", "."), ws)
    run(("git", "clean", "-fdq"), ws)
    (ws / plan.test_path).parent.mkdir(parents=True, exist_ok=True)
    (ws / plan.test_path).write_text(plan.test_code, encoding="utf-8")


def _add(a: dict, b: dict) -> dict:
    return {k: int(a.get(k) or 0) + int(b.get(k) or 0) for k in set(a) | set(b)}


def run_issue(issue: int, title: str, body: str, ws: Path, *, plan_fn, execute=None, run=run_cmd,
              attempts: int = ATTEMPTS, plan_only: bool = False, held_out=(), held_out_ref: str = "",
              pytest=PYTEST, checks=CHECKS,
              select=selected_tests, call_id: str = "", clock=time.time) -> Record:
    """Plan, test at base, up to `attempts` local steps each gated; any refusal ends as an escalation with why."""
    started = clock()
    rec = Record(issue, call_id or new_call_id())

    def done(stage: str, why: str, resolved: bool = False) -> Record:
        rec.stage, rec.why, rec.resolved, rec.seconds = stage, why, resolved, round(clock() - started, 1)
        return rec
    try:
        got = plan_fn(plan_prompt(issue, title, body), ws)
    except (PlanError, OSError, subprocess.SubprocessError) as exc:
        return done("plan", f"no plan: {exc}")
    rec.plan_tokens = got["tokens"]
    if got.get("is_error"):
        return done("plan", f"claude -p: {got['text'][:300]}")
    spent = counted(got["tokens"])
    try:
        plan = parse_plan(got["text"])
    except PlanError as exc:
        return done("plan", str(exc))
    rec.klass, rec.plan = plan.klass, asdict(plan)
    if plan.klass == OUT_OF_CLASS:
        return done("plan", f"out of class: {plan.why}")
    if spent > PLAN_TOKEN_CAP:
        from harness import cuts
        cuts.cut("fix_plan_token_cap", "a soh fix plan over its cloud token cap", kept=0, dropped=1)
        return done("plan", f"the plan spent {spent:,} counted cloud tokens, over the {PLAN_TOKEN_CAP:,} cap")
    base, digest = at_base(ws, plan, run, pytest)
    if not base.ok:
        return done(base.stage, base.why)
    if plan_only:
        return done("planned", base.why)
    refused = None
    for n in range(attempts):
        if n:
            reset(ws, plan, run)
        step = execute(ws, exec_prompt(plan, refused, pytest), rec.call_id)
        rec.local_tokens = _add(rec.local_tokens, step.get("tokens") or {})
        v = after(ws, plan, digest, run, pytest, checks, select)
        _, diff = run(("git", "diff"), ws)
        rec.attempts.append({**{k: step.get(k) for k in ("exit", "limit", "turns", "seconds", "model_usage")},
                             "stage": v.stage, "why": v.why, "output": v.output, "diff": tail(diff, 400)})
        if v.ok:
            break
        refused = v
    else:
        from harness import cuts
        cuts.cut("fix_attempts", "an issue whose every local attempt the gate refused", kept=0, dropped=1)
        return done(refused.stage, refused.why)
    if held_out:
        if held_out_ref:
            run(("git", "checkout", held_out_ref, "--", *held_out), ws)
        rc, out = run((*pytest, *held_out), ws)
        if rc != 0:
            rec.attempts[-1]["held_out"] = tail(out)
            return done("held-out", f"the merged PR's own tests fail on the local fix (exit {rc})")
    return done("ok", rec.attempts[-1]["why"], resolved=True)


def store(conn, rec: Record, alias: str, replay: bool = False, at: float | None = None) -> None:
    """The issue's rows in delegations: the local step under its call id, the cloud plan as id_source cloud."""
    from harness import delegations
    when = time.time() if at is None else at
    lane = f"{REPLAY_LANE if replay else LANE}:{rec.klass or 'unplanned'}"
    outcome = "used" if rec.resolved else "discarded"
    delegations.record(conn, rec.call_id, lane, spec=str(rec.issue), model=alias, seconds=rec.seconds,
                       prompt_tokens=int(rec.local_tokens.get("input") or 0) + int(rec.local_tokens.get("cache_write") or 0),
                       completion_tokens=int(rec.local_tokens.get("output") or 0), at=when)
    delegations.record(conn, rec.call_id + "/plan", f"{PLAN_LANE}:{rec.klass or 'unplanned'}", spec=str(rec.issue),
                       model=PLAN_MODEL, prompt_tokens=int(rec.plan_tokens.get("input") or 0)
                       + int(rec.plan_tokens.get("cache_write") or 0),
                       completion_tokens=int(rec.plan_tokens.get("output") or 0), id_source=delegations.CLOUD, at=when)
    why = f"{rec.stage}: {rec.why}"[:500]
    delegations.outcome(conn, rec.call_id, outcome, why, at=when)
    delegations.outcome(conn, rec.call_id + "/plan", outcome, why, at=when)


def stored(conn, since: float = 0.0, replay: bool = False) -> list[dict]:
    """Each issue's local and cloud rows from delegations, joined on the call id."""
    lane = REPLAY_LANE if replay else LANE
    rows = conn.execute("SELECT call_id, lane, spec, prompt_tokens, completion_tokens, outcome, why, at "
                        "FROM delegations WHERE at >= ? AND (lane LIKE ? OR lane LIKE ?) ORDER BY at",
                        (since, f"{lane}:%", f"{PLAN_LANE}:%")).fetchall()
    local = {r[0]: r for r in rows if r[1].startswith(lane + ":")}
    out = []
    for cid, r in local.items():
        plan = next((p for p in rows if p[0] == cid + "/plan"), None)
        out.append({"issue": int(r[2]) if str(r[2]).isdigit() else r[2], "class": r[1].split(":", 1)[1],
                    "resolved": r[5] == "used", "why": r[6], "local": int(r[3] or 0) + int(r[4] or 0),
                    "cloud": (int(plan[3] or 0) + int(plan[4] or 0)) if plan else 0})
    return out


def summarize(rows: list[dict]) -> dict:
    """Per class and overall: issues, resolved locally, local and cloud tokens, cloud per resolved issue."""
    def agg(rs):
        resolved = sum(1 for r in rs if r["resolved"])
        cloud, local = sum(r["cloud"] for r in rs), sum(r["local"] for r in rs)
        return {"issues": len(rs), "resolved": resolved, "fraction": round(resolved / len(rs), 3) if rs else None,
                "local_tokens": local, "cloud_tokens": cloud,
                "cloud_per_issue": round(cloud / len(rs)) if rs else None,
                "cloud_per_resolved": round(cloud / resolved) if resolved else None,
                "ratio": round(local / cloud, 3) if cloud else None}
    in_class = [r for r in rows if r["class"] in CLASSES]
    return {"all": agg(rows), "in_class": agg(in_class),
            "classes": {k: agg([r for r in rows if r["class"] == k]) for k in sorted({r["class"] for r in rows})}}


def lines(summary: dict) -> list[str]:
    out = [f"{'class':<24} {'issues':>6} {'local':>6} {'frac':>6} {'local tok':>10} {'cloud tok':>10} "
           f"{'cloud/issue':>11} {'cloud/resolved':>14}"]
    for name, s in [*summary["classes"].items(), ("in class", summary["in_class"]), ("all", summary["all"])]:
        out.append(f"{name:<24} {s['issues']:>6} {s['resolved']:>6} {s['fraction'] if s['fraction'] is not None else '-':>6} "
                   f"{s['local_tokens']:>10,} {s['cloud_tokens']:>10,} {s['cloud_per_issue'] or '-':>11} "
                   f"{s['cloud_per_resolved'] or '-':>14}")
    return out


@dataclass(frozen=True)
class Candidate:
    issue: int
    pr: int
    merge: str
    held_out: tuple[str, ...]

    @property
    def base(self) -> str:
        return self.merge + "^"


def candidate(pr_files, merge_oid: str, issue: int, pr: int) -> Candidate | None:
    """A closed issue the replay may try: its PR changed at most MAX_FILES source files, added a test, no forbidden path."""
    paths = [str(p) for p in pr_files]
    source = [p for p in paths if not p.startswith("tests/")]
    tests = tuple(p for p in paths if p.startswith("tests/") and Path(p).name.startswith("test_") and p.endswith(".py"))
    if not tests or not source or len(source) > MAX_FILES or any(FORBIDDEN.search(p) for p in source):
        return None
    return Candidate(issue, pr, merge_oid, tests)
