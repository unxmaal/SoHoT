"""Whether a launchd-started process may reach each serving node: macOS Local Network privacy. #739.

scripts/lan-probe.sh runs `connect` under `launchctl submit` with the gateway's own python, then
`verdict` reads what it wrote. Run as a file, so `connect` imports nothing outside the stdlib.
"""
from __future__ import annotations

import os
import sys
import time

#: EHOSTUNREACH on macOS; Local Network privacy refuses with it at once.
EHOSTUNREACH = 65
#: A denial takes milliseconds; a real "no route" waits on ARP for seconds.
INSTANT_MS = 500
SETTINGS = "System Settings > Privacy & Security > Local Network"
OK, PRIVACY, DOWN, UNKNOWN = "ok", "privacy", "down", "unknown"


def connect(host: str, port: int, timeout: float, ipv4: bool = True) -> str:
    """One line, "<errno|ok|timeout|dns> <milliseconds of the connect>", for a TCP connect to host:port."""
    import socket
    started = time.monotonic()
    try:
        family = socket.AF_INET if ipv4 else socket.AF_UNSPEC
        addr = socket.getaddrinfo(host, port, family, socket.SOCK_STREAM)[0][4]
        # Timed from here: an mDNS lookup is not the connect.
        started = time.monotonic()
        socket.create_connection(addr[:2], timeout).close()
        got = "ok"
    except socket.gaierror:
        got = "dns"
    except TimeoutError:
        got = "timeout"
    except OSError as exc:
        got = str(exc.errno or "error")
    return f"{got} {round((time.monotonic() - started) * 1000)}"


def classify(line: str) -> tuple[str, str]:
    """(OK|PRIVACY|DOWN|UNKNOWN, why) for one line `connect` wrote."""
    parts = (line or "").split()
    if len(parts) != 2 or not parts[1].isdigit():
        return UNKNOWN, f"the probe wrote {line.strip()!r}" if line.strip() else "the probe wrote nothing"
    what, ms = parts[0], int(parts[1])
    if what == "ok":
        return OK, f"connected in {ms} ms"
    if what == str(EHOSTUNREACH) and ms < INSTANT_MS:
        return PRIVACY, f"errno 65 (No route to host) after {ms} ms"
    if what == "timeout":
        return DOWN, f"no answer in {ms} ms"
    if what == "dns":
        return DOWN, "the name does not resolve"
    names = {"61": "connection refused", "60": "timed out", "64": "host is down",
             str(EHOSTUNREACH): "no route to host"}
    return DOWN, f"errno {what} ({names.get(what, 'connect failed')}) after {ms} ms"


def verdict(name: str, where: str, line: str, python: str = "") -> tuple[bool, str]:
    """(passed, the line to print): only a privacy block or a probe that never ran fails."""
    kind, why = classify(line)
    if kind == OK:
        return True, f"PASS  launchd can reach node {name} at {where}: {why}"
    if kind == DOWN:
        return True, f"DOWN  node {name} at {where} is down, not blocked: {why}"
    if kind == UNKNOWN:
        return False, f"FAIL  node {name} at {where}: no launchd probe result ({why})"
    binary = os.path.realpath(python) if python else "the gateway's python"
    return False, (f"FAIL  node {name} at {where}: macOS Local Network privacy blocks launchd jobs ({why}).\n"
                   f"      Allow it: {SETTINGS}, turn on the Python entry ({binary}),\n"
                   f"      then: ./scripts/launchd.sh restart gateway")


def targets(nodes) -> list[str]:
    """"name host port timeout ipv4" per node, for the shell to loop over."""
    from urllib.parse import urlsplit
    out = []
    for n in nodes:
        split = urlsplit(n.api_base)
        out.append(f"{n.name} {split.hostname} {split.port} {n.connect_timeout:g} {int(n.ipv4)}")
    return out


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = argv[:1]
    if cmd == ["connect"] and len(argv) == 5:
        print(connect(argv[1], int(argv[2]), float(argv[3]), argv[4] == "1"), flush=True)
        return 0
    if cmd == ["targets"]:
        from harness import nodes
        print("\n".join(targets(nodes.load())))
        return 0
    if cmd == ["verdict"] and len(argv) in (4, 5):
        try:
            with open(argv[3], encoding="utf-8") as fh:
                line = next((x for x in fh if x.strip()), "")
        except OSError:
            line = ""
        passed, text = verdict(argv[1], argv[2], line, argv[4] if len(argv) == 5 else "")
        print(text)
        return 0 if passed else 1
    print("usage: lanprobe.py connect HOST PORT TIMEOUT IPV4 | targets | verdict NAME HOST:PORT FILE [PYTHON]",
          file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
