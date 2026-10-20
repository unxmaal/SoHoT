"""A periodic watchdog outside the jobs it watches: observe, judge against a declared table, act from a fixed set, record (#814).

It acts only on what it identified positively as SoHoT's own: the discover
agent, a work queue job's process group, an evals.run under either, a run's
progress file (#813), the eval lock, the router, the gateway, the mlx server. Anything else it
sees is listed and left alone. Until LH_WATCHDOG_ACT=1 every action is a dry
run that prints and records what it would have done.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

NOTE, NOTIFY, FILE, PAUSE, STOP, REAP, UNLOAD, RESTART = (
    "note", "notify", "file", "pause", "stop", "reap", "unload", "restart")
ACTIONS = (NOTE, NOTIFY, FILE, PAUSE, STOP, REAP, UNLOAD, RESTART)

#: Wall clock a discover sweep, queue job or unowned eval may run at night before it is flagged.
LONG_RUN_S = 8 * 3600.0
#: The same, during the day hours.
LONG_RUN_DAY_S = 2 * 3600.0
#: Observed seconds per case over this multiple of the plan's reads as a harness defect (Decision #456).
OVERRUN_FACTOR = 2.0
#: Cases a run must have finished before its observed rate is judged against the plan.
OVERRUN_MIN_CASES = 3
#: Cases both candidates of a paired run must have finished before the challenger is judged against the incumbent (#864).
OVERRUN_MIN_PAIRS = 5
#: No case finished for this long reads as wedged, or this many planned cases if that is longer.
STALL_S = 1800.0
STALL_CASES = 10
#: An orphan younger than this may be a parent mid-exit; it is left one more wake.
ORPHAN_GRACE_S = 120.0
#: Eric's day, local hours [start, end): the discover agent fires at the end of it.
DAY_START_HOUR = 8
DAY_END_HOUR = 21
#: A GPU job running longer than this inside the day hours is paused for the night.
DAYTIME_GPU_S = 3600.0
#: The eval lock held this long with no SoHoT job running is a stuck holder.
IDLE_HOLD_S = 1800.0
#: Swapouts per minute while a job runs that read as memory trouble.
SWAPOUT_MAX_PER_MIN = 2000.0
#: Requests a serving node handed back to this machine in live_audit's window that read as a spike.
FALLBACK_MAX = 20
#: Prior trips of the same criterion on the same subject inside the window before the escalation is taken.
ESCALATE_AFTER = 2
ESCALATE_WINDOW_S = 1800.0
#: A stopped group gets this long after TERM before KILL.
STOP_GRACE_S = 30.0
#: launchd.sh restart waits on the GPU lock; the watchdog waits this long for it.
RESTART_TIMEOUT_S = 180.0
#: Each outside probe (ps, launchctl, gh, the gateway) gets this long.
PROBE_TIMEOUT_S = 10.0
GH_TIMEOUT_S = 30.0
#: One desktop notification per criterion and subject this often at most; a repeating trip is recorded, not re-shown.
NOTIFY_EVERY_S = 3600.0
NOTIFY_TIMEOUT_S = 10.0
NOTIFY_TITLE = "SoHoT watchdog"
NOTIFIED = "notified"

ACT_ENV = "LH_WATCHDOG_ACT"
FILE_ENV = "LH_WATCHDOG_FILE"
FINGERPRINT = "watchdog-fingerprint:"
LABEL = "com.unxmaal.localharness"

_EVAL = re.compile(r"(?:-m\s+evals\.run\b|evals/run\.py\b)")
_DISCOVER = re.compile(r"(?:serve-discover\.sh|\bdiscover\b.*--loop)")


# --- what is seen ---------------------------------------------------------------

@dataclass(frozen=True)
class Proc:
    pid: int
    ppid: int
    pgid: int
    elapsed_s: float
    command: str


@dataclass
class Subject:
    """One thing the watchdog identified as SoHoT's own, and how."""
    kind: str
    key: str
    why: str
    pid: int | None = None
    #: The group an action may signal; set only when every live member is ours.
    pgid: int | None = None
    elapsed_s: float | None = None
    command: str = ""
    owner: str = ""
    orphan: bool = False
    progress: dict | None = None
    children: list = field(default_factory=list)
    detail: dict = field(default_factory=dict)

    def runs(self) -> list[dict]:
        """The progress files this subject's evals write, its own first."""
        got = [self.progress] if self.progress else []
        return got + [c.progress for c in self.children if c.progress]


@dataclass
class World:
    now: float
    #: Top-level subjects: the discover agent, queue jobs, evals no job or sweep owns.
    top: list = field(default_factory=list)
    #: Every eval subject, owned or not.
    evals: list = field(default_factory=list)
    #: evals.run processes found that are not provably ours; reported, never acted on.
    unowned: list = field(default_factory=list)
    lock: dict | None = None
    resident: list | None = None
    pressure: object = None
    swap_per_min: float | None = None
    gateway_up: bool | None = None
    mlx_generating: bool | None = None
    fallbacks: list | None = None
    #: This wake's lane_probes rows (#924).
    lanes: list | None = None
    #: observation -> why it could not be made.
    gaps: dict = field(default_factory=dict)

    def busy(self) -> bool:
        return bool(self.top)


