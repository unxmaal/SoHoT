"""The live processes still running a release the deploy link no longer names. #1959."""
from __future__ import annotations

import os
import re
from pathlib import Path

from harness import holders, job_release, proc_identity

#: A process on another release is still the one seen there, or whether it is cannot be told.
STALE, UNKNOWN = "stale", "unknown"
#: Where a process's path was found, strongest evidence of the code it runs first; a cwd alone may be a shell.
_EVIDENCE = ("executable", "mapped file", "open fd", "cwd")


def _rank(how: str) -> int:
    return next((i for i, e in enumerate(_EVIDENCE) if how.startswith(e)), len(_EVIDENCE))


def release_in(path: str, root: str) -> str:
    """The name of the release directory under `root` holding `path`, '' outside every one."""
    rest = job_release._within(path, root)
    return re.split(r"[\\/]", rest.lstrip("\\/"), maxsplit=1)[0] if rest else ""


def _order(name: str) -> int:
    head = name.split("-", 1)[0]
    return int(head) if head.isdigit() else -1


def scan(root, serving: str, walk=None, identity=None, same=None, me: int | None = None) -> list[dict] | None:
    """Each live process whose strongest path lies in a release under `root` other than `serving`; None where nobody can tell."""
    walk = holders.walkers() if walk is None else walk
    if walk is None:
        return None
    pids, paths, name = walk
    identity, same = identity or proc_identity.identity, same or proc_identity.same
    me = os.getpid() if me is None else me
    top = os.path.realpath(root)
    out = []
    for pid in pids:
        if pid == me:
            continue
        # Identity before paths: a pid reused while its paths are read is then not named for them.
        who = identity(pid)
        best = None
        for how, path in paths(pid):
            rel = release_in(path, top)
            if rel and (best is None or _rank(how) < _rank(best[1])):
                best = (rel, how, path)
        if best is None or best[0] == serving:
            continue
        still = same(who)
        if still is False:
            continue
        out.append({"pid": pid, "name": name(pid), "release": best[0], "how": best[1], "path": best[2],
                    "code": _rank(best[1]) < _EVIDENCE.index("cwd"), "state": STALE if still else UNKNOWN,
                    "started": who.get("started", "")})
    return out


def _describe(procs: list[dict], probes) -> None:
    """Each process's command line and age from the process table; an MCP server also names its clients (#1166)."""
    from harness import mcp_peers, watchdog_observe
    probes = watchdog_observe.Probes() if probes is None else probes
    table = probes.processes()
    if not table:
        return
    by = {p.pid: p for p in table}
    for p in procs:
        q = by.get(p["pid"])
        if q is None:
            continue
        p.update(command=q.command[:200], up_s=q.elapsed_s)
        port = mcp_peers.port_of(q.command) if mcp_peers.is_server(q.command) else None
        if port:
            listing = probes.mcp_connections(port)
            held = mcp_peers.clients(listing, port) if listing is not None else {}
            p["clients"] = [mcp_peers.describe(c, table) for c in held.get(p["pid"], [])]


def report(serving: Path | None = None, probes=None, walk=None, identity=None, same=None) -> dict:
    """{'serving', 'procs'} for this home's releases; procs is None where this platform cannot tell."""
    serving = job_release.target() if serving is None else job_release.release_of(serving)
    name = serving.name if serving is not None else ""
    root = job_release.releases_dir()
    if not root.is_dir() or not [p for p in root.iterdir() if p.is_dir() and p.name != name]:
        return {"serving": name, "procs": []}
    procs = scan(root, name, walk=walk, identity=identity, same=same)
    if procs:
        _describe(procs, probes)
    return {"serving": name, "procs": procs}


def line(p: dict, serving: str) -> str:
    what = p.get("command") or p["name"]
    up = f" (up {p['up_s'] / 3600:.1f}h)" if p.get("up_s") is not None else ""
    where = f"{p['how']} {p['path']}"
    if p["state"] == UNKNOWN:
        return (f"pid {p['pid']}{up} may still run release {p['release']} ({where}): its start time cannot be read, "
                f"so whether it is the process seen there is unknown: {what}")
    older = "older " if serving and _order(p["release"]) < _order(serving) else ""
    verb = "runs" if p["code"] else "has its cwd in"
    return (f"pid {p['pid']}{up} {verb} {older}release {p['release']}, not the serving {serving or 'none'} "
            f"({where}): {what}")


def lines(r: dict, code_only: bool = False) -> list[str]:
    if r["procs"] is None:
        return ["no way to tell on this platform which live processes run another release"]
    out = []
    for p in r["procs"]:
        if code_only and not p["code"]:
            continue
        out.append(line(p, r["serving"]))
        out.extend(f"  its client {c}" for c in p.get("clients") or [])
    return out


def after_deploy(rec: dict, report_=None) -> str:
    """The alert for a deploy that migrated the store while processes still run another release's code; '' when none do."""
    if not rec.get("migrated") or not rec.get("release"):
        return ""
    got = (report_ or report)(serving=Path(rec["release"]))
    named = lines(got, code_only=True) if got["procs"] is not None else []
    if not named:
        return ""
    schema = f" to schema {rec['schema_to']}" if rec.get("schema_to") else ""
    return (f"deploy {rec.get('id', '')} migrated the store{schema}, and these still run another release's code, "
            f"so their next store connect is refused: " + "; ".join(named))


def morning_lines(r: dict | None) -> list[str]:
    if not r or not (r["procs"] is None or r["procs"]):
        return []
    got = lines(r)
    if r["procs"] is None:
        return [f"old code  {got[0]}"]
    return [f"old code  {len(r['procs'])} process(es) on another release than {r['serving'] or 'the link'}"] + [
        f"          {x}" for x in got]
