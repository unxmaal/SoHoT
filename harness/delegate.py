"""A text subtask handed to a lane's adopted local model. #475.

The MCP server calls this in-process rather than shelling out to `soh`, because
the caller wants the first-token time and the model that answered, which the
CLI does not print. It stays the same product by sharing the route: the lane
commands resolve their model through route() here too.
"""
from __future__ import annotations

import contextlib
import json
import os
import statistics
import time
import urllib.request

import httpx

from harness import completion, context, exclusive, gateway, purpose, reasons, serving

#: Lanes a delegated completion may name: the ones the gateway aliases as sohot-<lane>.
LANES = gateway.TEXT_LANES
MAX_PROMPT_CHARS = 100_000
#: The max_tokens cap when the served context is unknown.
MAX_TOKENS = 8192
#: Characters per prompt token where the served tokenizer cannot be asked; CJK and base64 run lower. #692.
CHARS_PER_TOKEN = 3
TIMEOUT_S = 300.0
#: Seconds to ask a server what it holds; an answer that late leaves residency unknown.
RESIDENCY_TIMEOUT_S = 2.0


class Refused(ValueError):
    """A request this module will not send, said before anything is loaded."""


def lane_model(lane: str, chosen: str | None = None) -> str:
    """-m when given, else the lane's adopted model here, else its typed constant. #297."""
    from harness import adopt, models, winners
    spec = chosen or adopt.default_for(lane, winners.typed().get(lane, ""))
    models.warn(spec)
    return spec


def route(lane: str, chosen: str | None = None, via: str = "") -> tuple[str, serving.Route]:
    """(spec, Route) for a text lane, as every lane command resolves it; a method routes as its base. #581."""
    from harness import methods
    spec = lane_model(lane, chosen)
    if methods.is_method(spec) and not methods.text_method(spec):
        raise Refused(f"the {lane} lane serves {spec}, which draws with an image engine "
                      f"rather than answering in text; run `soh svg` for it")
    return spec, serving.route(methods.base_of(spec) or spec, via)


def generate(spec: str, where: serving.Route, lane: str, prompt: str,
             call) -> tuple[str, dict, list]:
    """(text, cost, replies): `spec` served over `where`, each call made by
    call(prompt, model=, gateway=, modality=, sampling=) -> Completion. #581."""
    from harness import methods
    replies: list = []

    def ask(text: str, modality: str) -> str:
        got = call(text, model=where.model, gateway=where.base, modality=modality,
                   sampling=where.sampling or None)
        replies.append(got)
        return got.text
    text, cost = methods.run(spec, lane, prompt, ask)
    return text, cost, replies


def check_lane(lane: str) -> str:
    lane = (lane or "").strip().lower()
    if lane not in LANES:
        raise Refused(f"lane {lane!r} is not a text lane; delegation serves "
                      f"{', '.join(LANES)}. image and video go on the work queue.")
    return lane


def busy() -> str:
    """What holds the machine lock, or "" when nobody does. Never waits."""
    if os.environ.get(exclusive.HELD_ENV) == "1":
        return ""
    fd = os.open(exclusive.lock_path(), os.O_RDWR | os.O_CREAT, 0o644)
    try:
        if exclusive._take(fd):
            exclusive._release(fd)
            return ""
    finally:
        os.close(fd)
    return exclusive.describe(exclusive.holder())


def _preflight(*texts: str, max_tokens: int = 1) -> None:
    size = sum(len(t or "") for t in texts)
    if size > MAX_PROMPT_CHARS:
        raise Refused(f"prompt is {size} characters, over the {MAX_PROMPT_CHARS} "
                      f"cap; pass less material or summarise it first")
    if int(max_tokens) < 1:
        raise Refused(f"max_tokens must be at least 1, not {max_tokens}")


