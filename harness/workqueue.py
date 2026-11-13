"""Jobs from any caller, by priority then id within each resource class (resources.py): one GPU job at a time, the rest up to their capacity, while memory pressure is normal; GPU jobs and deploys behind the contention gate. #353, #573, #1153, #1509.

Jobs are rows in the store's `jobs` table (#418). The runner flock and the
paused flag stay files: a kernel lock and an operator switch.
"""
from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from harness import exclusive, job_state as js, paths, queue_hold, resources

PENDING, RUNNING, DONE, FAILED = js.PENDING, js.RUNNING, js.DONE, js.FAILED
CANCELLED, PAUSED = js.CANCELLED, js.PAUSED
#: The resource classes the worker starts by; a deploy runs alone. #1153, #1506, #1508.
GPU, CLOUD, DEPLOY = resources.GPU, resources.NETWORK, resources.DEPLOY
#: How often a worker with jobs running looks for one it can start beside them. #1153.
WATCH_S = 5.0
#: How long a cancelled job's process group gets to exit before it is killed. #628.
CANCEL_GRACE_S = 30.0

#: Set in a job's environment so evals.run can stamp the run it stores. #418.
JOB_ENV = "LH_JOB_ID"
#: Seconds of cases one queue item of an eval runs before the eval goes back to pending to wait its turn. #1618.
ITEM_S = 600.0
#: Set for a job the worker runs in items: an eval stops at the item's end and marks it, the next item resumes it.
ITEM_ENV = "LH_QUEUE_ITEM_S"

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
            "rc": r["rc"], "log": r["log"], "note": r["note"], "reason": r["reason"],
            "requested_by": r["requested_by"], "machine_id": r["machine_id"],
            "not_before": _iso(r["not_before"]), "runs": runs,
            "resource": r["resource"]}


def _select(conn, where: str = "", args=()) -> list[dict]:
    rows = conn.execute(f"SELECT * FROM jobs {where} ORDER BY id", args).fetchall()
    return [_row(conn, r) for r in rows]


def jobs(conn=None) -> list[dict]:
    with _store(conn) as c:
        return _select(c)


def _git(path: Path, *args: str) -> str | None:
    from harness import cuts
    try:
        with cuts.timeout("harness/workqueue.py:_git->subprocess.run(timeout)", f"git {' '.join(args)}"):
            out = subprocess.run(["git", "-C", str(path), *args], capture_output=True,
                                 text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def deployed() -> Path | None:
    """The deploy checkout, when this machine has one."""
    deploy = paths.deploy_checkout()
    return deploy if deploy is not None and (deploy / ".git").exists() else None


def queue_cwd(caller, deploy, explicit: str = "") -> str:
    """Where a queued job runs: the deploy, unless the caller's checkout is at another commit. #645."""
    if explicit:
        return str(Path(explicit).resolve())
    caller = Path(caller).resolve()
    if deploy is None:
        return str(caller)
    deploy = Path(deploy).resolve()
    top = _git(caller, "rev-parse", "--show-toplevel")
    if top is None:
        return str(deploy)
    if Path(top).resolve() == deploy:
        return str(caller)
    mine, theirs = _git(caller, "rev-parse", "HEAD"), _git(deploy, "rev-parse", "HEAD")
    if mine and mine == theirs:
        return str(deploy)
    raise ValueError(
        f"this checkout ({top}) is at {(mine or 'no commit')[:8]} but the deploy "
        f"({deploy}) is at {(theirs or 'no commit')[:8]}, and a queued job would run "
        f"this checkout's code; pass --cwd {caller} to mean it, or queue from the deploy")


def at_clock(hhmm: str, now: float) -> float:
    """The next local HH:MM at or after now. #900."""
    from datetime import datetime, timedelta
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", hhmm.strip())
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        raise ValueError(f"a start time is HH:MM, not {hhmm!r}")
    t = datetime.fromtimestamp(now)
    at = t.replace(hour=int(m.group(1)), minute=int(m.group(2)), second=0, microsecond=0)
    return (at if at >= t else at + timedelta(days=1)).timestamp()


def at_date(spec: str, now: float) -> float:
    """A local 'YYYY-MM-DD HH:MM' as that exact time; one already past is refused. #1297."""
    from datetime import datetime
    text = spec.strip().replace("T", " ")
    at = None
    for form in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            at = datetime.strptime(text, form)
            break
        except ValueError:
            continue
    if at is None:
        raise ValueError(f"a start time is HH:MM or YYYY-MM-DD HH:MM[:SS], not {spec!r}")
    if at.timestamp() < now:
        raise ValueError(f"the start {spec!r} is in the past")
    return at.timestamp()


#: The start a caller from before #1509 may still name; the contention gate, not the clock, now holds GPU work.
NIGHT = "night"


def start_at(spec: str, now: float | None = None) -> float | None:
    """'' or 'night' -> None, 'HH:MM' -> its next occurrence, 'YYYY-MM-DD HH:MM' -> then. #900, #1297, #1509."""
    spec = (spec or "").strip()
    if not spec or spec == NIGHT:
        return None
    now = time.time() if now is None else now
    return at_date(spec, now) if re.match(r"\d{4}-", spec) else at_clock(spec, now)


def _schema_file(cwd) -> Path | None:
    here = Path(cwd).resolve()
    return next((f for f in (t / "harness" / "memory_store" / "schema.py" for t in (here, *here.parents))
                 if f.is_file()), None)


def code_schema(cwd) -> int | None:
    """The SCHEMA_VERSION the nearest checkout at or above cwd speaks, read as text; None outside one. #1348."""
    schema = _schema_file(cwd)
    m = schema and re.search(r"^SCHEMA_VERSION\s*=\s*(\d+)", schema.read_text(encoding="utf-8"), re.M)
    return int(m.group(1)) if m else None


def stale_schema(cwd, conn) -> str:
    """Why a job in cwd would refuse this store (its code speaks an older schema), or ''. #1348."""
    code = code_schema(cwd)
    row = conn.execute("SELECT value FROM meta WHERE key='schema'").fetchone()
    store = int(row["value"]) if row else 0
    if code is None or code >= store:
        return ""
    top = _schema_file(cwd).parents[2]
    return (f"the job's code ({top}) speaks schema {code} but the store is schema {store}, "
            f"so it would refuse the store when it starts; queue from the deploy or update that checkout")


#: Planners that rerun a model the lane already measured (a knob sweep, a reverify), so no repo screen comes first. #1353
REMEASURES = ("sweep", "reverify")


def add(argv: list[str], title: str = "", cwd: str = "", kind: str = "command",
        output: str = "", priority: int = 0, requested_by: str = "",
        not_before: float | None = None, conn=None, resource: str = "", commit: bool = True) -> dict:
    if not commit and conn is None:
        raise ValueError("an uncommitted job needs the caller's connection")
    if resource:
        resources.check(resource)
    if not argv:
        raise ValueError("a job needs a command")
    if resources.node_of(resource) and resources.classify(argv, kind) != resource:
        raise ValueError(f"not queued: {resource} runs only an eval whose every candidate that node serves first")
    first = str(argv[0])
    if first.startswith("-"):
        raise ValueError(f"the command starts with {first!r}: an option this "
                         f"soh did not recognise was taken as the command")
    if any(c.isspace() for c in first) and not os.path.exists(first):
        raise ValueError(f"{first!r} is a whole command line in one argument; "
                         f"split it into words (zsh does not word-split $VAR). #363")
    if "evals.run" in [str(a) for a in argv]:
        from evals import run
        spend = run.argv_spend_refusal(argv) or (
            "" if requested_by in REMEASURES else run.argv_screen_refusal(argv))
        if spend:
            raise ValueError(f"not queued: {spend}")
    if "adopt" in [str(a) for a in argv]:
        from harness.commands import adopt as adopt_cmd
        unscreened = adopt_cmd.argv_screen_refusal(argv)
        if unscreened:
            raise ValueError(f"not queued: {unscreened}")
    with _store(conn) as c:
        stale = stale_schema(cwd or os.getcwd(), c)
        if stale:
            raise ValueError(f"not queued: {stale}")
        machine = _machine(c)
        # The store assigns the id inside the insert, so two writers cannot collide. #418.
        cur = c.execute(
            "INSERT INTO jobs (title, kind, output, priority, argv, cwd, state, reason, "
            "created_at, requested_by, machine_id, not_before, resource) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (title or " ".join(argv), kind, output, int(priority),
             json.dumps([str(a) for a in argv]), cwd or os.getcwd(), PENDING, js.ADDED,
             time.time(), requested_by, machine,
             None if not_before is None else float(not_before), resource))
        if commit:
            c.commit()
        return _select(c, "WHERE id = ?", (cur.lastrowid,))[0]


