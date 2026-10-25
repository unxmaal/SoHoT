"""Text generation through the local gateway, and recovering the artifact.

SVG and web pages are language-model jobs, not separate engines, so both go
through here. The candidate is a gateway alias, which is the point of the
gateway: swapping what is under test costs a string.

The system prompts live in this package and not in the eval suite. If the eval
steers the model differently from the CLI, it is measuring a product that does
not ship.
"""
from __future__ import annotations

import contextlib
import contextvars
import json
import os
import time
from dataclasses import dataclass, field

import httpx

from harness import reasons
from harness.checks.base import extract

DEFAULT_GATEWAY = "http://127.0.0.1:4000"
#: The gateway clients reach when none is given: a client machine sets it to the serving machine's. #702.
GATEWAY_ENV = "SOHOT_GATEWAY_URL"


def gateway_url(environ=None) -> str:
    """The gateway to use when a caller names none."""
    environ = os.environ if environ is None else environ
    return _bare(environ.get(GATEWAY_ENV) or "") or DEFAULT_GATEWAY


def _bare(base: str) -> str:
    return (base or "").strip().rstrip("/").removesuffix("/v1").rstrip("/")


_GATEWAYS: set = set()


def _answers_as_gateway(base: str) -> bool:
    """Whether `base` answers LiteLLM's liveness probe; only a yes is remembered."""
    if base in _GATEWAYS:
        return True
    try:
        r = httpx.get(base + "/health/liveliness", timeout=2.0)
    except httpx.HTTPError:
        return False
    if r.status_code == 200 and "alive" in r.text.lower():
        _GATEWAYS.add(base)
        return True
    return False


def is_gateway(base: str, environ=None, config=None) -> bool:
    """Whether `base` is a gateway: the configured or default one, else any base that is no config upstream and answers as LiteLLM."""
    from harness import gateway, serving
    got = _bare(base)
    if not got:
        return False
    if got in (gateway_url(environ), DEFAULT_GATEWAY):
        return True
    upstreams = {serving.api_base(e) for e in gateway.load(config).get("model_list") or []}
    if got in upstreams:
        return False
    return _answers_as_gateway(got)

# Per-modality steering. The checkers recover fenced or chatty output anyway,
# but asking for the bare artifact makes the comparison about the artifact
# rather than about who ignores instructions most politely.
SYSTEM = {
    "svg": ("You output a single SVG document and nothing else. No prose, no "
            "markdown fences. Include an xmlns and a viewBox. Use vector "
            "shapes only, never an embedded raster image."),
    "web": ("You output a single complete HTML document and nothing else. No "
            "prose, no markdown fences. Start with <!doctype html>. The page "
            "must be self-contained: inline all CSS and JS, and do not "
            "reference any external URL."),
    "code": ("You output working code and nothing else. No prose, no "
             "explanation, no example usage. A single markdown fence is "
             "acceptable. Include any imports the code needs. Do not write "
             "tests; do not print anything."),
    # The lane exists so a small model can be handed a log or a file listing
    # instead of spending a large model's context on it. Its value is a short
    # exact answer that the caller can use without parsing, so the prompt is
    # blunt about that.
    "extract": ("You answer with the fact asked for and nothing else. No "
                "preamble, no explanation, no restating the question, no "
                "prose around the answer. If the answer is a number, a "
                "filename or a line, give exactly that. If the material does "
                "not contain the answer, reply: NOT FOUND"),
    # A typed decision: one letter per field, as JSON, so the letter tokens
    # carry the probabilities. #423.
    # A case carries its own system prompt; this one serves a delegated request. #654.
    "claims": ("You read a numbered chat transcript and list durable technical claims as JSON: "
               "c is a list of [user, claim, refs], refs being the line numbers that support it."),
    "decide": ("You answer with a single JSON object and nothing else. No "
               "prose, no markdown fences, no explanation. Each key is a field "
               "name and each value is the letter of one allowed choice."),
    # One single-attempt patch against a real repository, applied with git apply. #887, #1129.
    "repo": ("You fix issues in a software repository from the files shown in the message. You have "
             "no tools: you cannot run commands or read, search or edit files, nothing in your reply "
             "is executed, and the files shown are all you get. Your whole reply is one unified diff "
             "that git apply accepts, with a/ and b/ paths from the repository root, and nothing else."),
}
NEUTRAL_SYSTEM = "Answer directly and concisely."

DEFAULT_TEMPERATURE = 0.2

