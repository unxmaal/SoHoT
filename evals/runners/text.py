"""Runner for candidates reachable through the local gateway.

SVG and web generation are language-model jobs, not separate engines, so both
run through here. The candidate is a gateway alias, which is the whole point of
the gateway: swapping what is under test costs a string.

The request itself, and the system prompts steering it, live in
harness.completion and are shared with the CLI. If the eval steered the model
differently from the product, it would be measuring something that does not
ship.
"""
from __future__ import annotations

from harness import completion, reasons

from evals.core import Case
from evals.runners.base import BaseRunner, RunnerError


#: How long a screen's untimed warm-up may spend loading weights. #406.
LOAD_TIMEOUT_S = completion.LOAD_TIMEOUT_S
#: What a hybrid thinking model is asked with on the screen's one retry. #406.
NO_THINKING = {"enable_thinking": False}


def _runner_error(exc: completion.CompletionError, prefix: str = "") -> RunnerError:
    limit = f"{exc.limit[0]}>{exc.limit[1]:g}" if exc.limit else ""
    return RunnerError(f"{prefix}{exc}", failure_class=exc.failure_class,
                       limit=limit)


class CompletionRunner(BaseRunner):
    def __init__(self, gateway: str, candidate: str,
                 timeout: float = completion.TIMEOUT_S,
                 sampling: dict | None = None, model: str = ""):
        self.gateway = gateway.rstrip("/")
        self.candidate = candidate
        self.model = model or candidate
        self.timeout = timeout
        #: Overrides on top of completion.SAMPLING for this run. Empty means
        #: the shipped defaults, which is what the product uses.
        self.sampling = dict(sampling or {})
        #: Whether this runner has had an answer back since it started. #468.
        self.answered = False
        self.last_timing: dict = {}

    def warm(self) -> None:
        """One untimed request, so a cold load is not counted against the
        case's timeout, as throughput.sweep does. #406."""
        try:
            completion.complete_with_usage(
                "Reply with the word ok.", model=self.model,
                gateway=self.gateway, timeout=LOAD_TIMEOUT_S, max_tokens=8,
                sampling=self.sampling or None)
        except completion.CompletionError as exc:
            # It loaded and answered; a budget this small is not the case's.
            if exc.failure_class in (reasons.TOKEN_BUDGET_EXHAUSTED,
                                     reasons.CONTENT_FAILED):
                self.answered = True
                return
            if exc.failure_class == reasons.TIMEOUT:
                exc.limit = ("load_timeout_s", LOAD_TIMEOUT_S)
            raise _runner_error(exc, "warm-up: ") from exc
        self.answered = True

    def _ask(self, case: Case, template: dict | None = None):
        cold = not self.answered
        got = completion.complete_full(
            case.prompt, model=self.model, gateway=self.gateway,
            modality=case.modality, context=case.context,
            timeout=self.timeout, sampling=self.sampling or None,
            template=template, stream=True,
            top_logprobs=completion.TOP_LOGPROBS if case.modality == "decide" else 0)
        self.answered = True
        self.last_timing = {**got.timing, "cold": cold}
        if case.modality == "decide":
            return self._decide(case, got)
        return got.text, got.usage

    def _decide(self, case: Case, got: completion.Completion):
        """Answer letters plus their token probabilities where the server
        returns logprobs; the bare answer otherwise, scored one-hot. #423."""
        import json

        from harness.checks import decide

        text, usage, tokens = got.text, got.usage, got.tokens
        if not tokens:
            return text, usage
        got = decide.from_logprobs(text, tokens, case.params["schema"])
        return json.dumps({**got, "raw": text}), usage

    def generate(self, case: Case):
        import time

        # perf_counter, not monotonic: `monotonic` is GetTickCount64 on
        # Windows and quantises to 15.6ms, which measured a 0.15s run as
        # 0.14 in 75 of 200 tries. This number is reported as a result and
        # divided into token counts, so its resolution is the measurement.
        started = time.perf_counter()
        self.last_metrics = {}
        self.last_timing = {}
        try:
            try:
                text, usage = self._ask(case)
            except completion.CompletionError as exc:
                # A screen asks whether it runs: a hybrid thinking model gets
                # one retry with thinking off rather than a verdict on our
                # budget. RULE #194, #406.
                if not (self.screening and exc.failure_class
                        == reasons.TOKEN_BUDGET_EXHAUSTED):
                    raise
                self.last_metrics = {"thinking_disabled": 1}
                text, usage = self._ask(case, template=NO_THINKING)
        except completion.CompletionError as exc:
            # One dud must never abort a fifty-case run: every failure is a row.
            raise _runner_error(exc) from exc
        # THROUGHPUT, not just latency. Two candidates can share a median while
        # one of them wrote three times as much, and a median alone cannot tell
        # a terse model from a fast one. Absent when the server reports no
        # usage -- MISSING rather than zero, because a zero would rank as the
        # slowest candidate rather than as an unknown.
        elapsed = time.perf_counter() - started
        out = int(usage.get("completion_tokens") or 0)
        if out and elapsed > 0:
            self.last_metrics = {
                **self.last_metrics,
                "completion_tokens": out,
                "tokens_per_s": round(out / elapsed, 1),
            }
        # Peak memory is not observable through an HTTP boundary; the server
        # holds the model. Reporting 0 is honest, and summarize() takes a max.
        return text, 0

    def extra_metrics(self) -> dict:
        return getattr(self, "last_metrics", {})
