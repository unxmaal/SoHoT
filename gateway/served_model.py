"""Name the model that answered in the gateway's reply headers, not the alias asked for. See README, #670.

Loaded by LiteLLM from the gateway config (`litellm_settings.callbacks`). Headers, because
LiteLLM 1.100.0 restamps the body's `model` to the requested name after every hook.
"""
import asyncio
import sys
import time
from functools import lru_cache
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from harness import models, nodes, serving  # noqa: E402
from harness.machine import LOOPBACK  # noqa: E402

try:
    from litellm.integrations.custom_logger import CustomLogger
except ImportError:  # the test suite has no litellm
    CustomLogger = object


def resolved(data: dict) -> tuple[str, str]:
    """(the real id, the alias asked for or "") for a request; ("", "") when nothing serves it."""
    model = str(data.get("model") or "")
    try:
        # GATEWAY_CONFIG names the config this gateway serves; its served copy wins.
        real = models.resolve(model)
    except Exception:  # noqa: BLE001
        return "", ""
    return real, (model if real and real != model else "")


@lru_cache(maxsize=1)
def this_machine() -> str:
    """This gateway host's machines fingerprint, "" when it cannot be told. #697."""
    try:
        from evals import environment
        return environment.identity()["fingerprint"]
    except Exception:  # noqa: BLE001
        return ""


def _entry(model: str) -> dict:
    try:
        return models._entry(models._name(model)) or {}
    except Exception:  # noqa: BLE001
        return {}


def upstream_host(model: str) -> str:
    """host:port of an entry's api_base when it is another host, else "". #697."""
    from urllib.parse import urlsplit
    base = str((_entry(model).get("litellm_params") or {}).get("api_base") or "")
    where = urlsplit(base)
    return "" if not where.hostname or where.hostname in LOOPBACK else where.netloc


def serving_machine(model: str) -> str:
    """Who answers: this host's fingerprint, a node's identity, or upstream:<host> for another host."""
    entry = _entry(model)
    if entry.get(nodes.NODE_KEY):
        return str(entry.get(nodes.MACHINE_KEY) or f"node:{entry[nodes.NODE_KEY]}")
    away = upstream_host(model)
    return f"upstream:{away}" if away else this_machine()


SHAPE_TTL_S = 30.0
#: How long a reply waits for a shape probe before it goes without ctx/slots headers. #722.
SHAPE_WAIT_S = 0.5
_SHAPES: dict = {}
_PROBING: dict = {}


def served_shape(model: str) -> dict:
    """{"ctx", "slots"} this gateway serves a model with, as far as it can tell; cached briefly. #697.

    Blocking: it asks the upstream over urllib. The gateway calls shape() instead. #722.
    """
    now = time.monotonic()
    hit = _SHAPES.get(model)
    if hit and now - hit[0] < SHAPE_TTL_S:
        return hit[1]
    from harness import context
    got = {}
    for key, probe in (("ctx", context.served_ctx), ("slots", context.served_slots)):
        try:
            got[key] = probe(model)
        except Exception:  # noqa: BLE001 - a reply header must not fail a reply
            got[key] = None
    got = {k: v for k, v in got.items() if v}
    _SHAPES[model] = (time.monotonic(), got)
    return got


async def shape(model: str) -> dict:
    """served_shape off the event loop, one probe per model at a time, waited on at most SHAPE_WAIT_S."""
    hit = _SHAPES.get(model)
    if hit and time.monotonic() - hit[0] < SHAPE_TTL_S:
        return hit[1]
    task = _PROBING.get(model)
    if task is None or task.done():
        task = asyncio.ensure_future(asyncio.to_thread(served_shape, model))
        _PROBING[model] = task
    try:
        return await asyncio.wait_for(asyncio.shield(task), SHAPE_WAIT_S)
    except Exception:  # noqa: BLE001 - slow or failed: this reply goes without, the next gets it
        return hit[1] if hit else {}


