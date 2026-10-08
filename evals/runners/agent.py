"""The agent lane's runner: a minimal OpenAI tool loop over a sandboxed repo. #474.

Speaks /v1/chat/completions with `tools` through the same route opencode would
use for the candidate (the gateway alias, or llama-server for a llamacpp:
stem), streaming so each step's first token is timed. No agent framework.
"""
from __future__ import annotations

import json
import re
import statistics
import time
from pathlib import Path

from evals import agent_pad, sandbox
from evals.core import Case
from evals.runners.base import BaseRunner, RunnerError
from harness import completion

SYSTEM = ("You are a coding agent working inside a small repository. Use the "
          "provided tools to inspect and change files and to run the tests. "
          "Paths are relative to the repository root. Make the smallest change "
          "that completes the task. When the task is done, reply with a short "
          "final message and no tool call.")
MAX_STEPS = 20
STEP_TIMEOUT_S = 300.0
CASE_TIMEOUT_S = 900.0

#: A tool call written into the text instead of the tools API.
_TEXT_CALL = re.compile(r"<tool_call>|<function=|\"name\"\s*:\s*\"(read_file|write_file|"
                        r"list_dir|run_tests)\"")


def bundle_of(case: Case) -> Path:
    return Path(case.source).parent / str(case.params["repo"])


def setup(case: Case) -> tuple[sandbox.Sandbox, str]:
    """The sandbox for a case and the first user message."""
    pad = agent_pad.padding(case.id, int(case.params.get("pad_tokens") or 0))
    box = sandbox.Sandbox.create(bundle_of(case) / "repo", extra=pad,
                                 tools=tuple(case.params["tools"]))
    goal = case.prompt.strip()
    if not pad:
        return box, goal
    files = {box.rel(p): p.read_text(encoding="utf-8") for p in sorted(box.root.rglob("*"))
             if p.is_file() and "__pycache__" not in p.parts}
    return box, (f"Repository snapshot ({len(files)} files):\n\n"
                 f"{agent_pad.snapshot(files)}\n\n---\n\n{goal}")


def finish(case: Case, box: sandbox.Sandbox, steps: list, final: str,
           stopped: str, started: float) -> str:
    """Grade the sandbox, roll the steps up, and return the transcript JSON."""
    bundle = bundle_of(case)
    hidden = bundle / "hidden" if case.assertions.get("hidden") else None
    try:
        grade = sandbox.grade(box, hidden, case.assertions.get("answer"), final)
    finally:
        box.cleanup()
    return json.dumps({"case": case.id, "stopped": stopped, "final": final,
                       "grade": grade, "steps": steps,
                       "metrics": rollup(steps, time.perf_counter() - started)})


def rollup(steps: list, wall: float) -> dict:
    calls = [c for s in steps for c in s.get("calls", [])]
    valid = sum(1 for c in calls if c.get("valid"))
    ttfts = [s["ttft_s"] for s in steps if s.get("ttft_s") is not None]
    out = {"agent_steps": len(steps), "agent_tool_calls": len(calls),
           "agent_valid_calls": valid,
           "agent_valid_call_rate": round(valid / len(calls), 4) if calls else 0.0,
           "agent_no_tool_steps": sum(1 for s in steps if s.get("failed") == "no tool call"),
           "agent_ttft_sum_s": round(sum(ttfts), 3),
           "agent_model_s": round(sum(s.get("seconds") or 0 for s in steps), 3),
           "agent_tool_s": round(sum(s.get("tool_s") or 0 for s in steps), 3),
           "agent_wall_s": round(wall, 3)}
    for key in ("prompt_tokens", "completion_tokens"):
        got = [s[key] for s in steps if isinstance(s.get(key), int)]
        if got:
            out[key] = sum(got)
    return out


def step_timing(steps: list) -> dict:
    """Row-level first-token timing: the median step. #468 fields."""
    def med(key):
        v = [s[key] for s in steps if s.get(key) is not None]
        return round(statistics.median(v), 4) if v else None
    return {"ttft_s": med("ttft_s"), "first_reasoning_s": med("first_reasoning_s"),
            "prefill_s": med("prefill_s")}


