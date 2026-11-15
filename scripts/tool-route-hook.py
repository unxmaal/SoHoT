#!/usr/bin/env python3
"""PostToolUse hook: small results pass at once, big ones go to `soh tool-route --hook`; any failure prints nothing."""
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def main(argv: list[str]) -> int:
    raw = sys.stdin.read()
    try:
        sys.path.insert(0, str(REPO))
        from harness import tool_route
        chars = int(argv[1]) if len(argv) > 1 else tool_route.CHARS
        wait = int(argv[2]) if len(argv) > 2 else tool_route.TIMEOUT_S - 10
        if not tool_route.wanted(json.loads(raw or "{}"), chars):
            return 0
        got = subprocess.run(["uv", "run", "--quiet", "--project", str(REPO), "soh", "tool-route", "--hook",
                              "--chars", str(chars)], input=raw, capture_output=True, text=True, timeout=wait,
                             check=False)
        if got.returncode == 0 and got.stdout.strip():
            json.loads(got.stdout)
            sys.stdout.write(got.stdout)
    except Exception:  # noqa: BLE001 - a hook that fails shows the result whole
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