def prompt_tokens(*texts: str, count=None) -> int:
    """Tokens in the prompt by the served tokenizer `count`, else at CHARS_PER_TOKEN. #692."""
    chars = sum(len(t or "") for t in texts)
    estimate = -(-chars // CHARS_PER_TOKEN)
    if count is None:
        return estimate
    try:
        return sum(int(count(t)) for t in texts if t)
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        return estimate


def cap(ctx: int | None, *texts: str, count=None) -> int:
    """The largest max_tokens a request may ask for: the served context less the prompt. #590, #692."""
    if ctx is None:
        return MAX_TOKENS
    return max(0, ctx - prompt_tokens(*texts, count=count))


def counter(spec: str):
    """count(text) by the tokenizer the spec is served with, or None where the server has none. #692."""
    where = context._upstream(spec)
    return completion.token_counter(*where) if where else None


def _budget(spec: str, max_tokens: int, *texts: str) -> None:
    ctx = context.served_ctx(spec)
    most = cap(ctx, *texts, count=counter(spec) if ctx else None)
    if int(max_tokens) > most:
        where = (f"the {ctx}-token context {spec} is served at, less the prompt"
                 if ctx else f"the cap while {spec}'s served context is unknown")
        raise Refused(f"max_tokens must be 1..{most} ({where}), not {max_tokens}")


def _call_label(spec: str, n: int, modality: str) -> str:
    """Which call of a method this is, e.g. "call 2 of plan:<model> (the answer)"; "" for a plain model."""
    from harness import methods
    try:
        parsed = methods.parse(spec)
    except ValueError:
        parsed = None
    if parsed is None:
        return ""
    steps = parsed.method.extra.get("steps")
    if parsed.method.name == "plan":
        what = "the answer" if modality else "the plan"
    elif steps:
        what = "the answer" if n >= len(steps) else f"the {steps[n - 1].name}"
    else:
        what = f"sample {n}"
    return f"call {n} of {spec} ({what})"


def template(lane: str, thinking: bool | None) -> dict | None:
    """The lane's chat-template kwargs, with enable_thinking set when the caller says. #590."""
    kwargs = dict(completion.TEMPLATE.get(lane) or {})
    if thinking is not None:
        kwargs["enable_thinking"] = bool(thinking)
    return kwargs or None


def admit(holder: str, resident: bool | None, level: int | None) -> tuple[bool, str]:
    """(ok, why): may a delegated call go now? Only a model load needs the lock; None is residency unknown. #588, #694."""
    from harness.pressure import NORMAL
    if not holder:
        return True, ""
    if resident is None:
        return False, (f"this machine is busy with {holder} and its server did not say in "
                       f"{RESIDENCY_TIMEOUT_S:g}s whether the model is loaded (residency unknown), "
                       f"and delegation does not wait: retry when it finishes")
    if not resident:
        return False, (f"this machine is busy with {holder}; answering would load the "
                       f"model under its lock, and delegation does not wait: retry "
                       f"when it finishes")
    if level is not None and level > NORMAL:
        return False, (f"this machine is busy with {holder} and memory pressure is "
                       f"level {level}; delegation does not wait: retry when it finishes")
    return True, f"the model is resident, so nothing loads beside {holder}"


def running_job(conn=None) -> str:
    """The queued job running here, with how long earlier runs of it took, or ""."""
    from harness import workqueue as wq
    try:
        job = wq.current(conn)
        took = wq.durations(job["title"], conn) if job else []
        # Another machine's speed is a weaker estimate, so it says whose it is. #697.
        elsewhere = bool(job) and not took
        if elsewhere:
            took = wq.durations(job["title"], conn, anywhere=True)
    except Exception:  # noqa: BLE001
        return ""
    if job is None:
        return ""
    started = wq._epoch(job.get("started"))
    ran = max(0.0, time.time() - started) / 60 if started else 0.0
    head = f"job {job['id']} ({job['title']}), running {ran:.0f} min"
    if not took:
        return f"{head}, no earlier run to estimate from"
    typical = statistics.median(took) / 60
    left = typical - ran
    whose = " on other or unrecorded machines" if elsewhere else ""
    if left <= 0:
        return f"{head}, past the {typical:.0f} min earlier runs of it{whose} took"
    return f"{head}, about {left:.0f} min left by earlier runs of it{whose}"


def _get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=RESIDENCY_TIMEOUT_S) as r:
        return json.loads(r.read() or b"{}")


def upstream(where: serving.Route, config=None) -> tuple[str, str]:
    """(server base, model name) that answers `where`, a gateway alias resolved; ("", "") if unknown."""
    from harness.completion import is_gateway
    base = serving.bare(where.base)
    if not is_gateway(base):
        return base, where.model
    for entry in gateway.load(config).get("model_list") or []:
        if str(entry.get("model_name", "")).strip().lower() == where.model.lower():
            params = entry.get("litellm_params") or {}
            return (str(params.get("api_base", "")).rstrip("/").removesuffix("/v1"),
                    gateway.strip_provider(str(params.get("model", ""))))
    return "", ""


