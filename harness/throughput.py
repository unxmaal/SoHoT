"""Requests per hour at several in-flight levels against one alias. See README, #310."""
from __future__ import annotations

import statistics
import subprocess
import sys
import threading
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
          sample_s: float = 0.5) -> list[dict]:
    """Each level sends every text with that many requests in flight; `footprint`
    returns the server's bytes, sampled for each level's peak."""
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
            with _Peak(footprint, sample_s) as peak:
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
                "tokens_per_s": (round(sum(t for _, t, _, _ in got) / wall, 1)
                                 if wall else 0.0),
                "peak_bytes": peak.peak,
                "warmup_s": round(warm_s, 2), "warmup_ok": warm_ok,
            })
    return out
