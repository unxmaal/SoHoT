"""Runners for the text methods of harness/methods.py: best-of and plan, each over its base's runner. #576.

What a method costs is part of its result: every row reports `method_calls`, and
the row's seconds are the whole method, every call included.
"""
from __future__ import annotations

from dataclasses import replace

from harness import completion

from evals import core
from evals.core import Case
from evals.runners.base import BaseRunner, RunnerError
from evals.runners.text import _runner_error


class BestOfRunner(BaseRunner):
    """Sample the base n times at the lane's temperature; keep what the lane's checks score highest."""

    def __init__(self, base: BaseRunner, n: int):
        self.base = base
        self.n = int(n)
        self.candidate = f"best-of-{self.n}/{base.candidate}"
        self.last_metrics: dict = {}

    def warm(self) -> None:
        self.base.warm()

    def score_kwargs(self) -> dict:
        return self.base.score_kwargs()

    def generate(self, case: Case):
        self.base.screening = self.screening
        best = best_key = None
        tokens = calls = 0
        failed = None
        for i in range(self.n):
            calls += 1
            try:
                artifact, peak = self.base.generate(case)
            except RunnerError as exc:
                failed = exc
                continue
            tokens += int(self.base.extra_metrics().get("completion_tokens") or 0)
            row = core.score(case, artifact, **self.base.score_kwargs())
            key = (row.passed, -len(row.warnings))
            if best_key is None or key > best_key:
                best, best_key, chosen = (artifact, peak), key, i + 1
        self.last_metrics = {"method_calls": calls, "method_samples": self.n}
        if best is None:
            raise failed or RunnerError("no sample came back")
        self.last_metrics["method_chosen"] = chosen
        if tokens:
            self.last_metrics["completion_tokens"] = tokens
        return best

    def extra_metrics(self) -> dict:
        return dict(self.last_metrics)


#: The first call: a plan, and no answer yet.
PLAN_PROMPT = """Before answering, write a short numbered plan for the task below.
Do not write the answer itself.

TASK:
{task}"""

#: The second call: the task again, with the plan to follow.
ANSWER_PROMPT = """{task}

Follow this plan:
{plan}"""


class PlanRunner(BaseRunner):
    """Plan, then answer: two calls through the base's own server and model."""

    def __init__(self, base, timeout: float | None = None):
        self.base = base
        self.timeout = timeout or base.timeout
        self.candidate = f"plan/{base.candidate}"
        self.last_metrics: dict = {}

    def warm(self) -> None:
        self.base.warm()

    def generate(self, case: Case):
        self.base.screening = self.screening
        sampling = {**completion.SAMPLING.get(case.modality, {}), **(self.base.sampling or {})}
        try:
            plan, usage = completion.complete_with_usage(
                PLAN_PROMPT.format(task=case.prompt), model=self.base.model,
                gateway=self.base.gateway, modality="", context=case.context,
                timeout=self.timeout, sampling=sampling or None)
        except completion.CompletionError as exc:
            raise _runner_error(exc, "plan: ") from exc
        artifact, peak = self.base.generate(
            replace(case, prompt=ANSWER_PROMPT.format(task=case.prompt, plan=plan.strip())))
        spent = int(usage.get("completion_tokens") or 0) + int(
            self.base.extra_metrics().get("completion_tokens") or 0)
        self.last_metrics = {"method_calls": 2}
        if spent:
            self.last_metrics["completion_tokens"] = spent
        return artifact, peak

    def extra_metrics(self) -> dict:
        return dict(self.last_metrics)
