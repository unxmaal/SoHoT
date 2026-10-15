"""`soh otel`: receive Claude Code's OpenTelemetry export, and print the settings that turn it on. #868."""
from __future__ import annotations

import json

from harness.commands.common import emit, note


def add_parser(sub) -> None:
    from harness import otel
    p = sub.add_parser("otel", help="Claude Code OpenTelemetry: serve the local OTLP/HTTP receiver, "
                       "or print the settings.json env that sends export to it")
    p.add_argument("action", choices=("serve", "env"))
    p.add_argument("--host", default=otel.HOST, help="loopback only")
    p.add_argument("--port", type=int, default=otel.PORT)
    p.set_defaults(func=cmd_otel)


def cmd_otel(a) -> int:
    from harness import otel
    if a.action == "env":
        block = otel.env(a.host, a.port)
        note("add to the \"env\" object in ~/.claude/settings.json (not applied here):")
        note(json.dumps(block, indent=2))
        emit(env=block)
        return 0
    try:
        srv = otel.server(a.host, a.port)
    except (ValueError, OSError) as exc:
        note(str(exc))
        emit(False, error=str(exc))
        return 2
    note(f"otlp  http://{a.host}:{a.port}/v1/metrics and /v1/logs (http/json)")
    try:
        srv.serve_forever()
    finally:
        srv.server_close()
    return 0
