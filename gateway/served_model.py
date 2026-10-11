"""Name the model that answered in the gateway's reply headers, not the alias asked for. See README, #670.

Loaded by LiteLLM from the gateway config (`litellm_settings.callbacks`). Headers, because
LiteLLM 1.100.0 restamps the body's `model` to the requested name after every hook.
"""
import sys
from functools import lru_cache
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from harness import models  # noqa: E402

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


LOOPBACK = ("127.0.0.1", "localhost", "::1", "0.0.0.0")


@lru_cache(maxsize=1)
def this_machine() -> str:
    """This gateway host's machines fingerprint, "" when it cannot be told. #697."""
    try:
        from evals import environment
        return environment.identity()["fingerprint"]
    except Exception:  # noqa: BLE001
        return ""


def upstream_host(model: str) -> str:
    """host:port of an entry's api_base when it is another host, else "". #697."""
    from urllib.parse import urlsplit
    try:
        entry = models._entry(models._name(model))
    except Exception:  # noqa: BLE001
        return ""
    base = str(((entry or {}).get("litellm_params") or {}).get("api_base") or "")
    where = urlsplit(base)
    return "" if not where.hostname or where.hostname in LOOPBACK else where.netloc


def serving_machine(model: str) -> str:
    """Who answers: this host's fingerprint, or upstream:<host> when an entry points elsewhere."""
    away = upstream_host(model)
    return f"upstream:{away}" if away else this_machine()


class ServedModel(CustomLogger):
    async def async_post_call_response_headers_hook(self, data, user_api_key_dict, response,
                                                    request_headers=None, litellm_call_info=None):
        real, alias = resolved(data)
        if not real:
            return None
        headers = {"x-sohot-model": real}
        who = serving_machine(str(data.get("model") or ""))
        if who:
            headers["x-sohot-machine"] = who
        if alias:
            headers["x-sohot-served-as"] = alias
        return headers


proxy_handler_instance = ServedModel()
