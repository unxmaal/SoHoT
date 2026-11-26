"""The mark serve-gateway.sh leaves when it serves the base config with no sohot-<lane> aliases (#2132)."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

FILE = "gateway-degraded"


def path() -> Path:
    from harness import paths
    return paths.home() / FILE


def mark(reason: str, now: float | None = None) -> Path:
    """Record that the gateway now serves the base config; serve-gateway.sh calls this before it execs litellm."""
    to = path()
    to.parent.mkdir(parents=True, exist_ok=True)
    to.write_text(json.dumps({"at": time.time() if now is None else now, "reason": reason[:500]}), encoding="utf-8")
    return to


def clear() -> None:
    path().unlink(missing_ok=True)


def read() -> dict | None:
    """The mark; None with none, {"reason": "unreadable mark"} when it cannot be read (still a degraded gateway)."""
    try:
        body = json.loads(path().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        return {"reason": "unreadable mark"}
    return body if isinstance(body, dict) else {"reason": "unreadable mark"}


def buildable() -> str:
    """"" when the served config can be built now (the store answers), else why not; builds in memory, writes nothing."""
    from harness import gateway
    try:
        gateway.served()
    except Exception as exc:  # noqa: BLE001 - any failure to build is the answer
        return f"{type(exc).__name__}: {exc}"[:300]
    return ""


def check() -> int:
    """monit's check: 1 while a degraded gateway is marked, saying why."""
    got = read()
    if got is None:
        print("the gateway serves its generated config")
        return 0
    print(f"the gateway serves the base config with no sohot-<lane> aliases since "
          f"{time.strftime('%m-%d %H:%M', time.localtime(float(got.get('at') or 0)))}: {got.get('reason', '')}")
    return 1


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:1] == ["mark"] and len(args) == 2:
        print(mark(args[1]))
        return 0
    if args == ["clear"]:
        clear()
        return 0
    if args == ["check"]:
        return check()
    print("usage: python -m harness.gateway_degraded mark REASON | clear | check", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
