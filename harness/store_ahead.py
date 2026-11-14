"""A store at a schema newer than this code: a deploy's reload pending, or a stale release link. #1799."""
from __future__ import annotations

import os
import re
import sys
import time
from pathlib import Path

from harness import paths

#: An open deploys row older than this is a deploy that died unsettled, not one whose reload is still to come.
RUNNING_FOR_S = 7200.0

#: The deploy link names another release: launchd's next start of this unit runs the code that speaks the store.
SUPERSEDED = "superseded"
#: This release is still linked, but a deploy is running: its switch flips the link and reloads every unit.
RELOAD = "reload"
#: This release is linked, no deploy runs, and the store is ahead of it: the link is stale and nothing will reload.
STALE = "stale"
#: Not a deployed release (a checkout or worktree): its code is older than the store.
BEHIND = "behind"
#: A deploy ended with the store ahead of the code and waits on its repair (soh deploy repair). #1841.
REPAIR = "repair"
#: Waiting on a reload that is coming: skipped quietly, exit 0, no alert, but only in a launchd unit.
QUIET = frozenset({SUPERSEDED, RELOAD})
#: Set in each launchd unit's environment (scripts/launchd.sh): launchd, not a person, starts it again. #1959.
UNIT_ENV = "LH_UNIT"

_SCHEMAS = re.compile(r"schema (\d+), this code speaks (\d+)")


def newer(exc: BaseException | None) -> BaseException | None:
    """The NewerStore refusal in exc's chain, None when there is none."""
    from harness.memory_store.migrations import NewerStore
    seen = set()
    while exc is not None and id(exc) not in seen:
        if isinstance(exc, NewerStore):
            return exc
        seen.add(id(exc))
        exc = exc.__cause__ or exc.__context__
    return None


def deploy_running(now: float | None = None, connect=None) -> bool:
    """Whether a deploy row is open and young, read as the store stands: no migration, no write."""
    from harness import store
    now = time.time() if now is None else now
    try:
        conn = (connect or store.open_as_is)()
    except Exception:  # noqa: BLE001 - an unreadable store says no deploy is known to be running
        return False
    try:
        row = conn.execute("SELECT MAX(started_at) AS at FROM deploys WHERE outcome = ''").fetchone()
    except Exception:  # noqa: BLE001 - a deploys table this code cannot read says the same
        return False
    finally:
        conn.close()
    return row is not None and row["at"] is not None and now - float(row["at"]) < RUNNING_FOR_S


def verdict(root: Path | None = None, link=None, running=None) -> str:
    """Which of REPAIR, SUPERSEDED, RELOAD, STALE or BEHIND this process is, for a store ahead of its code."""
    from harness import deploy_repair
    if deploy_repair.pending():
        return REPAIR
    root = Path(root or paths.REPO).resolve()
    if root.parent != (paths.home() / "releases").resolve():
        return BEHIND
    link = paths.deploy_link() if link is None else link
    if link and Path(link).resolve() != root:
        return SUPERSEDED
    return RELOAD if (deploy_running() if running is None else running) else STALE


def line(kind: str, exc: BaseException, root: Path | None = None) -> str:
    got = _SCHEMAS.search(str(exc))
    have, speaks = got.groups() if got else ("newer", "older")
    name = Path(root or paths.REPO).resolve().name
    if kind == SUPERSEDED:
        return (f"store ahead, waiting for reload: the store is schema {have}, release {name} speaks {speaks} and "
                f"is no longer linked; launchd's next start runs the linked release")
    if kind == RELOAD:
        return (f"store ahead, waiting for reload: the store is schema {have}, release {name} speaks {speaks}; "
                f"the running deploy's switch reloads this unit")
    if kind == REPAIR:
        from harness import deploy_repair
        return (f"store ahead: the store is schema {have}, release {name} speaks {speaks}; "
                + "; ".join(deploy_repair.lines(deploy_repair.pending())))
    if kind == STALE:
        return (f"store ahead of the linked release: the store is schema {have}, the linked release {name} speaks "
                f"{speaks} and no deploy is running, so nothing will reload it; link a release that speaks {have}")
    return str(exc)


def answer(exc: BaseException, told: set) -> tuple[str, str]:
    """(kind, line) for a server meeting a newer store; each kind is logged once per process, without a traceback."""
    kind = verdict()
    text = line(kind, exc)
    if kind not in told:
        told.add(kind)
        print(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {text}", file=sys.stderr, flush=True)
    return kind, text


def said(verb: str, exc: BaseException) -> int:
    """One line for a command that met a newer store, never a traceback: exit 0 in a unit a reload reruns, else 1."""
    from harness.commands import common
    kind = verdict()
    text = f"{verb or 'soh'}: {line(kind, exc)}"
    if kind in QUIET and in_unit():
        common.note(text)
        common.emit(True, store_ahead=kind, detail=text)
        return 0
    if kind in QUIET:
        text += "; this process was not started by a launchd unit, so no reload reruns it: run it again from the deploy"
    return common.err(text)


def _processes():
    from harness import watchdog_observe
    return watchdog_observe.Probes().processes()


def _tty() -> bool:
    return bool(sys.stdin is not None and sys.stdin.isatty())


def _cwd(pid: int) -> str:
    from harness import holders
    walk = holders.walkers()
    return next((path for how, path in walk[1](pid) if how == "cwd"), "") if walk else ""


def _unit_command(pid: int, command: str) -> bool:
    """Whether a process launchd started runs a unit: a word of its command or its cwd in a release or the deploy link."""
    from harness import job_release
    tops = {str(job_release.releases_dir()), os.path.realpath(job_release.releases_dir()), str(paths.home() / "deploy")}
    return any(job_release._within(w, t) is not None for w in [*command.split(), _cwd(pid)] for t in tops)


def in_unit(pid: int | None = None) -> bool:
    """Whether a launchd unit started this process, so a reload reruns it; a unit on a plist older than LH_UNIT too."""
    if os.environ.get(UNIT_ENV):
        return True
    if _tty():
        return False
    procs = _processes()
    if not procs:
        return True  # cannot tell: quiet, so an old-plist unit in a deploy window never alerts
    by = {p.pid: p for p in procs}
    p, seen = by.get(os.getpid() if pid is None else pid), set()
    while p is not None and p.ppid > 1 and p.pid not in seen:
        seen.add(p.pid)
        p = by.get(p.ppid)
    return p is None or _unit_command(p.pid, p.command)
