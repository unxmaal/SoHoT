"""Runners for the text methods of harness/methods.py: best-of and plan, each over its base's runner. #576.

What a method costs is part of its result: every row reports `method_calls`, and
the row's seconds are the whole method, every call included.
"""
from __future__ import annotations

import copy
from dataclasses import replace

from harness import completion, methods
from harness.methods import ANSWER_PROMPT, PLAN_PROMPT

from evals import core
from evals.core import Case
from evals.runners.base import BaseRunner, RunnerError
from evals.runners.text import _runner_error


class BestOfRunner(BaseRunner):
    """Sample the base up to n times at the lane's temperature, stopping once one passes clean; keep
    what the lane's checks score highest. Samples after the first go concurrently, one per slot. #807."""

    def __init__(self, base: BaseRunner, n: int, spec: str = "", slots: int | None = None):
        self.base = base
        self.n = int(n)
        self.spec = spec
        self.slots = slots
        self.candidate = f"best-of-{self.n}/{base.candidate}"
        self.last_metrics: dict = {}

    def warm(self) -> None:
        self.base.warm()

    def score_kwargs(self) -> dict:
        return self.base.score_kwargs()

    def _slots(self) -> int:
        if self.slots is None:
            self.slots = methods.slots_of(self.spec) if self.spec else 1
        return self.slots

    def generate(self, case: Case):
        self.base.screening = self.screening
        self.last_cut = ""

        def draw(i):
            # Each concurrent sample keeps its metrics and cut on its own copy of the base.
            runner = self.base if i == 0 else copy.copy(self.base)
            artifact, peak = runner.generate(case)
            return (artifact, peak), runner

        def rank(out):
            row = core.score(case, out[0][0], **self.base.score_kwargs())
            return (row.passed, -len(row.warnings))
        got, failed, made = methods.sample(self.n, self._slots, draw, rank, (RunnerError,))
        self.last_metrics = {"method_calls": made, "method_samples": self.n}
        if not got:
            raise failed[0] if failed else RunnerError("no sample came back")
        i, _, (best, runner) = max(got, key=lambda g: (g[1], -g[0]))
        self.last_cut = runner.cut_off()
        self.last_metrics["method_chosen"] = i + 1
        tokens = sum(int(r.extra_metrics().get("completion_tokens") or 0) for _, _, (_, r) in got)
        if tokens:
            self.last_metrics["completion_tokens"] = tokens
        return best

    def extra_metrics(self) -> dict:
        return dict(self.last_metrics)

    def cut_off(self) -> str:
        return getattr(self, "last_cut", "")


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
                timeout=max(self.timeout, completion.timeout_for(self.base.budget(case))),
                max_tokens=self.base.budget(case), sampling=sampling or None)
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

    def cut_off(self) -> str:
        return self.base.cut_off()


class TemplateRunner(PlanRunner):
    """A prompt-transform template's steps through the base's own server and model, the last answered by the base. #993."""

    def __init__(self, base, method, timeout: float | None = None):
        super().__init__(base, timeout)
        self.method = method
        self.steps = method.extra["steps"]
        self.candidate = f"{method.name}/{base.candidate}"

    def generate(self, case: Case):
        self.base.screening = self.screening
        sampling = {**completion.SAMPLING.get(case.modality, {}), **(self.base.sampling or {})}
        values, spent = {"task": case.prompt}, 0
        for i, step in enumerate(self.steps[:-1], 1):
            try:
                text, usage = completion.complete_with_usage(
                    methods.fill(step.prompt, values), model=self.base.model,
                    gateway=self.base.gateway, modality=case.modality if step.answers else "",
                    context=case.context,
                    timeout=max(self.timeout, completion.timeout_for(self.base.budget(case))),
                    max_tokens=self.base.budget(case), sampling=sampling or None)
            except completion.CompletionError as exc:
                raise _runner_error(exc, f"{self.method.name} step {i} ({step.name}): ") from exc
            spent += int(usage.get("completion_tokens") or 0)
            values[step.name] = text.strip()
        artifact, peak = self.base.generate(
            replace(case, prompt=methods.fill(self.steps[-1].prompt, values)))
        spent += int(self.base.extra_metrics().get("completion_tokens") or 0)
        self.last_metrics = {"method_calls": len(self.steps)}
        if spent:
            self.last_metrics["completion_tokens"] = spent
        return artifact, peak
