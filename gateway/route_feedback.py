"""Feed an adaptive routing arm our verdicts on the calls it routed: lane-checker pass/fail and delegation outcomes. #1338.

Loaded by LiteLLM from the gateway config (`litellm_settings.callbacks`). LiteLLM 1.100.0 has no feedback API, so verdicts
go straight into the arm's in-process bandit cells.
"""
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from harness import routes  # noqa: E402

try:
    from litellm.integrations.custom_logger import CustomLogger
except ImportError:  # the test suite has no litellm
    CustomLogger = object

FEED = routes.Feed()
_POLLED = {"at": 0.0}


def adaptive(router: str):
    """The AdaptiveRouter LiteLLM built for an arm alias, or None."""
    try:
        from litellm.proxy import proxy_server
        for tagged in (getattr(proxy_server.llm_router, "adaptive_routers", None) or {}).get(router, []):
            return tagged.strategy
    except Exception:  # noqa: BLE001 - no router built yet is no arm
        return None
    return None


def request_type(messages) -> str:
    """The adaptive classifier's request type for the newest ask, as the router computed it."""
    try:
        from litellm.router_strategy.adaptive_router.classifier import classify_prompt
        try:
            from litellm.router_strategy.complexity_router.complexity_router import (
                _extract_current_ask_and_system_prompt as ask)
            text = ask(list(messages or []))[0]
        except ImportError:
            from litellm.litellm_core_utils.prompt_templates.common_utils import get_last_user_message as last
            text = last(list(messages or []))
        return classify_prompt(text or "").value
    except Exception:  # noqa: BLE001
        return "general"


def apply(call_id: str, got: str) -> bool:
    """Add one verdict to the routed model's cell; False when the call or its arm is unknown."""
    held = FEED.take(call_id)
    if held is None:
        return False
    router, kind, model = held
    arm = adaptive(router)
    if arm is None:
        return False
    try:
        from litellm.router_strategy.adaptive_router.bandit import apply_delta
        from litellm.types.router import RequestType
        try:
            key = (RequestType(kind), model)
        except ValueError:
            key = (RequestType.GENERAL, model)
        cell = arm._cells.get(key)
        if cell is None:
            return False
        arm._cells[key] = apply_delta(cell, *routes.delta(got))
    except Exception:  # noqa: BLE001 - a verdict must never fail a request
        return False
    FEED.applied += 1
    return True


def remember(kwargs) -> None:
    kwargs = kwargs if isinstance(kwargs, dict) else {}
    slo = kwargs.get("standard_logging_object") or {}
    router = str(slo.get("model_group") or "")
    if adaptive(router) is None:
        return
    md = (kwargs.get("litellm_params") or {}).get("metadata") or {}
    decision = md.get("routing_decision") or {}
    model = md.get("adaptive_router_chosen_model") or (decision.get("routed_model") if isinstance(decision, dict) else "")
    kind = (md.get("adaptive_router_decision") or {}).get("request_type") or request_type(kwargs.get("messages"))
    FEED.remember(str(kwargs.get("litellm_call_id") or ""), router, kind, str(model or ""))


def sent(data: dict) -> list[tuple[str, str]]:
    for where in ((data.get("proxy_server_request") or {}).get("headers"),
                  (data.get("metadata") or {}).get("headers")):
        for key, value in (where or {}).items():
            if str(key).lower() == routes.HEADER:
                return routes.parse(value)
    return []


def _closed(ids: list[str]) -> list[tuple[str, str]]:
    from harness import memory_store as ms
    conn = ms.connect()
    try:
        return routes.closed(conn, ids)
    finally:
        conn.close()


async def poll(now: float | None = None) -> int:
    """Apply closed delegation outcomes for the calls still waiting, at most every DELEGATION_POLL_S."""
    now = time.monotonic() if now is None else now
    if not FEED.calls or now < _POLLED["at"]:
        return 0
    _POLLED["at"] = now + routes.DELEGATION_POLL_S
    try:
        got = await asyncio.to_thread(_closed, FEED.waiting())
    except Exception as exc:  # noqa: BLE001 - the next poll tries again
        print(f"route_feedback: delegation outcomes unread: {exc}", file=sys.stderr)
        return 0
    return sum(apply(call_id, v) for call_id, v in got)


class RouteFeedback(CustomLogger):
    async def async_pre_call_hook(self, user_api_key_dict, cache, data, call_type):
        for call_id, got in sent(data or {}):
            apply(call_id, got)
        await poll()
        return data

    async def async_log_success_event(self, kwargs, response_obj, start_time, end_time):
        try:
            remember(kwargs)
        except Exception as exc:  # noqa: BLE001 - a lost call only costs its verdict
            print(f"route_feedback: call not kept for a verdict: {exc}", file=sys.stderr)


proxy_handler_instance = RouteFeedback()
