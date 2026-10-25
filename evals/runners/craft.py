"""The craft lane's runners: a model as an MCP client of a craft app's own server, and the reference script replayed (#1209)."""
from __future__ import annotations

import json
import shutil
import time

from evals import craft
from evals.core import Case
from evals.runners.agent import _TEXT_CALL, AgentRunner, rollup, step_timing
from evals.runners import agent
from evals.runners.base import BaseRunner, RunnerError
from harness import completion, cuts, knobs, reasons

#: The candidate that replays a run book's reference script headless; it should score 1.0.
REFERENCE = "craft-reference"
SYSTEM = ("You are operating a design application through the tools its own server provides. Build exactly what "
          "the task asks, checking your work with the tools that read the document. Files live in the working "
          "folder the task names. When the task is done, reply with a short final message and no tool call.")
#: Every run book's own max_steps is multiplied by this.
MAX_STEPS_SCALE = 1.0


def step_cap(case: Case) -> int:
    return max(1, round(int(case.params["max_steps"]) * MAX_STEPS_SCALE))


def first_message(case: Case, root) -> str:
    return f"{case.prompt.strip()}\n\nThe working folder is {root}. Read and write files only there."


def _argv(case: Case) -> list[str]:
    app = craft.app_of(case)
    argv = craft.binary(app)
    if not argv:
        raise RunnerError(f"{app.cli} is not installed: install {case.params['release']['asset']} "
                          f"(sha256 {case.params['release']['sha256']}) or set SOHOT_{app.name.upper()}_CLI",
                          failure_class=reasons.ENVIRONMENT_ERROR)
    try:
        craft.check_pin(case, argv)
    except craft.PinError as exc:
        raise RunnerError(str(exc), failure_class=reasons.ENVIRONMENT_ERROR) from exc
    except craft.CraftError as exc:
        raise RunnerError(str(exc), failure_class=reasons.ENVIRONMENT_ERROR) from exc
    return argv


def metrics_of(got: dict, invalid: int = 0) -> dict:
    out = {"craft_requirements_met": got["met"], "craft_requirements_total": got["total"],
           "craft_requirement_rate": round(got["met"] / got["total"], 4) if got["total"] else 0.0,
           "craft_invalid_calls": invalid}
    if got.get("render_difference") is not None:
        out["craft_render_difference"] = got["render_difference"]
    return out


class ReplayRunner(BaseRunner):
    """The run book's own command script, run headless on the pinned release: the exam's ceiling row."""

    def __init__(self):
        self.candidate = REFERENCE

    def generate(self, case: Case):
        started = time.perf_counter()
        argv = _argv(case)
        root = craft.scratch(case)
        try:
            built = craft.headless(case, argv, craft.reference_steps(case), root)
            got = craft.grade(case, built["document"], root, built["render"], built["render"])
        except craft.CraftError as exc:
            raise RunnerError(f"reference build: {exc}", failure_class=reasons.ENVIRONMENT_ERROR) from exc
        finally:
            shutil.rmtree(root, ignore_errors=True)
        wall = round(time.perf_counter() - started, 3)
        return json.dumps({"case": case.id, "app": case.params["app"], "release": case.params["release"],
                           "stopped": "replayed", "grade": got, "steps": [],
                           "metrics": {**metrics_of(got), "agent_wall_s": wall}}), 0


