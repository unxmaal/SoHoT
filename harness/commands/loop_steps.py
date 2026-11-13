"""`soh discover --loop --run --jobs`: one sweep as queue jobs, a step each with its own resource class, each queuing the next. #1508."""
from __future__ import annotations

import contextvars
import json
import os
import sys
import time
import traceback
from typing import NamedTuple

from harness import resources
from harness.commands import loop as loop_cmd


class Step(NamedTuple):
    name: str
    #: The loop tier the heartbeat names, so a queued sweep reads as the loop does.
    tier: str
    resource: str


STEPS = (Step("sweep", "sweep", resources.NETWORK),
         Step("repair", "inspect", resources.NETWORK),
         Step("runtimes", "inspect", resources.GPU),
         Step("inspect", "inspect", resources.NETWORK),
         Step("queue", "queue", resources.GPU),
         Step("retests", "retests", resources.CPU),
         Step("reverify", "reverify", resources.CPU),
         Step("knob-sweeps", "knob sweeps", resources.CPU),
         Step("disk", "disk", resources.DISK),
         Step("fetch", "fetch", resources.NETWORK),
         Step("screen", "screen", resources.GPU),
         Step("measure", "measure", resources.GPU))
NAMES = tuple(s.name for s in STEPS)
#: The loop options a step carries to the next: (attribute, flag).
CARRIED = (("lane", "--lane"), ("top", "--top"), ("budget_gib", "--budget-gib"), ("repeat", "--repeat"),
           ("ceiling_h", "--ceiling-h"), ("effect", "--effect"), ("power_budget_min", "--power-budget-min"))
FAILED = "failed_steps"


def step(name: str) -> Step:
    return STEPS[NAMES.index(name)]


def argv(name: str, cycle: str, a) -> list[str]:
    """The command of one step of `cycle`; `--loop` in it lets the deploy guard and the watchdog know a sweep."""
    got = [sys.executable, "-m", "harness.cli", "discover", "--loop", "--run", "--step", name, "--cycle", cycle]
    for attr, flag in CARRIED:
        value = getattr(a, attr, None)
        if value not in (None, ""):
            got += [flag, str(value)]
    return got


def _cycle_of(words) -> str:
    words = [str(w) for w in words]
    if "--step" not in words or "--cycle" not in words[:-1]:
        return ""
    return words[words.index("--cycle") + 1]


def _step_of(words) -> str:
    words = [str(w) for w in words]
    return words[words.index("--step") + 1] if "--step" in words[:-1] else ""


def _jobs_of(conn, cycle: str) -> list[tuple[int, str, str]]:
    """(id, step, state) of every queued step job of `cycle`, in id order."""
    got = []
    for r in conn.execute("SELECT id, argv, state FROM jobs WHERE requested_by = ? ORDER BY id", ("discover",)):
        words = json.loads(r["argv"] or "[]")
        if _cycle_of(words) == cycle and _step_of(words) in NAMES:
            got.append((int(r["id"]), _step_of(words), r["state"]))
    return got


def _ran(conn, cycle: str, name: str, me: int | None) -> int | None:
    """The job showing step `name` of `cycle` already ran: a later step of it, or a later continuation of it, queued."""
    at = NAMES.index(name)
    for job, got, _ in _jobs_of(conn, cycle):
        if job != me and (NAMES.index(got) > at or got == name and me is not None and job > me):
            return job
    return None


def live(conn, but: str = "") -> dict[str, str]:
    """{cycle: job label} for each sweep with a step pending or running, other than `but`."""
    from harness import workqueue as wq
    got: dict[str, str] = {}
    for r in conn.execute("SELECT id, argv FROM jobs WHERE state IN (?, ?) ORDER BY id", (wq.PENDING, wq.RUNNING)):
        cycle = _cycle_of(json.loads(r["argv"] or "[]"))
        if cycle and cycle != but:
            got.setdefault(cycle, wq.label(r["id"]))
    return got


def _mine() -> dict | None:
    from harness import workqueue as wq
    key = os.environ.get(wq.JOB_ENV, "").strip()
    return wq.get(key) if key else None


def queue(name: str, cycle: str, a, conn=None, again: bool = False, commit: bool = True) -> dict:
    """Queue step `name` of `cycle` once, or with `again` this job's own continuation once; an earlier job of it comes back with `existed`."""
    from harness import paths
    from harness import memory_store as ms
    from harness import workqueue as wq
    words = argv(name, cycle, a)
    me = _mine()
    mine = int(me["id"]) if me else None
    own = conn is None
    conn = ms.connect() if own else conn
    try:
        for job, got, _ in _jobs_of(conn, cycle):
            if got == name and job != mine and (not again or mine is None or job > mine):
                return {**wq.get(job, conn), "existed": True}
        return wq.add(words, title=f"discover {name} (cycle {cycle})", cwd=str(paths.REPO),
                      priority=int((me or {}).get("priority") or 0), requested_by="discover",
                      resource=step(name).resource, conn=conn, commit=commit)
    finally:
        if own:
            conn.close()


