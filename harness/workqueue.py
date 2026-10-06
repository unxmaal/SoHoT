"""Jobs from any caller, run in order under the machine lock while the owner is away. #353.

Jobs are rows in the store's `jobs` table (#418). The runner flock and the
paused flag stay files: a kernel lock and an operator switch.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path

from harness import exclusive, paths

PENDING, RUNNING, DONE, FAILED = "pending", "running", "done", "failed"

#: Set in a job's environment so evals.run can stamp the run it stores. #418.
JOB_ENV = "LH_JOB_ID"

_STAMP = "%Y-%m-%dT%H:%M:%S"


def root() -> Path:
    """The queue's directory: runner.lock, the paused flag, and pre-#418 job files."""
    d = paths.home() / "queue"
    d.mkdir(parents=True, exist_ok=True)
    return d


def log_dir() -> Path:
    d = paths.logs() / "jobs"
    d.mkdir(parents=True, exist_ok=True)
    return d


@contextmanager
def _store(conn=None):
    if conn is not None:
        yield conn
        return
    from harness import memory_store as ms
    opened = ms.connect()
    try:
        yield opened
    finally:
        opened.close()


def _iso(t) -> str:
    return time.strftime(_STAMP, time.localtime(t)) if t else ""


def _epoch(stamp) -> float | None:
    try:
        return time.mktime(time.strptime(str(stamp), _STAMP))
    except (TypeError, ValueError, OverflowError):
        return None


def label(job_id) -> str:
    return f"{int(job_id):04d}"


def _key(job_id) -> int | None:
    s = str(job_id).strip()
    return int(s) if s.isdigit() else None


def _machine(conn) -> int | None:
    from harness import memory_store as ms
    return ms.remember_machine(conn)


def _row(conn, r) -> dict:
    runs = [x["id"] for x in conn.execute(
        "SELECT id FROM runs WHERE job_id = ? ORDER BY id", (r["id"],))]
    return {"id": label(r["id"]), "title": r["title"], "kind": r["kind"],
            "output": r["output"], "priority": int(r["priority"]),
            "argv": json.loads(r["argv"] or "[]"), "cwd": r["cwd"],
            "state": r["state"], "added": _iso(r["created_at"]),
            "started": _iso(r["started_at"]), "finished": _iso(r["finished_at"]),
            "rc": r["rc"], "log": r["log"], "note": r["note"],
            "requested_by": r["requested_by"], "machine_id": r["machine_id"],
            "runs": runs}


def _select(conn, where: str = "", args=()) -> list[dict]:
    rows = conn.execute(f"SELECT * FROM jobs {where} ORDER BY id", args).fetchall()
    return [_row(conn, r) for r in rows]


def jobs(conn=None) -> list[dict]:
    with _store(conn) as c:
        return _select(c)


def add(argv: list[str], title: str = "", cwd: str = "", kind: str = "command",
        output: str = "", priority: int = 0, requested_by: str = "",
        conn=None) -> dict:
    if not argv:
        raise ValueError("a job needs a command")
    first = str(argv[0])
    if first.startswith("-"):
        raise ValueError(f"the command starts with {first!r}: an option this "
                         f"soh did not recognise was taken as the command")
    if any(c.isspace() for c in first) and not os.path.exists(first):
        raise ValueError(f"{first!r} is a whole command line in one argument; "
                         f"split it into words (zsh does not word-split $VAR). #363")
    with _store(conn) as c:
        machine = _machine(c)
        # The store assigns the id inside the insert, so two writers cannot collide. #418.
        cur = c.execute(
            "INSERT INTO jobs (title, kind, output, priority, argv, cwd, state, "
            "created_at, requested_by, machine_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (title or " ".join(argv), kind, output, int(priority),
             json.dumps([str(a) for a in argv]), cwd or os.getcwd(), PENDING,
             time.time(), requested_by, machine))
        c.commit()
        return _select(c, "WHERE id = ?", (cur.lastrowid,))[0]


def order(got: list[dict]) -> list[dict]:
    """Run order: higher priority first, then the order added. #361."""
    return sorted(got, key=lambda j: (-int(j.get("priority") or 0), int(j["id"])))


def _here(c) -> tuple[str, tuple]:
    """Jobs this machine's worker owns: a shared store holds other machines' too."""
    from harness import memory_store as ms
    mid = ms.machine_row(c)
    if mid is None:
        return "machine_id IS NULL", ()
    return "(machine_id = ? OR machine_id IS NULL)", (mid,)


