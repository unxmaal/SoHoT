"""A text subtask handed to a lane's adopted local model. #475.

The MCP server calls this in-process rather than shelling out to `soh`, because
the caller wants the first-token time and the model that answered, which the
CLI does not print. It stays the same product by sharing the route: the lane
commands resolve their model through route() here too.
"""
from __future__ import annotations

import json
import os
import statistics
import time
import urllib.request

from harness import completion, exclusive, gateway, serving

#: Lanes a delegated completion may name: the ones the gateway aliases as sohot-<lane>.
LANES = gateway.TEXT_LANES
MAX_PROMPT_CHARS = 100_000
MAX_TOKENS = 8192
TIMEOUT_S = 300.0
#: Seconds to ask a server what it holds; an answer that late counts as not resident.
RESIDENCY_TIMEOUT_S = 2.0


class Refused(ValueError):
    """A request this module will not send, said before anything is loaded."""


def lane_model(lane: str, chosen: str | None = None) -> str:
    """-m when given, else the lane's adopted model here, else its typed constant. #297."""
    from harness import adopt, winners
    return chosen or adopt.default_for(lane, winners.typed().get(lane, ""))


def route(lane: str, chosen: str | None = None, via: str = "") -> tuple[str, serving.Route]:
    """(spec, Route) for a text lane, as every lane command resolves it."""
    spec = lane_model(lane, chosen)
    return spec, serving.route(spec, via)


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
    if not 1 <= int(max_tokens) <= MAX_TOKENS:
        raise Refused(f"max_tokens must be 1..{MAX_TOKENS}, not {max_tokens}")


def admit(holder: str, resident: bool, level: int | None) -> tuple[bool, str]:
    """(ok, why): may a delegated call go now? Only a model load needs the lock. #588."""
    from harness.pressure import NORMAL
    if not holder:
        return True, ""
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
    if left <= 0:
        return f"{head}, past the {typical:.0f} min earlier runs of it took"
    return f"{head}, about {left:.0f} min left by earlier runs of it"


def _get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=RESIDENCY_TIMEOUT_S) as r:
        return json.loads(r.read() or b"{}")


def upstream(where: serving.Route, config=None) -> tuple[str, str]:
    """(server base, model name) that answers `where`, a gateway alias resolved; ("", "") if unknown."""
    from harness.completion import DEFAULT_GATEWAY
    base = where.base.rstrip("/").removesuffix("/v1")
    if base != DEFAULT_GATEWAY:
        return base, where.model
    for entry in gateway.load(config).get("model_list") or []:
        if str(entry.get("model_name", "")).strip().lower() == where.model.lower():
            params = entry.get("litellm_params") or {}
            return (str(params.get("api_base", "")).rstrip("/").removesuffix("/v1"),
                    gateway.strip_provider(str(params.get("model", ""))))
    return "", ""


def loaded(where: serving.Route, get=None, config=None) -> bool:
    """True only when the server behind `where` holds its model now; unknown is False."""
    from harness import mlx_server, router
    get = get or _get_json
    base, model = upstream(where, config)
    if not model:
        return False
    try:
        if base in (serving.LLAMACPP_URL, router.url()):
            for m in get(base + "/models").get("data") or []:
                status = m.get("status")
                value = status.get("value") if isinstance(status, dict) else status
                if m.get("id") == model and value == "loaded":
                    return True
            return False
        if base == serving.MLX_URL:
            return get(base + mlx_server.LOADED_PATH).get("model") == model
        if base == serving.vllm_url():
            return any(m.get("id") == model
                       for m in get(base + "/v1/models").get("data") or [])
    except Exception:  # noqa: BLE001
        return False
    return False


def _gate(where: serving.Route) -> None:
    """Refuse a call that would load a model while another job holds the machine lock."""
    held = busy()
    if not held:
        return
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


def _timing(got: completion.Completion, started: float) -> dict:
    usage = got.usage or {}
    return {"ttft_s": (got.timing or {}).get("ttft_s"),
            "seconds": round(time.perf_counter() - started, 4),
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens")}


def complete(lane: str, prompt: str, system: str | None = None,
             max_tokens: int = 2048, temperature: float | None = None,
             timeout: float | None = None) -> dict:
    """One completion on the lane's adopted model, timed. Raises Refused or CompletionError."""
    lane = check_lane(lane)
    if not (prompt or "").strip():
        raise Refused("empty prompt")
    _preflight(prompt, system or "", max_tokens=max_tokens)
    spec, where = route(lane)
    _gate(where)
    started = time.perf_counter()
    got = completion.complete_full(
        prompt, model=where.model, gateway=where.base, modality=lane,
        timeout=timeout or TIMEOUT_S, temperature=temperature,
        max_tokens=int(max_tokens), sampling=where.sampling or None,
        stream=True, system=system)
    return {"text": got.text, "lane": lane, "spec": spec,
            "model": got.model or where.model, **_timing(got, started)}


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
           timeout: float | None = None) -> dict:
    """`soh decide` on the decide lane's adopted model, timed."""
    if not (question or "").strip():
        raise Refused("empty question")
    check_schema(schema)
    _preflight(question, context, str(schema))
    spec, where = route("decide")
    _gate(where)
    started = time.perf_counter()
    # Whole, not streamed: the gateway drops logprobs from a stream, and they are the answer.
    body, got = ask(question, schema, where, context=context,
                    timeout=timeout or TIMEOUT_S)
    return {**body, "lane": "decide", "spec": spec,
            "model": got.model or where.model, **_timing(got, started)}