def loaded(where: serving.Route, get=None, config=None) -> bool | None:
    """True when the server behind `where`, on any host, holds its model now; None when it did not answer. #694."""
    from harness import mlx_server
    get = get or _get_json
    base, model = upstream(where, config)
    if not model:
        return False
    try:
        engine = serving.engine_at(base, config=config)
        if engine == serving.LLAMACPP:
            for m in get(base + "/models").get("data") or []:
                status = m.get("status")
                value = status.get("value") if isinstance(status, dict) else status
                if m.get("id") == model and value == "loaded":
                    return True
            return False
        if engine == serving.DEFAULT:
            return get(base + mlx_server.LOADED_PATH).get("model") == model
        if engine in serving.VLLM_ENGINES:
            return any(m.get("id") == model
                       for m in get(base + "/v1/models").get("data") or [])
    except Exception:  # noqa: BLE001
        return None
    return False


def _gate(where: serving.Route) -> bool | None:
    """Refuse a call that would load a model while another job holds the machine lock; its residency, None unasked."""
    try:
        base, _ = upstream(where)
    except Exception:  # noqa: BLE001
        base = ""
    # This machine's lock and pressure say nothing about a server on another host.
    if base and not serving.loopback(base):
        return None
    held = busy()
    if not held:
        return None
    job = running_job()
    holder = f"{held} under {job}" if job else held
    resident = loaded(where)
    level = None
    if resident:
        from harness import pressure
        level = pressure.sample().level
    ok, why = admit(holder, resident, level)
    if not ok:
        raise Refused(why)
    return resident


def _timeout(max_tokens: int, resident: bool | None) -> float:
    """Long enough for the reply budget at the slowest decode, plus a load when the model may not be held. #694."""
    load = 0.0 if resident else completion.LOAD_TIMEOUT_S
    return max(TIMEOUT_S, completion.timeout_for(int(max_tokens or 0))) + load


def _allowance(where: serving.Route, max_tokens: int, timeout: float | None) -> float:
    """Gate the call, then `timeout` or one sized by the model's residency, asked even when no lock is held."""
    resident = _gate(where)
    return timeout or _timeout(max_tokens, loaded(where) if resident is None else resident)


def _timing(got: completion.Completion, started: float, replies=()) -> dict:
    """Timing of `got`; token counts summed over every reply a method made."""
    replies = list(replies) or [got]

    def total(key):
        counts = [(r.usage or {}).get(key) for r in replies]
        return sum(counts) if all(c is not None for c in counts) else counts[-1]
    return {"ttft_s": (replies[0].timing or {}).get("ttft_s"),
            "seconds": round(time.perf_counter() - started, 4),
            "prompt_tokens": total("prompt_tokens"),
            "completion_tokens": total("completion_tokens")}


@contextlib.contextmanager
def as_work(lane: str, spec: str, where: serving.Route, stream: bool, delegation: bool = False,
            tag: str = purpose.WORK):
    """Send the block's requests tagged `tag`; one that skips the gateway is logged as the gateway would. #825.

    `delegation` also records the result as a delegations row sharing the request row's call_id. #829.
    """
    direct = not completion.is_gateway(where.base)
    from harness import usage
    got: dict = {}
    at = time.time()
    with purpose.using(tag):
        try:
            yield got
        except Exception as exc:
            if direct:
                usage.record(usage.direct_row(lane, spec, where.model, at, error=exc, stream=stream, tag=tag))
            raise
    from harness import delegations
    # One id for the delegation and its request row: LiteLLM's via the gateway, ours when direct. #829.
    call_id = got.get("call_id") or (delegations.new_id() if delegation else "")
    if direct:
        usage.record({**usage.direct_row(lane, spec, got.get("model") or where.model, at, got,
                                         stream=stream, tag=tag), "call_id": call_id})
    if delegation:
        got.update(delegations.note(got, call_id, gateway=bool(got.get("call_id"))))


def _tag(delegated: bool) -> str:
    return purpose.WORK if delegated else purpose.INTERNAL