# Sampling, per modality, because the lanes want opposite things.
#
# The SVG lane's loudest failure is DEGENERATE REPETITION: the model emits a
# plausible <path>, and the highest-probability continuation is another one
# just like it, until the token budget runs out mid-attribute and leaves an
# unclosed document. `lh svg "a cartoon frog holding a coffee mug"` produced
# eighty near-identical paths and no frog.
#
# A repetition penalty is the standard lever for that. Its value here is NOT
# yet established: hand-run single samples suggested temperature was the
# culprit instead, and three-sample repeats contradicted that outright. This
# repo has a commit called "--repeat: one sample per prompt ranks noise" and
# an eval suite built for exactly this question, so the honest state is that
# the knob exists, is measurable, and has not been measured. Compare with:
#   uv run python -m evals.run --modality svg --repeat 5 --candidates mlx-community/Qwen2.5-7B-Instruct-4bit
# against a run overriding sampling to turn it off.
#
# `extract` and `code` are deliberately absent. Extract pulls one fact out of
# a log and wants to be as close to deterministic as the sampler allows;
# making it stochastic to fix a drawing problem would be a plain downgrade.
SAMPLING = {
    "svg": {"temperature": 0.4, "repetition_penalty": 1.1},
    "web": {"temperature": 0.4, "repetition_penalty": 1.1},
    # The answer is the argmax; the distribution comes from the logprobs.
    "decide": {"temperature": 0.0},
    "claims": {"temperature": 0.0},
}

#: Chat-template kwargs per modality; decide reads one pass of option logprobs, so no reasoning. #311.
TEMPLATE = {"decide": {"enable_thinking": False}}

#: OpenAI's ceiling is 20 and mlx_lm.server's is 11. #423.
TOP_LOGPROBS = 10

# Root tags worth recovering, per modality.
ROOT_TAGS = {"svg": ("svg",), "web": ("html", "!doctype"), "code": ()}

_START_HINT = "is the gateway up? ./scripts/serve-gateway.sh"


#: The token budget and request timeout this harness chooses. #406.
MAX_TOKENS = 4000
TIMEOUT_S = 180.0
LOAD_TIMEOUT_S = 1800.0

#: Eval reply budget per lane; code serves a reasoning model, sized at Qwen3's documented output length. #628.
BUDGET = {"svg": MAX_TOKENS, "web": MAX_TOKENS, "code": 32768, "extract": MAX_TOKENS,
          "decide": MAX_TOKENS, "agent": 8000, "claims": 400, "repo": 32768}
#: The slowest decode a budget's timeout allows for, tokens per second. #628.
MIN_DECODE_TOK_S = 25.0


#: Budgets a laddered eval retries a cut-off reply at, smallest first. #668.
LADDER = {"svg": (4000, 16000), "web": (4000, 16000), "code": (4000, 16000, 32000, 65536),
          "extract": (4000, 16000), "decide": (4000, 16000), "agent": (8000, 32000),
          "claims": (400, 1600), "repo": (32768, 65536)}


def ladder(lane: str) -> tuple:
    """The default budget ladder for `lane`; () where no text is generated. #668."""
    return tuple(LADDER.get(lane, ()))


def budget(lane: str) -> int:
    """The reply budget an eval of `lane` runs at unless the run names one; 0 where no text is generated. #628."""
    return BUDGET.get(lane, 0)


def timeout_for(max_tokens: int) -> float:
    """A request timeout long enough to spend `max_tokens` at MIN_DECODE_TOK_S. #628."""
    return max(TIMEOUT_S, float(max_tokens) / MIN_DECODE_TOK_S)


def unreachable(exc: BaseException | None) -> bool:
    """True when `exc`, or anything it was raised from, is a refused connection: nothing listens there yet. #1181."""
    seen = set()
    while exc is not None and id(exc) not in seen:
        if isinstance(exc, httpx.ConnectError):
            return True
        seen.add(id(exc))
        exc = exc.__cause__ or exc.__context__
    return False


class CompletionError(RuntimeError):
    """The gateway did not return usable text."""

    def __init__(self, detail: str, failure_class: str = "",
                 limit: tuple = (), usage: dict | None = None,
                 reasoning: str = "", finish: str = ""):
        super().__init__(detail)
        # Set where the cause is known; "" leaves it to reasons.classify. #408.
        self.failure_class = failure_class
        self.limit = limit
        self.usage = usage or {}
        #: The reasoning text of a reply that never answered, kept so the row can be read. #921.
        self.reasoning = reasoning
        self.finish = finish
        #: What was sent: max_tokens, sampling, template, system_sha; set by complete_full. #921.
        self.request: dict = {}


def user_message(prompt: str, context: str = "") -> str:
    """The material first, the instruction last.

    A small model that reads a long log and THEN the question does better than
    one that reads the question, works through forty lines, and has to
    remember what it was looking for.
    """
    if not context:
        return prompt
    return f"{context.rstrip()}\n\n---\n\n{prompt}"


