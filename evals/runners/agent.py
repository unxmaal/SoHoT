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

import httpx

from evals import agent_pad, sandbox
from evals.core import Case
from evals.runners.base import BaseRunner, RunnerError
from harness import completion, reasons

SYSTEM = ("You are a coding agent working inside a small repository. Use the "
          "provided tools to inspect and change files and to run the tests. "
          "Paths are relative to the repository root. Make the smallest change "
          "that completes the task. When the task is done, reply with a short "
          "final message and no tool call.")
#: Every case's own max_steps is multiplied by this; the knob a sweep moves. #695.
MAX_STEPS_SCALE = 1.0
STEP_TIMEOUT_S = 300.0
CASE_TIMEOUT_S = 900.0

#: What a server says when a request does not fit its context. #695.
_OVER_CONTEXT = re.compile(r"exceeds? the available context|context.?window.?exceeded|maximum context length"
                           r"|context length exceeded|exceeds? (the )?context (size|window|length)", re.I)

#: A tool call written into the text instead of the tools API.
_TEXT_CALL = re.compile(r"<tool_call>|<function=|\"name\"\s*:\s*\"(read_file|write_file|"
                        r"list_dir|run_tests)\"")


def served_counter(base: str, model: str):
    """count(text) by the served tokenizer, asked for on first use; the CHARS_PER_TOKEN estimate where there is none. #695."""
    held: list = []

    def count(text: str) -> float:
        if not held:
            held.append(completion.token_counter(base, model) or agent_pad.estimate)
        try:
            return held[0](text)
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            held[0] = agent_pad.estimate
            return held[0](text)
    return count


def step_cap(case: Case) -> int:
    """The steps a case may take: its own max_steps, scaled by the knob. #695."""
    if not case.params.get("max_steps"):
        raise RunnerError(f"{case.id}: an agent case names its max_steps", failure_class=reasons.HARNESS_ERROR)
    return max(1, round(int(case.params["max_steps"]) * MAX_STEPS_SCALE))


def bundle_of(case: Case) -> Path:
    return Path(case.source).parent / str(case.params["repo"])


def setup(case: Case, count=None) -> tuple[sandbox.Sandbox, str]:
    """The sandbox for a case and the first user message, padded by `count`, the served tokenizer."""
    pad = agent_pad.padding(case.id, int(case.params.get("pad_tokens") or 0), count=count)
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


