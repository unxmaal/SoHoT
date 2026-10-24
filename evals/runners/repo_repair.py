"""The repo lane's repair harness: the agent lane's tool loop over a repo attempt, graded by the patch harness's grader. #890."""
from __future__ import annotations

import json
import time

from evals import agent_pad, repo, repo_tools
from evals.core import Case
from evals.runners.agent import _TEXT_CALL, AgentRunner, rollup, step_timing
from evals.runners.base import RunnerError
from harness import completion, reasons

HARNESS = "repair"
SYSTEM = ("You are fixing an issue in a Python repository checked out at the commit before the fix. Use the "
          "tools to read and search the code, change it with apply_patch, and check your change with run_tests. "
          "Paths are relative to the repository root. Do not change test files. When the change is done, call "
          "finish; the working tree as it then stands is graded by tests you cannot see.")
ASK = ("Change the repository with apply_patch until the issue is fixed, check it with run_tests, then call "
       "finish. Do not change tests.")
#: Model turns a case may take.
MAX_STEPS = 30
#: Tokens the model may generate over a case's turns, reasoning included.
MAX_TOKENS = 60000
#: Tool calls one turn may make; the rest are not run and the model is told so.
CALLS_PER_TURN = 8
#: Seconds a case's turns and tool runs may take; building its checkout and environment is not counted.
CASE_TIMEOUT_S = 1800.0


def key(candidate: str) -> str:
    """The row key of a candidate run on this harness, so its rows never pool with its patch-harness rows."""
    return f"{HARNESS}/{candidate}"


def first_message(issue: str, attempt) -> str:
    """The patch harness's prompt (issue and oracle files at base), its reply instruction swapped for the tools'."""
    text = attempt.prompt(issue)
    return (text[:-len(repo.REPLY)].rstrip() if text.endswith(repo.REPLY) else text) + "\n\n" + ASK