def complete(prompt: str, model: str, gateway: str = "",
             **kw) -> str:
    """Ask `model` for a completion. Returns the raw text, unrecovered."""
    return complete_with_usage(prompt, model, gateway, **kw)[0]


def complete_with_usage(prompt: str, model: str, gateway: str = "",
             modality: str = "", context: str = "", timeout: float = TIMEOUT_S,
             temperature: float | None = None, max_tokens: int = MAX_TOKENS,
             sampling: dict | None = None,
             template: dict | None = None) -> tuple[str, dict]:
    """As `complete()`, but also returns the server's token `usage`.

    The gateway reports usage on every completion and this was thrown away, so
    the text lanes measured latency and never throughput -- two candidates can
    share a median while one of them wrote three times as much. Absent usage is
    an empty dict, never an error: mlx_lm.server has answered without the block.
    """
    text, usage, _ = complete_with_logprobs(
        prompt, model, gateway, modality=modality, context=context,
        timeout=timeout, temperature=temperature, max_tokens=max_tokens,
        sampling=sampling, template=template)
    return text, usage


def complete_with_logprobs(prompt: str, model: str,
                           gateway: str = "", modality: str = "",
                           context: str = "", timeout: float = TIMEOUT_S,
                           temperature: float | None = None,
                           max_tokens: int = MAX_TOKENS,
                           sampling: dict | None = None,
                           template: dict | None = None,
                           top_logprobs: int = 0) -> tuple[str, dict, list]:
    """As complete_with_usage, plus the per-token logprobs when asked for and
    the server returns them (OpenAI shape: content[i].top_logprobs); else []."""
    got = complete_full(prompt, model, gateway, modality=modality,
                        context=context, timeout=timeout,
                        temperature=temperature, max_tokens=max_tokens,
                        sampling=sampling, template=template,
                        top_logprobs=top_logprobs)
    return got.text, got.usage, got.tokens


class _Waits:
    """Busy-wait spans (perf_counter start, end) of the requests made inside one measuring() scope. #776."""

    def __init__(self, parent=None):
        import threading
        self.spans: list = []
        self.parent = parent
        self._lock = threading.Lock()

    def add(self, start: float, end: float, kind: str = "busy") -> None:
        with self._lock:
            self.spans.append((start, end, kind))
        if self.parent is not None:
            self.parent.add(start, end, kind)

    def within(self, start: float = float("-inf"), end: float = float("inf"), kind: str | None = None) -> float:
        """Seconds of [start, end] some request in this scope spent waiting (of `kind`, else any); overlaps count once."""
        with self._lock:
            spans = sorted((max(a, start), min(b, end)) for a, b, k in self.spans if kind in (None, k))
        total, reach = 0.0, start
        for a, b in spans:
            a = max(a, reach)
            if b > a:
                total += b - a
                reach = b
        return total


_WAITS: contextvars.ContextVar = contextvars.ContextVar("busy_waits", default=None)


@contextlib.contextmanager
def measuring():
    """A scope whose requests' busy waits since() leaves out; a nested scope also reports to the one around it. #776."""
    waits = _Waits(_WAITS.get())
    held = _WAITS.set(waits)
    try:
        yield waits
    finally:
        _WAITS.reset(held)


def busy_s(started: float, now: float | None = None) -> float:
    """Seconds since `started` that this scope's requests spent waiting out a busy serving machine. #776."""
    waits = _WAITS.get()
    return waits.within(started, time.perf_counter() if now is None else now) if waits else 0.0


def since(started: float) -> float:
    """perf_counter seconds since `started`, less the busy waits of this scope's requests. #776."""
    now = time.perf_counter()
    return now - started - busy_s(started, now)


def carrying(fn):
    """`fn` run in a copy of the caller's context, so a pool worker's busy waits reach the caller's scope. #776."""
    ctx = contextvars.copy_context()
    return lambda *a, **k: ctx.copy().run(fn, *a, **k)


def _timed(fn):
    """Stamp timing["busy_wait_s"] on the Completion `fn` returns when its requests waited. #776."""
    import functools

    @functools.wraps(fn)
    def call(*a, **k):
        with measuring() as waits:
            got = fn(*a, **k)
        got.timing.update(waited(waits))
        return got
    return call


#: The span kind a pool-full retry's lost attempt and lock wait carry. #1235.
POOL_FULL_WAIT = "pool_full"


def waited(waits) -> dict:
    """{"busy_wait_s": every hidden wait, "pool_full_wait_s": the pool-full part}, each only when nonzero. #776, #1235."""
    if not waits.spans:
        return {}
    pool = waits.within(kind=POOL_FULL_WAIT)
    return {"busy_wait_s": round(waits.within(), 3), **({"pool_full_wait_s": round(pool, 3)} if pool else {})}


