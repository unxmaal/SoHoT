"""A frontier model through headless Claude Code, on a subscription login. #359."""
from __future__ import annotations

import json
import subprocess
import tempfile
import time

from evals.core import Case
from evals.runners.base import BaseRunner, RunnerError
from harness import completion

PREFIX = "claude-code"


class EmptyResult(RunnerError):
    pass


class ClaudeCodeRunner(BaseRunner):
    def __init__(self, model: str, timeout: float = 600.0, execute=subprocess.run,
                 binary: str = "claude"):
        self.model = model
        self.candidate = f"{PREFIX}:{model}"
        self.timeout = timeout
        self.execute = execute
        self.binary = binary
        self.last_metrics: dict = {}

    def argv(self, case: Case) -> list[str]:
        system = completion.SYSTEM.get(case.modality, completion.NEUTRAL_SYSTEM)
        user = completion.user_message(case.prompt, case.context)
        # --tools takes a list, so it goes last or it swallows the prompt.
        # --bare cannot be used: it skips the subscription login.
        return [self.binary, "-p", user, "--model", self.model,
                "--output-format", "json", "--no-session-persistence",
                "--strict-mcp-config", "--setting-sources", "",
                "--system-prompt", system, "--tools", ""]

    def generate(self, case: Case):
        # One retry on an empty result: 1 in 45 calls came back empty and
        # never reproduced. Empty twice is the model's answer. #366.
        try:
            return self._once(case, retries=0)
        except EmptyResult:
            return self._once(case, retries=1)

    def _once(self, case: Case, retries: int):
        started = time.perf_counter()
        with tempfile.TemporaryDirectory(prefix="lh-claude-code-") as cwd:
            try:
                proc = self.execute(self.argv(case), cwd=cwd, capture_output=True,
                                text=True, timeout=self.timeout)
            except subprocess.TimeoutExpired as exc:
                raise RunnerError(f"claude -p timed out after {self.timeout}s") from exc
            except OSError as exc:
                raise RunnerError(f"could not run {self.binary}: {exc}") from exc
        elapsed = time.perf_counter() - started
        try:
            body = json.loads(proc.stdout)
        except ValueError as exc:
            raise RunnerError(
                f"claude -p exited {proc.returncode} without JSON: "
                f"{(proc.stderr or proc.stdout).strip()[:300]}") from exc
        if body.get("is_error") or proc.returncode != 0:
            raise RunnerError(f"claude -p: {str(body.get('result'))[:300]}")
        text = body.get("result") or ""
        if not text.strip():
            if retries:
                raise RunnerError("claude -p returned an empty result twice")
            raise EmptyResult("claude -p returned an empty result")
        out = int((body.get("usage") or {}).get("output_tokens") or 0)
        self.last_metrics = ({"completion_tokens": out,
                              "tokens_per_s": round(out / elapsed, 1)}
                             if out and elapsed > 0 else {})
        if retries:
            self.last_metrics["retries"] = retries
        return text, 0

    def extra_metrics(self) -> dict:
        return self.last_metrics