@dataclass(frozen=True)
class Finding:
    criterion: str
    subject: Subject
    evidence: dict


# --- the outside world, behind one seam the tests replace ------------------------

def _etime(text: str) -> float:
    """ps etime [[dd-]hh:]mm:ss in seconds."""
    days, _, rest = text.strip().rpartition("-")
    parts = [int(p) for p in rest.split(":")]
    while len(parts) < 3:
        parts.insert(0, 0)
    h, m, s = parts[-3:]
    return (int(days) if days else 0) * 86400.0 + h * 3600 + m * 60 + s


def parse_ps(text: str) -> list[Proc]:
    out = []
    for line in text.splitlines():
        bits = line.split(None, 4)
        if len(bits) < 5 or not bits[0].isdigit():
            continue
        try:
            out.append(Proc(int(bits[0]), int(bits[1]), int(bits[2]), _etime(bits[3]), bits[4]))
        except ValueError:
            continue
    return out


class Probes:
    """Every read of the machine the watchdog makes. None from a probe means it could not be asked."""

    def processes(self) -> list[Proc] | None:
        if sys.platform == "win32":
            return None
        try:
            got = subprocess.run(["ps", "-ww", "-axo", "pid=,ppid=,pgid=,etime=,command="], capture_output=True,
                                 text=True, timeout=PROBE_TIMEOUT_S)
        except (OSError, subprocess.SubprocessError):
            return None
        return parse_ps(got.stdout) if got.returncode == 0 else None

    def _launchctl(self, service: str):
        if sys.platform != "darwin":
            return None
        try:
            return subprocess.run(["launchctl", "print", f"gui/{os.getuid()}/{LABEL}.{service}"],
                                  capture_output=True, text=True, timeout=PROBE_TIMEOUT_S)
        except (OSError, subprocess.SubprocessError):
            return None

    def launchd_pid(self, service: str) -> int | None:
        got = self._launchctl(service)
        m = re.search(r"^\tpid = (\d+)", got.stdout, re.M) if got is not None and got.returncode == 0 else None
        return int(m.group(1)) if m else None

    def launchd_loaded(self, service: str) -> bool | None:
        got = self._launchctl(service)
        return None if got is None else got.returncode == 0

    def heartbeat(self) -> dict | None:
        from harness import heartbeat
        return heartbeat.read()

    def job_pids(self) -> dict:
        """Queue job id -> the pid of its group leader, from the files the worker leaves. #628."""
        from harness import workqueue
        out = {}
        for f in sorted(workqueue._pids().glob("*.pid")):
            with contextlib.suppress(OSError, ValueError):
                out[f.stem] = int(f.read_text(encoding="utf-8").strip())
        return out

    def job(self, job_id: str) -> dict | None:
        from harness import workqueue
        try:
            return workqueue.get(job_id)
        except Exception as exc:  # noqa: BLE001 - a store that cannot be read is a gap, not a crash
            return {"error": str(exc)}

    def worker_running(self) -> bool:
        from harness import workqueue
        return workqueue.running()

    def progress(self, evals: list[Proc]) -> list[dict] | None:
        return ProgressFiles().runs(evals)

    def lock(self) -> dict | None:
        """The eval lock's holder record when it is held, {} when it is free."""
        from harness import delegate, exclusive
        try:
            return exclusive.holder() or {"kind": "unknown"} if delegate.busy() else {}
        except OSError:
            return None

    def resident(self) -> list[str] | None:
        """Router models nothing serves or adopted; None when the router or the defaults cannot be read."""
        from harness import router
        held = router.statuses()
        if held is None:
            return None
        try:
            keep = router.protected()
        except Exception:  # noqa: BLE001 - unknown protection means nothing is free to unload
            return None
        return sorted(k for k, v in held.items() if v in router.RESIDENT and k not in keep)

    def pressure(self):
        from harness import pressure
        return pressure.sample()

    def gateway_up(self) -> bool | None:
        if not self.launchd_loaded("gateway"):
            return None
        import httpx

        from harness import completion
        try:
            r = httpx.get(completion.gateway_url() + "/health/liveliness", timeout=PROBE_TIMEOUT_S)
        except httpx.HTTPError:
            return False
        return r.status_code == 200

    def mlx_generating(self) -> bool | None:
        """False when the loaded mlx unit answers that its generation thread died (#912); None when it cannot be asked."""
        if not self.launchd_loaded("mlx"):
            return None
        from harness import mlx_server, serving
        return mlx_server.generating(serving.MLX_URL, timeout=PROBE_TIMEOUT_S)

    def lanes(self, conn, now: float) -> list[dict] | None:
        """One known-answer completion per resident text lane, each recorded in lane_probes (#924); None without a store."""
        if conn is None:
            return None
        from harness import lane_probe
        return lane_probe.wake(conn, now, machine_id=_machine(conn))

    def fallbacks(self, conn) -> list[dict] | None:
        from harness import live_audit
        if conn is None:
            return None
        try:
            return live_audit.node_fallbacks(conn)
        except Exception:  # noqa: BLE001 - no served config or no nodes file
            return None

    def state(self) -> Path:
        from harness import paths
        d = paths.home() / "watchdog"
        d.mkdir(parents=True, exist_ok=True)
        return d