@dataclass
class Completion:
    text: str
    usage: dict = field(default_factory=dict)
    tokens: list = field(default_factory=list)
    #: ttft_s, first_reasoning_s, prefill_s; None where not observed. #468.
    timing: dict = field(default_factory=dict)
    #: The model the server says answered, which an alias hides; "" if unsaid.
    model: str = ""
    #: The whole assistant message, tool_calls included; chat() only. #474.
    message: dict = field(default_factory=dict)
    #: The server's finish_reason; "length" means the budget cut the reply off. #628.
    finish: str = ""
    #: LiteLLM's x-litellm-call-id, the gateway_requests.call_id of this request; "" off the gateway. #829.
    call_id: str = ""
    #: The reply's reasoning_content; "" when the server sent none. #921.
    reasoning: str = ""
    #: What was sent: max_tokens, sampling, template, system_sha. #921.
    request: dict = field(default_factory=dict)


@_timed
def complete_full(prompt: str, model: str, gateway: str = "",
                  modality: str = "", context: str = "",
                  timeout: float = TIMEOUT_S,
                  temperature: float | None = None,
                  max_tokens: int = MAX_TOKENS, sampling: dict | None = None,
                  template: dict | None = None, top_logprobs: int = 0,
                  stream: bool = False, system: str | None = None,
                  response_format: dict | None = None) -> Completion:
    """One completion with its timing. `stream` asks for SSE so the first
    content token can be timed; a server that answers whole leaves ttft_s None."""
    sent: dict = {}
    try:
        got = _complete_full(sent, prompt, model, gateway, modality, context, timeout, temperature,
                             max_tokens, sampling, template, top_logprobs, stream, system,
                             response_format)
    except CompletionError as exc:
        exc.request = dict(sent)
        raise
    got.request = dict(sent)
    return got


#: Generated tokens past which a streamed reply is stopped at its yield stop point; None runs it to its budget. #1127.
_STOP_AFTER: contextvars.ContextVar = contextvars.ContextVar("stop_after", default=None)


@contextlib.contextmanager
def stopping_after(tokens: int | None):
    """Stop streamed replies inside this block once they generate more than `tokens`; the request itself is unchanged. #1127."""
    held = _STOP_AFTER.set(tokens)
    try:
        yield
    finally:
        _STOP_AFTER.reset(held)


def request_of(payload: dict) -> dict:
    """The parts of a chat request that decide what is asked: budget, sampler, template kwargs, system digest. #921."""
    import hashlib

    from harness.serving import SAMPLING_KEYS
    system = next((m.get("content") or "" for m in payload.get("messages") or []
                   if m.get("role") == "system"), "")
    return {"max_tokens": payload.get("max_tokens"),
            "sampling": {k: payload[k] for k in sorted(payload) if k in SAMPLING_KEYS},
            "template": dict(payload.get("chat_template_kwargs") or {}),
            "system_sha": hashlib.sha256(system.encode("utf-8")).hexdigest()[:16] if system else ""}


def payload_for(prompt, model, modality, context, temperature, max_tokens, sampling, template,
                top_logprobs, stream, system, response_format) -> dict:
    """The chat request body a completion sends, before any server-specific retry. #1094."""
    knobs = dict(SAMPLING.get(modality, {}))
    if temperature is not None:
        knobs["temperature"] = temperature
    if sampling:
        knobs.update(sampling)
    knobs.setdefault("temperature", DEFAULT_TEMPERATURE)

    system = system or SYSTEM.get(modality, NEUTRAL_SYSTEM)
    user = user_message(prompt, context)
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        **knobs,
    }
    template = template or TEMPLATE.get(modality)
    if template:
        payload["chat_template_kwargs"] = dict(template)
    if response_format:
        payload["response_format"] = dict(response_format)
    if top_logprobs:
        payload["logprobs"] = True
        payload["top_logprobs"] = int(top_logprobs)
    # LiteLLM drops logprobs from a streamed reply, and the logprobs are the
    # product here, so a logprobs request is never streamed (RULE #426).
    if stream and not top_logprobs:
        payload["stream"] = True
        payload["stream_options"] = {"include_usage": True}
    return payload


