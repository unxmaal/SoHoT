"""Requests per hour at several in-flight levels against one alias. See README, #310."""
from __future__ import annotations

import statistics
import time
from concurrent.futures import ThreadPoolExecutor

from harness import exclusive

INSTRUCTION = ("List every reusable technical fact in this conversation, one "
               "per line. Write none of the chatter.\n\n")


def _gateway_post(gateway: str, timeout: float):
    from harness import completion

    def post(payload: dict) -> dict:
        r = completion._post(gateway, {**payload, "stream": True,
                                       "stream_options": {"include_usage": True}},
                             timeout)
        r.raise_for_status()
        # First-token time rides along under a key no server sends. #468.
        return {**r.json(), "_ttft_s": (getattr(r, "timing", None) or {}).get("ttft_s")}
    return post


def sweep(model: str, texts: list[str], levels=(1, 2, 4), max_tokens: int = 300,
          gateway: str = "http://127.0.0.1:4000", timeout: float = 300.0,
          post=None, clock=time.perf_counter) -> list[dict]:
    """Each level sends every text with that many requests in flight."""
    post = post or _gateway_post(gateway, timeout)

    def one(text: str) -> tuple[float, int, bool, float | None]:
        payload = {"model": model, "max_tokens": max_tokens, "temperature": 0,
                   "messages": [{"role": "user", "content": INSTRUCTION + text}]}
        t = clock()
        ttft = None
        try:
            body = post(payload) or {}
            tokens = int((body.get("usage") or {}).get("completion_tokens") or 0)
            ttft = body.get("_ttft_s")
            ok = True
        except Exception:  # noqa: BLE001 - a failed request is a result
            tokens, ok = 0, False
        return clock() - t, tokens, ok, ttft

    out = []
    with exclusive.held("eval"):
        # Untimed: a model that is not resident loads on the first request,
        # and every ratio is taken against the first level. #333.
        warm_s, _, warm_ok, _ = one(texts[0]) if texts else (0.0, 0, True, None)
        for level in levels:
            t0 = clock()
            with ThreadPoolExecutor(max_workers=level) as pool:
                got = list(pool.map(one, texts))
            wall = clock() - t0
            lat = sorted(s for s, *_ in got)
            first = sorted(f for *_, f in got if f is not None)
            out.append({
                "concurrency": level, "n": len(got),
                "errors": sum(1 for _, _, ok, _ in got if not ok),
                "wall_s": round(wall, 2),
                "per_hour": round(len(got) / wall * 3600, 1) if wall else 0.0,
                "p50_s": round(statistics.median(lat), 2),
                "p95_s": round(lat[min(len(lat) - 1, int(len(lat) * 0.95))], 2),
                "ttft_p50_s": round(statistics.median(first), 3) if first else None,
                "ttft_p95_s": (round(first[min(len(first) - 1,
                                               int(len(first) * 0.95))], 3)
                               if first else None),
                "completion_tokens": sum(t for _, t, _, _ in got),
                "warmup_s": round(warm_s, 2), "warmup_ok": warm_ok,
            })
    return out