class ProgressFiles:
    """The progress.json files evals.run writes (evals/watch.py, #813): read them, and pause a run through its pause file."""

    from evals.watch import PAUSE_FILE, PROGRESS as NAME

    def __init__(self, roots=None):
        self.roots = roots

    def _roots(self) -> list[Path]:
        if self.roots is not None:
            return [Path(r) for r in self.roots]
        from harness import paths
        return [paths.runs()]

    def runs(self, evals: list[Proc] = ()) -> list[dict]:
        found = {p for root in self._roots() if root.is_dir() for p in root.glob(f"*/{self.NAME}")}
        for proc in evals:
            m = re.search(r"--out[= ](\S+)", proc.command)
            if m and Path(m.group(1)).is_absolute():
                found.add(Path(m.group(1)) / self.NAME)
        out = []
        for path in sorted(found):
            from evals.watch import read_progress
            got = read_progress(path.parent)
            if isinstance(got, dict) and got.get("state") == "running":
                out.append({**got, "_dir": str(path.parent)})
        return out

    def pause(self, run: dict) -> str:
        """Touch the run's pause file; the run checkpoints and exits between cases."""
        where = Path(run["_dir"])
        target = Path(run.get("pause_file") or where / self.PAUSE_FILE)
        if target.parent.resolve() != where.resolve():
            return f"refused: pause file {target} is outside the run directory {where}"
        target.write_text(time.strftime("%Y-%m-%dT%H:%M:%S"), encoding="utf-8")
        return f"pause file written: {target}"


# --- observe ---------------------------------------------------------------------

def _ancestors(pid: int, procs: dict) -> list[int]:
    out, seen = [], set()
    while pid in procs and pid not in seen and pid > 1:
        seen.add(pid)
        pid = procs[pid].ppid
        out.append(pid)
    return out


def _ours_only(pgid: int, procs: dict, ours) -> bool:
    members = [p for p in procs.values() if p.pgid == pgid]
    return bool(members) and all(ours(p) for p in members)


def observe(probes: Probes, conn=None, now: float | None = None) -> World:
    now = time.time() if now is None else now
    world = World(now=now)
    listed = probes.processes()
    if listed is None:
        world.gaps["processes"] = "the process table could not be read on this platform"
        listed = []
    procs = {p.pid: p for p in listed}

    discover = None
    dpid = probes.launchd_pid("discover")
    if dpid in procs and _DISCOVER.search(procs[dpid].command):
        p = procs[dpid]
        discover = Subject("discover", f"discover pid {p.pid}", "the launchd discover agent's pid", pid=p.pid,
                           pgid=p.pid if p.pgid == p.pid else None, elapsed_s=p.elapsed_s, command=p.command)
        world.top.append(discover)
    beat = probes.heartbeat() or {}
    loop_pid = beat.get("pid") if beat.get("state") == "running" else None
    marks = {pid: "discover" for pid in (dpid, loop_pid) if pid in procs}

    jobs = {}
    for job_id, pid in probes.job_pids().items():
        p = procs.get(pid)
        if p is None or p.pgid != pid:
            continue
        row = probes.job(job_id) or {}
        state = row.get("state", "")
        orphan = state not in ("running", "") or not probes.worker_running()
        s = Subject("job", f"job {job_id}", "a work queue pid file names its group leader", pid=pid, pgid=pid,
                    elapsed_s=p.elapsed_s, command=p.command, orphan=orphan,
                    detail={"title": row.get("title", ""), "state": state})
        jobs[pid] = s
        marks[pid] = f"job {job_id}"
        world.top.append(s)

    progress = probes.progress([p for p in listed if _EVAL.search(p.command)])
    if progress is None:
        world.gaps["progress"] = "no progress reader"
    by_pid = {int(r["pid"]): r for r in progress or [] if str(r.get("pid", "")).isdigit()}

    groups: dict = {}
    for p in listed:
        if _EVAL.search(p.command):
            groups.setdefault(p.pgid, []).append(p)
    for pgid, members in sorted(groups.items()):
        pids = {m.pid for m in members}
        top = min((m for m in members if m.ppid not in pids), key=lambda m: m.pid, default=members[0])
        owners = [marks[a] for a in [top.pid, *_ancestors(top.pid, procs), pgid] if a in marks]
        parent = next((t for o in owners for t in world.top
                       if t.key == o or (o == "discover" and t.kind == "discover")), None)
        owner = parent.key if parent is not None else (owners[0] if owners else "")
        run = next((by_pid[m.pid] for m in members if m.pid in by_pid), None)
        s = Subject("eval", f"eval pgid {pgid}", "", pid=top.pid,
                    pgid=pgid if _ours_only(pgid, procs, lambda q: bool(_EVAL.search(q.command))) else None,
                    elapsed_s=top.elapsed_s, command=top.command, owner=owner, progress=run)
        if owner:
            s.why = f"an evals.run under {owner}"
        elif run is not None:
            s.why = "an evals.run that writes a progress file"
        elif top.ppid == 1:
            s.why, s.orphan = "an evals.run whose parent is gone (reparented to launchd)", True
        else:
            world.unowned.append(s)
            continue
        if not owner and top.ppid == 1:
            s.orphan = True
        world.evals.append(s)
        if parent is not None:
            parent.children.append(s)
        else:
            world.top.append(s)

    world.lock = probes.lock()
    world.resident = probes.resident()
    world.pressure = probes.pressure()
    world.swap_per_min = _swap_rate(probes, world.pressure, now)
    world.gateway_up = probes.gateway_up()
    world.mlx_generating = probes.mlx_generating()
    world.fallbacks = probes.fallbacks(conn)
    try:
        world.lanes = probes.lanes(conn, now)
    except Exception as exc:  # noqa: BLE001 - a probe that cannot run is a gap, never a lost wake
        world.gaps["lanes"] = f"the lane probes failed: {type(exc).__name__}: {exc}"[:300]
    return world