def order(got: list[dict]) -> list[dict]:
    """Run order: higher priority first, then the order added. #361."""
    return sorted(got, key=lambda j: (-int(j.get("priority") or 0), int(j["id"])))


def _here(c) -> tuple[str, tuple]:
    """Jobs this machine's worker may take: a shared store holds other machines' too."""
    from harness import machine_scope
    return machine_scope.here(c, "jobs.claimable")


def pending(conn=None) -> list[dict]:
    with _store(conn) as c:
        where, args = _here(c)
        return order(_select(c, f"WHERE state = ? AND {where}", (PENDING, *args)))


def due(job: dict, now: float | None = None) -> bool:
    """Whether a job's earliest start has come. #900."""
    at = _epoch(job.get("not_before")) if job.get("not_before") else None
    return at is None or at <= (time.time() if now is None else now)


def ready(conn=None, now: float | None = None) -> list[dict]:
    """Pending jobs whose start time has come, in run order; a deploy only with no sweep running, and no measurement while it waits. #900, #1506, #1672."""
    from harness import hold
    with _store(conn) as c:
        got = [j for j in pending(c) if due(j, now)]
    if any(j["kind"] == DEPLOY for j in got):
        from harness import deploy
        if deploy.paused():
            got = [j for j in got if j["kind"] != DEPLOY]
        elif deploy.blocked():
            got = [j for j in got if j["kind"] != DEPLOY and not hold.measurement(j)]
    return hold.startable(got, conn, now)


def _claimed(c) -> tuple[str, tuple]:
    """Jobs this machine claimed: an unowned running job is nobody's to recover. #703."""
    from harness import machine_scope
    return machine_scope.here(c, "jobs.claimed")


def running_here(conn=None) -> list[dict]:
    """Every job this machine's worker is running, oldest first. #1153."""
    with _store(conn) as c:
        where, args = _claimed(c)
        return _select(c, f"WHERE state = ? AND {where}", (RUNNING, *args))


def current(conn=None) -> dict | None:
    """The job this machine's worker is running, the GPU one when cloud evals run beside it, or None. #588, #1153."""
    got = running_here(conn)
    gpu = [j for j in got if needs(j) == GPU]
    return (gpu or got or [None])[-1]


def durations(title: str, conn=None, anywhere: bool = False) -> list[float]:
    """Seconds each finished, successful job with this title took here, or on any machine. #588, #697."""
    with _store(conn) as c:
        here, args = ("1 = 1", ()) if anywhere else _claimed(c)
        rows = c.execute("SELECT started_at, finished_at FROM jobs WHERE state = ? "
                         "AND title = ? AND started_at IS NOT NULL "
                         f"AND finished_at IS NOT NULL AND {here}",
                         (DONE, title, *args)).fetchall()
    return [float(r[1]) - float(r[0]) for r in rows if r[1] >= r[0]]


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
    _not_pending(c, job_id, verb)


def _not_pending(c, job_id, verb: str):
    """Raise why a job that is not pending, or not there, cannot be `verb`."""
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


def cancel(job_id: str, conn=None, grace: float = CANCEL_GRACE_S) -> dict:
    """Record a pending job cancelled; stop a running one's process group, wait, and record it cancelled. #628, #1364."""
    with _store(conn) as c:
        job = get(job_id, conn=c)
        if job is None or job["state"] != RUNNING:
            frm = PAUSED if job is not None and job["state"] == PAUSED else PENDING
            note = f"cancelled by soh jobs cancel at {time.strftime(_STAMP)}; " + (
                "it was paused" if frm == PAUSED else "before it started")
            if job is None or not js.move(c, job["id"], frm, CANCELLED, js.CANCEL, note, finished_at=time.time()):
                _not_pending(c, job_id, "cancelled")
            c.commit()
            return get(job_id, conn=c)
    pid = _pid_of(job["id"])
    if pid is None:
        raise ValueError(f"job {job['id']} is running but no process of it is on this "
                         f"machine; cancel it where it runs")
    _cancel_flag(job["id"]).write_text(time.strftime(_STAMP), encoding="utf-8")
    from harness import executors
    how = executors.for_job(job).stop(pid, grace)
    _settle_cancelled(job, how)
    return get(job["id"]) or job


def _settle_cancelled(job: dict, how: str = "") -> bool:
    """Move a running job cancelled; False when its worker recorded its exit first, which then stands. #1728."""
    said = {"term": "stopped on request", "kill": "killed after the grace period",
            "gone": "had already exited"}.get(how, "stopped")
    with _store() as c:
        took = js.move(c, job["id"], RUNNING, CANCELLED, js.CANCEL,
                       f"cancelled by soh jobs cancel at {time.strftime(_STAMP)}; {said}", finished_at=time.time())
        c.commit()
    return took


def _pids() -> Path:
    d = root() / "running"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _pid_file(job_id) -> Path:
    return _pids() / f"{label(job_id)}.pid"