class CraftRunner(AgentRunner):
    """The agent lane's tool loop, its tools listed by the app's MCP server and its grade read from the app."""

    def generate(self, case: Case):
        started = time.perf_counter()
        self.last_stop = ("", "")
        argv = _argv(case)
        ref_root, root = craft.scratch(case, "soh-craft-ref-"), craft.scratch(case)
        session = None
        try:
            try:
                reference = craft.headless(case, argv, craft.reference_steps(case), ref_root)
                session = craft.Session(case, argv, root)
            except (craft.CraftError, craft.craft_mcp.McpError) as exc:
                raise RunnerError(f"{case.params['app']}: {exc}", failure_class=reasons.ENVIRONMENT_ERROR) from exc
            steps, final, stopped, cut = self._loop(case, session, root, started)
            try:
                built = session.finish()
            except (craft.CraftError, craft.craft_mcp.McpError) as exc:
                raise RunnerError(f"reading the document: {exc}", failure_class=reasons.ENVIRONMENT_ERROR) from exc
            got = craft.grade(case, built["document"], root, built["render"], reference["render"])
            if built.get("render_error"):
                got["render_error"] = built["render_error"]
        finally:
            if session is not None:
                session.cleanup()
            shutil.rmtree(root, ignore_errors=True)
            shutil.rmtree(ref_root, ignore_errors=True)
        self.last_stop = self._stop(stopped, cut, session)
        wall = round(time.perf_counter() - started - sum(s.get("busy_wait_s") or 0.0 for s in steps), 3)
        invalid = sum(1 for s in steps for c in s.get("calls", []) if not c.get("ok"))
        return json.dumps({"case": case.id, "app": case.params["app"], "release": case.params["release"],
                           "tools": len(session.tools), "stopped": stopped, "final": final, "grade": got,
                           "steps": steps, "metrics": {**rollup(steps, wall), **metrics_of(got, invalid)}}), 0

    def _loop(self, case: Case, session, root, started: float):
        tools = session.openai_tools()
        messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": first_message(case, root)}]
        allowed = max(float(case.params.get("timeout_s") or agent.CASE_TIMEOUT_S), self.step_seconds())
        deadline = started + allowed
        self._allowed = allowed
        steps: list[dict] = []
        final, stopped, cut = "", "step cap", ""
        cold = not self.answered
        for n in range(step_cap(case)):
            left = deadline - time.perf_counter()
            if left <= 0:
                stopped = "time cap"
                break
            try:
                rec, message, ended = self._step(n, messages, tools, min(self.step_seconds(), left))
            except completion.CompletionError as exc:
                limit = knobs.limit_text(exc.limit)
                raise RunnerError(f"step {len(steps) + 1}: {exc}", failure_class=exc.failure_class,
                                  limit=limit) from exc
            steps.append(rec)
            # A wait for another batch on the serving machine is not the case's to pay. #776.
            deadline += rec.get("busy_wait_s") or 0.0
            if ended == "length":
                rec["cut"] = True
                cut = knobs.limit("max_tokens.agent", self.max_tokens, "tokens")
            calls = message.get("tool_calls") or []
            if not calls:
                text = message.get("content") or ""
                if _TEXT_CALL.search(text) or "<tool_call>" in text:
                    rec["calls"] = [{"name": "", "valid": False, "parsed": False, "ok": False,
                                     "why": "tool call written as text"}]
                    messages += [{"role": "assistant", "content": text},
                                 {"role": "user", "content": "Call tools through the tools API, not as text."}]
                    continue
                final, stopped = text, "answered"
                break
            self._act(session, calls, message, messages, rec)
            if session.capped:
                stopped = "call cap"
                cuts.cut("craft_max_tool_calls", f"{case.id}: a model reached the tool-call cap",
                         value=session.cap, kept=session.cap, dropped=1)
                break
        self.last_timing = {**step_timing(steps), "cold": cold}
        return steps, final, stopped, cut

    def _stop(self, stopped: str, cut: str, session) -> tuple[str, str]:
        if stopped == "step cap":
            return reasons.STEP_CAP, knobs.limit("craft_steps_scale", MAX_STEPS_SCALE, "factor")
        if stopped == "call cap":
            return reasons.STEP_CAP, knobs.limit("craft_max_tool_calls", session.cap, "calls")
        if stopped == "time cap":
            return reasons.TIMEOUT, knobs.limit("agent_case_timeout_s", self._allowed, "s")
        if cut:
            return reasons.TOKEN_BUDGET_EXHAUSTED, cut
        return "", ""
