"""A periodic watchdog outside the jobs it watches: observe, judge against a declared table, act from a fixed set, record (#814).

It acts only on what it identified positively as SoHoT's own: the discover
agent, a work queue job's process group, an evals.run under either, a run's
progress file (#813), the eval lock, the router, the gateway, the mlx and tts servers. Anything else it
sees is listed and left alone. Until LH_WATCHDOG_ACT=1 every action is a dry
run that prints and records what it would have done.
"""
from __future__ import annotations

import contextlib
import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from harness import audio_models, interactive, machine_scope, serve_lease, watchdog_hands, watchdog_observe
from harness.overrun import cells as _cells, paired as _paired, unmeasured as _unmeasured

NOTE, NOTIFY, FILE, PAUSE, STOP, REAP, UNLOAD, RESTART = (
    "note", "notify", "file", "pause", "stop", "reap", "unload", "restart")
ACTIONS = (NOTE, NOTIFY, FILE, PAUSE, STOP, REAP, UNLOAD, RESTART)

#: Wall clock each kind of job (kind_of) may run before long_run flags it, then pauses it (#1372, #1509).
LONG_RUN_ADOPT_S = 8 * 3600.0
LONG_RUN_CONFIRM_S = 8 * 3600.0
LONG_RUN_EVAL_S = 8 * 3600.0
LONG_RUN_OTHER_S = 8 * 3600.0
LONG_RUN_SWEEP_S = 8 * 3600.0
KINDS = ("adopt", "confirm", "eval", "other", "sweep")
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
#: The owner's day, local hours [start, end), when an idle served model is given back sooner (#1157); no GPU limit (#1509).
DAY_START_HOUR = 8
DAY_END_HOUR = 21
#: The eval lock held this long with no SoHoT job running is a stuck holder.
IDLE_HOLD_S = 1800.0
#: Inside the day hours, a served model with no request this long is given back; at night the router's own sleep applies (#1157).
IDLE_UNLOAD_DAY_S = 600.0
#: The router's own --sleep-idle-seconds on a Mac, the night limit.
IDLE_UNLOAD_SITE = "scripts/router-sleep-idle.sh:SERVE_IDLE_UNLOAD_S"
#: Swapouts per minute while a job runs that read as memory trouble.
SWAPOUT_MAX_PER_MIN = 2000.0
#: Consecutive wakes at warn with nothing idle after which served models nothing uses go, then the sweep pauses. #1482.
WARN_SUSTAINED = 3
#: How often the watchdog wakes; a gap past 1.5 of it ends a run of warn samples.
EVERY_SITE = "scripts/launchd.sh:WATCHDOG_EVERY_MIN"
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
STALE_MCP_REMEDY = ("stopping it ends these clients' stream; Claude Code then refetches tools/list from the live "
                    "server, though a description it already loaded only changes in a new session")
GH_TIMEOUT_S = 30.0
#: One desktop notification per criterion and subject this often at most; a repeating trip is recorded, not re-shown.
NOTIFY_EVERY_S = 3600.0
NOTIFY_TIMEOUT_S = 10.0
NOTIFY_TITLE = "SoHoT watchdog"
NOTIFIED = "notified"
HELD = "notify held"
_HELD_WHAT = {"watchdog_escalate_after": "findings escalated after repeated trips",
              "watchdog_escalate_window": "findings not escalated: their earlier trips fell outside the window",
              "watchdog_notify_every": "notifications held: shown too recently"}
UNPAUSABLE = "no progress file to pause through: notified instead, and it runs on"
#: watchdog_actions.result: what came of an act. Readers decide on it; the outcome sentence is display only. #1778.
ACTED, WITHHELD, REFUSED, FAILED, UNAVAILABLE, DRY = "acted", "held", "refused", "failed", "unavailable", "dry_run"
RESULTS = (ACTED, WITHHELD, REFUSED, FAILED, UNAVAILABLE, DRY)


class Said(str):
    """An act's outcome sentence carrying its result code and whether it put a notification on the desktop."""

    def __new__(cls, text: str, result: str = ACTED, notified: bool = False):
        s = super().__new__(cls, text)
        s.result, s.notified = result, notified
        return s


def said(got, action: str = "") -> Said:
    """A hand's answer as a Said; a bare string is an act done that showed nothing."""
    return got if isinstance(got, Said) else Said(str(got), ACTED)