def _swap_rate(probes: Probes, sample, now: float) -> float | None:
    """Swapouts per minute since the last wake, from a counter kept beside the watchdog's lock."""
    have = getattr(sample, "swapouts", None)
    path = probes.state() / "swap.json"
    try:
        before = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        before = {}
    if have is not None:
        path.write_text(json.dumps({"at": now, "swapouts": have}), encoding="utf-8")
    if have is None or not before or now <= before.get("at", now) or have < before.get("swapouts", 0):
        return None
    return (have - before["swapouts"]) * 60.0 / (now - before["at"])


# --- judge -----------------------------------------------------------------------

def daytime(now: float) -> bool:
    return DAY_START_HOUR <= time.localtime(now).tm_hour < DAY_END_HOUR


def _long_run(w: World) -> list[Finding]:
    limit = LONG_RUN_DAY_S if daytime(w.now) else LONG_RUN_S
    return [Finding("long_run", s, {"elapsed_s": round(s.elapsed_s), "limit_s": limit, "day": daytime(w.now)})
            for s in w.top if s.elapsed_s is not None and s.elapsed_s > limit and not s.orphan]


def _cells(run: dict):
    """(incumbent key, {key: {case: [wall_s, reply tokens or None, rows]}}) from a paired run's checkpoint, else None. #864."""
    from evals.watch import read
    got = read(run["_dir"]) if run.get("_dir") else None
    if not got:
        return None
    ident, rows = got
    key_of = {spec: key for key, spec in (run.get("specs") or {}).items()}
    order = [key_of.get(c, c) for c in ident.get("candidates") or []]
    if len(order) < 2:
        return None
    budget = ident.get("max_tokens")
    by: dict = {}
    for r in rows:
        if r.get("candidate") is None or r.get("case_id") is None:
            continue
        toks = (r.get("metrics") or {}).get("completion_tokens")
        if not toks and r.get("failure_class") == "token_budget_exhausted":
            toks = budget
        cell = by.setdefault(r["candidate"], {}).setdefault(r["case_id"], [0.0, 0, 0])
        cell[0] += float(r.get("wall_s") or r.get("seconds") or 0.0)
        cell[1] = cell[1] + toks if toks and cell[1] is not None else None
        cell[2] += 1
    return order[0], by


def _paired(by: dict, inc: str, ch: str):
    """(observed challenger/incumbent ratio, basis, pairs) on the cases both finished, or None below the minimum. #864."""
    mine, theirs = by.get(ch) or {}, by.get(inc) or {}
    pairs = [c for c in mine if c in theirs and mine[c][2] == theirs[c][2]]
    tok = [c for c in pairs if mine[c][1] and theirs[c][1]]
    if len(tok) >= OVERRUN_MIN_PAIRS:
        a, at = sum(mine[c][0] for c in tok), sum(mine[c][1] for c in tok)
        b, bt = sum(theirs[c][0] for c in tok), sum(theirs[c][1] for c in tok)
        return ((a / at) / (b / bt) if b else None), "seconds per reply token", len(tok)
    if len(pairs) >= OVERRUN_MIN_PAIRS:
        b = sum(theirs[c][0] for c in pairs)
        return (sum(mine[c][0] for c in pairs) / b if b else None), "seconds", len(pairs)
    return None


def _overrun(w: World) -> list[Finding]:
    out = []
    for s in w.evals:
        run = s.progress or {}
        if int(run.get("done") or 0) < OVERRUN_MIN_CASES:
            continue
        planned, seen = run.get("planned_s_per_case") or {}, run.get("observed_s_per_case") or {}
        cells = _cells(run)
        worst = []
        for k in seen:
            if not (seen.get(k) and planned.get(k)):
                continue
            if cells is None or k == cells[0] or k not in cells[1]:
                if seen[k] > OVERRUN_FACTOR * planned[k]:
                    worst.append((seen[k] / planned[k], k, {}))
                continue
            # A challenger is judged against the incumbent on the same cases, not its plan's mean: case time is heavy-tailed. #864.
            inc = cells[0]
            got = _paired(cells[1], inc, k) if planned.get(inc) else None
            if got is None or got[0] is None:
                continue
            ratio, basis, n = got
            expected = planned[k] / planned[inc]
            if ratio > OVERRUN_FACTOR * expected:
                worst.append((ratio / expected, k, {"observed_ratio": round(ratio, 3), "planned_ratio": round(expected, 3),
                                                    "basis": basis, "paired": n, "against": inc}))
        if worst:
            _, k, extra = max(worst, key=lambda x: x[0])
            out.append(Finding("overrun", s, {"candidate": k, "observed_s_per_case": round(seen[k], 2),
                                              "planned_s_per_case": round(planned[k], 2), "factor": OVERRUN_FACTOR,
                                              "done": run.get("done"), "total": run.get("total"),
                                              "specs": run.get("specs"), **extra}))
    return out