def _complete_full(sent: dict, prompt, model, gateway, modality, context, timeout, temperature,
                   max_tokens, sampling, template, top_logprobs, stream, system,
                   response_format) -> Completion:
    from harness import knobs
    gateway = gateway or gateway_url()
    payload = payload_for(prompt, model, modality, context, temperature, max_tokens, sampling, template,
                          top_logprobs, stream, system, response_format)
    system, user = (m["content"] for m in payload["messages"])
    sent.update(request_of(payload))
    try:
        r = _post(gateway, payload, timeout)
        if (400 <= getattr(r, "status_code", 200) < 500
                and _refuses_system_role(getattr(r, "text", ""))):
            # The model's chat template has no system role (Gemma 2, Mistral
            # v0.3): same words, one user turn. #305.
            payload["messages"] = [{"role": "user",
                                    "content": f"{system}\n\n{user}"}]
            r = _post(gateway, payload, timeout)
        for drop in ("stream_options", "stream"):
            # A server that refuses a streaming knob is asked again without it.
            if (drop in payload and 400 <= getattr(r, "status_code", 200) < 500
                    and "stream" in (getattr(r, "text", "") or "").lower()):
                payload.pop(drop)
                payload.pop("stream_options", None)
                r = _post(gateway, payload, timeout)
        r.raise_for_status()
        body = r.json()
        choices = body.get("choices") or []
        message = choices[0]["message"]
        served = str(body.get("model") or "")
        text = message.get("content")
        reasoning = message.get("reasoning_content") or message.get("reasoning") or ""
        finish = str(choices[0].get("finish_reason") or "")
        usage = body.get("usage") or {}
        tokens = ((choices[0].get("logprobs") or {}).get("content") or []) \
            if top_logprobs else []
        timing = {"ttft_s": None, "first_reasoning_s": None,
                  **(getattr(r, "timing", None) or {}),
                  "prefill_s": prefill_s(body.get("timings"))}
    except httpx.TimeoutException as exc:
        raise CompletionError(f"timed out after {timeout}s", reasons.TIMEOUT,
                              knobs.hit("timeout_s", timeout, "s")) from exc
    except httpx.HTTPStatusError as exc:
        from harness import gateway_key
        status = exc.response.status_code
        if gateway_key.refused(status, exc.response.text, gateway_key.key()):
            raise CompletionError(
                f"gateway at {gateway} refused the key (HTTP {status}): "
                f"{gateway_key.HINT}", reasons.HARNESS_ERROR) from exc
        # LiteLLM explains itself in the body, not the status line.
        raise CompletionError(
            f"gateway returned HTTP {exc.response.status_code}: "
            f"{exc.response.text[:400]}",
            reasons.REFUSED_BY_GATEWAY if _refused(exc.response) else "") from exc
    except httpx.HTTPError as exc:
        raise CompletionError(
            f"gateway unreachable at {gateway}: {exc} ({_START_HINT})",
            reasons.REFUSED_BY_GATEWAY) from exc
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise CompletionError(f"malformed response: {exc}", reasons.CRASHED) from exc

    if finish == reasons.STOPPED_LOW_YIELD:
        stop = _STOP_AFTER.get()
        raise CompletionError(f"stopped after {stop} generated tokens, its yield stop point: tasks still running "
                              f"there rarely pass", reasons.STOPPED_LOW_YIELD, knobs.hit("yield_stop", stop, "tokens"),
                              usage=usage, reasoning=reasoning, finish=finish)
    if text is None or not text.strip():
        # A THINKING MODEL that spent its whole budget reasoning returns null
        # content and a populated reasoning_content. Qwen3-8B and Qwen3-14B do
        # this; Qwen3-4B-Instruct-2507 and Qwen2.5 do not. Saying so beats a
        # TypeError from three frames away, or "empty completion" for a model
        # that in fact produced 4000 tokens of thought.
        if reasoning:
            spent = reasoning_tokens(usage)
            raise CompletionError(
                f"{model} returned no answer: it spent the whole "
                f"{max_tokens}-token budget on reasoning ("
                + (f"{spent} tokens of reasoning, " if spent else "")
                + f"{len(reasoning)} characters). This is a hybrid "
                f"thinking model; use a non-thinking one for this lane, or "
                f"raise max_tokens.", reasons.TOKEN_BUDGET_EXHAUSTED,
                knobs.hit("max_tokens", max_tokens, "tokens"), usage=usage, reasoning=reasoning, finish=finish)
        raise CompletionError("empty completion", reasons.CONTENT_FAILED,
                              usage=usage, finish=finish)
    return Completion(text, usage,
                      list(tokens) if isinstance(tokens, list) else [], timing,
                      served, finish=finish, call_id=call_id_of(r), reasoning=reasoning)


#: The header LiteLLM's proxy answers with; its value is the logged litellm_call_id. #829.
CALL_ID_HEADER = "x-litellm-call-id"


def call_id_of(r) -> str:
    try:
        return str((getattr(r, "headers", None) or {}).get(CALL_ID_HEADER) or "")
    except (AttributeError, TypeError):
        return ""