def pending(conn=None) -> list[dict]:
    with _store(conn) as c:
        where, args = _here(c)
        return order(_select(c, f"WHERE state = ? AND {where}", (PENDING, *args)))


def get(job_id, conn=None) -> dict | None:
    key = _key(job_id)
    if key is None:
        return None
    with _store(conn) as c:
        got = _select(c, "WHERE id = ?", (key,))
    return got[0] if got else None


def _only_pending(c, job_id, sql: str, args=(), verb: str = "changed") -> None:
    """Run `sql` on a pending job; the state test is in the same statement."""
    key = _key(job_id)
    if key is not None and c.execute(sql + " WHERE id = ? AND state = ?",
                                     (*args, key, PENDING)).rowcount == 1:
        c.commit()
        return
    c.rollback()
    job = get(job_id, conn=c)
    if job is None:
        raise ValueError(f"no job {job_id}")
    raise ValueError(f"job {job_id} is {job['state']}; only a pending job can be {verb}")


def set_priority(job_id: str, priority: int, conn=None) -> dict:
    with _store(conn) as c:
        _only_pending(c, job_id, "UPDATE jobs SET priority = ?", (int(priority),),
                      "reordered")
        return _select(c, "WHERE id = ?", (_key(job_id),))[0]


def cancel(job_id: str, conn=None) -> dict:
    with _store(conn) as c:
        job = get(job_id, conn=c)
        _only_pending(c, job_id, "DELETE FROM jobs", verb="cancelled")
        return job


def _write(job: dict, conn=None) -> None:
    """Store a job dict's mutable fields back to its row."""
    with _store(conn) as c:
        c.execute("UPDATE jobs SET state = ?, started_at = ?, finished_at = ?, "
                  "rc = ?, log = ?, note = ?, priority = ? WHERE id = ?",
                  (job["state"], _epoch(job.get("started")),
                   _epoch(job.get("finished")), job.get("rc"),
                   job.get("log") or "", job.get("note") or "",
                   int(job.get("priority") or 0), int(job["id"])))
        c.commit()


def _pause_flag() -> Path:
    return root() / "paused"


def paused() -> bool:
    return _pause_flag().exists()


def pause() -> None:
    _pause_flag().write_text(time.strftime(_STAMP), encoding="utf-8")


def resume() -> None:
    _pause_flag().unlink(missing_ok=True)


def gate(away=None) -> tuple[bool, str]:
    """(open, why): may the next job start now? A running job always finishes."""
    from harness import presence
    if paused():
        return False, "paused (soh jobs resume)"
    gone, why = (away or presence.away)()
    return (True, why) if gone else (False, f"owner present: {why}")


def _runner_lock():
    """An fd holding the one-runner lock, or None if a runner already has it."""
    fd = os.open(root() / "runner.lock", os.O_RDWR | os.O_CREAT, 0o644)
    if exclusive._take(fd):
        return fd
    os.close(fd)
    return None


def running() -> bool:
    fd = _runner_lock()
    if fd is None:
        return True
    exclusive._release(fd)
    os.close(fd)
    return False


def run_one(job: dict, popen=subprocess.run) -> dict:
    log = log_dir() / f"{job['id']}.log"
    job.update(state=RUNNING, started=time.strftime(_STAMP), log=str(log))
    _write(job)
    env = {**os.environ, JOB_ENV: str(int(job["id"]))}
    # No machine lock here: each command takes it for the part that loads a
    # model, so a job that is downloading does not block a GPU run. #371.
    with open(log, "w", encoding="utf-8") as out:
        try:
            rc = popen(job["argv"], cwd=job["cwd"], stdout=out,
                       stderr=subprocess.STDOUT, env=env).returncode
        except OSError as exc:
            out.write(f"could not start: {exc}\n")
            rc = 127
    job.update(state=DONE if rc == 0 else FAILED, rc=rc,
               finished=time.strftime(_STAMP))
    _write(job)
    return get(job["id"]) or job


def _recover() -> None:
    """Only the runner-lock holder calls this, so nothing here is really running:
    a job still marked running was cut off (a reboot) and may be half done."""
    with _store() as c:
        where, args = _here(c)
        c.execute(f"UPDATE jobs SET state = ?, note = ? WHERE state = ? AND {where}",
                  (FAILED, "interrupted; add it again to retry", RUNNING, *args))
        c.commit()


