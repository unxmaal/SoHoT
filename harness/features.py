"""The feature table: each unit, switch, hold, lane, node, engine and hook on, off, paused, parked, on demand or broken, and what decides it (#2081)."""
from __future__ import annotations

import ast
import functools
import json
import os
import plistlib
import re
import subprocess
import sys
from pathlib import Path

ON, OFF, PAUSED, PARKED, ON_DEMAND, BROKEN, UNKNOWN = "on", "off", "paused", "parked", "on demand", "broken", "unknown"
STATES = (ON, OFF, PAUSED, PARKED, ON_DEMAND, BROKEN, UNKNOWN)
#: The line a serve script prints when it exits 0 with no model to load.
NOTHING = "nothing to serve"
LOG_TAIL = 4096
LAUNCHCTL_TIMEOUT_S = 10.0
KINDS = ("unit", "switch", "lane", "node", "engine", "hook")
_ENV_ARGS = ("environ", "env")
_LAUNCHCTL_RC = re.compile(r"-?\d+")


def row(kind: str, name: str, state: str, by: str, since=None) -> dict:
    return {"kind": kind, "name": name, "state": state, "by": by, "since": since}


def launchctl_list(prefix: str, run=None, platform: str | None = None) -> dict | None:
    """unit -> (pid, last exit) for every loaded label under prefix; None where launchd is not there to ask."""
    if (platform or sys.platform) != "darwin":
        return None
    got = (run or subprocess.run)(["launchctl", "list"], capture_output=True, text=True, timeout=LAUNCHCTL_TIMEOUT_S)
    if got.returncode:
        raise RuntimeError(f"launchctl list exited {got.returncode}: {(got.stderr or '').strip()[:200]}")
    out = {}
    for ln in got.stdout.splitlines():
        parts = ln.split("\t")
        if len(parts) == 3 and parts[2].startswith(prefix + "."):
            pid = int(parts[0]) if parts[0].isdigit() else None
            rc = int(parts[1]) if _LAUNCHCTL_RC.fullmatch(parts[1]) else None
            out[parts[2][len(prefix) + 1:]] = (pid, rc)
    return out


def _tail(p: Path) -> str:
    with open(p, "rb") as f:
        f.seek(max(0, p.stat().st_size - LOG_TAIL))
        return f.read().decode("utf-8", "replace")


def _plist_env(p: Path) -> dict:
    return dict(plistlib.loads(p.read_bytes()).get("EnvironmentVariables") or {})


def engine_units(root: Path, names) -> list[str]:
    """The units whose serve script can exit 0 with nothing to serve."""
    out = []
    for name in names:
        try:
            if NOTHING in (root / "scripts" / f"serve-{name}.sh").read_text(encoding="utf-8"):
                out.append(name)
        except OSError:
            continue
    return out


def units(names, agents: Path, listed: dict | None, logs: Path, prefix: str, engines=()) -> list[dict]:
    """A row per unit scripts/launchd.sh installs, and one per engine unit that last found nothing to serve."""
    out, idle = [], []
    for name in names:
        if not (agents / f"{prefix}.{name}.plist").is_file():
            out.append(row("unit", name, OFF, "not installed"))
            continue
        if listed is None:
            out.append(row("unit", name, UNKNOWN, "no launchd here to ask"))
            continue
        if name not in listed:
            out.append(row("unit", name, OFF, "installed, not loaded"))
            continue
        pid, rc = listed[name]
        if pid:
            out.append(row("unit", name, ON, "loaded, running"))
        elif rc == 0:
            out.append(row("unit", name, ON_DEMAND, "loaded, idle, last exit 0"))
        else:
            out.append(row("unit", name, BROKEN, f"loaded, idle, last exit {rc if rc is not None else 'unknown'}"))
        if name in engines:
            log = logs / f"{name}.log"
            try:
                lines = [ln.strip() for ln in _tail(log).splitlines() if ln.strip()]
            except FileNotFoundError:
                lines = []
            except OSError as exc:
                idle.append(row("engine", name, UNKNOWN, f"{log.name} not read: {exc}"[:300]))
                continue
            if pid:
                idle.append(row("engine", name, ON, "serving"))
            elif lines and NOTHING in lines[-1]:
                idle.append(row("engine", name, OFF, lines[-1][:200], log.stat().st_mtime))
    return out + idle