def canon(path) -> str:
    """The one spelling a run directory is stored and looked up by."""
    return os.path.realpath(str(path))

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
    #: The queue job this subject is, by id.
    job_id: int | None = None

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
    #: Process groups that hold a cloud slot and no GPU lock: their evals load no model here. #1135.
    cloud: set = field(default_factory=set)
    resident: list | None = None
    pressure: object = None
    swap_per_min: float | None = None
    #: The model the mlx server holds; None when it holds none or cannot be asked.
    mlx_held: str | None = None
    #: Models a lane, an adoption or a gateway alias serves; None when unreadable.
    protected: set | None = None
    gateway_up: bool | None = None
    mlx_generating: bool | None = None
    interactive: dict = field(default_factory=dict)
    fallbacks: list | None = None
    #: This wake's lane_probes rows (#924).
    lanes: list | None = None
    #: The owner's hold and the served lanes' client requests (contention.reading); None when unreadable. #1509.
    contention: dict | None = None
    #: The top subject whose process holds the GPU lock: "" when none does, None when that cannot be told. #1370.
    gpu: str | None = ""
    #: The mcp unit's pid and how long it has run; None when no unit is loaded or launchd cannot be asked.
    mcp_live: int | None = None
    mcp_live_s: float | None = None
    #: harness.mcp_server processes on the live one's port that are not it (#1155).
    mcp_stale: list = field(default_factory=list)
    #: Each loaded model either server could give back: {"server", "model", "in_flight": bool or None}. #1157.
    served: list = field(default_factory=list)
    #: "server:model" -> when it was last asked, seen first, or last named by a running eval. #1157.
    idle_since: dict = field(default_factory=dict)
    #: Earlier wakes in an unbroken run that found memory at warn; None when the store could not say. #1482.
    warn_samples: int | None = 0
    #: The tts server's pid, footprint_gib, in_flight and loaded models; {} with no tts unit here. #1671.
    tts: dict = field(default_factory=dict)
    #: observation -> why it could not be made.
    gaps: dict = field(default_factory=dict)

    def busy(self) -> bool:
        return bool(self.top)


@dataclass(frozen=True)
class Finding:
    criterion: str
    subject: Subject
    evidence: dict


# --- judge -----------------------------------------------------------------------

def daytime(now: float) -> bool:
    return DAY_START_HOUR <= time.localtime(now).tm_hour < DAY_END_HOUR


_CONFIRM = re.compile(r"\badopt\b.*\s--confirm\b")
_ADOPT = re.compile(r"\badopt\b")


def kind_of(s: Subject) -> str:
    """The job kind long_run's limits are keyed by: sweep, confirm, adopt, eval or other. #1372."""
    if s.kind == "discover":
        return "sweep"
    if _CONFIRM.search(s.command):
        return "confirm"
    if _ADOPT.search(s.command):
        return "adopt"
    return "eval" if s.kind == "eval" or _EVAL.search(s.command) else "other"


def long_run_limits() -> dict:
    """kind -> seconds, read when asked so a rebound knob takes effect. #1372."""
    return {"adopt": LONG_RUN_ADOPT_S, "confirm": LONG_RUN_CONFIRM_S, "eval": LONG_RUN_EVAL_S,
            "other": LONG_RUN_OTHER_S, "sweep": LONG_RUN_SWEEP_S}


def long_run_limit(s: Subject) -> tuple[str, float]:
    """(knob, seconds) of the long_run limit a subject is judged by. #1372."""
    kind = kind_of(s)
    return f"watchdog_long_run_{kind}", long_run_limits()[kind]


def _long_run(w: World) -> list[Finding]:
    from harness import knobs
    out = []
    for s in w.top:
        knob, limit = long_run_limit(s)
        if (worked := serve_lease.worked_s(s, w.now)) is not None and worked > limit and not s.orphan:
            out.append(Finding("long_run", s, {"elapsed_s": round(worked), "limit_s": limit,
                                               "kind": kind_of(s),
                                               "limit": knobs.limit_text(knobs.hit(knob, limit, "s"))}))
    return out


