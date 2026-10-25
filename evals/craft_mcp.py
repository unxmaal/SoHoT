"""A stdio MCP client for a craft app's own server: newline-delimited JSON-RPC, no SDK (#1209)."""
from __future__ import annotations

import contextlib
import json
import queue
import subprocess
import threading
import time
from pathlib import Path

PROTOCOL = "2025-06-18"


class McpError(RuntimeError):
    """The server could not be started, answered with an error, or went away."""


class McpTimeout(McpError):
    """The server did not answer within the call's timeout."""


class Client:
    def __init__(self, argv: list[str], cwd: Path, env: dict | None = None, stderr: Path | None = None):
        self.argv = [str(a) for a in argv]
        self._err = open(stderr, "ab") if stderr else subprocess.DEVNULL  # noqa: SIM115 - closed in close()
        try:
            self.proc = subprocess.Popen(self.argv, cwd=cwd, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                         stderr=self._err, text=True, encoding="utf-8", errors="replace", bufsize=1)
        except OSError as exc:
            self._close_err()
            raise McpError(f"could not start {self.argv[0]}: {exc}") from exc
        self._lines: queue.Queue = queue.Queue()
        self._next = 0
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self) -> None:
        for line in self.proc.stdout:
            self._lines.put(line)
        self._lines.put(None)

    def _close_err(self) -> None:
        if self._err is not subprocess.DEVNULL:
            with contextlib.suppress(OSError):
                self._err.close()

    def _send(self, message: dict) -> None:
        try:
            self.proc.stdin.write(json.dumps(message) + "\n")
            self.proc.stdin.flush()
        except (OSError, ValueError) as exc:
            raise McpError(f"{self.argv[0]} closed its input: {exc}") from exc

    def request(self, method: str, params: dict | None, timeout: float):
        self._next += 1
        rid = self._next
        self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}})
        deadline = time.monotonic() + timeout
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                raise McpTimeout(f"{method} had no answer in {timeout:g}s")
            try:
                line = self._lines.get(timeout=left)
            except queue.Empty:
                continue
            if line is None:
                raise McpError(f"{self.argv[0]} exited (code {self.proc.poll()}) during {method}")
            try:
                reply = json.loads(line)
            except ValueError:
                continue
            if not isinstance(reply, dict) or reply.get("id") != rid:
                continue
            if "error" in reply:
                err = reply["error"] or {}
                raise McpError(f"{method}: {err.get('message') or err}")
            return reply.get("result") or {}

    def notify(self, method: str, params: dict | None = None) -> None:
        self._send({"jsonrpc": "2.0", "method": method, **({"params": params} if params else {})})

    def initialize(self, timeout: float) -> dict:
        got = self.request("initialize", {"protocolVersion": PROTOCOL, "capabilities": {},
                                          "clientInfo": {"name": "sohot-craft", "version": "1"}}, timeout)
        self.notify("notifications/initialized")
        return got

    def tools(self, timeout: float) -> list[dict]:
        out, cursor = [], None
        while True:
            got = self.request("tools/list", {"cursor": cursor} if cursor else {}, timeout)
            out += got.get("tools") or []
            cursor = got.get("nextCursor")
            if not cursor:
                return out

    def call(self, name: str, arguments: dict, timeout: float) -> dict:
        return self.request("tools/call", {"name": name, "arguments": arguments}, timeout)

    def close(self, grace: float = 5.0) -> None:
        with contextlib.suppress(OSError, ValueError):
            self.proc.stdin.close()
        try:
            self.proc.wait(timeout=grace)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            with contextlib.suppress(subprocess.TimeoutExpired):
                self.proc.wait(timeout=grace)
        self._close_err()


def text_of(result: dict) -> str:
    """The text a tools/call result carries, structured content as JSON when there is no text."""
    parts = [c.get("text") or "" for c in result.get("content") or [] if c.get("type") == "text"]
    if parts:
        return "\n".join(parts)
    if result.get("structuredContent") is not None:
        return json.dumps(result["structuredContent"])
    return ""


def json_of(result: dict):
    """The JSON a tools/call result answers with: structured content, else its text parsed; None when neither."""
    if result.get("structuredContent") is not None:
        return result["structuredContent"]
    try:
        return json.loads(text_of(result))
    except ValueError:
        return None
