"""Record each request's shape, never its text unless asked, to the store. See README, #481.

Loaded by LiteLLM from the gateway config (`litellm_settings.callbacks`). The
hooks only enqueue; harness.usage.Writer writes from its own thread.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from harness import usage  # noqa: E402

try:
    from litellm.integrations.custom_logger import CustomLogger
except ImportError:  # the test suite has no litellm
    CustomLogger = object


class UsageLog(CustomLogger):
    def __init__(self, writer=None):
        super().__init__()
        self._writer = writer

    def _put(self, kwargs, response_obj) -> None:
        try:
            if self._writer is None:
                self._writer = usage.Writer().start()
            self._writer.put(usage.row(kwargs, response_obj),
                             usage.sample(kwargs, response_obj))
        except Exception:  # noqa: BLE001
            pass

    async def async_log_success_event(self, kwargs, response_obj, start_time, end_time):
        self._put(kwargs, response_obj)

    async def async_log_failure_event(self, kwargs, response_obj, start_time, end_time):
        self._put(kwargs, response_obj)


proxy_handler_instance = UsageLog()