def _overrun(w: World) -> list[Finding]:
    out, few_cases, few_pairs, per_case = [], 0, 0, []
    for s in w.evals:
        run = s.progress or {}
        planned, seen = run.get("planned_s_per_case") or {}, run.get("observed_s_per_case") or {}
        if int(run.get("done") or 0) < OVERRUN_MIN_CASES:
            few_cases += any(seen.get(k) and planned.get(k) and seen[k] > OVERRUN_FACTOR * planned[k] for k in seen)
            continue
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
            blind = _unmeasured(cells[1], inc, k) if got is None and planned.get(inc) else 0
            if blind:
                # Without measured incumbent seconds the challenger is held to its own plan per case. #1654.
                why = f"{blind} paired case(s) carry no measured seconds against {inc}: judged per case"
                if seen[k] > OVERRUN_FACTOR * planned[k]:
                    worst.append((seen[k] / planned[k], k, {"basis": "seconds per case", "why": why, "against": inc}))
                else:
                    per_case.append(why)
                continue
            if got is None and planned.get(inc):
                some = _paired(cells[1], inc, k, minimum=1)
                few_pairs += bool(some and some[0] is not None and some[0] > OVERRUN_FACTOR * planned[k] / planned[inc])
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
    from harness import cuts
    if out:
        cuts.cut("watchdog_overrun_factor", "runs judged far over their plan", dropped=len(out))
    if few_cases:
        cuts.cut("watchdog_overrun_min_cases", "runs over their plan not judged yet: too few cases", kept=few_cases)
    if few_pairs:
        cuts.cut("watchdog_overrun_min_pairs", "challengers over their plan not judged yet: too few pairs",
                 kept=few_pairs)
    if per_case:
        cuts.cut("watchdog_overrun_min_pairs", f"challengers not paired, within plan per case: {per_case[0]}",
                 kept=len(per_case))
    return out


def _no_progress(w: World) -> list[Finding]:
    out, stalled = [], {}
    for s in w.evals:
        run = s.progress or {}
        last = run.get("last_progress_at") or run.get("started_at")
        if last is None:
            continue
        plans = [v for v in (run.get("planned_s_per_case") or {}).values() if v]
        limit = max([STALL_S] + [STALL_CASES * v for v in plans])
        idle = w.now - float(last) - serve_lease.yielded_s(run, w.now, since_case=True)
        if idle > limit:
            stall_knob = "watchdog_stall" if limit == STALL_S else "watchdog_stall_cases"
            stalled[stall_knob] = stalled.get(stall_knob, 0) + 1
            out.append(Finding("no_progress", s, {"since_last_case_s": round(idle), "limit_s": round(limit),
                                                  "done": run.get("done"), "total": run.get("total")}))
    from harness import cuts
    for stall_knob, n in stalled.items():
        cuts.cut(stall_knob, "runs with no case finished for too long", dropped=n)
    return out


def _orphan(w: World) -> list[Finding]:
    young = sum(1 for s in w.top if s.orphan and (s.elapsed_s or 0) < ORPHAN_GRACE_S)
    if young:
        from harness import cuts
        cuts.cut("watchdog_orphan_grace", "orphans left one more wake", kept=young)
    return [Finding("orphan", s, {"elapsed_s": round(s.elapsed_s or 0), "why": s.why,
                                  "job_state": s.detail.get("state", "")})
            for s in w.top if s.orphan and (s.elapsed_s or 0) >= ORPHAN_GRACE_S]


def _mcp_clients(probes: watchdog_observe.Probes, world: World, procs: list) -> None:
    """Name the sessions each stale server holds: they keep its tool list until it stops, then refetch. #1166."""
    from harness import mcp_peers
    port = mcp_peers.port_of(world.mcp_stale[0].command)
    listing = probes.mcp_connections(port)
    if listing is None:
        world.gaps["mcp_clients"] = "lsof cannot be asked which clients hold the stale servers' streams"
        return
    held = mcp_peers.clients(listing, port)
    for s in world.mcp_stale:
        s.detail["clients"] = [mcp_peers.describe(c, procs) for c in held.get(s.pid, [])]


