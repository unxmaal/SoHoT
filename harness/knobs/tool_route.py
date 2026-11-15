"""Knobs of tool route (#2032)."""
from harness.knobs.base import _k

KNOBS = [
    _k("tool_route_chars", ["harness/tool_route.py:CHARS"], [4000, 8000, 16000], unit="chars",
       note="characters of a Bash result or whole-file Read below which it reaches the session as is; under about 2k tokens a digest saves little (#2032)"),
    _k("tool_route_keep_days", ["harness/tool_route.py:KEEP_DAYS"], [1, 7, 30], unit="days",
       note="days a routed raw output stays under tmp/tool-route for a later Read (#2032)"),
    _k("tool_route_timeout_s", ["harness/tool_route.py:TIMEOUT_S"], [60, 120, 300], unit="s",
       note="seconds Claude Code waits on the tool-route hook; past it the result goes through whole (#2032)"),
]

NEVER_CUTS = {
    "harness/tool_route.py:TIMEOUT_S": "Claude Code kills the hook at it and shows the result whole; no SoHoT process sees it bind",
}