def queue_cycle(a) -> int:
    """Queue the first step of a new sweep; refused while another sweep has a step waiting or running."""
    from harness import hold
    from harness import memory_store as ms
    held = hold.held()
    if held:
        print(f"=== no sweep: {held} ===", flush=True)
        return 0
    conn = ms.connect()
    try:
        others = live(conn)
        if others:
            cycle, job = next(iter(others.items()))
            print(f"sweep {cycle} has a step queued as job {job}; not queuing a second", file=sys.stderr)
            return 1
        cycle = str(int(time.time()))
        job = queue(STEPS[0].name, cycle, a, conn)
    finally:
        conn.close()
    print(f"queued sweep {cycle}: its {STEPS[0].name} step is job {job['id']}; each step queues the next")
    return 0


def _who(conn, cycle: str) -> dict:
    from harness import memory_store as ms
    return {"machine_id": ms.remember_machine(conn), "pid": None, "cycle": cycle}


def _lease(cycle: str) -> dict:
    """{} once `cycle` holds the discover-loop store lease, else its holder; a sweep with no step left frees it."""
    from harness import lease
    from harness import memory_store as ms
    from harness import job_procs
    conn = ms.connect()
    try:
        def stale(cur):
            return cur.get("cycle") == cycle or bool(cur.get("cycle")) and cur["cycle"] not in live(conn, but=cycle)
        return lease.take(conn, loop_cmd.LEASE, _who(conn, cycle), loop_cmd.LEASE_S, alive=job_procs.alive, stale=stale)
    finally:
        conn.close()


def _release(cycle: str) -> None:
    from harness import lease
    from harness import memory_store as ms
    conn = ms.connect()
    try:
        lease.release(conn, loop_cmd.LEASE, _who(conn, cycle))
    finally:
        conn.close()


def _body(name: str, a, sweep, failed: list) -> int:
    """Run step `name`, its failures noted in `failed`; its exit status."""
    lc = loop_cmd
    if name == "sweep":
        return lc._tier(a, "sweep", "sweep", failed)
    if name in ("repair", "runtimes"):
        rc = 0
        for repair, args in (lc._repairs(a) if name == "repair" else ((lc._trial_runtimes, ()),)):
            rc = lc._repair("inspect", repair, args, failed) or rc
        return rc
    if name == "inspect":
        return lc._tier(a, "inspect", "inspect", failed)
    if name == "queue":
        rc = lc._tier(a, "queue", "queue", failed)
        return lc._report(a, failed) or rc
    if name == "fetch":
        return lc._fetch(a, lc._sized(int(getattr(a, "top", 0) or 0), sweep), failed)
    if name == "screen":
        return lc._screen(a, sweep, lc._sized(int(getattr(a, "top", 0) or 0), sweep), failed)
    if name == "measure":
        return lc._measure(a, sweep, failed)
    lc._upkeep(step(name).tier)
    return 0


def _settle(sweep) -> None:
    """The sweep's end, as the loop's: only lane defaults resident, the ceiling said, the report published. #444."""
    from harness import heartbeat
    _unload("the discovery loop is done")
    print("\n".join(sweep.summary()))
    heartbeat.note(heartbeat.CEILING_UNUSED, sweep.unused())
    loop_cmd._publish_if_enabled()


def _unload(why: str) -> None:
    from harness import router
    router.settle(why)


def _end(cycle: str, rc: int | None, error: str = "") -> None:
    from harness import heartbeat
    heartbeat.finish(rc, error=error)
    _release(cycle)


#: The step this process is running, so a tier that dispatches back to run_step is refused, not recursed. #1646.
_RUNNING: contextvars.ContextVar[str] = contextvars.ContextVar("loop_step", default="")
#: The heartbeat key the last step sets to its cycle: that sweep is closed and none of its steps runs again. #1646.
CLOSED = "closed_cycle"


def _inner(a):
    """The step's options without --step, --cycle and --jobs, so its tiers' cmd_discover runs the tier itself. #1646."""
    import argparse
    return argparse.Namespace(**{**vars(a), "step": None, "cycle": None, "jobs": False})


