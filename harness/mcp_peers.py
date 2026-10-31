"""harness.mcp_server processes that are alive but not the one serving their port (#1155)."""
from __future__ import annotations

import re

DEFAULT_PORT = 8899

_MODULE = re.compile(r"(?:^|\s)-m\s+harness\.mcp_server(?:\s|$)")
_PORT = re.compile(r"\s--port[=\s]+(\d+)")
_STDIO = re.compile(r"\s--transport[=\s]+stdio\b")
_PYTHON = re.compile(r"(?:^|/)[Pp]ython[\d.]*$")


def port_of(command: str) -> int | None:
    """The port an mcp_server command line listens on; None for another command, stdio or port 0."""
    if not _MODULE.search(command) or _STDIO.search(command):
        return None
    m = _PORT.search(command)
    port = int(m.group(1)) if m else DEFAULT_PORT
    return port or None


def is_server(command: str) -> bool:
    """A Python running harness.mcp_server itself, never the uv or bash that started it."""
    argv0 = command.split(None, 1)[0] if command.strip() else ""
    return bool(_PYTHON.search(argv0)) and port_of(command) is not None


def _lineage(pid: int, procs: dict) -> set:
    out, seen = set(), set()
    while pid in procs and pid not in seen and pid > 1:
        seen.add(pid)
        pid = procs[pid].ppid
        out.add(pid)
    return out


def stale(procs, live: int, port: int | None = None) -> list:
    """Servers on the live one's port that are neither it, its ancestors nor its descendants."""
    by_pid = {p.pid: p for p in procs}
    if port is None:
        mine = [p for p in procs if p.pid == live or live in _lineage(p.pid, by_pid)]
        port = next((port_of(p.command) for p in mine if port_of(p.command)), None)
        if port is None:
            return []
    above = _lineage(live, by_pid)
    return [p for p in procs if is_server(p.command) and port_of(p.command) == port and p.pid != live
            and p.pid not in above and live not in _lineage(p.pid, by_pid)]


def stop_command(pids) -> str:
    """What the owner runs: SIGINT is uvicorn's force-quit while it drains; SIGTERM is not."""
    return "kill -INT " + " ".join(str(p) for p in pids)


def _port_in(name: str) -> int | None:
    tail = name.rsplit(":", 1)[-1]
    return int(tail) if tail.isdigit() else None


def clients(listing: str, port: int) -> dict:
    """Server pid -> what holds each of its established connections on `port`: a local pid, else the peer's address."""
    held, owner, pid = {}, {}, None
    for line in listing.splitlines():
        if line[:1] == "p":
            pid = int(line[1:]) if line[1:].isdigit() else None
        elif line[:1] == "n" and pid is not None and "->" in line:
            local, remote = line[1:].split("->", 1)
            if _port_in(local) == port:
                held.setdefault(pid, []).append(remote)
            elif _port_in(remote) == port:
                owner[local] = pid
    return {s: list(dict.fromkeys(owner.get(r, r) for r in remotes)) for s, remotes in held.items()}


def describe(peer, procs) -> str:
    """A client as the owner would find it: its pid, age and command line."""
    p = {q.pid: q for q in procs}.get(peer) if isinstance(peer, int) else None
    if p is None:
        return f"pid {peer}" if isinstance(peer, int) else peer
    return f"pid {p.pid} (up {p.elapsed_s / 3600:.0f}h) {p.command[:100]}"