def _stale_mcp(w: World) -> list[Finding]:
    from harness import mcp_peers
    if (w.mcp_live_s or 0) < ORPHAN_GRACE_S:
        if w.mcp_stale:
            from harness import cuts
            cuts.cut("watchdog_orphan_grace", "stale MCP servers left one more wake", kept=len(w.mcp_stale))
        return []
    return [Finding("stale_mcp", s, {"elapsed_s": round(s.elapsed_s or 0), "live_pid": w.mcp_live,
                                     "stop": mcp_peers.stop_command([s.pid]),
                                     "clients": s.detail.get("clients", w.gaps.get("mcp_clients")),
                                     "remedy": STALE_MCP_REMEDY}) for s in w.mcp_stale]


def _on_gpu(w: World, s: Subject) -> bool:
    """It holds the GPU lock; when the holder cannot be told, any subject not running cloud-only evals. #1370."""
    return s.key == w.gpu if w.gpu is not None else not _cloud_only(w, s)


def _contention(w: World) -> list[Finding]:
    """A batch job holding the GPU while an owner hold is in force or a client was served since it started. #1509."""
    from harness import contention
    c, out = w.contention, []
    for s in w.top:
        if s.orphan or s.elapsed_s is None or not _on_gpu(w, s) or not contention.batch(s.detail):
            continue
        since = w.now - s.elapsed_s
        # A client the eval already yielded to was served; pausing for it too would hold measurement twice. #1558.
        seen = [(a, at) for a, at in c["requests"]
                if at >= since and not any(serve_lease.during_yield(r, at, w.now) for r in s.runs())]
        if c["hold"] is None and not seen:
            continue
        by: dict = {}
        for a, _ in seen:
            by[a] = by.get(a, 0) + 1
        out.append(Finding(contention.CRITERION, s, {"hold": (c["hold"] or {}).get("said"), "served": len(seen),
                                                     "by_alias": by, "idle_s": contention.IDLE_S,
                                                     "gpu": "holds the GPU lock" if w.gpu is not None else
                                                     "the GPU lock's holder cannot be told"}))
    if any(f.evidence["served"] for f in out):
        from harness import cuts
        cuts.cut("contention_idle", "batch GPU jobs paused for served traffic", dropped=len(out))
    return out


def _cloud_only(w: World, s: Subject) -> bool:
    """A subject whose evals all hold a cloud slot, while it holds no GPU lock itself. #1135."""
    if not w.cloud or {s.pgid, s.pid} & {(w.lock or {}).get("pgid"), (w.lock or {}).get("pid")} - {None}:
        return False
    def mine(x):
        return x.pgid in w.cloud or x.pid in w.cloud
    return mine(s) or (bool(s.children) and all(mine(c) for c in s.children))


def _idle_lock(w: World) -> list[Finding]:
    held = w.lock or {}
    if not held or w.busy():
        return []
    since = held.get("since")
    age = w.now - float(since) if isinstance(since, (int, float)) else None
    if age is not None and age < IDLE_HOLD_S:
        return []
    if age is not None:
        from harness import cuts
        cuts.cut("watchdog_idle_hold", "an eval lock held with nothing running", dropped=1)
    who = Subject("lock", f"lock pid {held.get('pid')}", "the eval lock's holder record", pid=held.get("pid"),
                  detail=dict(held))
    return [Finding("idle_lock", who, {"holder": held, "held_s": round(age) if age is not None else None})]


def _idle_model(w: World) -> list[Finding]:
    if w.busy() or not w.resident:
        return []
    return [Finding("idle_model", Subject("model", f"model {stem}", "router resident, served by no alias or adoption",
                                          detail={"stem": stem}), {"stem": stem})
            for stem in w.resident]


def _memory_state(w: World) -> tuple[dict, bool, bool]:
    """(evidence, swapping or critical, warn without either)."""
    from harness import pressure
    level = getattr(w.pressure, "level", None)
    swapping = w.swap_per_min is not None and w.swap_per_min > SWAPOUT_MAX_PER_MIN
    critical = level is not None and level >= pressure.CRITICAL
    ev = {"pressure_level": level, "swapouts_per_min": None if w.swap_per_min is None else round(w.swap_per_min),
          "limit_per_min": SWAPOUT_MAX_PER_MIN}
    return ev, swapping or critical, bool(getattr(w.pressure, "alarming", False)) and not (swapping or critical)


