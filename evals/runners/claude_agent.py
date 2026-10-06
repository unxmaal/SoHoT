"""The agent lane's Opus baseline: claude -p on the sandbox's own tools over MCP. #474.

No API key exists here (subscription only), so Opus cannot go through the
OpenAI loop. Instead claude -p runs with every built-in tool disabled and one
stdio MCP server (evals/agent_mcp.py) exposing the same four tools over the
same Sandbox, so path confinement, the command allowlist and the hidden grade
are identical. Steps and first tokens are read from stream-json.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from evals.core import Case
from evals.runners import agent
from evals.runners.base import BaseRunner, RunnerError
from evals.runners.claude_code import PREFIX, result_of, stream_run

SERVER = "sandbox"
MCP_SCRIPT = Path(__file__).resolve().parents[1] / "agent_mcp.py"


def tool_name(name: str) -> str:
    return name.split("__", 2)[-1] if name.startswith(f"mcp__{SERVER}__") else name


def parse_steps(line_times, log: list[dict]) -> list[dict]:
    """Per-assistant-message steps from stream-json lines, calls matched to the log."""
    steps: list[dict] = []
    ref, cur = 0.0, None
    for at, line in line_times or ():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        if event.get("type") == "user":
            ref = at
            continue
        if event.get("type") != "stream_event":
            continue
        ev = event.get("event") or {}
        kind = ev.get("type")
        if kind == "message_start":
            usage = (ev.get("message") or {}).get("usage") or {}
            cur = {"step": len(steps) + 1, "ttft_s": None, "first_reasoning_s": None,
                   "prefill_s": None, "seconds": None, "calls": [],
                   "prompt_tokens": sum(int(usage.get(k) or 0) for k in (
                       "input_tokens", "cache_read_input_tokens",
                       "cache_creation_input_tokens"))}
            steps.append(cur)
            continue
        if cur is None:
            continue
        if kind == "content_block_start":
            block = ev.get("content_block") or {}
            if block.get("type") == "tool_use":
                cur["calls"].append({"name": tool_name(block.get("name") or "")})
                if cur["ttft_s"] is None:
                    cur["ttft_s"] = round(at - ref, 4)
        elif kind == "content_block_delta":
            dtype = (ev.get("delta") or {}).get("type")
            if dtype == "thinking_delta" and cur["first_reasoning_s"] is None:
                cur["first_reasoning_s"] = round(at - ref, 4)
            elif dtype in ("text_delta", "input_json_delta") and cur["ttft_s"] is None:
                cur["ttft_s"] = round(at - ref, 4)
        elif kind == "message_delta":
            out = ((ev.get("usage") or {}).get("output_tokens"))
            if isinstance(out, int):
                cur["completion_tokens"] = out
        elif kind == "message_stop":
            cur["seconds"] = round(at - ref, 4)
    pending = list(log)
    for step in steps:
        for call in step["calls"]:
            hit = next((e for e in pending if e.get("name") == call["name"]), None)
            if hit is None:
                call.update(valid=False, why="did not reach the sandbox")
                continue
            pending.remove(hit)
            call.update({k: hit.get(k) for k in ("parsed", "schema_ok", "real",
                                                  "valid", "ok", "why")})
    if pending and steps:
        steps[-1]["calls"] += [dict(e) for e in pending]
    return steps


class ClaudeAgentRunner(BaseRunner):
    def __init__(self, model: str, timeout: float = agent.CASE_TIMEOUT_S,
                 execute=stream_run, binary=("claude",)):
        self.model = model
        self.candidate = f"{PREFIX}:{model}"
        self.timeout = timeout
        self.execute = execute
        self.binary = [binary] if isinstance(binary, str) else list(binary)
        self.last_timing: dict = {}

    def argv(self, case: Case, config: Path) -> list[str]:
        allowed = ",".join(f"mcp__{SERVER}__{t}" for t in case.params["tools"])
        return [*self.binary, "-p", "--model", self.model,
                "--output-format", "stream-json", "--verbose",
                "--include-partial-messages", "--no-session-persistence",
                "--strict-mcp-config", "--mcp-config", str(config),
                "--setting-sources", "", "--system-prompt", agent.SYSTEM,
                "--tools", "", "--allowedTools", allowed]

    def generate(self, case: Case):
        started = time.perf_counter()
        box, first = agent.setup(case)
        cap = int(case.params.get("max_steps") or agent.MAX_STEPS)
        try:
            with tempfile.TemporaryDirectory(prefix="soh-claude-agent-") as cwd:
                log = Path(cwd) / "calls.jsonl"
                log.touch()
                config = Path(cwd) / "mcp.json"
                config.write_text(json.dumps({"mcpServers": {SERVER: {
                    "type": "stdio", "command": sys.executable,
                    "args": [str(MCP_SCRIPT), str(box.root), str(log),
                             ",".join(case.params["tools"]), str(cap)],
                    "env": {"PYTHONIOENCODING": "utf-8"}}}}), encoding="utf-8")
                timeout = float(case.params.get("timeout_s") or self.timeout)
                try:
                    proc = self.execute(self.argv(case, config), cwd=cwd,
                                        capture_output=True, text=True,
                                        encoding="utf-8", timeout=timeout, input=first)
                except subprocess.TimeoutExpired as exc:
                    raise RunnerError(f"claude -p timed out after {timeout:g}s") from exc
                except OSError as exc:
                    raise RunnerError(f"could not run {self.binary[0]}: {exc}") from exc
                calls = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()
                         if x.strip()]
            try:
                body = result_of(proc.stdout)
            except ValueError as exc:
                raise RunnerError(
                    f"claude -p exited {proc.returncode} without JSON: "
                    f"{(proc.stderr or proc.stdout).strip()[:300]}") from exc
            if body.get("is_error") and not body.get("result"):
                raise RunnerError(f"claude -p: {str(body)[:300]}")
        except BaseException:
            box.cleanup()
            raise
        steps = parse_steps(getattr(proc, "line_times", None), calls)
        final = str(body.get("result") or "")
        stopped = "answered" if not body.get("is_error") else f"error: {final[:200]}"
        self.last_timing = {**agent.step_timing(steps), "cold": False}
        return agent.finish(case, box, steps, final, stopped, started), 0
