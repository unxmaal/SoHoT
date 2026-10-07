"""Runners for the needle: kind (harness/needle.py) in the decide and agent lanes. #312."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from evals.core import Case
from evals.runners.agent import AgentRunner
from evals.runners.base import BaseRunner, RunnerError
from harness import needle, reasons


def _install(command, weights):
    if command is not None and weights is not None:
        return list(command), str(weights)
    try:
        got_cmd, got_w = needle.installed()
    except (ValueError, LookupError, OSError) as exc:
        raise RunnerError(f"needle is not installed: {exc}",
                          failure_class=reasons.HARNESS_ERROR) from exc
    return list(command or got_cmd), str(weights or got_w)


class NeedleDecideRunner(BaseRunner):
    def __init__(self, spec: str, outdir, command: list[str] | None = None,
                 weights: str | None = None):
        self.spec_ = needle.parse(spec)
        self.candidate = self.spec_.name
        self.outdir = Path(outdir)
        self.outdir.mkdir(parents=True, exist_ok=True)
        self.command, self.weights = command, weights

    def generate(self, case: Case):
        schema = case.params.get("schema")
        if not schema:
            raise RunnerError("needle scores a decide case; this one has no schema",
                              failure_class=reasons.HARNESS_ERROR)
        command, weights = _install(self.command, self.weights)
        out = (self.outdir / self.artifact(case, ".json")).resolve()
        task = needle.task_of(case.prompt, schema)
        try:
            with tempfile.TemporaryDirectory() as work:
                body = needle.decide(self.spec_, command, weights, schema, task,
                                     case.context or "", Path(work))
        except FileNotFoundError as exc:
            raise RunnerError(f"{exc} not installed", failure_class=reasons.HARNESS_ERROR) from exc
        out.write_text(json.dumps(body, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        return out, body["peak_kb"]


class NeedleAgentRunner(AgentRunner):
    def __init__(self, spec: str, chat: needle.Chat):
        super().__init__("", needle.parse(spec).name, chat=chat)

    def extra_metrics(self) -> dict:
        out = {"needle_withheld_calls": self.chat.withheld}
        if self.chat.peak_mb:
            out["needle_peak_mb"] = self.chat.peak_mb
        return out

    def close(self) -> None:
        self.chat.close()


def needle_agent_runner(spec: str, command: list[str] | None = None,
                        weights: str | None = None, port: int | None = None) -> NeedleAgentRunner:
    command, weights = _install(command, weights)
    work = Path(tempfile.mkdtemp(prefix="needle-agent-"))
    return NeedleAgentRunner(spec, needle.Chat(needle.parse(spec), command, weights, work, port))