def _cancel_flag(job_id) -> Path:
    return _pids() / f"{label(job_id)}.cancel"


def _item_flag(job_id) -> Path:
    return _pids() / f"{label(job_id)}.item"


def item_ended(environ=None) -> bool:
    """Mark that this queued job stopped at its item's end with cases left, so the worker queues its next item. #1618."""
    key = _key((environ if environ is not None else os.environ).get(JOB_ENV, ""))
    if key is None:
        return False
    _item_flag(key).write_text(time.strftime(_STAMP), encoding="utf-8")
    return True


def item_s(environ=None) -> float | None:
    """The seconds of this process's queue item, when the worker runs its job in items; None otherwise. #1618."""
    try:
        got = float((environ if environ is not None else os.environ).get(ITEM_ENV, ""))
    except ValueError:
        return None
    return got if got > 0 else None


def itemized(job: dict) -> bool:
    """Whether the worker runs a job in items: a gpu eval or paired adopt that sets no stop of its own. #1618."""
    from evals import run
    argv = [str(a) for a in job.get("argv") or []]
    if ITEM_S <= 0 or needs(job) != GPU or any(a.split("=")[0] in ("--stop-at", "--stop-after") for a in argv):
        return False
    if run.queued_args(argv) is not None:
        return True
    return (resources._verb(argv) == "adopt" and "--challenger" in argv
            and not {"--confirm", "--power", "--from-measurement", "--dry-run"} & set(argv))


def _flag_files(job_id) -> dict:
    """job_state flag name -> its file beside the job's pid file."""
    return {js.CANCEL_FLAG: _cancel_flag(job_id), js.STOP_FLAG: _stop_flag(job_id),
            js.ITEM_FLAG: _item_flag(job_id), js.DEPLOY_FLAG: _deploy_flag(job_id)}


def _flags(job_id) -> frozenset:
    """The flags set for a job, read once to choose its next move."""
    return frozenset(k for k, f in _flag_files(job_id).items() if f.exists())


def _clear_flags(job_id) -> None:
    for f in _flag_files(job_id).values():
        f.unlink(missing_ok=True)


def _pid_of(job_id) -> int | None:
    from harness import executors
    try:
        pid, started = executors.pid_record(_pid_file(job_id))
    except (OSError, ValueError):
        return None
    return pid if alive(pid) and _leads(pid, started) else None


def _leads(pid: int, started: str = "") -> bool:
    """Whether pid is still the job's started process: its own group's leader, started when its pid file says; a reused pid is not. #1728, #1820."""
    from harness import proc_identity
    return proc_identity.same({"pid": int(pid), "pgid": int(pid), "started": started}) is not False


def spawn_group(argv, cwd, stdout, env) -> subprocess.Popen:
    """Start argv as the leader of a new process group, stderr into stdout. #628."""
    if sys.platform == "win32":
        group = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    else:
        group = {"start_new_session": True}
    return subprocess.Popen(argv, cwd=cwd or None, stdout=stdout,
                            stderr=subprocess.STDOUT, env=env, **group)


def alive(pid: int) -> bool:
    """Whether a process with this pid exists (a zombie counts until reaped)."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x101000, False, int(pid))
        if not handle:
            return False
        try:
            code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return code.value == 259
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _group_alive(pid: int, proc=None) -> bool:
    """Whether a member of pid's group can still take a signal; reaps proc, the caller's own leader, first. #677."""
    if proc is not None:
        proc.poll()
    if sys.platform == "win32":
        return alive(pid)
    try:
        os.killpg(int(pid), 0)
    except (ProcessLookupError, PermissionError):  # EPERM on macOS: every member is a zombie or inside exit
        return sys.platform == "darwin" and _exiting_member(int(pid))
    if sys.platform.startswith("linux"):
        return _live_member(int(pid))
    return True


_KINFO_SIZE, _KINFO_P_STAT, _SZOMB = 648, 36, 5


def _pgrp_states(pgid: int):
    """The p_stat of each process in pgid, from macOS sysctl KERN_PROC_PGRP; None if unreadable. #1237."""
    import ctypes
    libc = ctypes.CDLL(None, use_errno=True)
    mib = (ctypes.c_int * 4)(1, 14, 2, int(pgid))  # CTL_KERN, KERN_PROC, KERN_PROC_PGRP
    size = ctypes.c_size_t(0)
    if libc.sysctl(mib, 4, None, ctypes.byref(size), None, 0):
        return None
    buf = ctypes.create_string_buffer(size.value + _KINFO_SIZE * 8)
    size = ctypes.c_size_t(len(buf))
    if libc.sysctl(mib, 4, buf, ctypes.byref(size), None, 0) or size.value % _KINFO_SIZE:
        return None
    return [buf.raw[off + _KINFO_P_STAT] for off in range(0, size.value, _KINFO_SIZE)]


def _exiting_member(pgid: int, read=_pgrp_states) -> bool:
    """macOS will not signal a member inside exit, which keeps its files until it is a zombie; unreadable counts. #1237."""
    states = read(pgid)
    return states is None or any(state != _SZOMB for state in states)


def _live_member(pgid: int, proc_root="/proc") -> bool:
    """Linux answers killpg for a group of zombies, so read each member's state; unreadable counts as live. #677."""
    try:
        names = os.listdir(proc_root)
    except OSError:
        return True
    seen = False
    for name in names:
        if not name.isdigit():
            continue
        try:
            stat = Path(proc_root, name, "stat").read_text(encoding="utf-8")
        except OSError:
            continue
        state, _, group = (stat.rpartition(")")[2].split() + ["", "", ""])[:3]
        if group == str(pgid):
            seen = True
            if state not in ("Z", "X"):
                return True
    return not seen


