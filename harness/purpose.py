"""Why a request was sent, carried to the gateway as a LiteLLM request tag. #825."""
from __future__ import annotations

import contextlib
import contextvars
import os

WORK, EVAL, SMOKE, DISCOVER, WATCHDOG = "work", "eval", "smoke", "discover", "watchdog"
#: A program's own pipeline call (morning, otel, claude-news, label), not work an agent delegated. #1158.
INTERNAL = "internal"
PURPOSES = (WORK, EVAL, SMOKE, DISCOVER, WATCHDOG, INTERNAL)
UNKNOWN = "unknown"
#: The purpose a process and its children send when nothing in the process sets one.
ENV = "SOHOT_PURPOSE"
HEADER = "x-litellm-tags"
TAG_PREFIX = "purpose:"

_CURRENT: contextvars.ContextVar[str] = contextvars.ContextVar("sohot_purpose", default="")


def _known(p) -> str:
    p = str(p or "").strip().lower()
    return p if p in PURPOSES else ""


def current(environ=None) -> str:
    return _known(_CURRENT.get()) or _known((os.environ if environ is None else environ).get(ENV))


def headers(environ=None) -> dict:
    p = current(environ)
    return {HEADER: TAG_PREFIX + p} if p else {}


@contextlib.contextmanager
def using(p: str):
    """Requests sent inside the block, in this thread or task, carry purpose `p`."""
    token = _CURRENT.set(_known(p))
    try:
        yield
    finally:
        _CURRENT.reset(token)


def set_process(p: str) -> None:
    """This process and its children send purpose `p`."""
    os.environ[ENV] = _known(p)


def of_tags(tags) -> str:
    """The purpose a request's tags name, else UNKNOWN."""
    for t in tags if isinstance(tags, (list, tuple)) else []:
        t = str(t).strip()
        if t.lower().startswith(TAG_PREFIX):
            return _known(t[len(TAG_PREFIX):]) or UNKNOWN
    return UNKNOWN