def _no_progress(w: World) -> list[Finding]:
    out = []
    for s in w.evals:
        run = s.progress or {}
        last = run.get("last_progress_at") or run.get("started_at")
        if last is None:
            continue
        plans = [v for v in (run.get("planned_s_per_case") or {}).values() if v]
        limit = max([STALL_S] + [STALL_CASES * v for v in plans])
        idle = w.now - float(last)
        if idle > limit:
            out.append(Finding("no_progress", s, {"since_last_case_s": round(idle), "limit_s": round(limit),
                                                  "done": run.get("done"), "total": run.get("total")}))
    return out


def _orphan(w: World) -> list[Finding]:
    return [Finding("orphan", s, {"elapsed_s": round(s.elapsed_s or 0), "why": s.why,
                                  "job_state": s.detail.get("state", "")})
            for s in w.top if s.orphan and (s.elapsed_s or 0) >= ORPHAN_GRACE_S]


def _daytime_gpu(w: World) -> list[Finding]:
    if not daytime(w.now):
        return []
    return [Finding("daytime_gpu", s, {"elapsed_s": round(s.elapsed_s), "limit_s": DAYTIME_GPU_S,
                                       "hours": [DAY_START_HOUR, DAY_END_HOUR]})
            for s in w.top if s.elapsed_s is not None and s.elapsed_s > DAYTIME_GPU_S and not s.orphan]


def _idle_lock(w: World) -> list[Finding]:
    held = w.lock or {}
    if not held or w.busy():
        return []
    since = held.get("since")
    age = w.now - float(since) if isinstance(since, (int, float)) else None
    if age is not None and age < IDLE_HOLD_S:
        return []
    who = Subject("lock", f"lock pid {held.get('pid')}", "the eval lock's holder record", pid=held.get("pid"),
                  detail=dict(held))
    return [Finding("idle_lock", who, {"holder": held, "held_s": round(age) if age is not None else None})]


def _idle_model(w: World) -> list[Finding]:
    if w.busy() or not w.resident:
        return []
    return [Finding("idle_model", Subject("model", f"model {stem}", "router resident, served by no alias or adoption",
                                          detail={"stem": stem}), {"stem": stem})
            for stem in w.resident]


def _memory(w: World) -> list[Finding]:
    level = getattr(w.pressure, "level", None)
    alarming = bool(getattr(w.pressure, "alarming", False))
    swapping = w.swap_per_min is not None and w.swap_per_min > SWAPOUT_MAX_PER_MIN
    if not (alarming or swapping):
        return []
    ev = {"pressure_level": level, "swapouts_per_min": None if w.swap_per_min is None else round(w.swap_per_min),
          "limit_per_min": SWAPOUT_MAX_PER_MIN}
    return [Finding("memory", s, ev) for s in w.top if not s.orphan]


def _gateway_down(w: World) -> list[Finding]:
    if w.gateway_up is not False:
        return []
    return [Finding("gateway_down", Subject("gateway", "gateway", "the launchd gateway unit is loaded",
                                            detail={"service": "gateway"}), {"liveliness": "no answer"})]


def _mlx_dead(w: World) -> list[Finding]:
    if w.mlx_generating is not False:
        return []
    return [Finding("mlx_dead", Subject("server", "mlx", "the launchd mlx unit is loaded and its /health says 503",
                                        detail={"service": "mlx"}), {"health": "unavailable"})]


def _node_fallbacks(w: World) -> list[Finding]:
    return [Finding("node_fallbacks", Subject("node", f"node {f['node']}", "live_audit.node_fallbacks",
                                              detail=f), {"requests": f["requests"], "limit": FALLBACK_MAX,
                                                          "aliases": f.get("aliases", [])})
            for f in w.fallbacks or [] if int(f.get("requests") or 0) >= FALLBACK_MAX]


@dataclass(frozen=True)
class Criterion:
    id: str
    #: The knobs (harness/knobs/watchdog.py) that set its threshold.
    knobs: tuple
    action: str
    escalation: str
    #: World fields it reads; a gap in any of them skips it, saying why.
    needs: tuple
    judge: object
    what: str


