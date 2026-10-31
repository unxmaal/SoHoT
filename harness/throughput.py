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
from pathlib import Path

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


def code_requests(cases) -> list[dict]:
    """The chat requests the code lane sends for these cases, with each case's checks kept aside. #682."""
    from harness import completion
    return [{"messages": [{"role": "system", "content": completion.SYSTEM["code"]},
                          {"role": "user", "content": completion.user_message(c.prompt, c.context)}],
             "temperature": completion.DEFAULT_TEMPERATURE, "_id": c.id,
             "_code": {"checks": list(c.assertions.get("checks") or []),
                       "preamble": getattr(c, "preamble", "")}} for c in cases]


def code_cases(side: str, root=None) -> list:
    """The code lane's cases on one side of its split, shipped and local-only, by id. #682."""
    from evals import core
    from harness import holdout
    split = holdout.for_lane("code", root)
    keep = set(split.holdout if side == "holdout" else split.dev if side == "dev"
               else (*split.dev, *split.holdout))
    base = Path(root) if root is not None else Path(__file__).resolve().parent.parent / "evals" / "cases"
    cases = list(core.load_cases(base))
    if root is None and core.local_root().is_dir():
        cases += core.load_cases(core.local_root(), private=True)
    return sorted((c for c in cases if c.modality == "code" and c.id in keep), key=lambda c: c.id)


