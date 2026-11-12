"""A running eval's checkpoint, pause hook and progress file, for resume (#813) and an outside watchdog (#810)."""
from __future__ import annotations

import contextlib
import json
import os
import statistics
import time
from dataclasses import dataclass, field
from pathlib import Path

from harness import proc_identity, run_state

#: Exit status of a run paused at --stop-at or on request, rows checkpointed. #813.
PAUSED = 75
#: Exit status of a --resume whose checkpoint is another exam. #813.
STALE = 77
#: Exit status of a paired run stopped because its incumbent answered none of its first cases. #1656.
SILENT = 78
#: The stop file reason of that run. #1656.
INCUMBENT_SILENT = "incumbent_silent"

CHECKPOINT = run_state.CHECKPOINT
PROGRESS = run_state.PROGRESS
#: Touch this file in a run's directory, or send the run SIGUSR1, and it pauses after the case in flight.
PAUSE_FILE = run_state.PAUSE_FILE
#: How a run that paused at its stop time says so. #1618.
AT_STOP_TIME = "paused at its stop time"
#: The watchdog writes this, naming its criterion, before it signals a run to stop. #1409.
STOP_FILE = run_state.STOP_FILE
#: The one stop that ends a run as a suspected harness defect rather than pausing it. #1409.
OVERRUN = "overrun"
#: The pause reason of a case whose KV would leave less than memory.MIN_HEADROOM_GB safely available. #1482.
MEMORY_HEADROOM = "memory_headroom"


def clock() -> float:
    return time.time()


def sleep(seconds: float) -> None:
    time.sleep(seconds)