def switch_readers(root: Path) -> tuple[tuple[str, str, str], ...]:
    """(module, function, variable) for each harness function of (environ=None) that returns a test of one env variable."""
    files = sorted((root / "harness").rglob("*.py"))
    return _scan(root, tuple((p, p.stat().st_mtime_ns, p.stat().st_size) for p in files))


@functools.lru_cache(maxsize=4)
def _scan(root: Path, stamps: tuple) -> tuple[tuple[str, str, str], ...]:
    out = []
    for p, _, _ in stamps:
        tree = ast.parse(p.read_text(encoding="utf-8"))
        consts = {}
        for node in tree.body:
            if (isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name)
                    and node.targets[0].id.endswith("_ENV") and isinstance(node.value, ast.Constant)
                    and isinstance(node.value.value, str)):
                consts[node.targets[0].id] = node.value.value
        for fn in tree.body:
            if not isinstance(fn, ast.FunctionDef) or not fn.body:
                continue
            a = fn.args
            if [x.arg for x in a.args] not in ([n] for n in _ENV_ARGS) or a.kwonlyargs or a.vararg or a.kwarg:
                continue
            last = fn.body[-1]
            if not (isinstance(last, ast.Return) and isinstance(last.value, ast.Compare)):
                continue
            named = [n.id for n in ast.walk(last.value) if isinstance(n, ast.Name) and n.id in consts]
            if len(set(named)) == 1:
                mod = ".".join(p.relative_to(root).with_suffix("").parts)
                out.append((mod, fn.name, consts[named[0]]))
    return tuple(out)


def switches(root: Path, envs: dict[str, dict], readers=None) -> list[dict]:
    """Each env switch as the units that set it see it; one no unit sets reads as its default."""
    import importlib
    out = []
    for mod, fn, var in (switch_readers(root) if readers is None else readers):
        setters = sorted(u for u, env in envs.items() if var in env)
        env = envs[setters[0]] if setters else {}
        got = bool(getattr(importlib.import_module(mod), fn)(env))
        on = not got if "disabled" in fn else got
        by = f"{var}={env[var]} in the {setters[0]} unit" if setters else f"{var} unset in every unit"
        out.append(row("switch", var, ON if on else OFF, f"{by}, read by {mod.removeprefix('harness.')}.{fn}"))
    return out


def holds(conn, now: float) -> list[dict]:
    from harness import hold
    out = []
    for scope in hold.SCOPES:
        h = hold.active(conn, now, scope)
        if h:
            by = f"hold: {h.get('said')}" + (f" until {hold._at(h['until'])}" if h.get("until") else "")
            out.append(row("switch", f"{scope} hold", PAUSED, by, h.get("held_at")))
        else:
            out.append(row("switch", f"{scope} hold", ON, "no hold"))
    return out


def queue_row(q: dict) -> list[dict]:
    if q.get("error"):
        return [row("switch", "queue", UNKNOWN, q["error"])]
    if q.get("paused"):
        return [row("switch", "queue", PAUSED, f"paused: {q.get('reason')}" + (f" by {q['by']}" if q.get("by") else ""),
                    q.get("paused_since"))]
    return [row("switch", "queue", ON, "not paused")]


def _engine_of(lane: str, spec: str) -> str:
    from harness import engines, lanes, serving
    head = spec.split(":", 1)[0]
    if ":" in spec and head in engines.names():
        return head
    if lane not in lanes.GGUF_SERVED:
        return ""
    try:
        return serving.engine_for(spec)
    except Exception:  # noqa: BLE001 - an unnamed engine is a blank cell, not a failed table
        return ""


def lanes_rows(defaults: dict, pinned, routed: list) -> list[dict]:
    """Each lane with something to serve: parked, served by a node, resident here, or loaded on demand."""
    from harness import lanes
    out = []
    for lane, spec in sorted(defaults.items()):
        engine = _engine_of(lane, spec)
        why, until = lanes.parked(lane)
        node = next((n for n in routed if lane in n.lanes), None)
        if why:
            out.append(row("lane", lane, PARKED, f"lanes.PARKED: {why}" + (f" until {until}" if until else "")))
        elif node:
            out.append(row("lane", lane, ON, f"served by node {node.name} ({node.engine})"))
        elif lane in pinned:
            out.append(row("lane", lane, ON, "resident: pinned by the interactive server" + (f" ({engine})" if engine else "")))
        else:
            out.append(row("lane", lane, ON_DEMAND, f"loaded on demand: {spec}" + (f" on {engine}" if engine else "")))
    return out