class AgentRunner(BaseRunner):
    def __init__(self, gateway: str, candidate: str, model: str = "",
                 sampling: dict | None = None, chat=completion.chat,
                 step_timeout: float = STEP_TIMEOUT_S, served_ctx: int | None = None,
                 max_tokens: int = 0):
        self.served_ctx = served_ctx
        #: The reply budget of each step; 0 is the lane's. #628.
        self.max_tokens = int(max_tokens or 0) or completion.budget("agent")
        self.gateway = gateway.rstrip("/")
        self.candidate = candidate
        self.model = model or candidate
        self.sampling = dict(sampling or {})
        self.chat = chat
        self.step_timeout = step_timeout
        self.answered = False
        self.last_timing: dict = {}

    def generate(self, case: Case):
        started = time.perf_counter()
        box, first = setup(case)
        tools = sandbox.openai_tools(case.params["tools"])
        messages = [{"role": "system", "content": SYSTEM},
                    {"role": "user", "content": first}]
        cap = int(case.params.get("max_steps") or MAX_STEPS)
        deadline = started + float(case.params.get("timeout_s") or CASE_TIMEOUT_S)
        steps: list[dict] = []
        final, stopped = "", "step cap"
        cold = not self.answered
        try:
            for n in range(cap):
                if time.perf_counter() > deadline:
                    stopped = "time cap"
                    break
                rec, message = self._step(n, messages, tools)
                steps.append(rec)
                calls = message.get("tool_calls") or []
                if not calls:
                    text = message.get("content") or ""
                    if _TEXT_CALL.search(text):
                        rec["calls"] = [{"name": "", "valid": False, "parsed": False,
                                         "why": "tool call written as text"}]
                        messages += [{"role": "assistant", "content": text},
                                     {"role": "user", "content":
                                      "Call tools through the tools API, not as text."}]
                        continue
                    if not any(c.get("valid") for s in steps for c in s.get("calls", [])):
                        rec["failed"] = "no tool call"
                    final, stopped = text, "answered"
                    break
                self._act(box, calls, message, messages, rec)
        except completion.CompletionError as exc:
            box.cleanup()
            limit = f"{exc.limit[0]}>{exc.limit[1]:g}" if exc.limit else ""
            raise RunnerError(f"step {len(steps) + 1}: {exc}",
                              failure_class=exc.failure_class, limit=limit) from exc
        except BaseException:
            box.cleanup()
            raise
        self.last_timing = {**step_timing(steps), "cold": cold}
        return finish(case, box, steps, final, stopped, started), 0

    def extra_metrics(self) -> dict:
        return {"agent_ctx": self.served_ctx} if self.served_ctx else {}

    def failed(self, case: Case, exc: RunnerError, seconds: float = 0.0):
        row = super().failed(case, exc, seconds)
        row.metrics = {**(row.metrics or {}), **self.extra_metrics()}
        return row

    def _step(self, n: int, messages: list, tools: list) -> tuple[dict, dict]:
        t0 = time.perf_counter()
        got = self.chat(messages, model=self.model, gateway=self.gateway,
                        tools=tools,
                        timeout=max(self.step_timeout, completion.timeout_for(self.max_tokens)),
                        max_tokens=self.max_tokens, sampling=self.sampling or None)
        self.answered = True
        firsts = [v for v in (got.timing.get("ttft_s"), got.timing.get("first_tool_s"))
                  if v is not None]
        rec = {"step": n + 1, "seconds": round(time.perf_counter() - t0, 4),
               "ttft_s": min(firsts) if firsts else None,
               "first_reasoning_s": got.timing.get("first_reasoning_s"),
               "prefill_s": got.timing.get("prefill_s"), "calls": []}
        for key in ("prompt_tokens", "completion_tokens"):
            if isinstance(got.usage.get(key), int):
                rec[key] = got.usage[key]
        return rec, got.message or {"content": got.text}

    def _act(self, box, calls, message, messages, rec) -> None:
        t0 = time.perf_counter()
        sent = []
        for i, call in enumerate(calls):
            fn = call.get("function") or {}
            sent.append({"id": call.get("id") or f"call_{rec['step']}_{i}",
                         "type": "function",
                         "function": {"name": fn.get("name") or "",
                                      "arguments": fn.get("arguments") or ""}})
        messages.append({"role": "assistant", "content": message.get("content") or "",
                         "tool_calls": sent})
        for call in sent:
            got, result = box.call(call["function"]["name"], call["function"]["arguments"])
            rec["calls"].append({"name": got.name, "parsed": got.parsed,
                                 "schema_ok": got.schema_ok, "real": got.real,
                                 "valid": got.valid, "ok": got.ok, "why": got.why})
            messages.append({"role": "tool", "tool_call_id": call["id"],
                             "content": result})
        rec["tool_s"] = round(time.perf_counter() - t0, 4)