def spread(items: list, n: int) -> list:
    """n items evenly spaced through `items`, in order; all of them when there are fewer."""
    if n >= len(items):
        return list(items)
    return [items[i * len(items) // n] for i in range(n)]


def code_passed(body: dict, request: dict) -> bool | None:
    """Whether a reply passes its case's code checks; None when the request carries none."""
    code = request.get("_code") if isinstance(request, dict) else None
    if not code:
        return None
    from harness.checks import code as code_check
    choices = body.get("choices")
    first = choices[0] if isinstance(choices, list) and choices else None
    message = first.get("message") if isinstance(first, dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if not content:
        return False
    return code_check.check(str(content), code["checks"], preamble=code.get("preamble", "")).ok


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


def _truncated(body) -> bool:
    """Whether the reply budget cut this reply off (finish_reason length). #699."""
    choices = body.get("choices") if isinstance(body, dict) else None
    first = choices[0] if isinstance(choices, list) and choices else None
    return isinstance(first, dict) and first.get("finish_reason") == "length"


def first_token(timing: dict) -> float | None:
    """Seconds to the first streamed token of any kind, reasoning included. #682."""
    got = [timing.get(k) for k in ("ttft_s", "first_reasoning_s")]
    got = [t for t in got if t is not None]
    return min(got) if got else None


def _gateway_post(gateway: str, timeout: float):
    from harness import completion

    def post(payload: dict) -> dict:
        r = completion._post(gateway, {**payload, "stream": True,
                                       "stream_options": {"include_usage": True}},
                             timeout)
        r.raise_for_status()
        # First-token time rides along under a key no server sends. #468.
        timing = getattr(r, "timing", None) or {}
        return {**r.json(), "_ttft_s": timing.get("ttft_s"), "_first_s": first_token(timing)}
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
    from harness import cuts
    with cuts.timeout("harness/throughput.py:_descendants->subprocess.run(timeout)", "ps listing a server's children"):
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


def default_levels() -> tuple[int, ...]:
    """Doublings from 1 to twice the most slots any plan serves, so a knee at the plan is bracketed. #699."""
    from harness import context
    top = 2 * max(context.EVAL_7B_SLOTS, context.ORNITH_SLOTS, context.LLAMACPP_SLOTS)
    out = [1]
    while out[-1] < top:
        out.append(out[-1] * 2)
    return tuple(out)


def deadline_s(n: int, levels, timeout: float) -> float:
    """The longest a sweep may hold the machine: the warm-up, then each level's waves at that level's timeout. #775."""
    import math

    from harness import completion
    return max(timeout, completion.LOAD_TIMEOUT_S) + sum(math.ceil(n / level) * timeout * level for level in levels)


def sweep(model: str, texts: list[str], levels=None, max_tokens: int | None = None,
          gateway: str = "", timeout: float = 300.0,
          post=None, clock=time.perf_counter, footprint=None,
          sample_s: float = 0.5, load=None) -> list[dict]:
    """Each level sends every text with that many requests in flight; `footprint`
    returns the server's bytes, sampled for each level's peak. A dict in `texts` is
    a chat request sent as given (messages, response_format). #665."""
    from harness import completion, cuts
    levels = default_levels() if levels is None else levels
    max_tokens = completion.MAX_TOKENS if max_tokens is None else max_tokens
    base = gateway or completion.gateway_url()
    # The warm-up may load weights; a request queued behind level-1 others may wait that long. #699.
    post_for = (lambda t: post) if post else (lambda t: _gateway_post(base, t))
    warm_post = post_for(max(timeout, completion.LOAD_TIMEOUT_S))
    if load is None and sys.platform != "win32":
        load = os.getloadavg

    def one(text, send=None) -> tuple:
        request = text if isinstance(text, dict) else {
            "messages": [{"role": "user", "content": INSTRUCTION + text}]}
        sent = {k: v for k, v in request.items() if not k.startswith("_")}
        payload = {"temperature": 0, **sent, "model": model, "max_tokens": max_tokens}
        t = clock()
        ttft, why, prompt, valid = None, "", 0, None
        with completion.measuring() as mine:
            try:
                body = (send or warm_post)(payload) or {}
                usage = body.get("usage") or {}
                tokens = int(usage.get("completion_tokens") or 0)
                prompt = int(usage.get("prompt_tokens") or 0)
                ttft = body.get("_ttft_s")
                valid = schema_valid(body, request)
                ok = True
            except Exception as exc:  # noqa: BLE001 - a failed request is a result
                tokens, ok, body = 0, False, {}
                if send is not None and cuts.timed_out(exc):
                    timed.append(text)
                valid = False if schema_valid({}, request) is not None else None
                why = f"{type(exc).__name__}: {str(exc).splitlines()[0] if str(exc) else ''}"[:160]
            exclusive.beat()
        # A wait for another batch on the serving machine is not this request's latency. #776.
        return clock() - t - mine.within(), tokens, ok, ttft, why, prompt, valid, body, request

    out, timed = [], []
    with exclusive.held("eval", deadline_s=deadline_s(len(texts), levels, timeout)):
        # Untimed: a model that is not resident loads on the first request,
        # and every ratio is taken against the first level. #333.
        warm_s, _, warm_ok, *_ = one(texts[0]) if texts else (0.0, 0, True, None, "")
        for level in levels:
            send = post_for(timeout * level)
            before = load()[0] if load else None
            with _Peak(footprint, sample_s) as peak, completion.measuring() as waits:
                t0 = clock()
                with ThreadPoolExecutor(max_workers=level) as pool:
                    got = list(pool.map(completion.carrying(lambda t: one(t, send)), texts))
                busy = waits.within()
                wall = clock() - t0 - busy
            after = load()[0] if load else None
            # Graded after the clock stops: running a check must not hold back the next request.
            graded = [(code_passed(r[7], r[8]), r[8].get("_id")) for r in got]
            lat = sorted(s for s, *_ in got)
            first = sorted(r[3] for r in got if r[3] is not None)
            any_first = sorted(r[7]["_first_s"] for r in got
                               if isinstance(r[7], dict) and r[7].get("_first_s") is not None)
            kinds: dict[str, int] = {}
            for why in (r[4] for r in got):
                if why:
                    kinds[why] = kinds.get(why, 0) + 1
            cut = [r[2] and _truncated(r[7]) for r in got]
            out.append({
                "concurrency": level, "n": len(got),
                "errors": sum(1 for _, _, ok, *_ in got if not ok),
                "error_kinds": kinds,
                "wall_s": round(wall, 2),
                # Answered requests only: refusals come back at once and read as speed. #666.
                "per_hour": (round(sum(1 for r, c in zip(got, cut) if r[2] and not c)
                                   / wall * 3600, 1) if wall else 0.0),
                # Replies the budget cut off: neither answered nor a fair rate. #699.
                "truncated": sum(cut),
                "p50_s": round(statistics.median(lat), 2),
                "p95_s": round(lat[min(len(lat) - 1, int(len(lat) * 0.95))], 2),
                "ttft_p50_s": round(statistics.median(first), 3) if first else None,
                "ttft_p95_s": (round(first[min(len(first) - 1,
                                               int(len(first) * 0.95))], 3)
                               if first else None),
                "first_token_p50_s": round(statistics.median(any_first), 3) if any_first else None,
                "first_token_p95_s": (round(any_first[min(len(any_first) - 1,
                                                          int(len(any_first) * 0.95))], 3)
                                      if any_first else None),
                "completion_tokens": sum(t for _, t, *_ in got),
                "tokens_per_s": (round(sum(t for _, t, *_ in got) / wall, 1)
                                 if wall else 0.0),
                "prompt_tokens": sum(r[5] for r in got),
                "schema_checked": sum(1 for r in got if r[6] is not None),
                "schema_valid": sum(1 for r in got if r[6]),
                "code_checked": sum(1 for c, _ in graded if c is not None),
                "code_passed": sum(1 for c, _ in graded if c),
                "outcomes": {cid: bool(c if c is not None else r[6])
                             for (c, cid), r in zip(graded, got) if cid is not None
                             and (c is not None or r[6] is not None)},
                "load_avg": [before, after],
                "peak_bytes": peak.peak,
                "warmup_s": round(warm_s, 2), "warmup_ok": warm_ok,
                "busy_wait_s": round(busy, 2),
            })
    if timed:
        cuts.cut("harness/throughput.py:sweep(timeout)", f"{model}: requests timed out across {len(levels)} level(s)",
                 value=timeout, dropped=len(timed))
    return out
