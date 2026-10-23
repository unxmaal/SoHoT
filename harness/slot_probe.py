"""Whether closing a streamed reply through the gateway frees its llama-server slot, which the yield stop's GPU saving rests on (#1127)."""
from __future__ import annotations

import json
import os
import time

import httpx

#: Tokens the probe asks for: more than the smallest model decodes in SETTLE_S, so only a closed stream ends it in time. #1127.
MAX_TOKENS = 4096
#: Seconds the slot has after the stream closes to go idle. #1127.
SETTLE_S = 5.0
POLL_S = 0.25
PROMPT = "Count upward from 1, one number per line, and do not stop."
FIX = ("a closed stream did not end generation upstream, so a yield stop saves no GPU: send eval text requests "
       "straight to llama-server (router.upstream_for) rather than through the gateway, or make the gateway "
       "cancel its upstream request when the client disconnects")


def _get(base: str, path: str) -> object:
    from harness import router
    r = httpx.get(base.rstrip("/") + path, timeout=router.TIMEOUT)
    r.raise_for_status()
    return r.json()


def _size(entry: dict) -> float:
    args = ((entry.get("status") or {}).get("args") or []) if isinstance(entry.get("status"), dict) else []
    for flag in ("-m", "--model"):
        if flag in args and args.index(flag) + 1 < len(args):
            try:
                return float(os.path.getsize(args[args.index(flag) + 1]))
            except OSError:
                break
    return float("inf")


def _timeout() -> float:
    from harness import router
    return router.TIMEOUT


def busy_text(conn=None) -> str:
    """The argv of each work-queue job running here, which names the models the probe must leave alone. #1153."""
    from harness import workqueue as wq
    try:
        jobs = wq.running_here(conn)
    except Exception:  # noqa: BLE001 - a store that cannot say leaves nothing marked busy
        return ""
    argvs = [j.get("argv") or "" for j in jobs]
    return "\n".join(a if isinstance(a, str) else json.dumps(a) for a in argvs)


def pick(models: list[dict], busy: str = "") -> str:
    """The smallest loaded router model no running job names; "" when there is none."""
    loaded = []
    for m in models:
        status = m.get("status")
        value = status.get("value") if isinstance(status, dict) else status
        if m.get("id") and str(value) == "loaded" and str(m["id"]) not in busy:
            loaded.append((_size(m), str(m["id"])))
    return min(loaded)[1] if loaded else ""


def idle(slots) -> bool | None:
    """Whether no slot is decoding; None when the answer has no slots in a shape this knows."""
    if isinstance(slots, dict):
        slots = slots.get("slots") or slots.get("data")
    if not isinstance(slots, list) or not slots:
        return None
    states = []
    for s in slots:
        if "is_processing" in s:
            states.append(bool(s["is_processing"]))
        elif "state" in s:
            states.append(int(s["state"]) != 0)
        else:
            return None
    return not any(states)


def probe(gateway: str, router: str, model: str, *, headers=None, get=_get, clock=time.monotonic,
          sleep=time.sleep, max_tokens: int | None = None, settle_s: float | None = None) -> tuple[bool, str]:
    """(ok, line): stream a reply, close it after its first token, and watch the slot go idle."""
    max_tokens = MAX_TOKENS if max_tokens is None else max_tokens
    settle_s = SETTLE_S if settle_s is None else settle_s

    def slots():
        try:
            return get(router, f"/slots?model={model}")
        except (httpx.HTTPError, ValueError):
            return get(router, "/slots")
    body = {"model": model, "max_tokens": max_tokens, "stream": True, "temperature": 0,
            "messages": [{"role": "user", "content": PROMPT}]}
    idle_open = None
    try:
        with httpx.stream("POST", gateway.rstrip("/") + "/v1/chat/completions", json=body,
                          headers=headers or {}, timeout=_timeout()) as r:
            if r.status_code >= 400:
                r.read()
                return False, f"slot probe: {model} via the gateway answered HTTP {r.status_code}: {r.text[:200]}"
            for line in r.iter_lines():
                if line.startswith("data:") and '"delta"' in line:
                    break
            idle_open = idle(slots())
    except (httpx.HTTPError, ValueError) as exc:
        return False, f"slot probe: {model}: {exc}"
    if idle_open is None:
        return False, (f"slot probe: {router}/slots told nothing about {model}'s slots; start llama-server "
                       f"with --slots so the check can see them")
    if idle_open:
        return False, f"slot probe: {model}'s slot was idle while its stream was open, so the probe proves nothing"
    closed = clock()
    while clock() - closed < settle_s:
        if idle(slots()):
            return True, f"a closed stream freed {model}'s slot in {clock() - closed:.1f}s"
        sleep(POLL_S)
    return False, f"slot probe: {model}'s slot still decoding {settle_s:g}s after its stream closed: {FIX}"


def main(argv=None) -> int:
    import argparse

    from harness import gateway_key, router
    p = argparse.ArgumentParser(prog="python -m harness.slot_probe")
    p.add_argument("--gateway", default="http://127.0.0.1:4000")
    p.add_argument("--router", default="", help="the llama-server router (default: this machine's)")
    p.add_argument("--model", default="", help="the router model to ask (default: the smallest loaded one no job uses)")
    a = p.parse_args(argv)
    base = a.router or router.url()
    try:
        models = (_get(base, "/models") or {}).get("data") or []
    except (httpx.HTTPError, ValueError) as exc:
        print(f"SKIP  slot probe: the router at {base} did not answer ({exc})")
        return 0
    model = a.model or pick(models, busy_text())
    if not model:
        print("SKIP  slot probe: no loaded router model that no running job uses")
        return 0
    ok, line = probe(a.gateway, base, model, headers=gateway_key.headers())
    print(f"{'PASS' if ok else 'FAIL'}  {line}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