class RepoRepairRunner(AgentRunner):
    #: (params) -> repo.Attempt; tests hand in a fixture's.
    attempt = staticmethod(repo.Attempt.open)
    #: Roots run_tests may not read; None hides $HOME but the checkout, its venv and its interpreter.
    denied = None

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.candidate = key(self.candidate)
        self.last_grade: dict = {}

    def generate(self, case: Case):
        self.last_stop, self.last_grade = ("", ""), {}
        try:
            attempt = self.attempt(case.params)
        except repo.RepoEnvError as exc:
            raise RunnerError(f"environment: {exc}", failure_class=reasons.ENVIRONMENT_ERROR) from exc
        try:
            return self._repair(case, attempt), 0
        except repo.RepoEnvError as exc:
            raise RunnerError(f"environment: {exc}", failure_class=reasons.ENVIRONMENT_ERROR) from exc
        finally:
            attempt.close()

    def _repair(self, case: Case, attempt) -> str:
        started = time.perf_counter()
        allowed = float(CASE_TIMEOUT_S)
        deadline = started + allowed
        box = repo_tools.Workspace(attempt, deadline=lambda: deadline - time.perf_counter(), denied=self.denied)
        first = first_message(repo.as_asked(case).prompt, attempt)
        tools = repo_tools.openai_tools()
        messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": first}]
        steps: list[dict] = []
        final, stopped, error, cut = "", "step cap", None, ""
        made = dropped = 0
        cold = not self.answered
        budget = self.max_tokens
        try:
            for n in range(int(MAX_STEPS)):
                left = deadline - time.perf_counter()
                if left <= 0:
                    stopped = "time cap"
                    break
                if made >= MAX_TOKENS:
                    stopped = "token cap"
                    break
                room = self._room(messages, tools)
                if room <= 0:
                    stopped = "context"
                    break
                self.max_tokens = int(max(1, min(budget, MAX_TOKENS - made, room)))
                rec, message, ended = self._step(n, messages, tools, min(self.step_seconds(), left))
                steps.append(rec)
                made += rec.get("completion_tokens") or round(agent_pad.estimate(json.dumps(message)))
                rec["generated_total"] = made
                if ended == "length":
                    rec["cut"] = True
                    cut = f"max_tokens.repo>{budget}" if self.max_tokens == budget else ""
                calls = message.get("tool_calls") or []
                if not calls:
                    text = message.get("content") or ""
                    if _TEXT_CALL.search(text) or repo._TOOL_CALL.search(text):
                        rec["calls"] = [{"name": "", "valid": False, "parsed": False,
                                         "why": "tool call written as text"}]
                        messages += [{"role": "assistant", "content": text},
                                     {"role": "user", "content": "Call tools through the tools API, not as text."}]
                        continue
                    final, stopped = text, "answered"
                    break
                cut_calls = max(0, len(calls) - int(CALLS_PER_TURN))
                calls = calls[:int(CALLS_PER_TURN)]
                had = len(messages)
                self._act(box, calls, message, messages, rec)
                if cut_calls:
                    rec["calls_cut"] = cut_calls
                    dropped += cut_calls
                    messages[-1]["content"] += (f"\n\n[{cut_calls} more tool calls in this turn were not run: "
                                                f"at most {int(CALLS_PER_TURN)} calls per turn]")
                for call, sent, asked in zip(rec["calls"], messages[had + 1:], messages[had]["tool_calls"]):
                    call["out_bytes"] = len(str(sent.get("content") or "").encode("utf-8"))
                    call["args"] = repo_tools.cut(asked["function"]["arguments"])
                if box.finished is not None:
                    final, stopped = box.finished, "finished"
                    break
            else:
                stopped = "step cap"
        except completion.CompletionError as exc:
            error, stopped = exc, "error"
        finally:
            self.max_tokens = budget
        if error is not None and not box.touched:
            limit = f"{error.limit[0]}>{error.limit[1]:g}" if error.limit else ""
            raise RunnerError(f"step {len(steps) + 1}: {error}", failure_class=error.failure_class, limit=limit)
        diff = box.diff()
        got = attempt.submit(diff)
        wall = round(time.perf_counter() - started, 3)
        self.last_timing = {**step_timing(steps), "cold": cold}
        self.last_stop = self._stop(stopped, cut, error, allowed)
        metrics = {"resolved": int(got.resolved), "patch_applied": int(got.patch_applied), "wall_s": wall,
                   "test_s": got.test_s, **rollup(steps, wall), "repair_generated_tokens": made,
                   "repair_test_runs": box.test_runs, "repair_calls_cut": dropped}
        self.last_grade = metrics
        return json.dumps({"case": case.id, "harness": HARNESS, "diff": diff, "reply": final,
                           "stopped": stopped, "error": str(error or ""),
                           "caps": {"repair_max_steps": MAX_STEPS, "repair_calls_per_turn": CALLS_PER_TURN, "repair_max_tokens": MAX_TOKENS,
                                    "repair_case_timeout_s": allowed, "repair_output_cap": repo_tools.OUTPUT_CAP},
                           "grade": {"resolved": got.resolved, "patch_applied": got.patch_applied,
                                     "detail": got.detail, "failed": got.failed, "limit": got.limit,
                                     "skipped": got.skipped, "failures": got.failures},
                           "steps": steps, "metrics": metrics})

    def _room(self, messages: list, tools: list) -> float:
        """Tokens the served context leaves for the next turn's reply; unbounded where the context is unknown."""
        if not self.served_ctx:
            return float("inf")
        count = self.count or agent_pad.estimate
        return self.served_ctx - count(json.dumps(messages)) - count(json.dumps(tools))

    def _stop(self, stopped: str, cut: str, error, allowed: float) -> tuple[str, str]:
        """(failure class, limit) a failing row is put down to: the cap that ended its loop, else ""."""
        if stopped == "step cap":
            return reasons.STEP_CAP, f"repair_max_steps>{MAX_STEPS:g}"
        if stopped == "token cap":
            return reasons.TOKEN_BUDGET_EXHAUSTED, f"repair_max_tokens>{MAX_TOKENS:g}"
        if stopped == "time cap":
            return reasons.TIMEOUT, f"repair_case_timeout_s>{allowed:g}"
        if stopped == "context":
            return reasons.CONTEXT_EXCEEDED, f"served_ctx>{self.served_ctx}"
        if error is not None:
            limit = f"{error.limit[0]}>{error.limit[1]:g}" if error.limit else ""
            return error.failure_class or reasons.CRASHED, limit
        if cut:
            return reasons.TOKEN_BUDGET_EXHAUSTED, cut
        return "", ""

    def run(self, case: Case):
        row = super().run(case)
        if "wall_s" in (row.metrics or {}):
            row.seconds = row.metrics["wall_s"]
        return row
