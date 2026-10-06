"""Refuse a missing or wrong gateway key with 401 naming `soh gateway key`. #501.

Loaded by LiteLLM from `general_settings.custom_auth`, resolved beside the config.
"""
import secrets

from litellm.proxy._types import (LiteLLMRoutes, LitellmUserRoles, ProxyErrorTypes,
                                  ProxyException, UserAPIKeyAuth)
from litellm.proxy.auth.auth_utils import get_request_route

MESSAGE = ("gateway key missing or wrong: `soh gateway key` prints this machine's key; "
           "a client of another machine's gateway sets SOHOT_GATEWAY_KEY to that machine's")


def matches(given, master) -> bool:
    """Constant-time; no master key refuses everyone."""
    if not isinstance(given, str) or not isinstance(master, str) or not given or not master:
        return False
    return secrets.compare_digest(given.encode("utf-8"), master.encode("utf-8"))


async def user_api_key_auth(request, api_key):
    from litellm.proxy import proxy_server
    if get_request_route(request) in LiteLLMRoutes.public_routes.value:
        # What LiteLLM itself grants these routes; custom_auth runs before its own check.
        return UserAPIKeyAuth(user_role=LitellmUserRoles.INTERNAL_USER_VIEW_ONLY)
    if matches(api_key, proxy_server.master_key):
        # A string hands the key back to LiteLLM's own master-key check.
        return api_key
    raise ProxyException(message=MESSAGE, type=ProxyErrorTypes.auth_error,
                         param="api_key", code=401)