def _memory(w: World) -> list[Finding]:
    from harness import pressure
    ev, trouble, _ = _memory_state(w)
    out = [Finding("memory", s, ev) for s in w.top if not s.orphan] if trouble else []
    level = ev["pressure_level"]
    if out and not (level is not None and level >= pressure.CRITICAL):
        from harness import cuts
        cuts.cut("watchdog_swapout_max", "jobs judged in memory trouble by their swap rate", dropped=len(out))
    return out


def _in_use(w: World) -> list[str] | None:
    """The spec text of every running eval, None when one wrote no progress file: unknown use is not idle."""
    specs = []
    for s in w.evals:
        if not s.progress:
            return None
        specs += [str(v) for v in (s.progress.get("specs") or {}).values()]
    return specs


def idle(w: World) -> list[dict]:
    """Resident models no running eval names and nothing serves: what a warn can give back. #1082."""
    used = _in_use(w)
    if used is None:
        return []
    out = [{"server": "router", "model": m} for m in w.resident or [] if not any(m in u for u in used)]
    if w.mlx_held and w.protected is not None and w.mlx_held not in w.protected \
            and not any(w.mlx_held in u for u in used):
        out.append({"server": "mlx", "model": w.mlx_held})
    return out


def unload_after(now: float) -> float:
    """Seconds without a request after which a served model is given back: the day limit in the owner's hours, else the router's own."""
    if daytime(now):
        return IDLE_UNLOAD_DAY_S
    from harness import knobs
    return float(knobs.resolve(IDLE_UNLOAD_SITE))


def _idle_unload(w: World) -> list[Finding]:
    limit, out = unload_after(w.now), []
    for m in w.served:
        since = w.idle_since.get(f"{m['server']}:{m['model']}")
        if m["in_flight"] is not False or since is None or w.now - since < limit:
            continue
        # The spell's start is in the key, so only an unload that did not take repeats and escalates.
        spell = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(since))
        out.append(Finding("idle_unload", Subject("model", f"{m['server']} {m['model']} idle since {spell}",
                                                  "loaded, no request in flight, named by no running eval", detail=m),
                           {"server": m["server"], "model": m["model"], "idle_s": round(w.now - since),
                            "limit_s": limit, "day": daytime(w.now)}))
    if out and daytime(w.now):
        from harness import cuts
        cuts.cut("serve_idle_unload_day_s", "idle models given back in the day hours", dropped=len(out))
        hour = time.localtime(w.now).tm_hour
        edge_knob = "watchdog_day_start_hour" if hour - DAY_START_HOUR < DAY_END_HOUR - hour else "watchdog_day_end_hour"
        cuts.cut(edge_knob, "idle models given back inside the day hours, at the nearer edge", dropped=len(out))
    return out


def _memory_warn(w: World) -> list[Finding]:
    ev, _, warn = _memory_state(w)
    if not warn or _sustained(w) is not None:
        return []
    ev = {**ev, "idle": idle(w)}
    return [Finding("memory_warn", s, ev) for s in w.top if not s.orphan]


#: The criteria whose rows are samples of memory at warn. #1482.
WARN_CRITERIA = ("memory_warn", "memory_sustained", "memory_stuck")


def _every_s() -> float:
    from harness import knobs
    return float(knobs.resolve(EVERY_SITE) or 5) * 60.0


def warn_samples(conn, now: float) -> int:
    """Earlier wakes, back from `now` with no wake between them missing, that recorded memory at warn here. #1482."""
    gap = 1.5 * _every_s()
    here, mine = _mine(conn)
    rows = conn.execute(
        f"SELECT DISTINCT at FROM watchdog_actions WHERE criterion IN ({','.join('?' * len(WARN_CRITERIA))}) "
        f"AND at < ? AND at >= ? AND {here} ORDER BY at DESC",
        (*WARN_CRITERIA, now, now - WARN_SUSTAINED * gap, *mine)).fetchall()
    n, last = 0, now
    for r in rows:
        if last - float(r["at"]) > gap:
            break
        n, last = n + 1, float(r["at"])
    return n


def spare(w: World) -> list[dict]:
    """Loaded models with no request in flight that no running eval names: what a sustained warn gives back. #1482."""
    used = _in_use(w)
    if used is None:
        return []
    return [{"server": m["server"], "model": m["model"]} for m in w.served
            if m.get("in_flight") is False and not any(m["model"] in u for u in used)]


