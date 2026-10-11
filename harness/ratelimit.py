"""GET JSON from an upstream that may ask us to wait (HTTP 429). #630."""
from __future__ import annotations

import time

ATTEMPTS = 5
MAX_WAIT_S = 60.0
sleep = time.sleep


class RateLimited(Exception):
    """The upstream still answered 429 after every attempt."""


def wait_s(retry_after, attempt: int, base: float = 1.0) -> float:
    """Seconds before the next attempt: Retry-After when the upstream sent one, else base doubling, capped. #704."""
    try:
        wait = float(retry_after)
    except (ValueError, TypeError):
        wait = base * 2 ** attempt
    return min(max(wait, 0.0), MAX_WAIT_S)


def _wait(response, attempt: int) -> float:
    return wait_s(response.headers.get("retry-after"), attempt)


def get_json(url: str, params: dict | None = None, timeout: float = 60):
    """GET `url` as JSON, waiting and retrying while it answers 429 or 5xx."""
    import httpx
    for attempt in range(ATTEMPTS):
        r = httpx.get(url, params=params, timeout=timeout, follow_redirects=True)
        if r.status_code != 429 and r.status_code < 500:
            r.raise_for_status()
            return r.json()
        if attempt < ATTEMPTS - 1:
            sleep(_wait(r, attempt))
    if r.status_code == 429:
        raise RateLimited(f"{url}: HTTP 429 after {ATTEMPTS} attempts")
    r.raise_for_status()
    raise AssertionError("unreachable: a 5xx always raises")
