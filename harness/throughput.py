"""Requests per hour at several in-flight levels against one alias. See README, #310."""
from __future__ import annotations

import statistics
import time
from concurrent.futures import ThreadPoolExecutor

from harness import exclusive

INSTRUCTION = ("List every reusable technical fact in this conversation, one "
               "per line. Write none of the chatter.\n\n")


def _gateway_post(gateway: str, timeout: float):
    import httpx

    def post(payload: dict) -> dict:
        r = httpx.post(f"{gateway.rstrip('/')}/v1/chat/completions",
                       json=payload, timeout=timeout,
                       headers={"Authorization": "Bearer sk-local"})
        r.raise_for_status()
        return r.json()
    return post


def sweep(model: str, texts: list[str], levels=(1, 2, 4), max_tokens: int = 300,
          gateway: str = "http://127.0.0.1:4000", timeout: float = 300.0,
          post=None) -> list[dict]:
    """Each level sends every text with that many requests in flight."""
    post = post or _gateway_post(gateway, timeout)

    def one(text: str) -> tuple[float, int, bool]:
        payload = {"model": model, "max_tokens": max_tokens, "temperature": 0,
                   "messages": [{"role": "user", "content": INSTRUCTION + text}]}
        t = time.perf_counter()
        try:
            body = post(payload) or {}
            tokens = int((body.get("usage") or {}).get("completion_tokens") or 0)
            ok = True
        except Exception:  # noqa: BLE001 - a failed request is a result
            tokens, ok = 0, False
        return time.perf_counter() - t, tokens, ok

    out = []
    with exclusive.held("eval"):
        # Untimed: a model that is not resident loads on the first request,
        # and every ratio is taken against the first level. #333.
        warm_s, _, warm_ok = one(texts[0]) if texts else (0.0, 0, True)
        for level in levels:
            t0 = time.perf_counter()
            with ThreadPoolExecutor(max_workers=level) as pool:
                got = list(pool.map(one, texts))
            wall = time.perf_counter() - t0
            lat = sorted(s for s, _, _ in got)
            out.append({
                "concurrency": level, "n": len(got),
                "errors": sum(1 for *_, ok in got if not ok),
                "wall_s": round(wall, 2),
                "per_hour": round(len(got) / wall * 3600, 1) if wall else 0.0,
                "p50_s": round(statistics.median(lat), 2),
                "p95_s": round(lat[min(len(lat) - 1, int(len(lat) * 0.95))], 2),
                "completion_tokens": sum(t for _, t, _ in got),
                "warmup_s": round(warm_s, 2), "warmup_ok": warm_ok,
            })
    return out