def reasoning_tokens(usage) -> int | None:
    """Tokens the server says went to reasoning; all completion tokens when it gave no split."""
    usage = usage or {}
    details = usage.get("completion_tokens_details") or {}
    got = details.get("reasoning_tokens") or usage.get("completion_tokens")
    return int(got) if got else None


def prefill_s(timings) -> float | None:
    """llama-server's own prompt-processing time, in seconds; None elsewhere."""
    try:
        ms = (timings or {}).get("prompt_ms")
        return None if ms is None else round(float(ms) / 1000.0, 4)
    except (AttributeError, TypeError, ValueError):
        return None



#: What a chat template says when it has no system role. #305.
SYSTEM_ROLE_REFUSALS = ("system role not supported",
                        "conversation roles must alternate")


def _refuses_system_role(body: str) -> bool:
    low = (body or "").lower()
    return any(p in low for p in SYSTEM_ROLE_REFUSALS)


#: (gateway, model) -> {"machine", "model", "ctx", "slots"} its last good reply named in x-sohot-* headers. #697.
SERVED: dict = {}


def _note(gateway: str, model, r) -> None:
    if getattr(r, "status_code", 200) >= 400:
        return
    got = getattr(r, "headers", None) or {}
    shape = {}
    for key in ("ctx", "slots"):
        try:
            shape[key] = int(got.get(f"x-sohot-{key}") or 0) or None
        except ValueError:
            shape[key] = None
    key = (gateway.rstrip("/"), str(model or ""))
    machine = str(got.get("x-sohot-machine") or "")
    # Every host that answered, so a run a node served only in part is not filed under one. #684.
    machines = sorted(set((SERVED.get(key) or {}).get("machines") or ()) | ({machine} - {""}))
    SERVED[key] = {"machine": machine, "machines": machines,
                   "model": str(got.get("x-sohot-model") or ""), **shape}


def served(gateway: str | None = None) -> dict:
    """What the replies so far said served them, for one gateway or all. #697."""
    want = gateway.rstrip("/") if gateway else None
    return {k: dict(v) for k, v in SERVED.items() if want is None or k[0] == want}


def _refused(response) -> bool:
    """A 503 the gateway sent on purpose: draining for a switch (#703) or busy with another batch (#769)."""
    from harness import batch, gateway_switch
    text = getattr(response, "text", "") or ""
    return getattr(response, "status_code", 200) == 503 and (
        gateway_switch.DRAINING in text or batch.BUSY in text)


def _busy(response) -> bool:
    from harness import batch
    return getattr(response, "status_code", 200) == 503 and batch.BUSY in (getattr(response, "text", "") or "")


#: Times a request is sent again after llama-server failed it, and every other one in flight, on a full shared KV pool. #755.
POOL_FULL_RETRIES = 1
#: How often a pool-full retry asks again for the gateway's retry lock; the request's own timeout bounds the wait. #755.
POOL_FULL_POLL_S = 0.5
#: (gateway, model) -> {"retried", "lost"} pool-full requests since the last clear; an eval's receipt reads it. #755.
POOL_FULL: dict = {}


def _pool_full(got) -> bool:
    if isinstance(got, CompletionError):
        text = str(got)
    elif getattr(got, "status_code", 200) >= 500:
        text = getattr(got, "text", "") or ""
    else:
        return False
    return reasons.classify(text) == reasons.POOL_FULL


def _count(gateway: str, payload: dict, kind: str) -> None:
    seen = POOL_FULL.setdefault((gateway.rstrip("/"), str(payload.get("model") or "")), {"retried": 0, "lost": 0})
    seen[kind] += 1


def pool_full_counts() -> tuple[int, int]:
    """(retried, lost) pool-full requests across every gateway and model since POOL_FULL was cleared. #755."""
    return (sum(v["retried"] for v in POOL_FULL.values()), sum(v["lost"] for v in POOL_FULL.values()))


def _post(gateway: str, payload: dict, timeout: float):
    """One request; a pool-full reply is sent again up to POOL_FULL_RETRIES times, one retry per gateway at a time. #755."""
    import hashlib

    from harness import exclusive
    first = time.perf_counter()
    got, sent = _attempt(gateway, payload, timeout), 0
    while _pool_full(got) and sent < POOL_FULL_RETRIES:
        sent += 1
        _count(gateway, payload, "retried")
        name = f"pool-retry.{hashlib.sha256(gateway.rstrip('/').encode()).hexdigest()[:12]}.lock"
        with exclusive.alone(name, timeout, POOL_FULL_POLL_S):
            if (waits := _WAITS.get()) is not None:
                # The lost attempt and the lock wait are not this request's model time. #1235.
                waits.add(first, time.perf_counter(), POOL_FULL_WAIT)
            got = _attempt(gateway, payload, timeout)
    if _pool_full(got):
        from harness import knobs
        _count(gateway, payload, "lost")
        text = str(got) if isinstance(got, CompletionError) else getattr(got, "text", "")
        raise CompletionError(f"llama-server's shared KV pool was full, sent {sent + 1} time(s): {text[:400]}",
                              reasons.POOL_FULL, knobs.hit("pool_full_retries", POOL_FULL_RETRIES, "calls"))
    return got


