"""The agent sandbox's tools as a stdio MCP server, for the Opus baseline. #474.

    python evals/agent_mcp.py <repo root> <call log> <tools,csv> <max calls>

claude -p gets these four tools and no built-in ones, so Opus works the same
sandbox the local loop does. Every call is appended to the log with the same
validity fields the local loop records. Newline-delimited JSON-RPC, no SDK.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evals import sandbox  # noqa: E402

PROTOCOL = "2025-06-18"


def handle(box: sandbox.Sandbox, request: dict, state: dict) -> dict | None:
    method, rid = request.get("method"), request.get("id")
    if rid is None:
        return None
    if method == "initialize":
        version = (request.get("params") or {}).get("protocolVersion") or PROTOCOL
        result = {"protocolVersion": version, "capabilities": {"tools": {}},
                  "serverInfo": {"name": "sandbox", "version": "1"}}
    elif method == "tools/list":
        result = {"tools": [{"name": n, "description": sandbox.TOOLS[n]["description"],
                             "inputSchema": sandbox.TOOLS[n]["parameters"]}
                            for n in box.tools]}
    elif method == "tools/call":
        params = request.get("params") or {}
        state["calls"] += 1
        if state["calls"] > state["cap"]:
            text, error = f"error: step cap of {state['cap']} tool calls reached", True
            entry = {"name": params.get("name"), "valid": False, "why": "cap"}
        else:
            args = params.get("arguments")
            call, text = box.call(params.get("name"), args if args is not None else {})
            error = not call.ok
            entry = {"name": call.name, "parsed": call.parsed, "schema_ok": call.schema_ok,
                     "real": call.real, "valid": call.valid, "ok": call.ok, "why": call.why}
        entry["at"] = time.time()
        with open(state["log"], "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
        result = {"content": [{"type": "text", "text": text}], "isError": error}
    elif method == "ping":
        result = {}
    else:
        return {"jsonrpc": "2.0", "id": rid,
                "error": {"code": -32601, "message": f"unknown method {method}"}}
    return {"jsonrpc": "2.0", "id": rid, "result": result}


def main(argv: list[str]) -> int:
    root, log, tools, cap = argv[0], argv[1], argv[2].split(","), int(argv[3])
    box = sandbox.Sandbox(Path(root), tools=tuple(t for t in tools if t))
    state = {"calls": 0, "cap": cap, "log": log}
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except ValueError:
            continue
        reply = handle(box, request, state)
        if reply is not None:
            sys.stdout.write(json.dumps(reply) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv[1:]))
