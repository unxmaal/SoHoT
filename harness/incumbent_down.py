"""The mark a paired measure leaves when its incumbent's runner answered none of its first cases; the status page reads it (#2157)."""
from __future__ import annotations

import json
import time
from pathlib import Path

FILE = "incumbent-down.json"
#: Ends the failed-step label of a pair stopped by its incumbent, which the sweep never measures again.
LABEL = " (incumbent)"


def path() -> Path:
    from harness import paths
    return paths.home() / FILE


def read() -> dict:
    """{lane: {"runner", "pair", "why", "at"}} for every lane whose incumbent answered nothing; {} with none or unreadable."""
    try:
        body = json.loads(path().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        body = None
    return body if isinstance(body, dict) else {"?": {"runner": "", "pair": "", "why": "unreadable mark file", "at": 0}}


def mark(lane: str, runner: str, pair: str, why: str, now: float | None = None) -> None:
    """Record that `lane`'s incumbent `runner` failed on its own, in the measure of `pair`."""
    got = {k: v for k, v in read().items() if k != "?"}
    got[lane] = {"runner": runner, "pair": pair, "why": why[:300], "at": time.time() if now is None else now}
    to = path()
    to.parent.mkdir(parents=True, exist_ok=True)
    to.write_text(json.dumps(got, sort_keys=True), encoding="utf-8")


def clear(lane: str) -> None:
    """The lane's incumbent answered again: drop its mark."""
    got = read()
    if got.pop(lane, None) is not None and "?" not in got:
        path().write_text(json.dumps(got, sort_keys=True), encoding="utf-8")


def stopped(name: str, lane: str, inc_spec: str, stderr: str, dry: bool) -> int:
    """The lane's incumbent answered none of its first cases: record the pair once as a harness failure and raise a needs-you mark. #2157."""
    from evals import watch
    from harness import memory_store as ms, reasons
    said = next((ln.strip() for ln in stderr.splitlines() if ln.startswith("stopped: the incumbent")), "")
    why = said or f"the incumbent {inc_spec} answered none of its first cases"
    print(f"  {name}: not measured: {why}", flush=True)
    if dry:
        return watch.SILENT
    mark(lane, inc_spec, name, why)
    store = ms.connect()
    try:
        ms.decide(store, name, "queued", tier=ms.MEASURE, detail=why[:200], reason=reasons.HARNESS,
                  failure_class=reasons.HARNESS_ERROR, lane=lane)
    except (KeyError, ms.IllegalTransition) as exc:
        print(f"  {name}: not recorded: {exc}", flush=True)
    finally:
        store.close()
    return watch.SILENT
