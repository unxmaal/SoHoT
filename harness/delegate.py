"""A text subtask handed to a lane's adopted local model. #475.

The MCP server calls this in-process rather than shelling out to `soh`, because
the caller wants the first-token time and the model that answered, which the
CLI does not print. It stays the same product by sharing the route: the lane
commands resolve their model through route() here too.
"""
from __future__ import annotations

import os
import time

from harness import completion, exclusive, gateway, serving

#: Lanes a delegated completion may name: the ones the gateway aliases as sohot-<lane>.
LANES = gateway.TEXT_LANES
MAX_PROMPT_CHARS = 100_000
MAX_TOKENS = 8192
TIMEOUT_S = 300.0


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
    held = busy()
    if held:
        raise Refused(f"this machine is busy with {held}; delegation does not wait "
                      f"behind a batch run or a generation, retry when it finishes")


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
    started = time.perf_counter()
    # Whole, not streamed: the gateway drops logprobs from a stream, and they are the answer.
    body, got = ask(question, schema, where, context=context,
                    timeout=timeout or TIMEOUT_S)
    return {**body, "lane": "decide", "spec": spec,
            "model": got.model or where.model, **_timing(got, started)}