def _sustained(w: World) -> dict | None:
    """The evidence when memory has sat at warn for WARN_SUSTAINED wakes with nothing idle, else None. #1482."""
    ev, _, warn = _memory_state(w)
    if not warn or w.warn_samples is None or "served" in w.gaps or w.warn_samples + 1 < WARN_SUSTAINED or idle(w):
        return None
    return {**ev, "samples": w.warn_samples + 1, "limit_samples": WARN_SUSTAINED, "spare": spare(w)}


def _warn_findings(w: World, criterion: str, with_spare: bool) -> list[Finding]:
    ev = _sustained(w)
    if ev is None or bool(ev["spare"]) != with_spare:
        return []
    out = [Finding(criterion, s, ev) for s in w.top if not s.orphan]
    if out:
        from harness import cuts
        cuts.cut("watchdog_warn_sustained", f"memory at warn for {ev['samples']} wakes with nothing idle: "
                                            f"{criterion}", dropped=len(ev["spare"]) or len(out))
    return out


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
    out = [Finding("node_fallbacks", Subject("node", f"node {f['node']}", "live_audit.node_fallbacks",
                                             detail=f), {"requests": f["requests"], "limit": FALLBACK_MAX,
                                                         "aliases": f.get("aliases", [])})
           for f in w.fallbacks or [] if int(f.get("requests") or 0) >= FALLBACK_MAX]
    if out:
        from harness import cuts
        cuts.cut("watchdog_fallback_max", "serving nodes judged a fallback spike", dropped=len(out))
    return out


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


_LONG_RUN_KNOBS = tuple(f"watchdog_long_run_{k}" for k in KINDS)

CRITERIA = (
    Criterion("long_run", _LONG_RUN_KNOBS, NOTIFY, PAUSE, ("processes",),
              _long_run, "has run longer than its kind's limit"),
    Criterion("overrun", ("watchdog_overrun_factor", "watchdog_overrun_min_cases", "watchdog_overrun_min_pairs"), FILE, STOP,
              ("processes", "progress"), _overrun,
              "observed s/case far over the plan's, or a challenger far slower than planned on the incumbent's cases"),
    Criterion("no_progress", ("watchdog_stall", "watchdog_stall_cases"), NOTIFY, STOP, ("processes", "progress"),
              _no_progress, "no case finished for too long: wedged"),
    Criterion("orphan", ("watchdog_orphan_grace",), REAP, FILE, ("processes",), _orphan,
              "an eval or job whose sweep, worker or queue row is gone"),
    Criterion("stale_mcp", ("watchdog_orphan_grace",), NOTIFY, FILE, ("processes", "mcp_unit"), _stale_mcp,
              "an old MCP server kept alive by a client's open stream, serving the tool list it started with"),
    Criterion("contention", ("contention_idle",), PAUSE, NOTIFY, ("processes", "contention"), _contention,
              "served lanes in use or an owner hold while a batch job holds the GPU: paused at its next case"),
    Criterion("idle_lock", ("watchdog_idle_hold",), NOTE, FILE, ("processes", "lock"), _idle_lock,
              "the eval lock held with nothing running"),
    Criterion("idle_model", (), NOTE, UNLOAD, ("processes", "resident"), _idle_model,
              "a router model resident with nothing running and nothing serving it"),
    Criterion("idle_unload", ("serve_idle_unload_s", "serve_idle_unload_day_s", "watchdog_day_start_hour",
                              "watchdog_day_end_hour"), UNLOAD, NOTIFY, ("processes", "served"),
              _idle_unload, "a loaded model with no request for longer than the day or night limit"),
    Criterion("memory", ("watchdog_swapout_max",), NOTIFY, PAUSE, ("processes", "pressure"), _memory,
              "swapping or critical memory pressure while a job runs"),
    Criterion("memory_warn", ("watchdog_swapout_max",), NOTIFY, UNLOAD, ("processes", "pressure"), _memory_warn,
              "memory pressure at warn with no swapping while a job runs: give back idle models, never pause"),
    Criterion("memory_sustained", ("watchdog_warn_sustained", "watchdog_every"), UNLOAD, NOTIFY,
              ("processes", "pressure", "warn_samples"), lambda w: _warn_findings(w, "memory_sustained", True),
              "memory at warn for several wakes with nothing idle: give back served models no running eval uses"),
    Criterion("memory_stuck", ("watchdog_warn_sustained", "watchdog_every"), PAUSE, NOTIFY,
              ("processes", "pressure", "warn_samples"), lambda w: _warn_findings(w, "memory_stuck", False),
              "memory at warn for several wakes with nothing to give back: pause the sweep, told once"),
    Criterion("gateway_down", (), NOTIFY, RESTART, ("gateway",), _gateway_down,
              "the gateway's liveliness probe fails"),
    Criterion("mlx_dead", (), RESTART, NOTIFY, ("mlx",), _mlx_dead,
              "mlx_lm.server is up but its generation thread died, so every request fails"),
    Criterion("interactive_down", (), RESTART, NOTIFY, (), interactive.finding, interactive.WHAT),
    Criterion("tts_footprint", ("tts_footprint_gb",), RESTART, NOTIFY, ("processes", "tts"), audio_models.finding,
              audio_models.WHAT),
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
             "gateway": w.gateway_up, "mlx": w.mlx_generating, "fallbacks": w.fallbacks,
             "mcp_unit": w.mcp_live, "warn_samples": w.warn_samples, "contention": w.contention}.get(need, True)
    if value is None:
        return {"lock": "the eval lock could not be read", "resident": "the router or its defaults could not be read",
                "pressure": "memory pressure could not be sampled",
                "gateway": "no gateway unit is loaded here, or launchd cannot be asked",
                "mlx": "no mlx unit is loaded here, or its /health did not answer",
                "fallbacks": "the store or the served config could not be read",
                "mcp_unit": "no mcp unit is loaded here, or launchd cannot be asked",
                "warn_samples": "the earlier warn samples could not be read",
                "contention": "the served lanes or the hold could not be read: no store"}[need]
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


