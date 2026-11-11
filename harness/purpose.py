"""Why a request was sent, carried to the gateway as a LiteLLM request tag. #825."""
from __future__ import annotations

import contextlib
import contextvars
import os

WORK, EVAL, SMOKE, DISCOVER, WATCHDOG = "work", "eval", "smoke", "discover", "watchdog"
#: A program's own pipeline call (morning, otel, claude-news, label), not work an agent delegated. #1158.
INTERNAL = "internal"
PURPOSES = (WORK, EVAL, SMOKE, DISCOVER, WATCHDOG, INTERNAL)
#: A process measuring a lane: a program call inside it is that measurement, not internal work. #1701
MEASURING = (EVAL, SMOKE)
UNKNOWN = "unknown"
#: The purpose a process and its children send when nothing in the process sets one.
ENV = "SOHOT_PURPOSE"
HEADER = "x-litellm-tags"
TAG_PREFIX = "purpose:"
JOB_PREFIX = "job:"
#: The delegation a request was made for, so the gateway's row carries its call_id. #1721.
DELEGATION_PREFIX = "delegation:"
#: workqueue.JOB_ENV, named here so purpose stays free of the queue's imports.
JOB_ENV = "LH_JOB_ID"

_CURRENT: contextvars.ContextVar[str] = contextvars.ContextVar("sohot_purpose", default="")
_DELEGATION: contextvars.ContextVar[str] = contextvars.ContextVar("sohot_delegation", default="")


def _known(p) -> str:
    p = str(p or "").strip().lower()
    return p if p in PURPOSES else ""


def current(environ=None) -> str:
    return _known(_CURRENT.get()) or _known((os.environ if environ is None else environ).get(ENV))


def headers(environ=None) -> dict:
    """The request tags: purpose:<p>; job:<id> inside a queued job (#1214); delegation:<call_id> on a delegation's behalf."""
    p = current(environ)
    job = str((os.environ if environ is None else environ).get(JOB_ENV) or "").strip()
    d = _DELEGATION.get()
    tags = ([TAG_PREFIX + p] if p else []) + ([JOB_PREFIX + job] if job else []) + (
        [DELEGATION_PREFIX + d] if d else [])
    return {HEADER: ",".join(tags)} if tags else {}


@contextlib.contextmanager
def using(p: str):
    """Requests sent inside the block, in this thread or task, carry purpose `p`."""
    token = _CURRENT.set(_known(p))
    try:
        yield
    finally:
        _CURRENT.reset(token)


@contextlib.contextmanager
def delegating(call_id: str):
    """Requests sent inside the block are delegation `call_id`'s; an inner block without one keeps the outer's."""
    token = _DELEGATION.set(str(call_id or "") or _DELEGATION.get())
    try:
        yield
    finally:
        _DELEGATION.reset(token)


def delegation() -> str:
    return _DELEGATION.get()


def delegation_of(tags) -> str:
    """The delegation call_id a request's tags name, else ""."""
    for t in tags if isinstance(tags, (list, tuple)) else []:
        t = str(t).strip()
        if t.lower().startswith(DELEGATION_PREFIX):
            return t[len(DELEGATION_PREFIX):].strip()
    return ""


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
