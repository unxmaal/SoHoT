"""`soh deploy [status|poll|now|pause|resume]`: deploys as work-queue jobs, one per green main commit. #1506."""
from __future__ import annotations

import os

from harness.commands.common import emit, err, note


def _poll(force: bool, sha: str) -> int:
    from harness import deploy
    got = deploy.poll(sha=sha, force=force)
    job = got["queued"]
    for s in got["superseded"]:
        note(f"cancelled deploy job {s}: superseded")
    if job:
        note(f"queued {job['id']}: {job['title']}; it starts when the queue gate opens and "
             f"{deploy.blocked() or 'nothing blocks it now'}")
    else:
        note(f"nothing queued: {got['why']}")
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
        return _poll(False, "")
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
    conn = ms.connect()
    try:
        got = deploy.status(conn)
    finally:
        conn.close()
    note(f"serving {got['head'][:12] or 'unknown'} from {got['serving'] or 'no deploy checkout'}"
         + (f" through {got['link']}" if got["link"] and got["link"] != got["serving"] else ""))
    note(f"a deploy {'waits: ' + got['blocked'] if got['blocked'] else 'may start now'}")
    for j in got["jobs"]:
        note(f"  job {j['id']} {j['state']:9} {j['title']}" + (f": {j['note']}" if j["note"] else ""))
    for d in got["recent"]:
        note(f"  {deploy.line(d)}")
    emit(**got)
    return 0