# --- record ----------------------------------------------------------------------

def _machine(conn) -> int | None:
    from harness import runs
    got = runs.here(conn)
    return got[0] if got else None


def _mine(conn) -> tuple[str, tuple]:
    return machine_scope.where("watchdog_actions.mine", _machine(conn))


def repeats(conn, f: Finding, now: float, dry_run: bool, windowed: bool = True) -> int:
    """Prior trips of this criterion on this subject inside the escalation window (or ever), this machine."""
    here, mine = _mine(conn)
    return int(conn.execute(
        "SELECT COUNT(*) AS n FROM watchdog_actions WHERE criterion = ? AND subject = ? AND dry_run = ? "
        f"AND at >= ? AND {here}",
        (f.criterion, f.subject.key, int(dry_run), now - ESCALATE_WINDOW_S if windowed else 0.0, *mine)).fetchone()["n"])


def overrun_stopped(conn, out) -> bool:
    """Whether the watchdog ever stopped the run in `out` as an overrun: its stop file, or its own record of a stop. #1409."""
    from evals import watch
    if watch.stop_reason(out) == watch.OVERRUN:
        return True
    row = conn.execute(
        "SELECT 1 FROM watchdog_actions WHERE criterion = ? AND action = ? AND dry_run = 0 AND result = ? "
        "AND run_dir = ? LIMIT 1", (watch.OVERRUN, STOP, ACTED, canon(out))).fetchone()
    return row is not None


def notified_since(conn, f: Finding, now: float) -> float | None:
    """When this criterion last put a notification on this subject's desktop inside NOTIFY_EVERY_S, this machine."""
    here, mine = _mine(conn)
    at = conn.execute(
        "SELECT MAX(at) AS at FROM watchdog_actions WHERE criterion = ? AND subject = ? AND dry_run = 0 "
        f"AND notified = 1 AND at >= ? AND {here}", (f.criterion, f.subject.key, now - NOTIFY_EVERY_S, *mine)).fetchone()["at"]
    return None if at is None else float(at)


#: Criteria whose pause is also put on the desktop, once. #1482.
PUSHED = ("memory_stuck",)


def _act(conn, hands: watchdog_hands.Hands, action: str, f: Finding, now: float) -> Said:
    if action == NOTIFY:
        last = notified_since(conn, f, now)
        if last is not None:
            return Said(f"{HELD}: shown {now - last:.0f}s ago (once per {NOTIFY_EVERY_S:.0f}s per criterion and "
                        "subject)", WITHHELD)
    done = said(hands.do(action, f), action)
    if action == PAUSE and f.criterion in PUSHED and notified_since(conn, f, now) is None:
        shown = said(hands.do(NOTIFY, f), NOTIFY)
        done = Said(f"{done}; {shown}", done.result, shown.notified)
    return done