def _attempt(gateway: str, payload: dict, timeout: float):
    """The reply, or the CompletionError a stream raised; a pool-full one is returned for _post to retry. #755."""
    try:
        return _busy_post(gateway, payload, timeout)
    except CompletionError as exc:
        if _pool_full(exc):
            return exc
        raise


def _busy_post(gateway: str, payload: dict, timeout: float):
    """One request, waited out while the serving machine is busy with another batch, up to batch.BUSY_WAIT_S. #769."""
    from harness import batch
    deadline = time.monotonic() + batch.BUSY_WAIT_S
    refused = None
    while True:
        sent = time.perf_counter()
        r = _send(gateway, payload, timeout)
        if not _busy(r) or time.monotonic() + batch.BUSY_POLL_S > deadline:
            if refused is not None and (waits := _WAITS.get()) is not None:
                waits.add(refused, time.perf_counter() if _busy(r) else sent)
            return r
        refused = sent if refused is None else refused
        time.sleep(batch.BUSY_POLL_S)


def _send(gateway: str, payload: dict, timeout: float):
    url = f"{gateway.rstrip('/')}/v1/chat/completions"
    from harness import batch, gateway_key
    headers = gateway_key.headers()
    if batch.current():
        headers = {**headers, batch.HEADER: batch.current()}
    if not payload.get("stream"):
        r = httpx.post(url, json=payload, timeout=timeout, headers=headers)
        _note(gateway, payload.get("model"), r)
        return r
    started = time.perf_counter()
    with httpx.stream("POST", url, json=payload, timeout=timeout,
                      headers=headers) as r:
        if (r.status_code >= 400 or "text/event-stream"
                not in r.headers.get("content-type", "")):
            r.read()
            _note(gateway, payload.get("model"), r)
            return r
        body, timing = assemble(r.iter_lines(), started, timeout)
        _note(gateway, payload.get("model"), r)
    return Streamed(body, timing, r.headers)


class Streamed:
    """An SSE reply assembled into the body a non-streaming request returns."""
    status_code = 200
    text = ""

    def __init__(self, body: dict, timing: dict, headers=None):
        self.body, self.timing, self.headers = body, timing, headers or {}

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return self.body


def assemble(lines, started: float, timeout: float = TIMEOUT_S):
    """(body, timing) from OpenAI-style SSE lines; offsets from `started`."""
    content, reasoning, tokens = [], [], []
    calls: dict[int, dict] = {}
    usage, timings, finish, model = {}, None, None, None
    stop, made = _STOP_AFTER.get(), 0
    first: dict = {"ttft_s": None, "first_reasoning_s": None}
    for line in lines:
        now = time.perf_counter() - started
        if now > timeout:
            # The non-streaming limit, kept as a total so a slow writer still times out.
            raise httpx.ReadTimeout(f"stream ran past {timeout}s")
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            break
        chunk = json.loads(data)
        if chunk.get("error"):
            raise CompletionError(
                f"server error mid-stream: {str(chunk['error'])[:400]}")
        usage = chunk.get("usage") or usage
        model = chunk.get("model") or model
        timings = chunk.get("timings") or timings
        for ch in chunk.get("choices") or []:
            delta = ch.get("delta") or {}
            if delta.get("content"):
                content.append(delta["content"])
                if first["ttft_s"] is None:
                    first["ttft_s"] = round(now, 4)
            think = delta.get("reasoning_content") or delta.get("reasoning")
            if think:
                reasoning.append(think)
                if first["first_reasoning_s"] is None:
                    first["first_reasoning_s"] = round(now, 4)
            for part in delta.get("tool_calls") or []:
                _merge_call(calls, part)
                first.setdefault("first_tool_s", round(now, 4))
            tokens.extend((ch.get("logprobs") or {}).get("content") or [])
            finish = ch.get("finish_reason") or finish
            # llama-server streams one generated token per chunk.
            made += bool(delta.get("content") or think or delta.get("tool_calls"))
        if stop is not None and made > stop:
            # Leaving the stream closes the connection, which ends the generation upstream.
            finish, usage = reasons.STOPPED_LOW_YIELD, {**usage, "completion_tokens": made}
            break
    message = {"role": "assistant",
               "content": "".join(content) if content else None,
               "reasoning_content": "".join(reasoning) if reasoning else None}
    if calls:
        message["tool_calls"] = [calls[i] for i in sorted(calls)]
    body = {"choices": [{"message": message, "finish_reason": finish,
                         "logprobs": {"content": tokens} if tokens else None}],
            "usage": usage, "timings": timings, "model": model}
    return body, first


