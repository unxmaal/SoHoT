"""Recorded jobs for headless `claude -p`, graded by deterministic checks, local alias against Claude. #830."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from harness import headless, knobs

TASKS_DIR = Path(__file__).resolve().parent / "headless_tasks"
#: Built-in tools offered; the same set for the local model and the control.
TOOLS = "Read,Write,Edit,Bash,Glob,Grep"
#: Seconds one task's whole `claude -p` may take.
TASK_TIMEOUT_S = 600.0
#: Agent turns one task may take before Claude Code stops it.
MAX_TURNS = 30
CONTROL_PREFIX = "claude:"
#: Tool results that mean the call itself was malformed, not that the tool met a missing file.
_INVALID = re.compile(r"InputValidationError|No such tool available|Invalid tool parameters|"
                      r"is not a valid tool|tool_use_error>Error: No such tool", re.I)


@dataclass(frozen=True)
class Task:
    name: str
    job: str
    prompt: str
    checks: tuple
    root: Path = field(compare=False)
    timeout_s: float = TASK_TIMEOUT_S


def load(names=None, root: Path = TASKS_DIR) -> list[Task]:
    tasks = []
    for d in sorted(p for p in root.iterdir() if (p / "task.yaml").is_file()):
        spec = yaml.safe_load((d / "task.yaml").read_text(encoding="utf-8"))
        tasks.append(Task(d.name, spec["job"], spec["prompt"], tuple(spec["checks"]), d,
                          float(spec.get("timeout_s") or TASK_TIMEOUT_S)))
    if names:
        unknown = set(names) - {t.name for t in tasks}
        if unknown:
            raise ValueError(f"no headless task named {sorted(unknown)}")
        tasks = [t for t in tasks if t.name in names]
    return tasks


def _read(work: Path, rel: str) -> str:
    return (work / rel).read_text(encoding="utf-8")


def _norm(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.strip().splitlines())


def check_one(spec: dict, work: Path, task_root: Path) -> tuple[bool, str]:
    """One assertion over the workspace a run left: (passed, why)."""
    kind, rel = spec["kind"], spec["file"]
    if not (work / rel).is_file():
        return False, f"{rel} was not written"
    try:
        text = _read(work, rel)
    except (OSError, UnicodeDecodeError) as exc:
        return False, f"{rel} unreadable: {exc}"
    if kind == "line":
        lines = text.strip("﻿").splitlines()
        got = lines[spec["line"] - 1].strip() if len(lines) >= spec["line"] else ""
        ok = re.search(spec["pattern"], got, re.I) is not None
        return ok, "" if ok else f"{rel} line {spec['line']} is {got[:80]!r}"
    if kind == "text":
        ok = text.strip() == spec["equals"]
        return ok, "" if ok else f"{rel} is {text.strip()[:80]!r}"
    if kind == "contains":
        missing = [s for s in spec["all"] if s not in text]
        return not missing, f"{rel} lacks {missing}" if missing else ""
    if kind == "regex":
        ok = re.search(spec["pattern"], text) is not None
        return ok, "" if ok else f"{rel} does not match {spec['pattern']!r}"
    if kind == "same":
        ok = _norm(text) == _norm((task_root / spec["expected"]).read_text(encoding="utf-8"))
        return ok, "" if ok else f"{rel} differs from {spec['expected']}"
    try:
        got = json.loads(text)
    except ValueError as exc:
        return False, f"{rel} is not JSON: {exc}"
    if kind == "json":
        ok = got == spec["equals"]
        return ok, "" if ok else f"{rel} is {json.dumps(got)[:120]}"
    if kind == "labels":
        if not isinstance(got, list) or not all(isinstance(x, str) for x in got):
            return False, f"{rel} is not a list of strings"
        allowed = set(_read(task_root / "files", spec["allowed_file"]).split())
        bad = [x for x in got if x not in allowed]
        lacking = [x for x in spec["required"] if x not in got]
        wrong = [x for x in got if x in spec["forbidden"]]
        why = "; ".join(s for s in (bad and f"not allowed {bad}", lacking and f"missing {lacking}",
                                    wrong and f"wrong {wrong}") if s)
        return not why, why
    raise ValueError(f"unknown check kind {kind!r}")


def grade(task: Task, work: Path) -> tuple[bool, list[str]]:
    whys = []
    for spec in task.checks:
        ok, why = check_one(spec, work, task.root)
        if not ok:
            whys.append(why)
    return not whys, whys


def parse_stream(stdout: str) -> dict:
    """Turns, tool calls and the result body from `--output-format stream-json` lines."""
    ids, calls, invalid, tool_errors, result = set(), 0, 0, 0, {}
    for line in stdout.splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if not isinstance(ev, dict):
            continue
        msg = ev.get("message") if isinstance(ev.get("message"), dict) else {}
        content = msg.get("content") if isinstance(msg.get("content"), list) else []
        if ev.get("type") == "assistant":
            if msg.get("id"):
                ids.add(msg["id"])
            calls += sum(1 for b in content if isinstance(b, dict) and b.get("type") == "tool_use")
        elif ev.get("type") == "user":
            for b in content:
                if isinstance(b, dict) and b.get("type") == "tool_result" and b.get("is_error"):
                    tool_errors += 1
                    invalid += bool(_INVALID.search(json.dumps(b.get("content"))))
        elif ev.get("type") == "result":
            result = ev
    return {"api_calls": len(ids), "tool_calls": calls, "invalid_calls": invalid,
            "tool_errors": tool_errors, "result": result}


def argv(model: str, local: bool, binary: str = "claude") -> list[str]:
    """`claude -p` for one task; the prompt goes on stdin (--tools is variadic and eats a positional)."""
    cmd = [binary, "-p", "--model", model, "--output-format", "stream-json", "--verbose",
           "--no-session-persistence", "--strict-mcp-config", "--setting-sources", "",
           "--max-turns", str(MAX_TURNS), "--tools", TOOLS, "--allowedTools", TOOLS]
    # --bare reads no keychain or OAuth, so a local run cannot fall back to the login.
    return cmd + ["--bare"] if local else cmd


def run_task(task: Task, model: str, env: dict, local: bool, execute=subprocess.run,
             clock=time.time) -> dict:
    """Run one task in a fresh copy of its files and grade what it leaves behind."""
    alias = model.removeprefix(CONTROL_PREFIX)
    with tempfile.TemporaryDirectory(prefix=f"soh-headless-{task.name}-") as tmp:
        work = Path(tmp) / "work"
        shutil.copytree(task.root / "files", work)
        start = clock()
        limit, rc, stdout, timeout = "", None, "", task.timeout_s
        try:
            proc = execute(argv(alias, local), cwd=work, env=env, input=task.prompt,
                           capture_output=True, text=True, encoding="utf-8", timeout=timeout)
            rc, stdout = proc.returncode, proc.stdout or ""
        except subprocess.TimeoutExpired as exc:
            limit = knobs.limit("headless_task_timeout_s", timeout, "s")
            out = exc.stdout or ""
            stdout = out.decode("utf-8", "replace") if isinstance(out, bytes) else out
        end = clock()
        stream = parse_stream(stdout)
        res = stream["result"]
        if not limit and res.get("subtype") == "error_max_turns":
            limit = knobs.limit("headless_max_turns", MAX_TURNS, "turns")
        passed, whys = grade(task, work)
    return {"task": task.name, "job": task.job, "model": model, "local": local,
            "passed": passed, "why": whys, "limit": limit, "exit": rc,
            "is_error": bool(res.get("is_error")) if res else True,
            "turns": res.get("num_turns"), "api_calls": stream["api_calls"],
            "tool_calls": stream["tool_calls"], "invalid_calls": stream["invalid_calls"],
            "tool_errors": stream["tool_errors"],
            "model_usage": sorted((res.get("modelUsage") or {}).keys()),
            "start": start, "end": end, "wall_s": round(end - start, 2)}


def run_set(tasks: list[Task], model: str, env: dict, local: bool, **kw) -> list[dict]:
    return [run_task(t, model, env, local, **kw) for t in tasks]


def attach_leaks(rows: list[dict], store: Path, alias: str, settle_s: float = 3.0,
                 query=headless.requests_between) -> dict:
    """Each local row gets its window's gateway requests and leak verdict; returns the whole run's."""
    for r, after in zip(rows, rows[1:] + [None]):
        got = query(store, r["start"], min(r["end"] + settle_s, after["start"]) if after else r["end"] + settle_s)
        r["leak"] = headless.leak_check(got, alias, r["model_usage"], r["api_calls"])
    every = query(store, rows[0]["start"], rows[-1]["end"] + settle_s) if rows else []
    return headless.leak_check(every, alias, sorted({m for r in rows for m in r["model_usage"]}),
                               sum(r["api_calls"] for r in rows))


def summary(rows: list[dict]) -> dict:
    calls = sum(r["tool_calls"] for r in rows)
    return {"tasks": len(rows), "passed": sum(r["passed"] for r in rows),
            "turns": sum(r["turns"] or 0 for r in rows),
            "tool_calls": calls, "invalid_calls": sum(r["invalid_calls"] for r in rows),
            "valid_rate": round(1 - sum(r["invalid_calls"] for r in rows) / calls, 3) if calls else None,
            "wall_s": round(sum(r["wall_s"] for r in rows), 1)}