def run_dir(s: Subject) -> str:
    """The run directory a subject's own eval writes, from its progress file or an absolute --out; '' when none."""
    m = re.search(r"--out[= ](\S+)", s.command or "")
    d = (s.progress or {}).get("_dir") or (m.group(1) if m and Path(m.group(1)).is_absolute() else "")
    return canon(d) if d else ""


def record(conn, f: Finding, action: str, escalated: bool, dry_run: bool, outcome: str, now: float) -> int:
    evidence = {**f.evidence, "identified_by": f.subject.why, "pid": f.subject.pid, "pgid": f.subject.pgid,
                "command": f.subject.command, "owner": f.subject.owner, "fingerprint": watchdog_hands.fingerprint(f)}
    got = Said(outcome, DRY) if dry_run else said(outcome, action)
    cur = conn.execute(
        "INSERT INTO watchdog_actions (at, machine_id, criterion, subject, action, escalated, dry_run, "
        "evidence, outcome, result, notified, job_id, pgid, run_dir) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (now, _machine(conn), f.criterion, f.subject.key, action, int(escalated), int(dry_run),
         json.dumps(evidence, default=str, sort_keys=True), str(got), got.result, int(got.notified),
         f.subject.job_id, f.subject.pgid, run_dir(f.subject)))
    conn.commit()
    return cur.lastrowid


# --- one wake --------------------------------------------------------------------

def acting(environ=None) -> bool:
    environ = os.environ if environ is None else environ
    return environ.get(ACT_ENV, "") == "1"


@contextlib.contextmanager
def _alone(probes: watchdog_observe.Probes):
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


def wake(conn, probes: watchdog_observe.Probes | None = None, hands: watchdog_hands.Hands | None = None, act: bool = False,
         now: float | None = None, say=print) -> dict:
    """Observe, judge, act (or say what it would), record each act. Returns what happened."""
    probes = probes or watchdog_observe.Probes()
    hands = hands or watchdog_hands.Hands(say=say)
    now = time.time() if now is None else now
    with _alone(probes) as alone:
        if not alone:
            say("another watchdog wake holds the lock; nothing done")
            return {"acted": [], "skipped": {}, "unowned": [], "busy": True}
        world = watchdog_observe.observe(probes, conn, now)
        findings, skipped = judge(world)
        acted, held = [], {}
        for f in findings:
            c = BY_ID[f.criterion]
            escalated = repeats(conn, f, now, not act) >= ESCALATE_AFTER
            if escalated or repeats(conn, f, now, not act, windowed=False) >= ESCALATE_AFTER:
                held_knob = "watchdog_escalate_after" if escalated else "watchdog_escalate_window"
                held[held_knob] = held.get(held_knob, 0) + 1
            action = c.escalation if escalated else c.action
            if action == PAUSE and not f.subject.runs():
                # A time or memory limit never stops a job; one with nothing to pause through is told about. #1371.
                action, f = NOTIFY, Finding(f.criterion, f.subject, {**f.evidence, "unpausable": UNPAUSABLE})
            outcome = _act(conn, hands, action, f, now) if act else Said("dry-run", DRY)
            if outcome.result == WITHHELD:
                held_knob = "watchdog_notify_every"
                held[held_knob] = held.get(held_knob, 0) + 1
            row = record(conn, f, action, escalated, not act, outcome, now)
            mark = "" if act else "[dry-run] would "
            say(f"{mark}{action}{' (escalated)' if escalated else ''} {f.subject.key}: {f.criterion} "
                f"{json.dumps(f.evidence, default=str)} -> {outcome}")
            acted.append({"row": row, "criterion": f.criterion, "subject": f.subject.key, "action": action,
                          "escalated": escalated, "outcome": outcome})
        from harness import cuts
        for held_knob, n in held.items():
            cuts.cut(held_knob, _HELD_WHAT[held_knob], dropped=n, conn=conn)
        for cid, why in skipped.items():
            say(f"skipped {cid}: {why}")
        from harness import lane_probe, owned
        for line in owned.reap(act=act):
            say(f"{'' if act else '[dry-run] '}{line}")
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