UP_TTL_S = 10.0
#: node name -> (monotonic time, reachable).
_REACH: dict = {}
_REACHING: dict = {}


async def _connects(base: str, timeout: float, ipv4: bool = True) -> bool:
    import socket
    from urllib.parse import urlsplit
    where = urlsplit(base)
    how = {"family": socket.AF_INET} if ipv4 else {"happy_eyeballs_delay": 0.25}
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(
            where.hostname, where.port or (443 if where.scheme == "https" else 80), **how), timeout)
    except Exception:  # noqa: BLE001 - refused, unresolvable or silent: not reachable
        return False
    writer.close()
    return True


async def reachable(entry: dict) -> bool:
    """Whether a node entry's server takes a connection within its connect timeout; cached."""
    name = str(entry[nodes.NODE_KEY])
    seen = _REACH.get(name)
    now = time.monotonic()
    if seen and now - seen[0] < (UP_TTL_S if seen[1] else _cooldown(entry)):
        return seen[1]
    task = _REACHING.get(name)
    if task is None or task.done():
        base = str((entry.get("litellm_params") or {}).get("api_base") or "")
        task = asyncio.ensure_future(_connects(
            base, float(entry.get(nodes.CONNECT_KEY) or nodes.CONNECT_TIMEOUT_S),
            bool(entry.get(nodes.IPV4_KEY, True))))
        _REACHING[name] = task
    ok = await asyncio.shield(task)
    _REACH[name] = (time.monotonic(), ok)
    return ok


def _cooldown(entry: dict) -> float:
    return float((entry.get("model_info") or {}).get("cooldown_time") or nodes.COOLDOWN_S)


def _answered(response, entry: dict) -> str:
    """The api_base of the deployment that answered: LiteLLM's record, else the entry's own."""
    hidden = getattr(response, "_hidden_params", None) or {}
    return str(hidden.get("api_base") or (entry.get("litellm_params") or {}).get("api_base") or "")


class ServedModel(CustomLogger):
    async def async_pre_call_hook(self, user_api_key_dict, cache, data, call_type):
        """A node that takes no connection in a few seconds is skipped for this machine's copy. #684."""
        model = str(data.get("model") or "")
        entry = _entry(model)
        if entry.get(nodes.NODE_KEY) and _entry(model + nodes.LOCAL_SUFFIX) \
                and not await reachable(entry):
            data["model"] = model + nodes.LOCAL_SUFFIX
        return data

    async def async_post_call_response_headers_hook(self, data, user_api_key_dict, response,
                                                    request_headers=None, litellm_call_info=None):
        sent = str(data.get("model") or "")
        asked = sent.removesuffix(nodes.LOCAL_SUFFIX)
        routed = _entry(asked)
        node = routed.get(nodes.NODE_KEY) and serving.bare(_answered(response, _entry(sent))) \
            == serving.bare(str((routed.get("litellm_params") or {}).get("api_base") or ""))
        local = asked + nodes.LOCAL_SUFFIX
        answered = asked if node or not _entry(local) else local
        real = resolved({"model": answered})[0]
        alias = asked if real and asked != real else ""
        headers = {}
        who = serving_machine(answered)
        if who:
            headers["x-sohot-machine"] = who
        if real:
            headers["x-sohot-model"] = real
            for key, value in (await shape(answered)).items():
                headers[f"x-sohot-{key}"] = str(value)
        if node:
            headers["x-sohot-node"] = str(routed[nodes.NODE_KEY])
            headers["x-sohot-served-as"] = f"{alias or asked}@{routed[nodes.NODE_KEY]}"
        elif alias:
            headers["x-sohot-served-as"] = alias
        if routed.get(nodes.NODE_KEY) and not node:
            headers["x-sohot-fallback"] = str(routed[nodes.NODE_KEY])
            # A node that failed one name is skipped for every name it holds until its cooldown ends.
            _REACH[str(routed[nodes.NODE_KEY])] = (time.monotonic(), False)
        return headers or None


proxy_handler_instance = ServedModel()