def nodes_rows(every: list) -> list[dict]:
    out = []
    for n in every:
        role = n.role or ("interactive" if n.lanes else "node")
        if n.parked:
            out.append(row("node", n.name, PARKED, f"nodes.yaml parked: true (role {role})"))
        else:
            out.append(row("node", n.name, ON, f"nodes.yaml routed (role {role}, {n.engine})"))
    return out


def hook_rows(settings: Path) -> list[dict]:
    from harness import tool_route
    try:
        data = json.loads(settings.read_text(encoding="utf-8") or "{}")
    except FileNotFoundError:
        return [row("hook", "tool-route", OFF, f"no {settings.name}")]
    found = any(tool_route.SCRIPT in str(h.get("command") or "")
                for e in (data.get("hooks") or {}).get("PostToolUse") or [] for h in e.get("hooks") or [])
    return [row("hook", "tool-route", ON if found else OFF,
                f"{'in' if found else 'not in'} {settings.name} PostToolUse")]


def settings_path(environ=None) -> Path:
    from harness import ask
    environ = os.environ if environ is None else environ
    return Path(environ.get(ask.CLAUDE_ENV) or Path.home() / ".claude") / "settings.json"


def _group(kind: str, fn, *args) -> list[dict]:
    try:
        return fn(*args)
    except Exception as exc:  # noqa: BLE001 - one source failing leaves the others' rows
        return [row(kind, "not read", UNKNOWN, f"{type(exc).__name__}: {exc}"[:300])]


def gather(conn, now: float, queue: dict | None = None, *, root: Path | None = None, agents: Path | None = None,
           logs: Path | None = None, listed=..., nodes_file=None, settings: Path | None = None, pinned=None,
           defaults=None, readers=None) -> dict:
    """Every feature row, read from the units, switches, holds, lanes, nodes.yaml and settings.json."""
    from harness import adopt, install_env, interactive, nodes, paths
    root = root or paths.REPO
    agents = agents or Path.home() / "Library" / "LaunchAgents"
    logs = logs or paths.logs()
    prefix = install_env.PREFIX
    names = install_env.services(root / "scripts" / "launchd.sh")
    rows = []
    try:
        got = launchctl_list(prefix) if listed is ... else listed
        rows += units(names, agents, got, logs, prefix, engine_units(root, names))
    except Exception as exc:  # noqa: BLE001
        rows.append(row("unit", "not read", UNKNOWN, f"{type(exc).__name__}: {exc}"[:300]))
    envs = {}
    for n in names:
        p = agents / f"{prefix}.{n}.plist"
        if not p.is_file():
            continue
        try:
            envs[n] = _plist_env(p)
        except (OSError, plistlib.InvalidFileException, ValueError) as exc:
            rows.append(row("switch", f"{n} unit environment", UNKNOWN, f"{p.name} does not parse: {exc}"[:300]))
    rows += _group("switch", switches, root, envs, readers)
    rows += _group("switch", holds, conn, now) if conn is not None else [row("switch", "holds", UNKNOWN, "store down")]
    if queue is not None:
        rows += queue_row(queue)
    every = []
    try:
        every = nodes._all(nodes_file)
        rows += nodes_rows(every)
    except Exception as exc:  # noqa: BLE001
        rows.append(row("node", "not read", UNKNOWN, f"{type(exc).__name__}: {exc}"[:300]))
    rows += _group("lane", lambda: lanes_rows(adopt.lane_defaults(conn) if defaults is None else defaults,
                                              interactive.pinned() if pinned is None else pinned,
                                              [n for n in every if not n.parked]))
    rows += _group("hook", hook_rows, settings or settings_path())
    order = {k: i for i, k in enumerate(KINDS)}
    rows.sort(key=lambda r: order.get(r["kind"], len(KINDS)))
    return {"rows": rows}