def ask_pause(outdir, reason: str = "") -> Path:
    """Write the run's pause file: a timestamp, then the reason a reader can act on. #1082."""
    target = Path(outdir) / PAUSE_FILE
    target.write_text(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {reason}".strip(), encoding="utf-8")
    return target


def pause_reason(outdir) -> str:
    """The reason a pause file names after its timestamp; "" for a bare touch, SIGUSR1 or no file. #1082."""
    return _reason(outdir, PAUSE_FILE)


def mark_stop(outdir, reason: str) -> Path:
    """Write the run's stop file: a timestamp, then why the watchdog stopped it. #1409."""
    target = Path(outdir) / STOP_FILE
    target.write_text(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {reason}".strip(), encoding="utf-8")
    return target


def stop_reason(outdir) -> str:
    """Why the watchdog stopped the run in `outdir`; "" when it named none or never stopped it. #1409."""
    return _reason(outdir, STOP_FILE)


def _reason(outdir, name: str) -> str:
    try:
        text = (Path(outdir) / name).read_text(encoding="utf-8").strip()
    except (OSError, ValueError):
        return ""
    return text.partition(" ")[2].strip()


class Stop(Exception):
    """The run pauses between cases."""

    def __init__(self, why: str):
        super().__init__(why)
        self.why = why


class Deferred(Stop):
    """The run pauses before a case that does not fit now; `reason` goes in its pause file. #1482."""

    def __init__(self, why: str, reason: str):
        super().__init__(f"paused on request ({reason}): {why}")
        self.reason = reason


class Silent(Stop):
    """The run ends: its incumbent answered nothing, so there is no comparison to resume. #1656."""


@dataclass
class Watch:
    planned: dict = field(default_factory=dict)
    stop_at: float | None = None
    outdir: Path | None = None
    left: dict = field(default_factory=dict)
    walls: dict = field(default_factory=dict)
    began: float = 0.0
    asked: bool = False
    #: A serve_lease.Yielder when this run yields to serving between cases; None never yields. #1556.
    yielder: object = None
    yields: int = 0
    yield_s: float = 0.0
    #: Yield seconds since the last finished case, which the watchdog leaves out of no_progress. #1556.
    yield_since_case_s: float = 0.0
    yielding_since: float | None = None
    yielding_to: str = ""
    #: [start, end] of each yield, so the watchdog does not pause a run for a client it already yielded to. #1558.
    yield_spans: list = field(default_factory=list)
    cuts: list = field(default_factory=list)
    changed: object = None

    def _requested(self) -> bool:
        return self.asked or (self.outdir is not None and (self.outdir / PAUSE_FILE).exists())

    def before(self, key: str, case: str = "") -> bool:
        """Raise Stop when the run pauses here; whether it yielded to serving first. #813, #1556."""
        served = self._serve()
        if self._requested():
            raise Stop(f"paused on request, {self.left_cases()} case(s) left")
        # The slice is the run's own time: seconds yielded to serving move its stop time on. #1556.
        if self.stop_at is not None and clock() >= self.stop_at + self.yield_s:
            raise Stop(f"{AT_STOP_TIME}, {self.left_cases()} case(s) left")
        self.restart(key, case)
        return served

    def restart(self, key: str = "", case: str = "") -> None:
        """Start the case's clock now, after any warm-up a yield made it need."""
        self.began = clock()
        if self.yielder is not None and key:
            self.yielder.contended()
            self.yielder.case(key, case, self.planned.get(key))

    def cut(self, key: str, case: str, why: str) -> None:
        """A case cut to serve a delegation: a harness cut, its row thrown away, the case run again. #1556."""
        self.cuts.append({"candidate": key, "case": case, "why": why})
        print(f"  cut {case} of {key} to serve ({why}); it runs again after the yield", flush=True)
        self._changed()

    def _serve(self) -> bool:
        """Wait out a serving lease between cases, the wait kept out of every case's and the run's time. #1556."""
        if self.yielder is None:
            return False
        from harness import serve_lease
        node = getattr(self.yielder, "node", "")
        who = serve_lease.held(node=node)
        if not who:
            return False
        start, mark = clock(), time.perf_counter()
        self.yielding_since, self.yielding_to = start, who
        self.yielder.yielding(who)
        print(f"yielding to {who} between cases", flush=True)
        self._changed()
        try:
            while serve_lease.held(node=node) and not self._requested():
                sleep(serve_lease.POLL_S)
        finally:
            span = max(0.0, clock() - start)
            self.yields += 1
            self.yield_s += span
            self.yield_since_case_s += span
            self.yield_spans.append([start, start + span])
            self.yielding_since, self.yielding_to = None, ""
            self.yielder.between()
            _hidden(mark)
            print(f"resumed after {span:.0f}s yielded to serving", flush=True)
            self._changed()
        return True

    def _changed(self) -> None:
        if callable(self.changed):
            self.changed()

    def served(self) -> dict:
        """This run's yields to serving so far, for progress.json and the run's evidence. #1556."""
        return {"count": self.yields, "seconds": round(self.yield_s, 3),
                "since_case_s": round(self.yield_since_case_s, 3),
                "yielding_since": self.yielding_since, "to": self.yielding_to, "cut": list(self.cuts),
                "spans": [list(x) for x in self.yield_spans]}

    def lap(self, key: str) -> float:
        wall = max(0.0, clock() - self.began)
        self.walls.setdefault(key, []).append(wall)
        self.left[key] = max(0, self.left.get(key, 1) - 1)
        self.yield_since_case_s = 0.0
        if self.yielder is not None:
            self.yielder.between()
        return wall

    def observed(self, key: str) -> float | None:
        got = self.walls.get(key)
        return statistics.fmean(got) if got else None

    def left_cases(self) -> int:
        return sum(self.left.values())


#: The completion wait kind a yield to serving is recorded as. #1556.
SERVING_YIELD = "serving_yield"


def _hidden(mark: float) -> None:
    """A yield is a wait no measuring() scope around it counts as model time. #1556."""
    from harness import completion
    waits = completion._WAITS.get()
    if waits is not None:
        waits.add(mark, time.perf_counter(), SERVING_YIELD)


@contextlib.contextmanager
def asks_pause(eye: Watch):
    """SIGUSR1 sets the pause request, read between cases; nothing where the platform lacks it."""
    import signal
    import threading
    sig = getattr(signal, "SIGUSR1", None)
    if sig is None or threading.current_thread() is not threading.main_thread():
        yield
        return

    def _ask(signum, frame):
        eye.asked = True

    before = signal.signal(sig, _ask)
    try:
        yield
    finally:
        signal.signal(sig, before)


#: Identity fields a checkpoint from before they were recorded lacks; their absence there is not a change. #1094.
LATER = ("identities",)


def differs(had: dict, now: dict) -> list[str]:
    """The identity fields a checkpoint and this run disagree on."""
    return sorted(k for k in set(had) | set(now) if had.get(k) != now.get(k)
                  and not (k in LATER and k not in had))


def read(outdir) -> tuple[dict, list[dict]] | None:
    """(identity, rows) a run directory's checkpoint holds; None when it has none."""
    path = Path(outdir) / CHECKPOINT
    if not path.is_file():
        return None
    lines = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            lines.append(json.loads(line))
        except ValueError:
            continue   # a torn line, or one an older resume glued a row onto (#1757)
    if not lines or "identity" not in lines[0]:
        return None
    return lines[0]["identity"], [x["row"] for x in lines[1:] if "row" in x]


class Checkpoint:
    """Every finished case as one line, so a pause or a kill loses at most the case in flight."""

    def __init__(self, outdir, identity: dict, keep: bool = False):
        self.path = Path(outdir) / CHECKPOINT
        if not keep:
            self.path.write_text(json.dumps({"identity": identity}) + "\n", encoding="utf-8")
        else:
            self._cut_torn()

    def _cut_torn(self) -> None:
        """Drop a last line a kill left with no newline, so the next row starts its own line. #1757."""
        data = self.path.read_bytes() if self.path.is_file() else b""
        if data and not data.endswith(b"\n"):
            tmp = self.path.with_suffix(".cut")
            tmp.write_bytes(data[:data.rfind(b"\n") + 1])
            os.replace(tmp, self.path)

    def add(self, row: dict, wall_s: float) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"row": {**row, "wall_s": round(wall_s, 3)}}, default=str) + "\n")
            f.flush()
            os.fsync(f.fileno())


