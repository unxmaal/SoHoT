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

from harness import exclusive, paths, resources

PENDING, RUNNING, DONE, FAILED = "pending", "running", "done", "failed"
CANCELLED = "cancelled"
#: A job whose command paused on request with its work checkpointed (evals.watch.PAUSED). #1357.
PAUSED = "paused"
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
            "rc": r["rc"], "log": r["log"], "note": r["note"],
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
        not_before: float | None = None, conn=None, resource: str = "") -> dict:
    if resource:
        resources.check(resource)
    if not argv:
        raise ValueError("a job needs a command")
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
            "INSERT INTO jobs (title, kind, output, priority, argv, cwd, state, "
            "created_at, requested_by, machine_id, not_before, resource) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (title or " ".join(argv), kind, output, int(priority),
             json.dumps([str(a) for a in argv]), cwd or os.getcwd(), PENDING,
             time.time(), requested_by, machine,
             None if not_before is None else float(not_before), resource))
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


def due(job: dict, now: float | None = None) -> bool:
    """Whether a job's earliest start has come. #900."""
    at = _epoch(job.get("not_before")) if job.get("not_before") else None
    return at is None or at <= (time.time() if now is None else now)


def ready(conn=None, now: float | None = None) -> list[dict]:
    """Pending jobs whose start time has come, in run order; a deploy only with no sweep running. #900, #1506."""
    with _store(conn) as c:
        got = [j for j in pending(c) if due(j, now)]
    if any(j["kind"] == DEPLOY for j in got):
        from harness import deploy
        if deploy.blocked():
            got = [j for j in got if j["kind"] != DEPLOY]
    from harness import hold
    return hold.startable(got, conn, now)


