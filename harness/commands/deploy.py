"""`soh deploy [status|poll|now|pause|resume|repair]`: deploys as work-queue jobs, one per green main commit. #1506."""
from __future__ import annotations

import os
from pathlib import Path

from harness.commands.common import emit, err, note


def _nodes(retry: bool = False) -> dict:
    from harness import node_deploy
    got = node_deploy.follow(retry=retry)
    for name, r in got["nodes"].items():
        note(node_deploy.line(name, r))
    return got


def _poll(force: bool, sha: str, nodes: bool = False) -> int:
    from harness import deploy
    got = deploy.poll(sha=sha, force=force)
    job = got["queued"]
    if got["confirm"]:
        note(got["confirm"])
    for s in got["superseded"]:
        note(f"cancelled deploy job {s}: superseded")
    if job:
        note(f"queued {job['id']}: {job['title']}; it starts when the queue gate opens and "
             f"{deploy.blocked() or 'nothing blocks it now'}")
    else:
        note(f"nothing queued: {got['why']}")
    # A node down at the deploy, or added since, follows at the next poll. #1692.
    emit(**got, nodes=_nodes() if nodes else {})
    return 0


def _repair(which: str) -> int:
    """No id: the deploys waiting on a repair; an id: do its repair (#1841)."""
    from harness import deploy_repair
    if not which:
        waiting = deploy_repair.pending()
        for line in deploy_repair.lines(waiting):
            note(line)
        if not waiting:
            note("no deploy waits on a repair")
        emit(pending=waiting)
        return 0
    if not which.isdigit():
        return err(f"soh deploy repair takes a deploy number, not {which!r}")
    got = deploy_repair.repair(int(which))
    if not got["ok"]:
        return err(f"deploy {which} not repaired: {got['detail']}")
    note(f"deploy {which} repaired ({got['how']}): {got['detail']}")
    emit(**got)
    return 0


def cmd_deploy(a) -> int:
    from harness import deploy
    from harness import memory_store as ms
    from harness import workqueue as wq
    if a.action == "pause":
        deploy.pause()
        note("deploys paused: nothing is queued and a pending deploy job waits; soh deploy resume undoes it")
        emit(paused=True)
        return 0
    if a.action == "resume":
        deploy.resume()
        note(f"deploys resumed; {deploy.blocked() or 'a pending deploy may start now'}")
        emit(paused=False)
        return 0
    if a.action == "poll":
        return _poll(False, "", nodes=True)
    if a.action == "repair":
        return _repair(a.sha)
    if a.action == "nodes":
        got = _nodes(retry=True)
        if got["why"] or not got["nodes"]:
            note(f"no node deployed: {got['why'] or 'every node is at ' + got['sha'][:12]}")
        emit(**got)
        return 0
    if a.action == "now":
        return _poll(True, a.sha or "")
    if a.action == "migrate":
        conn = ms.connect()
        try:
            have = deploy._store_schema(conn)
        finally:
            conn.close()
        note(f"store at schema {have}")
        emit(schema=have)
        return 0
    if a.action == "run":
        if not a.sha:
            return err("soh deploy run needs the commit; the queue gives it")
        return deploy.run(a.sha, os.environ.get(wq.JOB_ENV) or None)
    from harness import node_deploy
    conn = ms.connect()
    try:
        got = deploy.status(conn)
        got["nodes"] = node_deploy.status(conn)
    finally:
        conn.close()
    note(f"serving {got['head'][:12] or 'unknown'} from {got['serving'] or 'no deploy checkout'}"
         + (f" through {got['link']}" if got["link"] and got["link"] != got["serving"] else ""))
    if got["deploy"] and got["deploy"]["state"] == "split":
        note(f"deploy {got['deploy']['deploy']} {deploy.said(got['deploy'])}")
    note(f"a deploy {'waits: ' + got['blocked'] if got['blocked'] else 'may start now'}")
    for j in got["jobs"]:
        note(f"  job {j['id']} {j['state']:9} {j['title']}" + (f": {j['note']}" if j["note"] else ""))
    for d in got["recent"]:
        note(f"  {deploy.line(d)}")
    for name, r in got["nodes"].items():
        note(f"  {node_deploy.line(name, r)}")
    from harness import release_procs
    got["old_release"] = release_procs.report(serving=Path(got["serving"]) if got["serving"] else None)
    for x in release_procs.lines(got["old_release"]):
        note(f"  old code: {x}")
    emit(**got)
    return 0