CRITERIA = (
    Criterion("long_run", ("watchdog_long_run", "watchdog_long_run_day"), NOTIFY, PAUSE, ("processes",),
              _long_run, "has run a long time (tighter during the day)"),
    Criterion("overrun", ("watchdog_overrun_factor", "watchdog_overrun_min_cases", "watchdog_overrun_min_pairs"), FILE, STOP,
              ("processes", "progress"), _overrun,
              "observed s/case far over the plan's, or a challenger far slower than planned on the incumbent's cases"),
    Criterion("no_progress", ("watchdog_stall", "watchdog_stall_cases"), NOTIFY, STOP, ("processes", "progress"),
              _no_progress, "no case finished for too long: wedged"),
    Criterion("orphan", ("watchdog_orphan_grace",), REAP, FILE, ("processes",), _orphan,
              "an eval or job whose sweep, worker or queue row is gone"),
    Criterion("daytime_gpu", ("watchdog_day_start_hour", "watchdog_day_end_hour", "watchdog_daytime_gpu"), PAUSE,
              STOP, ("processes",), _daytime_gpu, "a long GPU job inside Eric's day hours"),
    Criterion("idle_lock", ("watchdog_idle_hold",), NOTE, FILE, ("processes", "lock"), _idle_lock,
              "the eval lock held with nothing running"),
    Criterion("idle_model", (), NOTE, UNLOAD, ("processes", "resident"), _idle_model,
              "a router model resident with nothing running and nothing serving it"),
    Criterion("memory", ("watchdog_swapout_max",), NOTIFY, PAUSE, ("processes", "pressure"), _memory,
              "memory pressure or swap growth while a job runs"),
    Criterion("gateway_down", (), NOTIFY, RESTART, ("gateway",), _gateway_down,
              "the gateway's liveliness probe fails"),
    Criterion("mlx_dead", (), RESTART, NOTIFY, ("mlx",), _mlx_dead,
              "mlx_lm.server is up but its generation thread died, so every request fails"),
    Criterion("node_fallbacks", ("watchdog_fallback_max",), NOTIFY, FILE, ("fallbacks",), _node_fallbacks,
              "a serving node's requests falling back to this machine"),
)
BY_ID = {c.id: c for c in CRITERIA}


def _gap(w: World, need: str) -> str:
    if need in w.gaps:
        return w.gaps[need]
    if need == "progress" and not any(s.progress for s in w.evals):
        return "no running eval has written a progress file"
    value = {"lock": w.lock, "resident": w.resident, "pressure": w.pressure,
             "gateway": w.gateway_up, "mlx": w.mlx_generating, "fallbacks": w.fallbacks}.get(need, True)
    if value is None:
        return {"lock": "the eval lock could not be read", "resident": "the router or its defaults could not be read",
                "pressure": "memory pressure could not be sampled",
                "gateway": "no gateway unit is loaded here, or launchd cannot be asked",
                "mlx": "no mlx unit is loaded here, or its /health did not answer",
                "fallbacks": "the store or the served config could not be read"}[need]
    return ""


def judge(w: World) -> tuple[list[Finding], dict]:
    """(findings, criterion -> why it was skipped)."""
    found, skipped = [], {}
    for c in CRITERIA:
        why = next((g for g in (_gap(w, n) for n in c.needs) if g), "")
        if why:
            skipped[c.id] = why
            continue
        found.extend(c.judge(w))
    return found, skipped


# --- act -------------------------------------------------------------------------

def fingerprint(f: Finding) -> str:
    """Stable across wakes and pids: the criterion, the kind, and what was running."""
    s = f.subject
    what = json.dumps(sorted((s.progress or {}).get("specs") or {}), sort_keys=True) if s.progress else \
        re.sub(r"\d+", "N", s.command or s.key)
    return hashlib.sha256(f"{f.criterion}|{s.kind}|{what}".encode()).hexdigest()[:16]


def desktop(title: str, message: str, subtitle: str = "", run=subprocess.run, platform: str | None = None) -> str:
    """One macOS desktop notification through osascript; the outcome string. #818, #867."""
    platform = platform or sys.platform
    if platform != "darwin":
        return (f"notify unavailable: no desktop notifier on {platform} (macOS osascript only); "
                "the row and the log line are the notice")
    message = message[:200]
    # argv, not string interpolation, so a command line in the subject cannot break the AppleScript.
    script = ["osascript", "-e", "on run argv", "-e",
              "display notification (item 2 of argv) with title (item 1 of argv) subtitle (item 3 of argv)",
              "-e", "end run", title, message, subtitle[:120]]
    try:
        got = run(script, capture_output=True, text=True, timeout=NOTIFY_TIMEOUT_S)
    except (OSError, subprocess.SubprocessError) as exc:
        return f"notify failed: {exc}"
    if got.returncode != 0:
        return f"notify failed: osascript rc {got.returncode}: {(got.stderr or '').strip()[:200]}"
    return f"{NOTIFIED}: {message}"