def _prefill(rec: dict) -> float:
    """A step's prompt processing: the server's own figure, else the wait for its first token of any kind."""
    if rec.get("prefill_s") is not None:
        return float(rec["prefill_s"])
    firsts = [v for v in (rec.get("ttft_s"), rec.get("first_reasoning_s")) if v is not None]
    return float(min(firsts)) if firsts else 0.0


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
                 max_tokens: int = 0, count=None):
        self.served_ctx = served_ctx
        #: count(text) -> tokens by the served tokenizer; None estimates. #695.
        self.count = count
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
        #: (failure class, limit) a failing row is put down to: the cap or budget that stopped it. #695.
        self.last_stop: tuple[str, str] = ("", "")

    def warm(self) -> None:
        """One untimed turn at the load allowance, so the first step does not pay the load. #406, #694."""
        try:
            self.chat([{"role": "user", "content": "Reply with the word ok."}], model=self.model,
                      gateway=self.gateway, timeout=completion.LOAD_TIMEOUT_S, max_tokens=8,
                      sampling=self.sampling or None)
        except completion.CompletionError as exc:
            if exc.failure_class not in (reasons.TOKEN_BUDGET_EXHAUSTED, reasons.CONTENT_FAILED):
                if exc.failure_class == reasons.TIMEOUT:
                    exc.limit = ("load_timeout_s", completion.LOAD_TIMEOUT_S)
                raise RunnerError(f"warm-up: {exc}", failure_class=exc.failure_class,
                                  limit=f"{exc.limit[0]}>{exc.limit[1]:g}" if exc.limit else "") from exc
        self.answered = True

    def step_seconds(self) -> float:
        """Seconds one step may take: the step timeout, stretched for the reply budget."""
        return max(self.step_timeout, completion.timeout_for(self.max_tokens))

    def _fits(self, case: Case, box, first: str, tools: list) -> None:
        """Refuse a case whose first prompt and reply budget overflow the served context. #695."""
        if not self.served_ctx:
            return
        count = self.count or agent_pad.estimate
        prompt = count(SYSTEM) + count(first) + count(json.dumps(tools))
        if prompt + self.max_tokens > self.served_ctx:
            box.cleanup()
            raise RunnerError(f"unrunnable here: a {prompt:.0f}-token prompt and the {self.max_tokens}-token "
                              f"reply budget overflow the {self.served_ctx}-token served context",
                              failure_class=reasons.CONTEXT_EXCEEDED, limit=f"served_ctx>{self.served_ctx}")

    def generate(self, case: Case):
        started = time.perf_counter()
        self.last_stop = ("", "")
        box, first = setup(case, self.count)
        tools = sandbox.openai_tools(case.params["tools"])
        self._fits(case, box, first, tools)
        messages = [{"role": "system", "content": SYSTEM},
                    {"role": "user", "content": first}]
        cap = step_cap(case)
        # A bigger reply budget stretches the case as it stretches a step; never shorter than one step.
        stretch = max(1.0, self.max_tokens / completion.budget("agent"))
        allowed = max(float(case.params.get("timeout_s") or CASE_TIMEOUT_S) * stretch, self.step_seconds())
        case_limit = f"agent_case_timeout_s>{allowed:g}"
        deadline = started + allowed
        steps: list[dict] = []
        final, stopped = "", "step cap"
        cut = ""
        prefill = 0.0
        cold = not self.answered
        try:
            for n in range(cap):
                left = deadline - time.perf_counter()
                if left <= 0:
                    stopped = "time cap"
                    break
                try:
                    rec, message, ended = self._step(n, messages, tools, min(self.step_seconds(), left + prefill))
                except completion.CompletionError as exc:
                    if exc.failure_class == reasons.TIMEOUT and exc.limit:
                        took = exc.limit[1]
                        exc.limit = (("agent_case_timeout_s", allowed) if took < self.step_seconds()
                                     else ("agent_step_timeout_s", took))
                    elif _OVER_CONTEXT.search(str(exc)):
                        exc.failure_class = reasons.CONTEXT_EXCEEDED
                        exc.limit = ("served_ctx", self.served_ctx) if self.served_ctx else ()
                    raise
                steps.append(rec)
                # Prefill grows with the context, not with the agent's work, so it is not the case's to pay. #695.
                # The prompt only grows, so the largest prefill yet is this step's floor.
                prefill = max(prefill, _prefill(rec))
                deadline += _prefill(rec)
                if ended == "length":
                    rec["cut"] = True
                    cut = f"max_tokens.agent>{self.max_tokens}"
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
        if cut:
            self.last_stop = (reasons.TOKEN_BUDGET_EXHAUSTED, cut)
        elif stopped == "time cap":
            self.last_stop = (reasons.TIMEOUT, case_limit)
        elif stopped == "step cap":
            self.last_stop = (reasons.STEP_CAP, f"agent_steps_scale>{MAX_STEPS_SCALE:g}")
        return finish(case, box, steps, final, stopped, started), 0

    def stopped_by(self) -> tuple[str, str]:
        return self.last_stop

    def extra_metrics(self) -> dict:
        return {"agent_ctx": self.served_ctx} if self.served_ctx else {}

    def failed(self, case: Case, exc: RunnerError, seconds: float = 0.0):
        row = super().failed(case, exc, seconds)
        row.metrics = {**(row.metrics or {}), **self.extra_metrics()}
        return row

    def _step(self, n: int, messages: list, tools: list, timeout: float) -> tuple[dict, dict, str]:
        t0 = time.perf_counter()
        got = self.chat(messages, model=self.model, gateway=self.gateway,
                        tools=tools, timeout=timeout,
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
        return rec, got.message or {"content": got.text}, got.finish

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
