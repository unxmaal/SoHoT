"""A frontier model through headless Claude Code, on a subscription login. #359."""
from __future__ import annotations

import json
import subprocess
import tempfile
import threading
import time

from evals.core import Case
from evals.runners.base import BaseRunner, RunnerError
from harness import completion

PREFIX = "claude-code"


class EmptyResult(RunnerError):
    pass


class Streamed:
    """What subprocess.run returns, plus when each stdout line arrived. #468."""

    def __init__(self, returncode: int, lines: list, stderr: str):
        self.returncode, self.stderr = returncode, stderr
        self.line_times = lines
        self.stdout = "".join(line for _, line in lines)


def stream_run(argv, *, cwd, input, timeout, encoding="utf-8", **_kw) -> Streamed:
    """subprocess.run's contract, timing each stdout line from the spawn."""
    started = time.perf_counter()
    proc = subprocess.Popen(argv, cwd=cwd, stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, encoding=encoding)
    err: list[str] = []
    expired = threading.Event()
    timer = threading.Timer(timeout, lambda: (expired.set(), proc.kill()))

    def feed():
        try:
            proc.stdin.write(input or "")
            proc.stdin.close()
        except OSError:
            pass

    readers = [threading.Thread(target=feed, daemon=True),
               threading.Thread(target=lambda: err.append(proc.stderr.read()),
                                daemon=True)]
    timer.start()
    for t in readers:
        t.start()
    lines = []
    try:
        for line in proc.stdout:
            lines.append((time.perf_counter() - started, line))
        proc.wait()
    finally:
        timer.cancel()
    for t in readers:
        t.join(1.0)
    if expired.is_set():
        raise subprocess.TimeoutExpired(argv, timeout)
    return Streamed(proc.returncode, lines, "".join(err))


def first_token(line_times) -> dict:
    """Arrival of the first text and thinking deltas, CLI and network included."""
    got = {"ttft_s": None, "first_reasoning_s": None}
    for at, line in line_times or ():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict) or event.get("type") != "stream_event":
            continue
        delta = ((event.get("event") or {}).get("delta") or {})
        key = {"text_delta": "ttft_s",
               "thinking_delta": "first_reasoning_s"}.get(delta.get("type"))
        if key == "ttft_s" and not delta.get("text"):
            continue
        if key and got[key] is None:
            got[key] = round(at, 4)
    return got


def result_of(stdout: str) -> dict:
    """The result body, from --output-format json or the last stream-json line."""
    try:
        body = json.loads(stdout)
        if isinstance(body, dict):
            return body
    except ValueError:
        pass
    for line in reversed((stdout or "").splitlines()):
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict) and event.get("type") == "result":
            return event
    raise ValueError("no result event")


class ClaudeCodeRunner(BaseRunner):
    def __init__(self, model: str, timeout: float = 600.0, execute=stream_run,
                 binary: str = "claude"):
        self.model = model
        self.candidate = f"{PREFIX}:{model}"
        self.timeout = timeout
        self.execute = execute
        self.binary = binary
        self.last_metrics: dict = {}
        self.last_timing: dict = {}

    def argv(self, case: Case) -> list[str]:
        system = completion.SYSTEM.get(case.modality, completion.NEUTRAL_SYSTEM)
        # The prompt goes on stdin: in argv, a case starting with "-" (a diff)
        # is parsed as options. #368. --bare skips the subscription login.
        return [self.binary, "-p", "--model", self.model,
                "--output-format", "stream-json", "--verbose",
                "--include-partial-messages", "--no-session-persistence",
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
        self.last_timing = {}
        with tempfile.TemporaryDirectory(prefix="lh-claude-code-") as cwd:
            try:
                proc = self.execute(
                    self.argv(case), cwd=cwd, capture_output=True, text=True,
                    encoding="utf-8",
                    timeout=self.timeout,
                    input=completion.user_message(case.prompt, case.context))
            except subprocess.TimeoutExpired as exc:
                raise RunnerError(f"claude -p timed out after {self.timeout}s") from exc
            except OSError as exc:
                raise RunnerError(f"could not run {self.binary}: {exc}") from exc
        elapsed = time.perf_counter() - started
        try:
            body = result_of(proc.stdout)
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
        # A fresh CLI per case loads no weights, so no row is cold.
        self.last_timing = {**first_token(getattr(proc, "line_times", None)),
                            "prefill_s": None, "cold": False}
        return text, 0

    def extra_metrics(self) -> dict:
        return self.last_metrics