def complete(lane: str, prompt: str, system: str | None = None,
             max_tokens: int = 2048, temperature: float | None = None,
             timeout: float | None = None, thinking: bool | None = None, delegated: bool = False,
             model: str | None = None) -> dict:
    """The lane's adopted model or method, timed; `method` is a method's cost. Raises Refused or CompletionError.

    `thinking` None serves the lane as it was measured; False sends enable_thinking false.
    Only `delegated` (an agent's local_complete) is work with a delegations row; a program's call is internal. #1158.
    """
    lane = check_lane(lane)
    if not (prompt or "").strip():
        raise Refused("empty prompt")
    _preflight(prompt, system or "", max_tokens=max_tokens)
    spec, where = route(lane, model)
    from harness import methods
    base = methods.base_of(spec) or spec
    _budget(base, max_tokens, prompt, system or completion.SYSTEM.get(lane, ""))
    timeout = _allowance(where, max_tokens, timeout)
    started = time.perf_counter()
    made = []

    def call(text, modality="", **kw):
        made.append(modality)
        mine = system if modality else None
        label = _call_label(spec, len(made), modality)
        try:
            # Each call of a method gets the whole cap and the thinking switch. #581.
            if label:
                _budget(base, max_tokens, text, mine or completion.SYSTEM.get(modality, ""))
            if modality == "claims":
                from harness.checks import claims
                try:
                    kw = {**kw, "response_format": claims.response_format(claims.served_schema())}
                except claims.NoSchema as exc:
                    raise Refused(str(exc)) from exc
            return completion.complete_full(
                text, modality=modality, timeout=timeout,
                temperature=temperature, max_tokens=int(max_tokens), stream=True,
                system=mine, template=template(modality, thinking), **kw)
        except Refused as exc:
            raise Refused(f"{label}: {exc}") from exc
        except completion.CompletionError as exc:
            if exc.failure_class != reasons.TOKEN_BUDGET_EXHAUSTED:
                raise
            hint = "" if thinking is False else " Or pass thinking=false to answer without reasoning."
            raise completion.CompletionError(
                f"{label + ': ' if label else ''}{exc}{hint}",
                exc.failure_class, exc.limit) from exc
    with as_work(lane, spec, where, stream=True, delegation=delegated, tag=_tag(delegated)) as out:
        text, cost, replies = generate(spec, where, lane, prompt, call)
        got = replies[-1]
        out.update({"text": text, "lane": lane, "spec": spec,
                    "model": _answered_by(got.model or where.model), "method": cost or None,
                    "call_id": got.call_id, **_timing(got, started, replies)})
    return out


def _answered_by(model: str) -> str:
    """The real id behind a model name a server echoed; the name when nothing resolves it. #670."""
    from harness import models
    return models.resolve(model) or model


def check_schema(schema) -> dict:
    """The flat decide schema, validated as `soh decide` validates it."""
    from harness.checks import decide as decide_check
    if not isinstance(schema, dict) or not schema:
        raise ValueError("the schema must map field names to fields")
    for name, spec in schema.items():
        if not isinstance(spec, dict):
            raise ValueError(f"field {name!r} must be an object")
        decide_check.choices(spec)
        if not str(spec.get("description") or "").strip():
            raise ValueError(f"field {name!r} needs a description")
    return schema


def ask(question: str, schema: dict, where: serving.Route, context: str = "",
        timeout: float | None = None, stream: bool = False):
    """(answers/probabilities body, Completion): the core of `soh decide`. #423."""
    from harness.checks import decide as decide_check
    prompt = f"{question.rstrip()}\n\n{decide_check.render(schema)}"
    got = completion.complete_full(
        prompt, model=where.model, gateway=where.base, modality="decide",
        context=context, timeout=timeout or completion.TIMEOUT_S,
        sampling=where.sampling or None, top_logprobs=completion.TOP_LOGPROBS,
        stream=stream, response_format=decide_check.response_format(schema))
    parsed = decide_check.parse(
        decide_check.from_logprobs(got.text, got.tokens, schema), schema)
    missing = [n for n, f in parsed.items() if f["answer"] is None]
    if missing:
        raise ValueError(f"no usable answer for {', '.join(missing)}: "
                         f"{got.text.strip()[:200]}")
    body = {"answers": {n: f["answer"] for n, f in parsed.items()},
            "probabilities": {n: f["probs"] or {f["answer"]: 1.0}
                              for n, f in parsed.items()}}
    return body, got


def decide(question: str, schema: dict, context: str = "",
           timeout: float | None = None, delegated: bool = False) -> dict:
    """`soh decide` on the decide lane's adopted model, timed; `delegated` as in complete()."""
    if not (question or "").strip():
        raise Refused("empty question")
    check_schema(schema)
    _preflight(question, context, str(schema))
    spec, where = route("decide")
    timeout = _allowance(where, 0, timeout)
    started = time.perf_counter()
    # Whole, not streamed: the gateway drops logprobs from a stream, and they are the answer.
    with as_work("decide", spec, where, stream=False, delegation=delegated, tag=_tag(delegated)) as out:
        body, got = ask(question, schema, where, context=context, timeout=timeout)
        out.update({**body, "lane": "decide", "spec": spec,
                    "model": got.model or where.model, "call_id": got.call_id,
                    **_timing(got, started)})
    return out
