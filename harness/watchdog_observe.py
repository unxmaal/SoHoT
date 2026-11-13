"""What the watchdog reads of the machine, and the world it builds from it each wake. #814, #1909."""
from __future__ import annotations

import contextlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

from harness import audio_models, interactive

if TYPE_CHECKING:
    from harness.watchdog import Proc, World


def _etime(text: str) -> float:
    """ps etime [[dd-]hh:]mm:ss in seconds."""
    days, _, rest = text.strip().rpartition("-")
    parts = [int(p) for p in rest.split(":")]
    while len(parts) < 3:
        parts.insert(0, 0)
    h, m, s = parts[-3:]
    return (int(days) if days else 0) * 86400.0 + h * 3600 + m * 60 + s


def parse_ps(text: str) -> list[Proc]:
    from harness import watchdog as wd
    out = []
    for line in text.splitlines():
        bits = line.split(None, 4)
        if len(bits) < 5 or not bits[0].isdigit():
            continue
        try:
            out.append(wd.Proc(int(bits[0]), int(bits[1]), int(bits[2]), _etime(bits[3]), bits[4]))
        except ValueError:
            continue
    return out


class Probes:
    """Every read of the machine the watchdog makes. None from a probe means it could not be asked."""

    def processes(self) -> list[Proc] | None:
        from harness import watchdog as wd
        if sys.platform == "win32":
            return None
        try:
            got = subprocess.run(["ps", "-ww", "-axo", "pid=,ppid=,pgid=,etime=,command="], capture_output=True,
                                 text=True, timeout=wd.PROBE_TIMEOUT_S)
        except (OSError, subprocess.SubprocessError):
            return None
        return parse_ps(got.stdout) if got.returncode == 0 else None

    def _launchctl(self, service: str):
        from harness import watchdog as wd
        if sys.platform != "darwin":
            return None
        try:
            return subprocess.run(["launchctl", "print", f"gui/{os.getuid()}/{wd.LABEL}.{service}"],
                                  capture_output=True, text=True, timeout=wd.PROBE_TIMEOUT_S)
        except (OSError, subprocess.SubprocessError):
            return None

    def launchd_pid(self, service: str) -> int | None:
        got = self._launchctl(service)
        m = re.search(r"^\tpid = (\d+)", got.stdout, re.M) if got is not None and got.returncode == 0 else None
        return int(m.group(1)) if m else None

    def mcp_connections(self, port: int) -> str | None:
        """`lsof -F pn` of every established TCP connection on `port`; None when lsof cannot be asked."""
        from harness import watchdog as wd
        if sys.platform == "win32":
            return None
        try:
            got = subprocess.run(["lsof", "-nP", f"-iTCP:{port}", "-sTCP:ESTABLISHED", "-Fpn"], capture_output=True,
                                 text=True, timeout=wd.PROBE_TIMEOUT_S)
        except (OSError, subprocess.SubprocessError):
            return None
        # lsof exits 1 when it matched nothing
        return got.stdout if got.returncode == 0 or (got.returncode == 1 and not got.stdout) else None

    def launchd_loaded(self, service: str) -> bool | None:
        got = self._launchctl(service)
        return None if got is None else got.returncode == 0

    def heartbeat(self) -> dict | None:
        from harness import heartbeat
        return heartbeat.read()

    def job_pids(self) -> dict:
        """Queue job id -> the pid of its group leader, from the files the worker leaves. #628."""
        from harness import executors, job_procs
        out = {}
        for f in sorted(job_procs._pids().glob("*.pid")):
            with contextlib.suppress(OSError, ValueError):
                out[f.stem] = executors.pid_record(f)[0]
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
        except (OSError, exclusive.StoreDown):
            return None

    def cloud(self) -> set:
        """The process groups (and pids) holding a cloud slot, not the GPU lock. #1135."""
        from harness import exclusive
        try:
            held = exclusive.holders()
        except (OSError, exclusive.StoreDown):
            return set()
        gpu = {h.get(k) for h in held if h["lock"] == "gpu" for k in ("pgid", "pid")}
        return {h.get(k) for h in held if h["lock"] == "cloud" for k in ("pgid", "pid")} - gpu - {None}

    def resident(self) -> list[str] | None:
        """Router models nothing serves or adopted; None when the router or the defaults cannot be read."""
        from harness import router
        held = router.statuses()
        if held is None:
            return None
        try:
            keep = router.kept()
        except Exception:  # noqa: BLE001 - unknown protection means nothing is free to unload
            return None
        return sorted(k for k, v in held.items() if v in router.RESIDENT and k not in keep)

    def footprint(self, pid: int) -> float | None:
        return audio_models.footprint_gib(pid)

    def pressure(self):
        from harness import pressure
        return pressure.sample()

    def mlx_held(self) -> str | None:
        from harness import watchdog as wd
        if not self.launchd_loaded("mlx"):
            return None
        from harness import mlx_server, serving
        return mlx_server.held(serving.MLX_URL, timeout=wd.PROBE_TIMEOUT_S)

    def protected(self) -> set | None:
        from harness import router
        try:
            return set(router.protected())
        except Exception:  # noqa: BLE001 - unknown protection means nothing is free to unload
            return None

    def gateway_up(self) -> bool | None:
        from harness import watchdog as wd
        if not self.launchd_loaded("gateway"):
            return None
        import httpx

        from harness import completion
        try:
            r = httpx.get(completion.gateway_url() + "/health/liveliness", timeout=wd.PROBE_TIMEOUT_S)
        except httpx.HTTPError:
            return False
        return r.status_code == 200

    def mlx_generating(self) -> bool | None:
        """False when the loaded mlx unit answers that its generation thread died (#912); None when it cannot be asked."""
        from harness import watchdog as wd
        if not self.launchd_loaded("mlx"):
            return None
        from harness import mlx_server, serving
        return mlx_server.generating(serving.MLX_URL, timeout=wd.PROBE_TIMEOUT_S)

    def served(self) -> list[dict]:
        """Router models loaded now and a held mlx model other than its boot one, each with whether a request is in flight."""
        from harness import watchdog as wd
        from harness import router, slot_probe
        out = []
        for stem, status in (router.statuses() or {}).items():
            if status != "loaded":
                continue
            try:
                busy = slot_probe.idle(router._get(f"/slots?model={stem}"))
            except Exception:  # noqa: BLE001 - unknown slots are an unknown in-flight request
                busy = None
            out.append({"server": "router", "model": stem, "in_flight": None if busy is None else not busy})
        if self.launchd_loaded("mlx"):
            from harness import mlx_server, serving
            got = mlx_server.activity(serving.MLX_URL, timeout=wd.PROBE_TIMEOUT_S) or {}
            n = got.get("in_flight")
            if got.get("model") and got.get("model") != got.get("boot"):
                out.append({"server": "mlx", "model": got["model"],
                            "in_flight": None if not isinstance(n, int) or not got.get("boot") else n > 0})
        return out

    def last_use(self, conn, since: float) -> dict:
        """Served model -> its latest request since `since` that the watchdog or a smoke test did not send; None without a store."""
        if conn is None:
            return None
        from harness import gateway, purpose
        out: dict = {}
        for served, at in conn.execute(
                "SELECT served, MAX(at) FROM gateway_requests WHERE at >= ? AND purpose NOT IN (?, ?) GROUP BY served",
                (since, purpose.WATCHDOG, purpose.SMOKE)):
            model = gateway.strip_provider(str(served or ""))
            out[model] = max(float(at), out.get(model, 0.0))
        return out

    def lanes(self, conn, now: float) -> list[dict] | None:
        """One known-answer completion per resident text lane, each recorded in lane_probes (#924); None without a store."""
        from harness import watchdog as wd
        if conn is None:
            return None
        from harness import lane_probe
        return lane_probe.wake(conn, now, machine_id=wd._machine(conn))

    def contention(self, conn, now: float) -> dict | None:
        """The owner's hold and the served lanes' requests in the contention window; None without a store. #1509."""
        if conn is None:
            return None
        from harness import contention
        return contention.reading(conn, now)

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
        from harness import run_state
        for path in sorted(found):
            state = run_state.of(path.parent)
            if state.name in run_state.PAUSABLE:
                out.append({**state.progress, "_dir": str(path.parent)})
            elif state.name in (run_state.CRASHED, run_state.SIGNALLED):
                # Its process is gone, so no one acts on its pause; a paused run's pause file still says why. #1740.
                (path.parent / self.PAUSE_FILE).unlink(missing_ok=True)
        return out

    def pause(self, run: dict, reason: str = "") -> str:
        """Write the run's pause file naming why; the run checkpoints and exits between cases."""
        from harness import watchdog as wd
        from evals.watch import ask_pause
        where = Path(run["_dir"])
        target = Path(run.get("pause_file") or where / self.PAUSE_FILE)
        if target.parent.resolve() != where.resolve() or target.name != self.PAUSE_FILE:
            return wd.Said(f"refused: pause file {target} is outside the run directory {where}", wd.REFUSED)
        return wd.Said(f"pause file written: {ask_pause(where, reason)}")

    def mark_stop(self, run: dict, reason: str) -> str:
        """Write the run's stop file naming why, so its measure step can tell an overrun from any other stop. #1409."""
        from evals.watch import mark_stop
        try:
            return f"stop file written: {mark_stop(Path(run['_dir']), reason)}"
        except (KeyError, OSError) as exc:
            return f"stop file not written: {exc}"


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
    from harness import watchdog as wd
    now = time.time() if now is None else now
    world = wd.World(now=now)
    listed = probes.processes()
    if listed is None:
        world.gaps["processes"] = "the process table could not be read on this platform"
        listed = []
    procs = {p.pid: p for p in listed}

    discover = None
    dpid = probes.launchd_pid("discover")
    if dpid in procs and wd._DISCOVER.search(procs[dpid].command):
        p = procs[dpid]
        discover = wd.Subject("discover", f"discover pid {p.pid}", "the launchd discover agent's pid", pid=p.pid,
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
        s = wd.Subject("job", f"job {job_id}", "a work queue pid file names its group leader", pid=pid, pgid=pid,
                    elapsed_s=p.elapsed_s, command=p.command, orphan=orphan,
                    job_id=int(job_id) if str(job_id).isdigit() else None,
                    detail={"title": row.get("title", ""), "state": state,
                            "requested_by": row.get("requested_by", "")})
        jobs[pid] = s
        marks[pid] = f"job {job_id}"
        world.top.append(s)

    progress = probes.progress([p for p in listed if wd._EVAL.search(p.command)])
    if progress is None:
        world.gaps["progress"] = "no progress reader"
    by_pid = {int(r["pid"]): r for r in progress or [] if str(r.get("pid", "")).isdigit()}

    groups: dict = {}
    for p in listed:
        if wd._EVAL.search(p.command):
            groups.setdefault(p.pgid, []).append(p)
    for pgid, members in sorted(groups.items()):
        pids = {m.pid for m in members}
        top = min((m for m in members if m.ppid not in pids), key=lambda m: m.pid, default=members[0])
        owners = [marks[a] for a in [top.pid, *_ancestors(top.pid, procs), pgid] if a in marks]
        parent = next((t for o in owners for t in world.top
                       if t.key == o or (o == "discover" and t.kind == "discover")), None)
        owner = parent.key if parent is not None else (owners[0] if owners else "")
        run = next((by_pid[m.pid] for m in members if m.pid in by_pid), None)
        s = wd.Subject("eval", f"eval pgid {pgid}", "", pid=top.pid,
                    pgid=pgid if _ours_only(pgid, procs, lambda q: bool(wd._EVAL.search(q.command))) else None,
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

    world.mcp_live = probes.launchd_pid("mcp")
    if world.mcp_live in procs:
        from harness import mcp_peers
        world.mcp_live_s = procs[world.mcp_live].elapsed_s
        for p in mcp_peers.stale(listed, world.mcp_live):
            world.mcp_stale.append(wd.Subject("mcp", f"mcp pid {p.pid}", "a harness.mcp_server the mcp unit is not",
                                           pid=p.pid, elapsed_s=p.elapsed_s, command=p.command,
                                           orphan=p.ppid == 1, detail={"live_pid": world.mcp_live}))
        if world.mcp_stale:
            wd._mcp_clients(probes, world, listed)
    world.lock = probes.lock()
    world.gpu = _gpu_holder(world, procs)
    world.cloud = probes.cloud()
    world.resident = probes.resident()
    world.pressure = probes.pressure()
    world.swap_per_min = _swap_rate(probes, world.pressure, now)
    world.mlx_held = probes.mlx_held()
    world.protected = probes.protected() if world.mlx_held else None
    world.gateway_up = probes.gateway_up()
    world.mlx_generating = probes.mlx_generating()
    world.interactive = interactive.watch(probes.launchd_loaded("interactive"))
    world.fallbacks = probes.fallbacks(conn)
    try:
        world.tts = audio_models.watch(probes, listed)
    except Exception as exc:  # noqa: BLE001 - an unreadable tts server restarts nothing this wake
        world.gaps["tts"] = f"the tts server could not be read: {type(exc).__name__}: {exc}"[:300]
    try:
        world.served = probes.served()
        asked = probes.last_use(conn, now - wd.unload_after(now))
        if asked is None:
            world.gaps["served"] = "the served models' requests could not be read: no store, so none is called idle"
        else:
            world.idle_since = _idle_since(probes, world, asked, now)
    except Exception as exc:  # noqa: BLE001 - an unreadable server or store gives nothing back this wake
        world.gaps["served"] = f"the served models could not be read: {type(exc).__name__}: {exc}"[:300]
    try:
        world.warn_samples = wd.warn_samples(conn, now) if conn is not None else 0
    except Exception as exc:  # noqa: BLE001 - an unreadable history is a gap: a warn stays a warn
        world.warn_samples = None
        world.gaps["warn_samples"] = f"the earlier warn samples could not be read: {type(exc).__name__}: {exc}"[:300]
    try:
        world.contention = probes.contention(conn, now)
    except Exception as exc:  # noqa: BLE001 - unread contention pauses nothing this wake
        world.gaps["contention"] = f"the served lanes or the hold could not be read: {type(exc).__name__}: {exc}"[:300]
    try:
        world.lanes = probes.lanes(conn, now)
    except Exception as exc:  # noqa: BLE001 - a probe that cannot run is a gap, never a lost wake
        world.gaps["lanes"] = f"the lane probes failed: {type(exc).__name__}: {exc}"[:300]
    if world.lanes is None and "lanes" not in world.gaps:
        world.gaps["lanes"] = "the lane probes were not sent: no store, so no open incident could be read or probed"
    return world


def _gpu_holder(w: World, procs: dict) -> str | None:
    """The key of the top subject whose process, its evals' or a descendant's, holds the GPU lock. #1370."""
    held = w.lock
    if held is None:
        return None
    if not held:
        return ""
    pids = {p for p in (held.get("pid"), held.get("pgid")) if isinstance(p, int)}
    if not pids:
        return None
    chain = pids | {a for p in pids for a in _ancestors(p, procs)}
    for s in w.top:
        if any({x.pid, x.pgid} & chain for x in [s, *s.children]):
            return s.key
    return ""


def _idle_since(probes: Probes, w: World, asked: dict, now: float) -> dict:
    """"server:model" -> the latest of its last request, when this residency was first seen, when a run last named it."""
    from harness import watchdog as wd
    path = probes.state() / "idle.json"
    try:
        before = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        before = {}
    used, kept, out = wd._in_use(w), {}, {}
    for m in w.served:
        key, was = f"{m['server']}:{m['model']}", before.get(f"{m['server']}:{m['model']}") or {}
        named = used is None or m["in_flight"] is True or any(m["model"] in u for u in used)
        kept[key] = {"seen": was.get("seen", now), "pinned": now if named else was.get("pinned")}
        out[key] = max(t for t in (kept[key]["seen"], kept[key]["pinned"], asked.get(m["model"])) if t is not None)
    path.write_text(json.dumps(kept), encoding="utf-8")
    return out


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