def run_pending(popen=subprocess.run, gate=lambda: (True, "")) -> list[dict]:
    """Work the queue in order while the gate stays open. One runner at a time."""
    fd = _runner_lock()
    if fd is None:
        return []
    done = []
    try:
        _recover()
        while True:
            nxt = next(iter(pending()), None)
            if nxt is None or not gate()[0]:
                return done
            done.append(run_one(nxt, popen=popen))
    finally:
        exclusive._release(fd)
        os.close(fd)


def link_run(conn, run_id: int, environ=None) -> bool:
    """Stamp a stored run with the job that produced it, if a job did. #418."""
    key = _key((environ if environ is not None else os.environ).get(JOB_ENV, ""))
    if key is None or run_id is None:
        return False
    if not conn.execute("SELECT 1 FROM jobs WHERE id = ?", (key,)).fetchone():
        return False
    conn.execute("UPDATE runs SET job_id = ? WHERE id = ?", (key, run_id))
    conn.commit()
    return True


_LOGGED_RUN = re.compile(r"^artifacts \+ results\.json in (.+?)(?:; stored as run \d+)?$",
                         re.M)


def import_json(conn) -> dict:
    """Once, at migration: pre-#418 job files into rows, ids kept, files left. #418."""
    from harness import runs
    src = paths.home() / "queue" / "jobs"
    got = {"imported": 0, "skipped": 0, "linked": 0}
    if not src.is_dir():
        return got
    machine = _machine(conn)
    for f in sorted(src.glob("*.json")):
        try:
            j = json.loads(f.read_text(encoding="utf-8"))
            key = int(j["id"])
        except (OSError, ValueError, KeyError, TypeError):
            got["skipped"] += 1
            continue
        if conn.execute("SELECT 1 FROM jobs WHERE id = ?", (key,)).fetchone():
            got["skipped"] += 1
            continue
        added = _epoch(j.get("added")) or f.stat().st_mtime
        conn.execute(
            "INSERT INTO jobs (id, title, kind, output, priority, argv, cwd, "
            "state, created_at, started_at, finished_at, rc, log, note, "
            "requested_by, machine_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (key, j.get("title") or "", j.get("kind") or "command",
             j.get("output") or "", int(j.get("priority") or 0),
             json.dumps(list(j.get("argv") or [])), j.get("cwd") or "",
             j.get("state") or PENDING, added, _epoch(j.get("started")),
             _epoch(j.get("finished")), j.get("rc"), j.get("log") or "",
             j.get("note") or "", "migration", machine))
        got["imported"] += 1
        log = Path(j.get("log") or "")
        try:
            text = log.read_text(encoding="utf-8", errors="replace") if j.get("log") else ""
        except OSError:
            text = ""
        for outdir in _LOGGED_RUN.findall(text):
            where = Path(j.get("cwd") or ".") / outdir.strip()
            got["linked"] += conn.execute(
                "UPDATE runs SET job_id = ? WHERE path = ? AND job_id IS NULL",
                (key, runs.path_key(where))).rowcount
    from harness import store
    if store.backend() == store.POSTGRES:
        conn.execute("SELECT setval(pg_get_serial_sequence('jobs', 'id'), "
                     "COALESCE((SELECT MAX(id) FROM jobs), 1))")
    return got


def serve(poll: float = 30.0, sleep=time.sleep, popen=subprocess.run,
          gate_fn=None, forever=True) -> None:
    """The worker service: check the gate every `poll` seconds, run what waits."""
    gate_fn = gate_fn or gate
    said = ""
    while True:
        if pending():
            ok, why = gate_fn()
            if why != said:
                print(f"{time.strftime('%H:%M:%S')} {'running' if ok else 'waiting'}: {why}",
                      flush=True)
                said = why
            if ok:
                ran = run_pending(popen=popen, gate=gate_fn)
                for j in ran:
                    print(f"{time.strftime('%H:%M:%S')} {j['id']} {j['state']} "
                          f"rc={j['rc']} {j['title']}", flush=True)
                if ran:
                    continue
        if not forever:
            return
        sleep(poll)


if __name__ == "__main__":
    serve(poll=float(os.environ.get("LH_QUEUE_POLL", "30")))