def _claimed(c) -> tuple[str, tuple]:
    """Jobs this machine claimed: an unowned running job is nobody's to recover. #703."""
    from harness import memory_store as ms
    mid = ms.machine_row(c)
    if mid is None:
        # _claim stamps the machine, so a machine with no row has claimed nothing.
        return "1 = 0", ()
    return "machine_id = ?", (mid,)


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
        if anywhere:
            where, args = "1 = 1", ()
        else:
            # An unstamped job ran on some machine, not necessarily this one.
            from harness import memory_store as ms
            mid = ms.machine_row(c)
            where, args = ("machine_id = ?", (mid,)) if mid is not None else ("0 = 1", ())
        rows = c.execute("SELECT started_at, finished_at FROM jobs WHERE state = ? "
                         "AND title = ? AND started_at IS NOT NULL "
                         f"AND finished_at IS NOT NULL AND {where}",
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
            note = f"cancelled by soh jobs cancel at {time.strftime(_STAMP)}; before it started"
            _only_pending(c, job_id, "UPDATE jobs SET state = ?, finished_at = ?, note = ?",
                          (CANCELLED, time.time(), note), verb="cancelled")
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


def _settle_cancelled(job: dict, how: str = "", rc=None) -> None:
    said = {"term": "stopped on request", "kill": "killed after the grace period",
            "gone": "had already exited"}.get(how, "stopped")
    note = f"cancelled by soh jobs cancel at {time.strftime(_STAMP)}; {said}"
    stored = get(job["id"])
    if not how and stored and stored["state"] == CANCELLED:
        note = stored["note"]
    job.update(state=CANCELLED, finished=job.get("finished") or time.strftime(_STAMP),
               note=note, rc=job.get("rc") if rc is None else rc)
    _write(job)


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


def _pid_of(job_id) -> int | None:
    try:
        pid = int(_pid_file(job_id).read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None
    return pid if alive(pid) else None


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
    if paused():
        return False, "paused (soh jobs resume)"
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


def quiesce(wait=0.5, sleep=time.sleep, is_running=None) -> bool:
    """Pause the queue and wait until no job is running; return the prior paused state. #577."""
    was_paused = paused()
    pause()
    is_running = is_running or running
    while is_running():
        sleep(wait)
    return was_paused


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
    with _store() as c:
        mid = _machine(c)
        took = c.execute(
            "UPDATE jobs SET state = ?, started_at = ?, log = ?, machine_id = ? "
            "WHERE id = ? AND state = ? AND (machine_id = ? OR machine_id IS NULL)",
            (RUNNING, _epoch(started), str(log), mid, int(job["id"]), PENDING,
             mid)).rowcount == 1
        c.commit()
    if took:
        job.update(state=RUNNING, started=started, log=str(log), machine_id=mid)
    return took


def _unclaim(job: dict, why: str) -> None:
    with _store() as c:
        c.execute("UPDATE jobs SET state = ?, started_at = NULL, log = '', note = ? WHERE id = ? AND state = ?",
                  (PENDING, why, int(job["id"]), RUNNING))
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
        while not stop.wait(item_lease.TTL_S / 3):
            try:
                with _store() as c:
                    item_lease.beat(c, got["id"])
            except Exception as exc:  # noqa: BLE001 - a missed beat lapses the lease, which recovery reads
                print(f"{time.strftime('%H:%M:%S')} job {job['id']}: lease beat failed: {exc}", flush=True)

    beating = threading.Thread(target=keep, name=f"lease-{job['id']}", daemon=True)
    beating.start()
    try:
        yield got
    finally:
        stop.set()
        with _store() as c:
            item_lease.release(c, got["id"])


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
        job.update(rc=None, state=FAILED, note=f"not started: {stale}", finished=time.strftime(_STAMP))
        _write(job)
        return get(job["id"]) or job
    env = {**job_venv(job["cwd"] or ".", os.environ), JOB_ENV: str(int(job["id"]))}
    env.pop(ITEM_ENV, None)
    if itemized(job):
        env[ITEM_ENV] = f"{ITEM_S:g}"
    _cancel_flag(job["id"]).unlink(missing_ok=True)
    _item_flag(job["id"]).unlink(missing_ok=True)
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
    flag = _cancel_flag(job["id"])
    job.update(rc=rc, finished=time.strftime(_STAMP))
    if flag.exists():
        flag.unlink(missing_ok=True)
        _settle_cancelled(job, rc=rc)
    else:
        from evals import watch
        from harness import deploy
        if job.get("kind") == DEPLOY and rc == deploy.HANDED_OFF:
            # Left running and unwritten: the store may be migrated past this code; settle closes it. #1506.
            return {**job, "state": RUNNING, "handed_off": True}
        job.update(state=DONE if rc == 0 else PAUSED if rc == watch.PAUSED else FAILED)
        if not (job["state"] == PAUSED and (_next_item(job) or _repend(job))):
            _write(job)
    return get(job["id"]) or job


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
    run = runs.for_job(c, int(job["id"]))
    if "evals.run" not in [str(a) for a in job["argv"]] or run is None:
        return None
    return resume_argv(job["argv"], runs.run_dir(run["path"]))


def _next_item(job: dict) -> bool:
    """A job that stopped at its item's end waits again for its next item, resumed where it stopped. #1618."""
    flag = _item_flag(job["id"])
    if not flag.exists():
        return False
    flag.unlink(missing_ok=True)
    from evals import run
    with _store() as c:
        argv = _resumed(c, job) if run.queued_args(job["argv"]) is not None else list(job["argv"])
        if argv is None:
            return False
        took = (_epoch(job.get("finished")) or time.time()) - (_epoch(job.get("started")) or time.time())
        c.execute("UPDATE jobs SET state = ?, finished_at = NULL, rc = ?, argv = ?, note = ? WHERE id = ?",
                  (PENDING, job.get("rc"), json.dumps(argv),
                   f"item ended after {took:.0f}s of a planned {ITEM_S:.0f}s; the next item waits its turn",
                   int(job["id"])))
        c.commit()
    from harness import cuts
    cuts.cut("queue_item", f"job {label(job['id'])}: an item ended after {took:.0f}s; the next waits its turn", kept=1)
    return True


def _repend(job: dict) -> bool:
    """A job the watchdog paused for contention waits again to resume where it stopped, unless it queued its own continuation. #1509."""
    from harness import contention
    with _store() as c:
        if not contention.paused_for(c, job) or c.execute(
                "SELECT 1 FROM jobs WHERE argv = ? AND state = ? AND id != ?",
                (json.dumps([str(a) for a in job["argv"]]), PENDING, int(job["id"]))).fetchone():
            return False
        argv = _resumed(c, job) or list(job["argv"])
        c.execute("UPDATE jobs SET state = ?, finished_at = NULL, rc = ?, argv = ?, note = ? WHERE id = ?",
                  (PENDING, job.get("rc"), json.dumps(argv),
                   f"paused for contention at {job.get('finished')}; resumes when the contention gate opens",
                   int(job["id"])))
        c.commit()
    return True


def _settle_gone(c, job: dict) -> None:
    """A running job whose worker and process are gone: an eval that stored a run waits again to resume it, else it failed."""
    argv = _resumed(c, job)
    if argv is not None:
        c.execute("UPDATE jobs SET state = ?, started_at = NULL, argv = ?, note = ? WHERE id = ? AND state = ?",
                  (PENDING, json.dumps(argv), "its worker went away; resumes from its stored run", int(job["id"]), RUNNING))
    else:
        c.execute("UPDATE jobs SET state = ?, note = ? WHERE id = ? AND state = ?",
                  (FAILED, "interrupted; add it again to retry", int(job["id"]), RUNNING))
    c.commit()


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


def needs(job: dict) -> str:
    """The resource class a job waits for (resources.of). #1153, #1508."""
    return resources.of(job)


def _free(cls: str, live: dict) -> bool:
    """Whether a job of this class may start beside the jobs in `live` (thread -> (class, id)). #1153, #1508."""
    if cls == DEPLOY or any(c == DEPLOY for c, _ in live.values()):
        return not live
    mine = sum(1 for c, _ in live.values() if c == cls)
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
            nxt = None if errors or handed.is_set() else _startable(live, clock())
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
    gate_fn = gate_fn or gate
    said = ""
    while True:
        settle_deploys()
        watch_deploys(clock())
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
        print("was-paused" if quiesce() else "was-running")
        sys.exit(0)
    serve(poll=float(os.environ.get("LH_QUEUE_POLL", "30")))