def stop_group(pid: int, grace: float = CANCEL_GRACE_S, sleep=time.sleep, proc=None) -> str:
    """Signal the process group led by pid, wait up to `grace`, then kill it: "term", "kill" or "gone". #628, #677."""
    if not _group_alive(pid, proc):
        return "gone"
    if sys.platform == "win32":
        # The tree is walked from a live leader, and a console child has no SIGTERM to catch.
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(int(pid))], capture_output=True)
        deadline = time.monotonic() + grace
        while _group_alive(pid, proc) and time.monotonic() < deadline:
            sleep(0.1)
        return "kill"
    try:
        os.killpg(int(pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        if not _group_alive(pid, proc):
            return "gone"
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline:
        if not _group_alive(pid, proc):
            return "term"
        sleep(0.1)
    try:
        os.killpg(int(pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        return "term"
    return "kill"


def _pause_flag() -> Path:
    return root() / "paused"


def paused() -> bool:
    return _pause_flag().exists()


def pause(why: str = "", holder: int | None = None) -> None:
    """Pause the queue; a holder pid makes it a hold that ends with that process, not an owner's pause. #1760."""
    _pause_flag().write_text(queue_hold.text(why, holder), encoding="utf-8")


def resume() -> None:
    _pause_flag().unlink(missing_ok=True)


def _pressed(level, now: float) -> tuple[bool, str]:
    """Memory pressure holds every job but a deploy at the head of the queue past its bound on it. #1672."""
    from harness import contention, deploy
    try:
        with _store() as c:
            head = ready(c, now)[:1]
            since = deploy.waiting_since(c, head[0]["id"])[0] if head and head[0]["kind"] == DEPLOY else None
    except RuntimeError:
        since = None
    if since is None:
        return False, f"memory pressure level {level}"
    if now - since < contention.DEPLOY_PRESSURE_S:
        return False, f"memory pressure level {level}; the deploy waits on it until {contention.pressure_until(since)}"
    return True, (f"memory pressure level {level}; only the deploy starts, past its "
                  f"{contention.DEPLOY_PRESSURE_S:.0f} s bound on memory pressure")


def gate(sample=None, now: float | None = None) -> tuple[bool, str]:
    """(open, why): may the next job start now? A running job always finishes. #573."""
    from harness import env, pressure
    lifted = queue_hold.lift([_held_flag(), _pause_flag()])
    if paused():
        return False, queue_hold.why_paused(_pause_flag())
    if lifted:
        ok, why = gate(sample, now)
        return ok, f"{'; '.join(lifted)}; {why}"
    from harness import serve_lease
    serving = serve_lease.held()
    if serving:
        # Serving comes first: a job started now would load a model under a delegation. #1556.
        return False, f"serving {serving}"
    vol = env.unmounted(env.configured())
    if vol:
        return False, f"paused until it returns: the weights volume {vol} {env.NOT_MOUNTED}"
    p = (sample or pressure.sample)()
    if p.alarming:
        return _pressed(p.level, time.time() if now is None else now)
    return True, "memory pressure normal" if p.level is not None else "memory pressure unknown"


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


def _in_group(job: dict):
    """A popen that runs the job under its executor, which leaves its pid where cancel finds it. #628, #1508."""
    from harness import executors
    run = executors.for_job(job).run
    return lambda argv, cwd=None, stdout=None, stderr=None, env=None: run(job, argv, cwd=cwd, stdout=stdout, env=env)


def _claim(job: dict, log: Path) -> bool:
    """Take a pending job for this machine in one statement, so two workers cannot both run it. #703."""
    started = time.strftime(_STAMP)
    from harness import machine_scope
    with _store() as c:
        mid = _machine(c)
        here, args = machine_scope.where("jobs.claimable", mid)
        took = js.move(c, job["id"], PENDING, RUNNING, js.CLAIMED, started_at=_epoch(started), log=str(log),
                       machine_id=mid, where=here, args=args)
        c.commit()
    if took:
        job.update(state=RUNNING, started=started, log=str(log), machine_id=mid)
    return took


def _unclaim(job: dict, why: str) -> None:
    with _store() as c:
        js.move(c, job["id"], RUNNING, PENDING, js.UNCLAIMED, why, started_at=None, log="")
        c.commit()


def _loads(n) -> str:
    """A lease's detail: which models were resident when it was taken and what it loads. #1617."""
    said = [f"resident {', '.join(n.resident)}" if n.resident else "",
            f"loads {', '.join(f'{s} {g} GiB' for s, g in n.priced)}" if n.priced else ""]
    return n.why or "; ".join(x for x in said if x)


def _detail(job: dict, n) -> str:
    """The lease's detail: its loads, and for an item the seconds it is planned to run. #1617, #1618."""
    planned = f"an item of up to {ITEM_S:.0f}s" if itemized(job) else ""
    return "; ".join(x for x in (_loads(n), planned) if x)


@contextmanager
def leased(job: dict, pid: int | None = None):
    """Hold the job's lease on its class, beaten every TTL_S/3 while the block runs; yields it, or None at capacity. #1558."""
    from harness import admission, item_lease
    cls, said = needs(job), {}
    # A job a gone worker left running is already loaded; only a new start is admitted. #1558.
    n = admission.need(job) if cls == GPU and pid is None else admission.Need(None, why="not a new gpu load")

    def fits(held):
        lapsed = exclusive._lapsed(c, time.time())
        if lapsed:
            said["why"] = f"gpu lease {lapsed[0]['id']} ({lapsed[0]['item']}) lapsed while its holder still runs"
            return False
        ok, said["why"] = admission.admit(n, held)
        return ok
    with _store() as c:
        got = item_lease.take(c, cls, f"job {label(job['id'])}", job_id=int(job["id"]), pid=pid,
                              priority=int(job.get("priority") or 0), mem_gb=n.gb,
                              fits=fits if cls == GPU and pid is None else None, detail=_detail(job, n))
    if got is None:
        job["refused"] = said.get("why") or f"{cls} is leased to capacity; waits for a free place"
        yield None
        return
    stop = threading.Event()

    def keep():
        ok_at, wait = time.monotonic(), item_lease.TTL_S / 3
        while not stop.wait(wait):
            try:
                with _store() as c:
                    if item_lease.beat(c, got["id"]):
                        ok_at, wait = time.monotonic(), item_lease.TTL_S / 3
                        continue
                why = "its lease lapsed or was released"
            except Exception as exc:  # noqa: BLE001 - a store that will not answer is retried until the deadline
                gone = time.monotonic() - ok_at
                why = f"no lease beat for {gone:.0f}s: {exc}"
                print(f"{time.strftime('%H:%M:%S')} job {job['id']}: lease beat failed: {exc}", flush=True)
                if gone < item_lease.TTL_S * 2 / 3:
                    wait = item_lease.TTL_S / 12
                    continue
            if not stop.is_set():
                _lease_lost(job, why)
            return

    beating = threading.Thread(target=keep, name=f"lease-{job['id']}", daemon=True)
    beating.start()
    try:
        yield got
    finally:
        stop.set()
        with _store() as c:
            item_lease.release(c, got["id"])


def _lease_lost(job: dict, why: str) -> None:
    """Stop a job whose lease is gone or about to lapse, so no second job takes its class under it. #1728, #1732."""
    from harness import executors
    print(f"{time.strftime('%H:%M:%S')} job {job['id']}: lease lost ({why}); stopping it", flush=True)
    pid = _pid_of(job["id"])
    if pid is not None:
        executors.for_job(job).stop(pid, CANCEL_GRACE_S)


def run_one(job: dict, popen=None) -> dict | None:
    """Run a pending job here under its lease; None when another worker claimed it first or its class is full."""
    log = log_dir() / f"{job['id']}.log"
    if not _claim(job, log):
        return None
    with leased(job) as lease:
        if lease is None:
            _unclaim(job, job["refused"])
            return None
        return _run_claimed(job, log, popen)


def _bin(venv: Path) -> Path:
    return venv / ("Scripts" if sys.platform == "win32" else "bin")


def job_venv(cwd, environ) -> dict:
    """environ with VIRTUAL_ENV and its PATH entry moved to the .venv of the checkout cwd is in, or dropped. #1655."""
    env = dict(environ)
    was = env.pop("VIRTUAL_ENV", "")
    if not was:
        return env
    here = Path(cwd).resolve()
    root = next((p for p in (here, *here.parents) if (p / "pyproject.toml").is_file()), None)
    venv = root / ".venv" if root is not None and (root / ".venv").is_dir() else None
    if venv is not None:
        env["VIRTUAL_ENV"] = str(venv)
    if "PATH" in env:
        old = os.path.normcase(str(_bin(Path(was))))
        new = str(_bin(venv)) if venv is not None else ""
        moved = (new if os.path.normcase(p) == old else p for p in env["PATH"].split(os.pathsep))
        env["PATH"] = os.pathsep.join(p for p in moved if p)
    return env


def _run_claimed(job: dict, log: Path, popen=None) -> dict | None:
    with _store() as c:
        stale = stale_schema(job["cwd"] or ".", c)
        if stale:
            log.write_text(f"not started: {stale}\n", encoding="utf-8")
            js.move(c, job["id"], RUNNING, FAILED, js.NOT_STARTED, f"not started: {stale}", rc=None,
                    finished_at=time.time())
            c.commit()
            return get(job["id"], conn=c) or job
    env = {**job_venv(job["cwd"] or ".", os.environ), JOB_ENV: str(int(job["id"]))}
    env.pop(ITEM_ENV, None)
    if itemized(job):
        env[ITEM_ENV] = f"{ITEM_S:g}"
    _clear_flags(job["id"])
    popen = popen or _in_group(job)
    # No machine lock here: each command takes it for the part that loads a
    # model, so a job that is downloading does not block a GPU run. #371.
    with open(log, "a", encoding="utf-8") as out:
        try:
            rc = popen(job["argv"], cwd=job["cwd"], stdout=out,
                       stderr=subprocess.STDOUT, env=env).returncode
        except OSError as exc:
            out.write(f"could not start: {exc}\n")
            rc = 127
    job.update(rc=rc, finished=time.strftime(_STAMP))
    if _settle_exit(job, rc):
        # Left running and unwritten: the store may be migrated past this code; settle closes it. #1506.
        return {**job, "state": RUNNING, "handed_off": True}
    return get(job["id"]) or job


def _settle_exit(job: dict, rc) -> bool:
    """Move a job whose process exited, as job_state.exit_move chooses from its flags and rc; True when a handed-off deploy stays running. #1728."""
    from evals import watch
    from harness import contention, deploy
    flags = _flags(job["id"])
    handed = job.get("kind") == DEPLOY and rc == deploy.HANDED_OFF
    with _store() as c:
        contended = rc == watch.PAUSED and js.DEPLOY_FLAG not in flags and contention.paused_for(c, job)
        to, why = js.exit_move(rc, flags, handed, contended)
        if to == RUNNING:
            return True
        argv = _item_argv(c, job) if why == js.NEXT_ITEM else None
        if why == js.NEXT_ITEM and argv is None:
            to, why = js.exit_move(rc, flags - {js.ITEM_FLAG}, handed, contended)
        if why == js.DEPLOY_STOP:
            _repend_stopped(c, job)
        elif why in (js.DEPLOY_PAUSE, js.CONTENTION_PAUSE):
            _repend(c, job, why)
        elif why == js.NEXT_ITEM:
            _next_item(c, job, argv)
        else:
            note = f"cancelled by soh jobs cancel at {time.strftime(_STAMP)}; stopped" if why == js.CANCEL else None
            if why == js.CHECKPOINTED:
                from harness import paused_jobs
                why, note = paused_jobs.cause(c, job)
            js.move(c, job["id"], RUNNING, to, why, note, rc=rc, finished_at=_epoch(job["finished"]))
            c.commit()
    _clear_flags(job["id"])
    return False


def resume_argv(argv: list, out) -> list[str]:
    """argv without any --out or --resume, then --out `out` --resume."""
    got, skip = [], False
    for a in map(str, argv):
        if skip:
            skip = False
        elif a == "--out":
            skip = True
        elif a != "--resume" and not a.startswith("--out="):
            got.append(a)
    return [*got, "--out", str(out), "--resume"]


def _resumed(c, job: dict) -> list | None:
    """The argv that resumes an eval job from its stored run, or None when it is no eval or stored none. #1509."""
    from harness import runs
    if confirms(job):
        return list(job["argv"])
    run = runs.for_job(c, int(job["id"]))
    if "evals.run" not in [str(a) for a in job["argv"]] or run is None:
        return None
    return resume_argv(job["argv"], runs.run_dir(run["path"]))


def confirms(job: dict) -> bool:
    """Whether a job is `soh adopt --confirm`, whose own argv resumes the newest unfinished run of its pair. #1357, #1675."""
    argv = [str(a) for a in job.get("argv") or []]
    return resources._verb(argv) == "adopt" and "--confirm" in argv


def _item_argv(c, job: dict) -> list | None:
    """The argv of a job's next item: its eval resumed from its stored run, or its own; None when an eval stored none. #1618."""
    from evals import run
    return _resumed(c, job) if run.queued_args(job["argv"]) is not None else list(job["argv"])


def _next_item(c, job: dict, argv: list) -> bool:
    """A job that stopped at its item's end waits again for its next item, resumed where it stopped. #1618."""
    took = (_epoch(job.get("finished")) or time.time()) - (_epoch(job.get("started")) or time.time())
    moved = js.move(c, job["id"], RUNNING, PENDING, js.NEXT_ITEM,
                    f"item ended after {took:.0f}s of a planned {ITEM_S:.0f}s; the next item waits its turn",
                    finished_at=None, rc=job.get("rc"), argv=json.dumps(argv))
    c.commit()
    if moved:
        from harness import cuts
        cuts.cut("queue_item", f"job {label(job['id'])}: an item ended after {took:.0f}s; the next waits its turn", kept=1)
    return moved


def _repend(c, job: dict, why: str) -> bool:
    """A job paused for contention or a deploy waits again to resume where it stopped, unless it queued its own continuation. #1509, #1672."""
    from harness import machine_scope
    here, mine = machine_scope.where("jobs.twin", job.get("machine_id"))
    twin = c.execute(f"SELECT id FROM jobs WHERE argv = ? AND state = ? AND id != ? AND {here}",
                     (json.dumps([str(a) for a in job["argv"]]), PENDING, int(job["id"]), *mine)).fetchone()
    if twin is not None:
        moved = js.move(c, job["id"], RUNNING, PAUSED, js.CONTINUED, f"paused; job {label(twin[0])} continues it",
                        rc=job.get("rc"), finished_at=_epoch(job.get("finished")))
        c.commit()
        return moved
    argv = _resumed(c, job) or list(job["argv"])
    note = ("paused for a deploy at {}; resumes after it" if why == js.DEPLOY_PAUSE else
            "paused for contention at {}; resumes when the contention gate opens").format(job.get("finished"))
    moved = js.move(c, job["id"], RUNNING, PENDING, why, note, finished_at=None, rc=job.get("rc"),
                    argv=json.dumps(argv))
    c.commit()
    return moved


def _deploy_flag(job_id) -> Path:
    return _pids() / f"{label(job_id)}.deploy"


def _stop_flag(job_id) -> Path:
    return _pids() / f"{label(job_id)}.stopped"


def paused_for_deploy(environ=None) -> bool:
    """Whether a due deploy asked this queued job to pause, so the worker re-pends it rather than it queueing a continuation. #1675."""
    key = _key((environ if environ is not None else os.environ).get(JOB_ENV, ""))
    return key is not None and _deploy_flag(key).exists()


def _repend_stopped(c, job: dict) -> bool:
    """A running job a deploy stopped waits again, resumed where it stopped when it can be; False when its exit was recorded first. #1675."""
    try:
        said = json.loads(_stop_flag(job["id"]).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        said = {}
    argv = (said.get("argv") if isinstance(said, dict) else None) or _resumed(c, job) or list(job["argv"])
    moved = js.move(c, job["id"], RUNNING, PENDING, js.DEPLOY_STOP,
                    f"stopped for a deploy at {time.strftime(_STAMP)}; resumes after it",
                    started_at=None, finished_at=None, argv=json.dumps(argv))
    c.commit()
    return moved


def _stopped_argv(job: dict, pids: set) -> list[str] | None:
    """The argv that resumes a bare eval job from the one run its processes were writing, or None. #1675."""
    from harness import run_state, sweep_guard
    if "evals.run" not in [str(a) for a in job["argv"]]:
        return None
    outs = set()
    for path in sorted(paths.runs().glob(f"*/{sweep_guard.PROGRESS}")):
        got = run_state.of(path.parent, alive=lambda pid, pgid, started="": sweep_guard._pid(pid) in pids)
        if got.name in run_state.LIVE and sweep_guard._pid(got.progress.get("pid")) in pids:
            outs.add(path.parent)
    return resume_argv(job["argv"], outs.pop()) if len(outs) == 1 else None


def _held_flag() -> Path:
    return root() / "paused.deploy"


def hold_for_deploy(grace: float = CANCEL_GRACE_S, stop=None, tree=None, stop_rest=None, holder=None) -> list[str]:
    """LH_DEPLOY_DURING_SWEEP: pause the queue for the install, then stop each job running here, every process under it, to resume after. #1675."""
    from harness import executors, sweep_guard
    said = queue_hold.lift([_held_flag(), _pause_flag()])
    if not paused():
        # The marker goes down before the pause it marks, so no death between them leaves an owner-looking pause. #1754.
        text = queue_hold.text(f"held for a deploy by pid {holder or os.getpid()}", holder)
        _held_flag().write_text(text, encoding="utf-8")
        _pause_flag().write_text(text, encoding="utf-8")
        said.append("queue held for the deploy; it is released when the install ends")
    elif _held_flag().exists():
        said.append("queue already held for a deploy; it is released when the install ends")
    else:
        said.append("queue was already paused by its owner and stays paused after the deploy (soh jobs resume)")
    for job in running_here():
        pid = _pid_of(job["id"])
        if job["kind"] == DEPLOY or pid is None:
            continue
        # Snapshot first: a process measure started in its own session is not in the job's group.
        procs = (tree or _tree)(pid)
        under = [{"pid": p} for p, _ in procs if p != pid]
        _stop_flag(job["id"]).write_text(json.dumps({"at": time.strftime(_STAMP), "argv": _stopped_argv(
            job, {p for p, _ in procs})}), encoding="utf-8")
        how = (stop or executors.for_job(job).stop)(pid, grace)
        rest = [r for r in under if alive(r["pid"])]
        left = (stop_rest or sweep_guard.stop)(rest, grace=grace, alive=alive) if rest else []
        with _store() as c:
            _repend_stopped(c, job)
        tail = f"; pid(s) {', '.join(map(str, left))} outlived SIGKILL" if left else ""
        said.append(f"job {job['id']} stopped for the deploy ({how}); it resumes after it{tail}")
    return said


def release_for_deploy() -> str:
    """Lift the hold hold_for_deploy set, whatever the install did; an owner's pause, or one set since, stays. #1675."""
    return queue_hold.release(_held_flag(), _pause_flag())


def _tree(pid: int) -> list[tuple[int, str]]:
    """(pid, command) of pid and every process under it, in any session, from ps; [] where there is none to ask. #1675."""
    from harness import sweep_guard
    if sys.platform == "win32":
        return []
    try:
        got = subprocess.run(["ps", "-ww", "-axo", "pid=,ppid=,command="], capture_output=True, text=True,
                             timeout=sweep_guard.PS_TIMEOUT_S)
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"{time.strftime('%H:%M:%S')} could not list the processes of pid {pid}: {exc}", flush=True)
        return []
    rows = [r for r in (ln.split(None, 2) for ln in got.stdout.splitlines()) if len(r) >= 2 and r[0].isdigit()]
    kids: dict[str, list] = {}
    for r in rows:
        kids.setdefault(r[1], []).append(r)
    found, seen, todo = [], set(), [r for r in rows if r[0] == str(pid)]
    while todo:
        r = todo.pop(0)
        if r[0] in seen:
            continue
        seen.add(r[0])
        found.append((int(r[0]), r[2] if len(r) == 3 else ""))
        todo += kids.get(r[0], [])
    return found


def _evals_in(pid: int) -> list[int]:
    """Pids of the evals.run processes under pid: measure starts each in a session of its own, so not its group. #1672, #1675."""
    from harness import sweep_guard
    return [p for p, command in _tree(pid) if sweep_guard.EVAL.search(command)]


def preempt_for_deploy(now: float | None = None, evals=None, signal_=None) -> list[str]:
    """A due deploy asks each running measurement job's evals here to pause at their next case; the job then waits to resume. #1672."""
    from harness import deploy, hold
    sig = signal_ if signal_ is not None else getattr(signal, "SIGUSR1", None)
    if sig is None or deploy.paused():
        return []
    with _store() as c:
        if not any(j["kind"] == DEPLOY and due(j, now) for j in pending(c)):
            return []
        busy = [j for j in running_here(c) if hold.measurement(j)]
    said = []
    for job in busy:
        pid, flag = _pid_of(job["id"]), _deploy_flag(job["id"])
        asked = set(flag.read_text(encoding="utf-8").split()) if flag.exists() else set()
        fresh = [p for p in (evals or _evals_in)(pid) if str(p) not in asked] if pid is not None else []
        for p in fresh:
            try:
                os.kill(p, sig)
            except OSError as exc:
                said.append(f"job {job['id']}: eval {p} not asked to pause: {exc}")
                continue
            asked.add(str(p))
            said.append(f"job {job['id']}: eval {p} asked to pause at its next case for the pending deploy")
        if asked:
            flag.write_text(" ".join(sorted(asked)), encoding="utf-8")
    return said + _ask_loop(sig, evals or _evals_in)


def _ask_loop(sig, evals) -> list[str]:
    """The scheduled sweep yields at its next checkpoint, its evals pause after their case, and it goes on on the new release. #1675."""
    from harness import heartbeat, sweep_guard
    beat = heartbeat.read() or {}
    if beat.get("state") != heartbeat.RUNNING or not beat.get(heartbeat.YIELDS):
        return []
    said = []
    for r in sweep_guard.running(paths.home()):
        if r["what"] != "discover loop" or r["pid"] != beat.get("pid"):
            continue
        # Asked each turn: an eval the loop starts before its checkpoint is asked too.
        for p in [r["pid"], *evals(r["pid"])]:
            try:
                os.kill(p, sig)
            except OSError as exc:
                said.append(f"discover loop {r['pid']}: {p} not asked to yield: {exc}")
        flag = root() / "loop-yield"
        if not flag.exists() or flag.read_text(encoding="utf-8") != str(r["pid"]):
            flag.write_text(str(r["pid"]), encoding="utf-8")
            said.append(f"discover loop {r['pid']} asked to yield at its next checkpoint for the pending deploy")
    return said


def _settle_gone(c, job: dict) -> None:
    """A running job whose worker and process are gone, as job_state.gone_move chooses: an eval that stored a run, or a confirm, waits again to resume it, else it failed."""
    flags = _flags(job["id"])
    argv = None if flags & {js.CANCEL_FLAG, js.STOP_FLAG} else _resumed(c, job)
    to, why = js.gone_move(flags, argv is not None)
    if why == js.DEPLOY_STOP:
        _repend_stopped(c, job)
    elif why == js.WORKER_GONE:
        js.move(c, job["id"], RUNNING, PENDING, why, "its worker went away; resumes from its stored run",
                started_at=None, argv=json.dumps(argv))
    elif why == js.CANCEL:
        js.move(c, job["id"], RUNNING, CANCELLED, why, "cancelled by soh jobs cancel; its worker went away "
                "before it recorded the exit", finished_at=time.time())
    else:
        js.move(c, job["id"], RUNNING, to, why, "interrupted; add it again to retry")
    c.commit()
    _clear_flags(job["id"])


def _recover() -> list[dict]:
    """At the runner's start each running job here lost its worker: those whose process runs on, to watch; the rest settled. #1558."""
    settle_deploys()
    left = []
    with _store() as c:
        where, args = _claimed(c)
        for job in _select(c, f"WHERE state = ? AND kind != ? AND {where}", (RUNNING, DEPLOY, *args)):
            if _pid_of(job["id"]) is not None:
                left.append(job)
            else:
                _settle_gone(c, job)
    return left


def _watch_left(job: dict, poll: float = WATCH_S) -> None:
    """Lease a job a gone worker left running until its process exits, then settle it. #1558."""
    pid = _pid_of(job["id"])
    if pid is not None:
        with leased(job, pid=pid):
            while alive(pid):
                time.sleep(poll)
    _pid_file(job["id"]).unlink(missing_ok=True)
    with _store() as c:
        _settle_gone(c, job)


def settle_deploys() -> list:
    """deploy.settle, logged rather than raised: a settle error must not stop the worker. #1506."""
    import sqlite3

    from harness import deploy
    try:
        got = deploy.settle()
    except (OSError, ValueError, RuntimeError, sqlite3.Error) as exc:
        print(f"{time.strftime('%H:%M:%S')} deploy settle failed: {exc}", flush=True)
        return []
    for d in got:
        print(f"{time.strftime('%H:%M:%S')} settled {d}", flush=True)
    return got


def watch_deploys(now: float | None = None) -> dict | None:
    """deploy.watch_wait, logged rather than raised: a pending deploy waiting too long alerts once. #1672."""
    from harness import deploy
    try:
        got = deploy.watch_wait(now)
    except Exception as exc:  # noqa: BLE001 - a check of the wait must not stop the worker, on any store
        print(f"{time.strftime('%H:%M:%S')} deploy wait check failed: {exc}", flush=True)
        return None
    if got is not None:
        print(f"{time.strftime('%H:%M:%S')} alerted: {deploy.wait_line(got)}", flush=True)
    return got


def deploy_turn(now: float) -> None:
    """Each worker turn: a pending deploy pauses measurement for itself and alerts once if it waits too long. #1672."""
    try:
        said = preempt_for_deploy(now)
    except Exception as exc:  # noqa: BLE001 - preempting must not stop the worker, on any store
        said = [f"preempting for the deploy failed: {exc}"]
    for line in said:
        print(f"{time.strftime('%H:%M:%S')} {line}", flush=True)
    watch_deploys(now)


def needs(job: dict) -> str:
    """The resource class a job waits for (resources.of). #1153, #1508."""
    return resources.of(job)


def _free(cls: str, live: dict) -> bool:
    """Whether a job of this class may start beside the jobs in `live` (thread -> (class, id)). #1153, #1508."""
    if cls == DEPLOY or any(c == DEPLOY for c, _ in live.values()):
        return not live
    mine = sum(1 for c, _ in live.values() if c == cls)
    if resources.node_of(cls):
        # A run started by hand holds the node's lease too. #1689.
        from harness import item_lease
        with _store() as c:
            mine = max(mine, len(item_lease.live(c, cls)))
    if cls == GPU:
        # A gpu lease taken outside the queue (with-gpu-lock, soh image) holds the class too. #1619.
        try:
            mine = max(mine, exclusive.gpu_leases())
        except exclusive.StoreDown as exc:
            print(f"{time.strftime('%H:%M:%S')} {exclusive.refuse('worker', exc)}", flush=True)
            return False
    if cls == CLOUD:
        # Cloud evals outside the queue hold cloud slots too. #1135.
        mine = max(mine, sum(exclusive._taken(exclusive.cloud_lock_path(i))
                             for i in range(resources.capacity(CLOUD))))
    return mine < resources.capacity(cls)


def _contended(now: float, job: dict | None = None) -> bool:
    """Whether the contention gate holds GPU jobs, or this deploy, at now. #1509, #1672."""
    from harness import contention, deploy
    with _store() as c:
        since = deploy.waiting_since(c, job["id"])[0] if job is not None and needs(job) == DEPLOY else None
        return not contention.gate(c, now, since=since)[0]


def _admitted(job: dict) -> bool:
    """Whether memory admits a gpu job now; a refused one waits, its note naming the numbers once. #1558."""
    from harness import admission, item_lease
    with _store() as c:
        ok, why = admission.admit(admission.need(job), item_lease.live(c))
        if not ok and job.get("note") != f"waits for memory: {why}":
            c.execute("UPDATE jobs SET note = ? WHERE id = ? AND state = ?",
                      (f"waits for memory: {why}", int(job["id"]), PENDING))
            c.commit()
    return ok


def _on_node(job: dict, cls: str) -> bool:
    """Whether the node a job's class is on admits it now by its own report; a refused one waits, its note naming why. #1689."""
    from evals import run
    from harness import node_state
    args = run.queued_args(job.get("argv") or [])
    _, held = node_state.placed(run.split_candidates(getattr(args, "candidates", "") or "")) if args else ("", [])
    ok, why = node_state.admits(resources.node_of(cls), held)
    if not ok and job.get("note") != f"waits for its node: {why}":
        with _store() as c:
            c.execute("UPDATE jobs SET note = ? WHERE id = ? AND state = ?",
                      (f"waits for its node: {why}", int(job["id"]), PENDING))
            c.commit()
    return ok


def _affine(job: dict, rest: list[dict], blocked) -> dict:
    """The first gpu job at job's priority whose models are all resident, job itself first; else job. #1617."""
    from harness import admission
    held = admission._resident()

    def loaded(j):
        n = admission.need(j, resident=lambda: held)
        return n.gb == 0.0 and bool(n.resident)
    same = [j for j in rest if needs(j) == GPU and int(j.get("priority") or 0) == int(job.get("priority") or 0)]
    return next((j for j in [job, *same] if (j is job or not blocked(j)) and loaded(j)), job)


def _startable(live: dict, now: float) -> tuple[dict, str] | None:
    """The first ready job, in run order, whose lock class is free; a GPU job or deploy only past the contention gate. #1153, #1509."""
    from harness import contention
    started, held = {i for _, i in live.values()}, []
    jobs = [j for j in ready(now=now) if j["id"] not in started]

    def blocked(job) -> bool:
        if not contention.batch(job):
            return False
        if needs(job) == DEPLOY:
            return _contended(now, job)
        if not held:
            held.append(_contended(now))
        return held[0]
    for at, job in enumerate(jobs):
        cls = needs(job)
        if resources.node_of(cls):
            # A node's work loads nothing here, so this machine's contention and memory never hold it. #1689.
            if _free(cls, live) and _on_node(job, cls):
                return job, cls
            continue
        if cls in (GPU, DEPLOY) and blocked(job):
            if cls == DEPLOY:
                return None
            continue
        if cls == GPU and _free(cls, live) and (pick := _affine(job, jobs[at + 1:], blocked)) is not job \
                and _admitted(pick):
            return pick, cls
        if _free(cls, live) and (cls != GPU or _admitted(job)):
            return job, cls
        if cls == DEPLOY:
            return None  # a ready deploy waits for the running jobs, and nothing new starts ahead of it. #1506
    return None


def run_pending(popen=None, gate=lambda: (True, ""), clock=time.time, watch: float = WATCH_S) -> list[dict]:
    """Work the queue while the gate stays open: one GPU job, and cloud evals beside it in free cloud slots. #1153."""
    fd = _runner_lock()
    if fd is None:
        return []
    done, errors, live = [], [], {}
    finished, handed = threading.Event(), threading.Event()

    def work(job):
        try:
            ran = run_one(job, popen=popen)
            if ran is not None:
                done.append(ran)
                if ran.get("handed_off"):
                    handed.set()
        except BaseException as exc:  # noqa: BLE001 - raised again once the other jobs finish
            errors.append(exc)
        finally:
            finished.set()

    try:
        for job in _recover():
            t = threading.Thread(target=_watch_left, args=(job, watch), name=f"left-{job['id']}", daemon=True)
            live[t] = (needs(job), job["id"])
            t.start()
        while True:
            finished.clear()
            live = {t: c for t, c in live.items() if t.is_alive()}
            # Nothing starts beside a deploy, and once it migrates this release's store reads are refused. #1795.
            deploying = any(c == DEPLOY for c, _ in live.values())
            if not deploying:
                deploy_turn(clock())
            nxt = None if errors or handed.is_set() or deploying else _startable(live, clock())
            if nxt is not None and gate()[0]:
                t = threading.Thread(target=work, args=(nxt[0],), name=f"job-{nxt[0]['id']}")
                live[t] = (nxt[1], nxt[0]["id"])
                t.start()
                continue
            if not live:
                if errors:
                    raise errors[0]
                return done
            finished.wait(watch)
    finally:
        for t in live:
            t.join()
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


def serve(poll: float = 30.0, sleep=time.sleep, popen=None,
          gate_fn=None, forever=True, clock=time.time) -> None:
    """The worker service: check the gate every `poll` seconds, run what waits."""
    from harness import paused_jobs
    gate_fn = gate_fn or gate
    said = ""
    while True:
        settle_deploys()
        deploy_turn(clock())
        paused_jobs.turn(clock())
        try:
            waiting = ready(now=clock())
        except RuntimeError as exc:
            # A deploy migrated the store past this worker's code; its switch reloads the worker. #1506.
            print(f"{time.strftime('%H:%M:%S')} waiting for a reload: {exc}", flush=True)
            waiting = []
        if waiting:
            ok, why = gate_fn()
            if why != said:
                print(f"{time.strftime('%H:%M:%S')} {'running' if ok else 'waiting'}: {why}",
                      flush=True)
                said = why
            if ok:
                ran = run_pending(popen=popen, gate=gate_fn, clock=clock)
                for j in ran:
                    print(f"{time.strftime('%H:%M:%S')} {j['id']} {j['state']} "
                          f"rc={j['rc']} {j['title']}", flush=True)
                if ran:
                    continue
        if not forever:
            return
        sleep(poll)


if __name__ == "__main__":
    import sys
    if sys.argv[1:] == ["quiesce"]:
        from harness import quiesce as _quiesce
        sys.exit(_quiesce.cli())
    if sys.argv[1:] == ["hold-for-deploy"]:
        print("\n".join(hold_for_deploy(holder=queue_hold.from_env())), flush=True)
        sys.exit(0)
    if sys.argv[1:] == ["release-for-deploy"]:
        print(release_for_deploy(), flush=True)
        sys.exit(0)
    serve(poll=float(os.environ.get("LH_QUEUE_POLL", "30")))