def _merge_call(calls: dict, part: dict) -> None:
    """Fold one streamed tool_calls fragment into the call at its index."""
    at = part.get("index")
    at = len(calls) if not isinstance(at, int) else at
    got = calls.setdefault(at, {"id": "", "type": "function",
                                "function": {"name": "", "arguments": ""}})
    if part.get("id"):
        got["id"] = part["id"]
    fn = part.get("function") or {}
    if fn.get("name"):
        got["function"]["name"] += fn["name"]
    if isinstance(fn.get("arguments"), str):
        got["function"]["arguments"] += fn["arguments"]
    elif fn.get("arguments") is not None:
        got["function"]["arguments"] = json.dumps(fn["arguments"])


@_timed
def chat(messages: list, model: str, gateway: str = "",
         tools: list | None = None, timeout: float = TIMEOUT_S,
         max_tokens: int = MAX_TOKENS, sampling: dict | None = None,
         stream: bool = True) -> Completion:
    """One turn of a multi-turn conversation with OpenAI tools. #474.

    `text` may be empty when the turn is tool calls; `message` is the whole
    assistant message, tool_calls included. timing["first_tool_s"] is the
    first tool-call fragment.
    """
    import harness.knobs
    gateway = gateway or gateway_url()
    knobs = {"temperature": DEFAULT_TEMPERATURE, **(sampling or {})}
    payload = {"model": model, "max_tokens": max_tokens,
               "messages": list(messages), **knobs}
    if tools:
        payload["tools"] = list(tools)
        payload["tool_choice"] = "auto"
    if stream:
        payload["stream"] = True
        payload["stream_options"] = {"include_usage": True}
    try:
        r = _post(gateway, payload, timeout)
        if (stream and 400 <= getattr(r, "status_code", 200) < 500
                and "stream" in (getattr(r, "text", "") or "").lower()):
            payload.pop("stream")
            payload.pop("stream_options")
            r = _post(gateway, payload, timeout)
        r.raise_for_status()
        body = r.json()
        message = dict((body.get("choices") or [])[0]["message"])
        usage = body.get("usage") or {}
        timing = {"ttft_s": None, "first_reasoning_s": None,
                  "first_tool_s": None,
                  **(getattr(r, "timing", None) or {}),
                  "prefill_s": prefill_s(body.get("timings"))}
    except httpx.TimeoutException as exc:
        raise CompletionError(f"timed out after {timeout}s", reasons.TIMEOUT,
                              harness.knobs.hit("timeout_s", timeout, "s")) from exc
    except httpx.HTTPStatusError as exc:
        raise CompletionError(
            f"gateway returned HTTP {exc.response.status_code}: "
            f"{exc.response.text[:400]}",
            reasons.REFUSED_BY_GATEWAY if _refused(exc.response) else "") from exc
    except httpx.HTTPError as exc:
        raise CompletionError(
            f"gateway unreachable at {gateway}: {exc} ({_START_HINT})",
            reasons.REFUSED_BY_GATEWAY) from exc
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise CompletionError(f"malformed response: {exc}", reasons.CRASHED) from exc
    return Completion(message.get("content") or "", usage, [], timing,
                      model=str(body.get("model") or ""), message=message,
                      finish=str(body["choices"][0].get("finish_reason") or ""))


def token_counter(base: str, model: str):
    """A count(text) -> int from the served model's own tokenizer (llama-server POST /tokenize), or None when the server has none. #695."""
    url = f"{base.rstrip('/')}/tokenize"
    try:
        r = httpx.post(url, json={"model": model, "content": "probe"}, timeout=TIMEOUT_S)
        r.raise_for_status()
        if not isinstance(r.json().get("tokens"), list):
            return None
    except (httpx.HTTPError, ValueError, AttributeError):
        return None

    def count(text: str) -> int:
        got = httpx.post(url, json={"model": model, "content": text}, timeout=TIMEOUT_S)
        got.raise_for_status()
        return len(got.json()["tokens"])
    return count


def artifact(text: str, modality: str) -> str:
    """Recovered artifact for a known modality; the raw text otherwise.

    `code` maps to an empty tag tuple rather than being absent: extract() with
    no root tags still unwraps a markdown fence, which is exactly what code
    needs and what a bare .strip() would leave in.
    """
    if modality not in ROOT_TAGS:
        return text.strip()
    return extract(text, ROOT_TAGS[modality])
