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


def _refuse(detail: str):
    from fastapi import HTTPException
    raise HTTPException(status_code=503, detail=detail)


def batch_of(data: dict) -> str:
    """The x-sohot-batch a request names, or "". #769."""
    from harness import batch
    for where in ((data.get("proxy_server_request") or {}).get("headers"),
                  (data.get("metadata") or {}).get("headers")):
        for key, value in (where or {}).items():
            if str(key).lower() == batch.HEADER and str(value or "").strip():
                return str(value).strip()
    return ""


def _addressed_here(data: dict) -> bool:
    """Whether the request reached this gateway by a loopback name, so its client runs on this host. #1231."""
    import ipaddress
    from urllib.parse import urlsplit
    host = ""
    for key, value in ((data.get("proxy_server_request") or {}).get("headers") or {}).items():
        if str(key).lower() == "host":
            host = str(value or "").strip()
    try:
        name = urlsplit("//" + host).hostname or ""
    except ValueError:
        return False
    if name in LOOPBACK:
        return True
    try:
        return ipaddress.ip_address(name).is_loopback
    except ValueError:
        return False


def _claim(deployment: str, batch_id: str, local: bool = False) -> dict:
    from harness import batch
    from harness import memory_store as ms
    from harness import workqueue as wq
    conn = ms.connect()
    try:
        return batch.claim(conn, deployment, batch_id, who=batch.from_gateway(batch_id, local=local),
                           alive=wq.alive)
    finally:
        conn.close()


def _keep(deployment: str, batch_id: str) -> bool:
    from harness import batch
    from harness import memory_store as ms
    conn = ms.connect()
    try:
        return batch.keep(conn, deployment, batch_id)
    finally:
        conn.close()


#: litellm_call_id -> (deployment, batch, monotonic start) for a batch request in flight. #769.
_INFLIGHT: dict = {}
_RENEWER: dict = {}


def _longest_request_s() -> float:
    from harness import gateway_switch
    return gateway_switch.DRAIN_S


async def _renew_inflight() -> None:
    """Keep a batch's lease while one of its requests is still running, however long the reply takes."""
    from harness import batch
    while _INFLIGHT:
        await asyncio.sleep(batch.TTL_S / 3)
        now = time.monotonic()
        for call, (_, _, since) in list(_INFLIGHT.items()):
            if now - since > _longest_request_s():
                _INFLIGHT.pop(call, None)
        for deployment, batch_id in {(d, b) for d, b, _ in list(_INFLIGHT.values())}:
            try:
                await asyncio.to_thread(_keep, deployment, batch_id)
            except Exception as exc:  # noqa: BLE001 - the next pass tries again
                print(f"served_model: batch lease renew for {batch_id} failed: {exc}", file=sys.stderr)


def _track(call: str, deployment: str, batch_id: str) -> None:
    if not call:
        return
    _INFLIGHT[call] = (deployment, batch_id, time.monotonic())
    task = _RENEWER.get("task")
    if task is None or task.done():
        _RENEWER["task"] = asyncio.ensure_future(_renew_inflight())


async def _finished(call) -> None:
    """A batch request ended: its lease runs TTL_S from now."""
    got = _INFLIGHT.pop(str(call or ""), None)
    if got:
        try:
            # Renew only: the client may have let the lease go already, and an ended batch must not take it back. #1231.
            await asyncio.to_thread(_keep, got[0], got[1])
        except Exception as exc:  # noqa: BLE001 - the lease still expires on its own
            print(f"served_model: batch lease renew for {got[1]} failed: {exc}", file=sys.stderr)


async def hold_for_batch(data: dict) -> None:
    """Take or renew the serving deployment's batch lease for this request, or refuse it as busy. #769."""
    from harness import batch
    batch_id = batch_of(data)
    if not batch_id:
        return
    deployment = serving_machine(str(data.get("model") or ""))
    got = await asyncio.to_thread(_claim, deployment, batch_id, _addressed_here(data))
    if got:
        _refuse(f"{batch.BUSY} ({batch.describe(got)}); retry once it finishes (refused batch {batch_id})")
    _track(str(data.get("litellm_call_id") or ""), deployment, batch_id)


class ServedModel(CustomLogger):
    async def async_pre_call_hook(self, user_api_key_dict, cache, data, call_type):
        """A node that takes no connection in a few seconds is skipped for this machine's copy. #684."""
        from harness import gateway_switch
        if gateway_switch.draining():
            _refuse(f"{gateway_switch.DRAINING} for an alias switch; retry once it has restarted")
        model = str(data.get("model") or "")
        entry = _entry(model)
        if entry.get(nodes.NODE_KEY) and not await reachable(entry):
            if not _entry(model + nodes.LOCAL_SUFFIX):
                # Waiting out the connect timeout and retries ends in a bare 500. #823.
                _refuse(f"node {entry[nodes.NODE_KEY]} is down and {nodes.NO_LOCAL_COPY} {model}")
            data["model"] = model + nodes.LOCAL_SUFFIX
        await hold_for_batch(data)
        return data

    async def async_post_call_success_hook(self, data, user_api_key_dict, response):
        await _finished((data or {}).get("litellm_call_id"))
        return response

    async def async_post_call_failure_hook(self, request_data, original_exception, user_api_key_dict,
                                           traceback_str=None):
        await _finished((request_data or {}).get("litellm_call_id"))

    async def async_log_success_event(self, kwargs, response_obj, start_time, end_time):
        await _finished((kwargs or {}).get("litellm_call_id"))

    async def async_log_failure_event(self, kwargs, response_obj, start_time, end_time):
        await _finished((kwargs or {}).get("litellm_call_id"))

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
