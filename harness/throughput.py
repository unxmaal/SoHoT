"""Requests per hour at several in-flight levels against one alias. See README, #310."""
from __future__ import annotations

import json
import os
import statistics
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from harness import exclusive

INSTRUCTION = ("List every reusable technical fact in this conversation, one "
               "per line. Write none of the chatter.\n\n")


def claims_requests(rows) -> list[dict]:
    """The chat requests the claims lane sends for these export rows: system, transcript, schema. #665."""
    from harness import completion
    from harness.checks import claims
    return [{"messages": [{"role": "system", "content": r["system"]},
                          {"role": "user", "content": completion.user_message(r["transcript"])}],
             "response_format": claims.response_format(r["schema"])} for r in rows]


def schema_valid(body: dict, request: dict) -> bool | None:
    """Whether a reply validates against the request's json_schema; None when it asks for none."""
    from jsonschema import Draft202012Validator
    rf = request.get("response_format") if isinstance(request, dict) else None
    shape = rf.get("json_schema") if isinstance(rf, dict) and rf.get("type") == "json_schema" else None
    schema = shape.get("schema") if isinstance(shape, dict) else None
    if not isinstance(schema, dict):
        return None
    choices = body.get("choices")
    first = choices[0] if isinstance(choices, list) and choices else None
    message = first.get("message") if isinstance(first, dict) else None
    if not isinstance(message, dict) or message.get("content") is None:
        return False
    try:
        parsed = json.loads(str(message["content"]).strip())
    except ValueError:
        return False
    return Draft202012Validator(schema).is_valid(parsed)


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


def _phys_footprint(pid: int) -> int:
    import ctypes
    import ctypes.util
    libproc = ctypes.CDLL(ctypes.util.find_library("proc") or "libproc.dylib")
    buf = (ctypes.c_uint64 * 64)()
    if libproc.proc_pid_rusage(int(pid), 2, ctypes.byref(buf)) != 0:
        return 0
    # rusage_info_v2: a 16-byte uuid, then ri_phys_footprint is the eighth uint64.
    return int(buf[2 + 7])


def _descendants(pid: int) -> list[int]:
    out = subprocess.run(["ps", "-A", "-o", "pid=,ppid="], capture_output=True,
                         text=True, timeout=10).stdout
    kids: dict[int, list[int]] = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            kids.setdefault(int(parts[1]), []).append(int(parts[0]))
    found, todo = [], [pid]
    while todo:
        for child in kids.get(todo.pop(), []):
            found.append(child)
            todo.append(child)
    return found


def footprint_tree(pid: int) -> int | None:
    """phys_footprint of a server and every process under it; None off macOS. #283, #310."""
    if sys.platform != "darwin":
        return None
    return sum(_phys_footprint(p) for p in [pid, *_descendants(pid)])


class _Peak:
    """The highest footprint seen while a level runs: once at each end and every sample_s between."""

    def __init__(self, footprint, sample_s: float):
        self.footprint, self.sample_s = footprint, sample_s
        self.peak: int | None = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _take(self) -> None:
        got = self.footprint()
        if got is not None:
            self.peak = max(self.peak or 0, int(got))

    def _run(self) -> None:
        while not self._stop.wait(self.sample_s):
            self._take()

    def __enter__(self):
        if self.footprint is not None:
            self._take()
            self._thread.start()
        return self

    def __exit__(self, *exc):
        if self.footprint is not None:
            self._stop.set()
            self._thread.join()
            self._take()


def sweep(model: str, texts: list[str], levels=(1, 2, 4), max_tokens: int = 300,
          gateway: str = "http://127.0.0.1:4000", timeout: float = 300.0,
          post=None, clock=time.perf_counter, footprint=None,
          sample_s: float = 0.5, load=None) -> list[dict]:
    """Each level sends every text with that many requests in flight; `footprint`
    returns the server's bytes, sampled for each level's peak. A dict in `texts` is
    a chat request sent as given (messages, response_format). #665."""
    post = post or _gateway_post(gateway, timeout)
    if load is None and sys.platform != "win32":
        load = os.getloadavg

    def one(text) -> tuple[float, int, bool, float | None, str, int, bool | None]:
        request = text if isinstance(text, dict) else {
            "messages": [{"role": "user", "content": INSTRUCTION + text}]}
        payload = {**request, "model": model, "max_tokens": max_tokens, "temperature": 0}
        t = clock()
        ttft, why, prompt, valid = None, "", 0, None
        try:
            body = post(payload) or {}
            usage = body.get("usage") or {}
            tokens = int(usage.get("completion_tokens") or 0)
            prompt = int(usage.get("prompt_tokens") or 0)
            ttft = body.get("_ttft_s")
            valid = schema_valid(body, request)
            ok = True
        except Exception as exc:  # noqa: BLE001 - a failed request is a result
            tokens, ok = 0, False
            valid = False if schema_valid({}, request) is not None else None
            why = f"{type(exc).__name__}: {str(exc).splitlines()[0] if str(exc) else ''}"[:160]
        return clock() - t, tokens, ok, ttft, why, prompt, valid

    out = []
    with exclusive.held("eval"):
        # Untimed: a model that is not resident loads on the first request,
        # and every ratio is taken against the first level. #333.
        warm_s, _, warm_ok, *_ = one(texts[0]) if texts else (0.0, 0, True, None, "")
        for level in levels:
            before = load()[0] if load else None
            with _Peak(footprint, sample_s) as peak:
                t0 = clock()
                with ThreadPoolExecutor(max_workers=level) as pool:
                    got = list(pool.map(one, texts))
                wall = clock() - t0
            after = load()[0] if load else None
            lat = sorted(s for s, *_ in got)
            first = sorted(r[3] for r in got if r[3] is not None)
            kinds: dict[str, int] = {}
            for why in (r[4] for r in got):
                if why:
                    kinds[why] = kinds.get(why, 0) + 1
            out.append({
                "concurrency": level, "n": len(got),
                "errors": sum(1 for _, _, ok, *_ in got if not ok),
                "error_kinds": kinds,
                "wall_s": round(wall, 2),
                # Answered requests only: refusals come back at once and read as speed. #666.
                "per_hour": (round(sum(1 for r in got if r[2]) / wall * 3600, 1)
                             if wall else 0.0),
                "p50_s": round(statistics.median(lat), 2),
                "p95_s": round(lat[min(len(lat) - 1, int(len(lat) * 0.95))], 2),
                "ttft_p50_s": round(statistics.median(first), 3) if first else None,
                "ttft_p95_s": (round(first[min(len(first) - 1,
                                               int(len(first) * 0.95))], 3)
                               if first else None),
                "completion_tokens": sum(t for _, t, *_ in got),
                "tokens_per_s": (round(sum(t for _, t, *_ in got) / wall, 1)
                                 if wall else 0.0),
                "prompt_tokens": sum(r[5] for r in got),
                "schema_checked": sum(1 for r in got if r[6] is not None),
                "schema_valid": sum(1 for r in got if r[6]),
                "load_avg": [before, after],
                "peak_bytes": peak.peak,
                "warmup_s": round(warm_s, 2), "warmup_ok": warm_ok,
            })
    return out
