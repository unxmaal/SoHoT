"""Record what a metered alias spends and refuse it past api_budget. See README, #1214.

Loaded by LiteLLM from the gateway config (`litellm_settings.callbacks`).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from harness import api_spend  # noqa: E402

try:
    from litellm.integrations.custom_logger import CustomLogger
except ImportError:  # the test suite has no litellm
    CustomLogger = object


class SpendGuard(CustomLogger):
    async def async_pre_call_hook(self, user_api_key_dict, cache, data, call_type):
        why = api_spend.gate(str(data.get("model") or ""))
        if why:
            from fastapi import HTTPException
            raise HTTPException(status_code=api_spend.REFUSED_STATUS, detail=why)
        return data

    async def async_log_success_event(self, kwargs, response_obj, start_time, end_time):
        api_spend.note(kwargs, response_obj)


proxy_handler_instance = SpendGuard()
