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

import time

from harness import completion, delegate, knobs, reasons, routes

from evals.core import Case
from evals.runners.base import BaseRunner, RunnerError


#: How long the untimed warm-up may spend loading weights. #406.
LOAD_TIMEOUT_S = completion.LOAD_TIMEOUT_S
#: What a hybrid thinking model is asked with on the screen's one retry. #406.
NO_THINKING = {"enable_thinking": False}


def _runner_error(exc: completion.CompletionError, prefix: str = "") -> RunnerError:
    limit = knobs.limit_text(exc.limit)
    return RunnerError(f"{prefix}{exc}", failure_class=exc.failure_class,
                       limit=limit)


class CompletionRunner(BaseRunner):
    def __init__(self, gateway: str, candidate: str,
                 timeout: float = completion.TIMEOUT_S,
                 sampling: dict | None = None, model: str = "",
                 max_tokens: int = 0, served_ctx: int | None = None, count=None,
                 template: dict | None = None):
        self.gateway = gateway.rstrip("/")
        #: Chat-template kwargs the spec names, sent on every case in place of the lane's. #921.
        self.template = dict(template or {})
        #: One record per request of the case in hand: the reply's reasoning, finish and tokens, and what was sent. #921.
        self.trajectories: list = []
        #: Each distinct request this runner sent, for the receipt. #921.
        self.sent: list = []
        self.candidate = candidate
        self.model = model or candidate
        self.timeout = timeout
        #: Seconds the untimed first request may spend loading; a knob a run can set. #636.
        self.load_timeout = LOAD_TIMEOUT_S
        #: The run's reply budget; 0 asks each case at its lane's. #628.
        self.max_tokens = int(max_tokens or 0)
        self.last_cut = ""
        #: The per-slot context the candidate is served at; None when unknown. #692.
        self.served_ctx = served_ctx
        #: count(text) -> tokens by the served tokenizer; None estimates. #692.
        self.count = count
        #: Generated tokens past which a reply is stopped as low yield; None runs every reply to its budget. #1127.
        self.stop_tokens: int | None = None
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
                gateway=self.gateway, timeout=self.load_timeout, max_tokens=8,
                sampling=self.sampling or None)
        except completion.CompletionError as exc:
            # It loaded and answered; a budget this small is not the case's.
            if exc.failure_class in (reasons.TOKEN_BUDGET_EXHAUSTED,
                                     reasons.CONTENT_FAILED):
                self.answered = True
                return
            if exc.failure_class == reasons.TIMEOUT:
                exc.limit = knobs.hit("load_timeout_s", self.load_timeout, "s")
            raise _runner_error(exc, "warm-up: ") from exc
        self.answered = True

    def _ask(self, case: Case, template: dict | None = None):
        from harness import serving
        if self._reply_shape(case) and serving.drops_schema(self.gateway):
            raise completion.CompletionError(
                f"{self.model} is asked on mlx_lm.server, which ignores the "
                f"{case.modality} lane's response_format, so its reply would be "
                f"scored on a request the lane never sends. #572",
                reasons.REFUSED_BY_GATEWAY)
        cold = not self.answered
        asked = self.budget(case)
        system = self._system(case)
        room = self.room(case, system)
        budget = min(asked, room) if room is not None else asked
        if budget < 1:
            raise completion.CompletionError(
                f"unrunnable here: the prompt fills the {self.served_ctx}-token served context",
                reasons.CONTEXT_EXCEEDED, knobs.hit("served_ctx", self.served_ctx, "tokens"))
        # The served context, not the reply budget, is what stops a reply the room was clamped to. #692.
        limit = (knobs.limit("served_ctx", self.served_ctx, "tokens") if budget < asked
                 else knobs.limit(f"max_tokens.{case.modality}", budget, "tokens"))
        timeout = max(self.timeout, completion.timeout_for(budget))
        stop = self.stop_tokens if self.stop_tokens is not None and self.stop_tokens < budget else None
        try:
            with completion.stopping_after(stop):
                got = completion.complete_full(
                    case.prompt, model=self.model, gateway=self.gateway,
                    modality=case.modality, context=case.context,
                    timeout=timeout + (self.load_timeout if cold else 0.0),
                    max_tokens=budget, sampling=self.sampling or None,
                    template=template or self.template or None, stream=True,
                    top_logprobs=completion.TOP_LOGPROBS if case.modality == "decide" else 0,
                    response_format=self._reply_shape(case),
                    system=system)
        except completion.CompletionError as exc:
            self._keep(exc.request, exc.reasoning, exc.finish, exc.usage, str(exc))
            self.last_call_id, self.last_routed, self.last_usage = exc.call_id, exc.routed, dict(exc.usage)
            if exc.failure_class == reasons.TOKEN_BUDGET_EXHAUSTED:
                exc.failure_class, exc.limit = self._cut(self._stopped_at(limit, exc.usage))
            elif exc.failure_class == reasons.TIMEOUT and cold:
                # Nothing has answered yet, so the request was given the load's allowance and the load is what ran out. #694.
                exc.limit = knobs.hit("load_timeout_s", self.load_timeout, "s")
            elif not exc.failure_class and reasons.OVER_CONTEXT.search(str(exc)):
                exc.failure_class = reasons.CONTEXT_EXCEEDED
                exc.limit = knobs.hit("served_ctx", self.served_ctx, "tokens") if self.served_ctx else ()
            raise
        self._keep(got.request, got.reasoning, got.finish, got.usage)
        self.answered = True
        self.last_call_id, self.last_routed, self.last_usage = got.call_id, got.routed, dict(got.usage)
        self.last_timing = {**got.timing, "cold": cold}
        spent = int(got.usage.get("completion_tokens") or 0)
        if got.finish == "length" or spent >= budget:
            self.last_cut = self._stopped_at(limit, got.usage)
        if case.modality == "decide":
            return self._decide(case, got)
        return got.text, got.usage

    def _keep(self, request: dict, reasoning: str, finish: str, usage: dict, error: str = "") -> None:
        if request and request not in self.sent:
            self.sent.append(dict(request))
        self.trajectories.append({
            "request": dict(request or {}), "finish_reason": finish or "",
            "prompt_tokens": (usage or {}).get("prompt_tokens"),
            "completion_tokens": (usage or {}).get("completion_tokens"),
            "reasoning_tokens": ((usage or {}).get("completion_tokens_details") or {}).get("reasoning_tokens"),
            "reasoning": reasoning or "", "error": error})

    @staticmethod
    def _system(case: Case) -> str | None:
        """The case's own system prompt (claims cases carry one; the repo runner sets it, #1129), else None."""
        return case.params.get("system") if case.modality in ("claims", "repo") else None

    @staticmethod
    def _reply_shape(case: Case):
        if case.modality == "claims":
            from harness.checks import claims
            return claims.response_format(case.params["schema"])
        if case.modality != "decide":
            return None
        from harness.checks import decide
        return decide.response_format(case.params["schema"])

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
        # perf_counter, not monotonic: `monotonic` is GetTickCount64 on
        # Windows and quantises to 15.6ms, which measured a 0.15s run as
        # 0.14 in 75 of 200 tries. This number is reported as a result and
        # divided into token counts, so its resolution is the measurement.
        started = time.perf_counter()
        self.last_metrics = {}
        self.last_timing = {}
        self.last_cut = ""
        self.last_call_id = self.last_routed = ""
        self.last_usage = {}
        # Its own scope: a best-of sample is timed without its siblings' busy waits. #776.
        with completion.measuring():
            text, usage = self._generate(case)
            elapsed = completion.since(started)
        # THROUGHPUT, not just latency. Two candidates can share a median while
        # one of them wrote three times as much, and a median alone cannot tell
        # a terse model from a fast one. Absent when the server reports no
        # usage -- MISSING rather than zero, because a zero would rank as the
        # slowest candidate rather than as an unknown.
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

    def _generate(self, case: Case):
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
        return text, usage

    def extra_metrics(self) -> dict:
        return getattr(self, "last_metrics", {})

    def graded(self, case: Case, row) -> None:
        """A routing arm's row says where it went; its verdict goes back to the gateway, which keeps only the calls it routed. #1338."""
        routed = getattr(self, "last_routed", "")
        if not routed:
            return
        cloud = routes.is_cloud(routed)
        usage = getattr(self, "last_usage", None) or {}
        spent = int(usage.get("prompt_tokens") or 0) + int(usage.get("completion_tokens") or 0)
        row.metrics = {**(row.metrics or {}), "routed_cloud": int(cloud), "cloud_tokens": spent if cloud else 0}
        routes.report(self.last_call_id, routes.verdict(row.passed, row.failure_class))

    def budget(self, case: Case) -> int:
        return self.max_tokens or completion.budget(case.modality) or completion.MAX_TOKENS

    def room(self, case: Case, system: str | None = None) -> int | None:
        """Tokens the served context leaves for the reply after the prompt; None when the context is unknown. #692."""
        if not self.served_ctx:
            return None
        system = system or completion.SYSTEM.get(case.modality, completion.NEUTRAL_SYSTEM)
        return delegate.cap(self.served_ctx, system, completion.user_message(case.prompt, case.context),
                            count=self.count)

    def _stopped_at(self, limit: str, usage: dict) -> str:
        """The served context when the server's own count of prompt plus reply reached it, else `limit`. #692."""
        used = int(usage.get("completion_tokens") or 0) + int(usage.get("prompt_tokens") or 0)
        return knobs.limit("served_ctx", self.served_ctx, "tokens") if self.served_ctx and used >= self.served_ctx else limit

    def _cut(self, limit: str) -> tuple[str, tuple]:
        """(failure class, limit) for a reply stopped at `limit`, a "name>value" body."""
        name, _, value = limit.rpartition(">")
        cls = reasons.CONTEXT_EXCEEDED if name == "served_ctx" else reasons.TOKEN_BUDGET_EXHAUSTED
        return cls, knobs.hit(name, knobs.number(value), "tokens")

    def cut_off(self) -> str:
        return self.last_cut

    def stopped_by(self) -> tuple[str, str]:
        """A reply stopped at the served context is that limit's, not the reply budget's. #692."""
        if self.last_cut.startswith("served_ctx>"):
            return reasons.CONTEXT_EXCEEDED, self.last_cut
        return super().stopped_by()