def _already(name: str, cycle: str) -> str:
    """Why step `name` of `cycle` must not run again, or "": the sweep is closed, or the step queued what follows it."""
    from harness import heartbeat
    from harness import memory_store as ms
    from harness import workqueue as wq
    if (heartbeat.read() or {}).get(CLOSED) == cycle:
        return "the sweep is closed"
    me = _mine()
    conn = ms.connect()
    try:
        job = _ran(conn, cycle, name, int(me["id"]) if me else None)
    finally:
        conn.close()
    return f"job {wq.label(job)} follows it" if job is not None else ""


def run_step(a) -> int:
    """One step of a queued sweep: under the sweep's lease and heartbeat, then its successor queued whatever it returned."""
    from harness import ceiling, heartbeat, power
    name, cycle = a.step, str(a.cycle or "")
    if not cycle:
        print("--step needs --cycle: the sweep it belongs to", file=sys.stderr)
        return 2
    if _RUNNING.get():
        print(f"the {name} step of sweep {cycle} was entered again from inside its own step; refusing", file=sys.stderr)
        return 1
    done = _already(name, cycle)
    if done:
        print(f"sweep {cycle}: the {name} step already ran ({done}); nothing to do")
        return 0
    held = _lease(cycle)
    if held:
        print(f"another discover loop holds the store lease ({json.dumps(held, sort_keys=True)}); "
              f"sweep {cycle} stops before its {name} step", file=sys.stderr)
        if heartbeat.attach(cycle):
            heartbeat.finish(1, error="another discover loop holds the store lease")
        return 1
    me = step(name)
    lane = (getattr(a, "lane", "") or "").strip().lower()
    data = None if me is STEPS[0] else heartbeat.attach(cycle)
    data = data or heartbeat.start(lane=lane, total=loop_cmd.LOOP_TOTAL, cycle=cycle)
    sweep = ceiling.Sweep(float(getattr(a, "ceiling_h", None) or power.SWEEP_CEILING_H) * 3600,
                          started=float(data["started"]))
    failed: list[str] = []
    print(f"\n=== sweep {cycle}: the {name} step ===", flush=True)
    entered = _RUNNING.set(name)
    try:
        loop_cmd._beat(me.tier)
        rc = _body(name, _inner(a), sweep, failed)
    except loop_cmd.WeightsGone as gone:
        heartbeat.pause(gone.tier, gone.reason)
        print(f"\n=== sweep paused before {gone.tier}: {gone.reason} ===", file=sys.stderr, flush=True)
        _end(cycle, loop_cmd.PAUSED)
        return loop_cmd.PAUSED
    except Exception as exc:  # noqa: BLE001 - a crashed step is a failed step; the sweep goes on, as the loop's repairs do
        traceback.print_exc()
        rc = loop_cmd._step(f"{name} ({type(exc).__name__}: {exc})", 1, failed)
    except BaseException as exc:
        _end(cycle, None, error=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        _RUNNING.reset(entered)
    seen = list((heartbeat.read() or {}).get(FAILED) or []) + failed
    heartbeat.note(FAILED, seen)
    return _next(a, me, cycle, sweep, seen, rc)


def _next(a, me: Step, cycle: str, sweep, seen: list, rc: int) -> int:
    """Queue the step after `me`, or this measure again when a run paused on request; the last step ends the sweep."""
    from harness import heartbeat
    after = me if me.name == "measure" and sweep.halted else (
        None if me is STEPS[-1] else STEPS[STEPS.index(me) + 1])
    if after is None:
        _settle(sweep)
        heartbeat.note(CLOSED, cycle)
        _end(cycle, loop_cmd._why_nonzero(1 if seen else 0, seen))
        print(f"\nsweep {cycle} is closed: its {me.name} step is its last")
        return rc
    from harness import memory_store as ms
    conn = ms.connect()
    try:
        job = queue(after.name, cycle, a, conn=conn, again=after is me, commit=False)
        if not job.get("existed"):
            # The heartbeat names the next step before a worker can see it, or that step's attach is overwritten. #1865.
            try:
                heartbeat.handoff(job["id"], after.tier)
            finally:
                conn.commit()
    except ValueError as exc:
        job = {"refused": str(exc)}
    finally:
        conn.close()
    if job.get("refused"):
        print(f"sweep {cycle} stops: its {after.name} step could not be queued ({job['refused']})", file=sys.stderr)
        _end(cycle, 1, error=job["refused"])
        return 1
    if job.get("existed"):
        print(f"\nthe {after.name} step of sweep {cycle} is already job {job['id']}; not queuing another", flush=True)
        return rc
    if after is me:
        # A run paused on request waits in the queue; its model must not hold memory the requester needs.
        _unload("the discovery loop's measure paused on request")
    print(f"\nqueued the {after.name} step of sweep {cycle} as job {job['id']}", flush=True)
    return rc
