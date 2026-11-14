"""Refuse a shell script's act on the whole machine from a home monitor.live_home() says is not the live one (#2008)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

try:
    from harness import monitor
except ImportError:  # python3 -I puts no checkout on sys.path, so this folder stands in for the package. #1910.
    import types
    _pkg = sys.modules["harness"] = types.ModuleType("harness")
    _pkg.__path__ = [str(Path(__file__).resolve().parent)]
    from harness import monitor

#: harness/load_log.SERVING_ENV, restated because this loads only monitor and what it imports.
SERVING_ENV = "LH_SERVING_HOME"
LIVE, OFF = 0, 3


def refusal(home: str | Path, what: str, serving: str = "") -> str:
    """'' when `home`, or the live router a canary home names in `serving`, is the live home; else why `what` is refused."""
    if monitor.live_home(Path(home)) or (serving and monitor.live_home(Path(serving).expanduser())):
        return ""
    return monitor.off_live(what, Path(home))


def main(argv: list[str] | None = None, environ=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    environ = os.environ if environ is None else environ
    serving = "--serving" in args
    args = [a for a in args if a != "--serving"]
    if len(args) != 2:
        print("usage: live_gate.py HOME WHAT [--serving]", file=sys.stderr)
        return 2
    why = refusal(args[0], args[1], environ.get(SERVING_ENV, "") if serving else "")
    if why:
        print(why, file=sys.stderr)
    return OFF if why else LIVE


if __name__ == "__main__":
    sys.exit(main())
