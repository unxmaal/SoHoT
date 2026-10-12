"""GET JSON from an upstream that may ask us to wait (HTTP 429). #630."""
from __future__ import annotations

import time
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

ATTEMPTS = 5
MAX_WAIT_S = 60.0
sleep = time.sleep


class RateLimited(Exception):
    """The upstream still answered 429 after every attempt."""


def wait_s(retry_after, attempt: int, base: float = 1.0) -> float:
    """Seconds before the next attempt: Retry-After (seconds or HTTP-date) when sent, else base doubling, capped. #704."""
    try:
        wait = float(retry_after)
    except (ValueError, TypeError):
        wait = _until_date(retry_after)
        if wait is None:
            wait = base * 2 ** attempt
    return min(max(wait, 0.0), MAX_WAIT_S)


def _until_date(retry_after) -> float | None:
    try:
        when = parsedate_to_datetime(str(retry_after))
    except (TypeError, ValueError, IndexError):
        return None
    return None if when is None or when.tzinfo is None else when.timestamp() - time.time()


def hf_headers(url: str) -> dict:
    """The HF token as a bearer header for a huggingface.co URL, {} without one; anonymous calls 429 far sooner. #797."""
    host = urlparse(url).hostname or ""
    if host != "huggingface.co" and not host.endswith(".huggingface.co"):
        return {}
    try:
        from huggingface_hub import get_token
        token = get_token()   # the token snapshot_download uses: HF_TOKEN or `hf auth login`
    except Exception:  # noqa: BLE001 - no hub, no token
        token = None
    return {"Authorization": f"Bearer {token}"} if token else {}


class Pace:
    """One batch's shared view of an upstream's rate limit: once 429'd, every later call waits. #797."""

    def __init__(self):
        self.active = False
        self.reset()

    def reset(self) -> None:
        self.gap = 0.0
        self.not_before = 0.0
        self.stopped = ""

    def start(self) -> None:
        self.reset()
        self.active = True

    def end(self) -> None:
        self.active = False
        self.reset()

    def before(self) -> None:
        if not self.active:
            return
        wait = max(self.gap, self.not_before - time.time())
        if wait > 0:
            sleep(min(wait, MAX_WAIT_S))

    def limited(self, retry_after) -> None:
        if not self.active:
            return
        self.gap = min(max(self.gap * 2, 1.0), MAX_WAIT_S)
        told = wait_s(retry_after, 0, 0.0)
        self.not_before = max(self.not_before, time.time() + told)

    def stop(self, why: str) -> None:
        if self.active:
            self.stopped = why


def _wait(response, attempt: int) -> float:
    return wait_s(response.headers.get("retry-after"), attempt)


def get_json(url: str, params: dict | None = None, timeout: float = 60):
    """GET `url` as JSON, waiting and retrying while it answers 429 or 5xx."""
    import httpx
    for attempt in range(ATTEMPTS):
        r = httpx.get(url, params=params, timeout=timeout, follow_redirects=True,
                      headers=hf_headers(url))
        if r.status_code != 429 and r.status_code < 500:
            r.raise_for_status()
            return r.json()
        if attempt < ATTEMPTS - 1:
            sleep(_wait(r, attempt))
    if r.status_code == 429:
        raise RateLimited(f"{url}: HTTP 429 after {ATTEMPTS} attempts")
    r.raise_for_status()
    raise AssertionError("unreachable: a 5xx always raises")