class Hands:
    """The fixed action set. Each returns an outcome string for the store row."""

    def __init__(self, reader: ProgressFiles | None = None, run=subprocess.run, environ=None, say=print,
                 platform: str | None = None):
        self.reader = reader or ProgressFiles()
        self.run = run
        self.environ = os.environ if environ is None else environ
        self.say = say
        self.platform = sys.platform if platform is None else platform

    def note(self, f: Finding) -> str:
        return "noted"

    def notify(self, f: Finding) -> str:
        return desktop(NOTIFY_TITLE, f"{f.criterion}: {f.subject.key}", BY_ID[f.criterion].what,
                       run=self.run, platform=self.platform)

    def file(self, f: Finding) -> str:
        if self.environ.get(FILE_ENV, "") != "1":
            return f"not filed: {FILE_ENV} is not 1"
        from harness import paths
        fp = fingerprint(f)
        try:
            seen = self.run(["gh", "issue", "list", "--state", "open", "--search", f"{fp} in:body",
                             "--json", "number", "--limit", "1"], capture_output=True, text=True,
                            timeout=GH_TIMEOUT_S, cwd=paths.REPO)
            if seen.returncode != 0:
                return f"not filed: gh issue list failed: {seen.stderr.strip()[:200]}"
            hits = json.loads(seen.stdout or "[]")
            if hits:
                return f"already filed: #{hits[0]['number']}"
            title = f"watchdog: {f.criterion} on {f.subject.kind} ({BY_ID[f.criterion].what})"
            body = (f"The watchdog (#814) judged `{f.criterion}` on {f.subject.key}.\n\n"
                    f"Identified as: {f.subject.why}\n\nCommand: `{f.subject.command}`\n\n"
                    f"Evidence:\n```json\n{json.dumps(f.evidence, indent=2, default=str)}\n```\n\n"
                    f"{FINGERPRINT} {fp}\n")
            made = self.run(["gh", "issue", "create", "--title", title, "--body", body], capture_output=True,
                            text=True, timeout=GH_TIMEOUT_S, cwd=paths.REPO)
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            return f"not filed: {exc}"
        if made.returncode != 0:
            return f"not filed: gh issue create failed: {made.stderr.strip()[:200]}"
        return f"filed: {made.stdout.strip()}"

    def pause(self, f: Finding) -> str:
        runs = f.subject.runs()
        if not runs:
            return "pause unavailable: no progress file to pause through"
        return "; ".join(self.reader.pause(r) for r in runs)

    def _group(self, s: Subject) -> str:
        from harness import workqueue
        if s.pgid is None:
            return f"refused: {s.key} has no process group made only of SoHoT processes"
        return f"group {s.pgid}: {workqueue.stop_group(s.pgid, grace=STOP_GRACE_S)}"

    def stop(self, f: Finding) -> str:
        return self._group(f.subject)

    def reap(self, f: Finding) -> str:
        if not f.subject.orphan:
            return f"refused: {f.subject.key} is not an orphan"
        return self._group(f.subject)

    def unload(self, f: Finding) -> str:
        from harness import router
        stem = f.subject.detail.get("stem", "")
        gone = router.release([stem], "watchdog: resident with nothing running", say=self.say)
        return f"unloaded {stem}" if gone else f"kept {stem}: protected, gone, or a run is in flight"

    def restart(self, f: Finding) -> str:
        from harness import paths
        service = f.subject.detail.get("service", "")
        if service == "mlx":
            return self._kickstart(service)
        if service != "gateway":
            return f"refused: {service or f.subject.kind} is not a service the watchdog restarts"
        try:
            got = self.run(["/bin/bash", str(paths.REPO / "scripts" / "launchd.sh"), "restart", service],
                           capture_output=True, text=True, timeout=RESTART_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            return f"restart of {service} still waiting on the GPU lock after {RESTART_TIMEOUT_S:.0f}s"
        except OSError as exc:
            return f"restart of {service} failed: {exc}"
        return f"restarted {service}" if got.returncode == 0 else \
            f"restart of {service} failed rc {got.returncode}: {got.stderr.strip()[:200]}"

    def _kickstart(self, service: str) -> str:
        """kickstart -k without the GPU lock: a server that cannot generate has no work in flight to protect."""
        if self.platform != "darwin":
            return f"refused: restarting {service} needs launchd (macOS); this is {self.platform}"
        try:
            got = self.run(["launchctl", "kickstart", "-k", f"gui/{os.getuid()}/{LABEL}.{service}"],
                           capture_output=True, text=True, timeout=RESTART_TIMEOUT_S)
        except (AttributeError, OSError, subprocess.SubprocessError) as exc:
            return f"restart of {service} failed: {exc}"
        return f"restarted {service}" if got.returncode == 0 else \
            f"restart of {service} failed rc {got.returncode}: {(got.stderr or '').strip()[:200]}"

    def do(self, action: str, f: Finding) -> str:
        if action not in ACTIONS:
            raise ValueError(f"not a watchdog action: {action}")
        try:
            return getattr(self, action)(f)
        except Exception as exc:  # noqa: BLE001 - one failed action must not cost the rest of the wake
            return f"{action} failed: {type(exc).__name__}: {exc}"


# --- record ----------------------------------------------------------------------

def _machine(conn) -> int | None:
    from harness import runs
    got = runs.here(conn)
    return got[0] if got else None


def repeats(conn, f: Finding, now: float, dry_run: bool) -> int:
    """Prior trips of this criterion on this subject inside the escalation window, this machine."""
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM watchdog_actions WHERE criterion = ? AND subject = ? AND dry_run = ? "
        "AND at >= ? AND (machine_id = ? OR (machine_id IS NULL AND ? IS NULL))",
        (f.criterion, f.subject.key, int(dry_run), now - ESCALATE_WINDOW_S, _machine(conn), _machine(conn))
    ).fetchone()
    return int(row["n"])