class Progress:
    """progress.json beside the checkpoint, rewritten whole after every case."""

    def __init__(self, outdir, eye: Watch, specs: dict, total: int, done: int):
        self.path = Path(outdir) / PROGRESS
        self.eye, self.specs, self.total, self.done = eye, specs, total, done
        self.started = clock()
        self.at = self.started
        eye.changed = self.write

    def write(self, state: str = "", why: str = "", run_id=None) -> dict:
        pgid = os.getpgid(0) if hasattr(os, "getpgid") else None
        state = state or (run_state.W_YIELDING if self.eye.yielding_since is not None else run_state.W_RUNNING)
        if state not in run_state.WRITTEN:
            raise ValueError(f"progress state {state!r} is none of {run_state.WRITTEN}")
        got = {"state": state, "why": why, "done": self.done, "total": self.total,
               "serving_yields": self.eye.served(),
               "specs": self.specs, "planned_s_per_case": self.eye.planned,
               "observed_s_per_case": {k: self.eye.observed(k) for k in self.eye.walls},
               "started_at": self.started, "last_progress_at": self.at,
               "pid": os.getpid(), "pgid": pgid, "pid_started": proc_identity.started(os.getpid()),
               "pause_file": str(self.path.parent / PAUSE_FILE),
               "run_id": run_id}
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(got, indent=2, default=str), encoding="utf-8")
        os.replace(tmp, self.path)
        return got

    def case_done(self) -> None:
        from harness import exclusive
        self.done += 1
        self.at = clock()
        self.write()
        # A run's length is not known when it takes the lock; a waiter behind it reads these beats. #775.
        exclusive.beat()


def read_progress(outdir) -> dict:
    try:
        return json.loads((Path(outdir) / PROGRESS).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def claim(outdir, held: contextlib.ExitStack) -> str:
    """Make this process the run dir's one writer until `held` closes; why it may not, or "". #1740."""
    from harness import exclusive, proc_identity
    out = Path(outdir)
    fd = os.open(out / run_state.WRITER, os.O_RDWR | os.O_CREAT, 0o644)
    if not exclusive._take(fd):
        os.close(fd)
        return f"another evals.run holds {out / run_state.WRITER}, which names it"
    held.callback(_let_go, fd)
    os.ftruncate(fd, 0)
    os.write(fd, json.dumps(proc_identity.identity(os.getpid())).encode())
    state = run_state.of(out)
    pid = state.progress.get("pid")
    # A writer of an older release takes no lock; its progress file names it. No file names no writer.
    if (out / PROGRESS).exists() and state.name in run_state.LIVE and str(pid) != str(os.getpid()):
        return f"{out} is {state.name} under pid {pid}{f' ({state.why})' if state.why else ''}"
    return ""


def _let_go(fd: int) -> None:
    from harness import exclusive
    os.lseek(fd, 0, os.SEEK_SET)
    exclusive._release(fd)
    os.close(fd)
