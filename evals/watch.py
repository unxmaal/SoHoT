"""A running eval's checkpoint, pause hook and progress file, for resume (#813) and an outside watchdog (#810)."""
from __future__ import annotations

import contextlib
import json
import os
import statistics
import time
from dataclasses import dataclass, field
from pathlib import Path

#: Exit status of a run paused at --stop-at or on request, rows checkpointed. #813.
PAUSED = 75
#: Exit status of a --resume whose checkpoint is another exam. #813.
STALE = 77

CHECKPOINT = "checkpoint.jsonl"
PROGRESS = "progress.json"
#: Touch this file in a run's directory, or send the run SIGUSR1, and it pauses after the case in flight.
PAUSE_FILE = "pause"


def clock() -> float:
    return time.time()


class Stop(Exception):
    """The run pauses between cases."""

    def __init__(self, why: str):
        super().__init__(why)
        self.why = why


@dataclass
class Watch:
    planned: dict = field(default_factory=dict)
    stop_at: float | None = None
    outdir: Path | None = None
    left: dict = field(default_factory=dict)
    walls: dict = field(default_factory=dict)
    began: float = 0.0
    asked: bool = False

    def before(self, key: str) -> None:
        if self.asked or (self.outdir is not None and (self.outdir / PAUSE_FILE).exists()):
            raise Stop(f"paused on request, {self.left_cases()} case(s) left")
        if self.stop_at is not None and clock() >= self.stop_at:
            raise Stop(f"paused at its stop time, {self.left_cases()} case(s) left")
        self.began = clock()

    def lap(self, key: str) -> float:
        wall = max(0.0, clock() - self.began)
        self.walls.setdefault(key, []).append(wall)
        self.left[key] = max(0, self.left.get(key, 1) - 1)
        return wall

    def observed(self, key: str) -> float | None:
        got = self.walls.get(key)
        return statistics.fmean(got) if got else None

    def left_cases(self) -> int:
        return sum(self.left.values())


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


def differs(had: dict, now: dict) -> list[str]:
    """The identity fields a checkpoint and this run disagree on."""
    return sorted(k for k in set(had) | set(now) if had.get(k) != now.get(k))


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
            break   # a kill mid-write leaves a torn last line
    if not lines or "identity" not in lines[0]:
        return None
    return lines[0]["identity"], [x["row"] for x in lines[1:] if "row" in x]


class Checkpoint:
    """Every finished case as one line, so a pause or a kill loses at most the case in flight."""

    def __init__(self, outdir, identity: dict, keep: bool = False):
        self.path = Path(outdir) / CHECKPOINT
        if not keep:
            self.path.write_text(json.dumps({"identity": identity}) + "\n", encoding="utf-8")

    def add(self, row: dict, wall_s: float) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"row": {**row, "wall_s": round(wall_s, 3)}}, default=str) + "\n")


class Progress:
    """progress.json beside the checkpoint, rewritten whole after every case."""

    def __init__(self, outdir, eye: Watch, specs: dict, total: int, done: int):
        self.path = Path(outdir) / PROGRESS
        self.eye, self.specs, self.total, self.done = eye, specs, total, done
        self.started = clock()
        self.at = self.started

    def write(self, state: str = "running", why: str = "", run_id=None) -> dict:
        pgid = os.getpgid(0) if hasattr(os, "getpgid") else None
        got = {"state": state, "why": why, "done": self.done, "total": self.total,
               "specs": self.specs, "planned_s_per_case": self.eye.planned,
               "observed_s_per_case": {k: self.eye.observed(k) for k in self.eye.walls},
               "started_at": self.started, "last_progress_at": self.at,
               "pid": os.getpid(), "pgid": pgid, "pause_file": str(self.path.parent / PAUSE_FILE),
               "run_id": run_id}
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(got, indent=2, default=str), encoding="utf-8")
        os.replace(tmp, self.path)
        return got

    def case_done(self) -> None:
        self.done += 1
        self.at = clock()
        self.write()


def read_progress(outdir) -> dict:
    try:
        return json.loads((Path(outdir) / PROGRESS).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