def notified_since(conn, f: Finding, now: float) -> float | None:
    """When this criterion last put a notification on this subject's desktop inside NOTIFY_EVERY_S, this machine."""
    row = conn.execute(
        "SELECT MAX(at) AS at FROM watchdog_actions WHERE criterion = ? AND subject = ? AND action = ? "
        "AND dry_run = 0 AND outcome LIKE ? AND at >= ? AND (machine_id = ? OR (machine_id IS NULL AND ? IS NULL))",
        (f.criterion, f.subject.key, NOTIFY, f"{NOTIFIED}:%", now - NOTIFY_EVERY_S, _machine(conn), _machine(conn))
    ).fetchone()
    return None if row["at"] is None else float(row["at"])


def _act(conn, hands: Hands, action: str, f: Finding, now: float) -> str:
    if action == NOTIFY:
        last = notified_since(conn, f, now)
        if last is not None:
            return f"notify held: shown {now - last:.0f}s ago (once per {NOTIFY_EVERY_S:.0f}s per criterion and subject)"
    return hands.do(action, f)


def record(conn, f: Finding, action: str, escalated: bool, dry_run: bool, outcome: str, now: float) -> int:
    evidence = {**f.evidence, "identified_by": f.subject.why, "pid": f.subject.pid, "pgid": f.subject.pgid,
                "command": f.subject.command, "owner": f.subject.owner, "fingerprint": fingerprint(f)}
    cur = conn.execute(
        "INSERT INTO watchdog_actions (at, machine_id, criterion, subject, action, escalated, dry_run, "
        "evidence, outcome) VALUES (?,?,?,?,?,?,?,?,?)",
        (now, _machine(conn), f.criterion, f.subject.key, action, int(escalated), int(dry_run),
         json.dumps(evidence, default=str, sort_keys=True), outcome))
    conn.commit()
    return cur.lastrowid


# --- one wake --------------------------------------------------------------------

def acting(environ=None) -> bool:
    environ = os.environ if environ is None else environ
    return environ.get(ACT_ENV, "") == "1"


@contextlib.contextmanager
def _alone(probes: Probes):
    """One wake at a time on a machine; a second one returns at once."""
    from harness import exclusive
    fd = os.open(probes.state() / "lock", os.O_RDWR | os.O_CREAT, 0o644)
    try:
        taken = exclusive._take(fd)
        try:
            yield taken
        finally:
            if taken:
                exclusive._release(fd)
    finally:
        os.close(fd)


def wake(conn, probes: Probes | None = None, hands: Hands | None = None, act: bool = False,
         now: float | None = None, say=print) -> dict:
    """Observe, judge, act (or say what it would), record each act. Returns what happened."""
    probes = probes or Probes()
    hands = hands or Hands(say=say)
    now = time.time() if now is None else now
    with _alone(probes) as alone:
        if not alone:
            say("another watchdog wake holds the lock; nothing done")
            return {"acted": [], "skipped": {}, "unowned": [], "busy": True}
        world = observe(probes, conn, now)
        findings, skipped = judge(world)
        acted = []
        for f in findings:
            c = BY_ID[f.criterion]
            escalated = repeats(conn, f, now, not act) >= ESCALATE_AFTER
            action = c.escalation if escalated else c.action
            outcome = _act(conn, hands, action, f, now) if act else "dry-run"
            row = record(conn, f, action, escalated, not act, outcome, now)
            mark = "" if act else "[dry-run] would "
            say(f"{mark}{action}{' (escalated)' if escalated else ''} {f.subject.key}: {f.criterion} "
                f"{json.dumps(f.evidence, default=str)} -> {outcome}")
            acted.append({"row": row, "criterion": f.criterion, "subject": f.subject.key, "action": action,
                          "escalated": escalated, "outcome": outcome})
        for cid, why in skipped.items():
            say(f"skipped {cid}: {why}")
        from harness import lane_probe
        for r in world.lanes or []:
            say(lane_probe.line(r))
        if "lanes" in world.gaps:
            say(world.gaps["lanes"])
        down = [r["lane"] for r in world.lanes or [] if r["outcome"] == lane_probe.DOWN]
        for s in world.unowned:
            say(f"left alone (not provably SoHoT's): pid {s.pid} {s.command[:120]}")
        if not findings and not down:
            say(f"all clear: {len(world.top)} running, {len(world.evals)} eval(s)")
        return {"acted": acted, "skipped": skipped, "unowned": [s.key for s in world.unowned], "busy": False,
                "lanes": world.lanes, "down": down}


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="soh watchdog", description=__doc__.splitlines()[0])
    ap.add_argument("--act", action="store_true", help=f"take the actions (default: dry run unless {ACT_ENV}=1)")
    ap.add_argument("--dry-run", action="store_true", help="print and record what it would do, whatever the env says")
    a = ap.parse_args(argv)
    return run(a)


def run(a) -> int:
    from harness import memory_store as ms
    from harness import purpose
    purpose.set_process(purpose.WATCHDOG)
    act = (a.act or acting()) and not a.dry_run
    conn = ms.connect()
    try:
        wake(conn, act=act)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
