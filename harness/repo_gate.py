"""The repo lane gates code adoption: a code challenger meets the repo lane first, and only a win there goes on. #889."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from harness import lanes, methods

GATE = "repo"
#: Lanes whose adoption waits on a repo-lane win; leetcode/hevalpro stay the cheap screen before it.
GATED = ("code",)
#: Tasks whose every case this machine's `soh cases control repo` found valid before the gate holds (#889 acceptance).
MIN_TASKS = 30


def valid_tasks(machine: str | None = None) -> set:
    """Fix commits of repo tasks whose every committed case is valid on this machine."""
    from evals import repo
    from evals.core import load_cases
    from evals.importers import CASES
    from harness import holdout
    from harness import memory_store as ms
    cases = load_cases(CASES / GATE) if (CASES / GATE).is_dir() else []
    got = repo.verdicts(cases, machine or ms.this_machine()["fingerprint"])
    tasks: dict = {}
    for c in cases:
        if holdout.task_of(c):
            tasks.setdefault(holdout.task_of(c), []).append(got.get(c.id) == "valid")
    return {t for t, ok in tasks.items() if all(ok)}


def active() -> bool:
    """The gate holds where the repo lane can grade (macOS sandbox-exec) and MIN_TASKS tasks are valid here."""
    from evals import repo
    if sys.platform != "darwin" or not Path(repo.SANDBOX_EXEC).is_file():
        return False
    return len(valid_tasks()) >= MIN_TASKS


def lane_of(row: dict, want: str = "") -> str:
    """The lane `row` is measured in, as measure._measure picks it; a repo row stays a repo row."""
    from harness.commands import measure as measure_cmd
    return measure_cmd.lane_for(row, want)


def verdict(conn, name: str, before: float | None = None) -> str | None:
    """The outcome of the proposal's latest repo-lane verdict at adopt (decided before `before`), None when it has none."""
    from harness import adopt
    got = conn.execute("SELECT v.outcome FROM verdicts v JOIN proposals p ON p.id = v.proposal_id "
                       "WHERE p.name = ? AND v.tier = ? AND v.detail LIKE ? AND (? IS NULL OR v.decided_at < ?) "
                       "ORDER BY v.id DESC LIMIT 1", (name, adopt.TIER, f"{GATE}:%", before, before)).fetchone()
    return got[0] if got else None


def needs(conn, row: dict, want: str = "", before: float | None = None) -> bool:
    """Whether `row` is a gated comparison whose repo-lane comparison has not been won; the gate's activity aside."""
    return (lane_of(row, want) in GATED and methods.runs_in(row.get("name", ""), GATE)
            and verdict(conn, row.get("name", ""), before) != "measured")


def owed(conn) -> list[dict]:
    """Proposals whose latest verdict is a repo-lane win: their code comparison is still to run."""
    from harness import adopt
    rows = conn.execute("SELECT p.name, p.lane, p.attaches_to FROM proposals p "
                        "JOIN verdicts v ON v.id = p.state_verdict_id "
                        "WHERE p.state = 'measured' AND v.tier = ? AND v.detail LIKE ? ORDER BY v.id",
                        (adopt.TIER, f"{GATE}:%")).fetchall()
    return [{**dict(r), "lane": GATED[0]} for r in rows
            if any(lanes.serves(r["lane"], g) for g in GATED)]


def join(rows, conn, want: str = "", on: bool | None = None) -> list[dict]:
    """`rows` and the owed code comparisons not among them, so the gain order keys them too. #1323."""
    from harness.commands import measure as measure_cmd
    if not (active() if on is None else on):
        return list(rows)
    rows = list(rows)
    names = {r.get("name") for r in rows}
    return rows + [r for r in owed(conn) if r["name"] not in names and measure_cmd.takes(r, want)]


def order(rows, conn, want: str = "", on: bool | None = None, before: float | None = None) -> list[dict]:
    """Each gated row with its repo-lane comparison just ahead of it, where the queue put it; nothing else moves. #1323."""
    if not (active() if on is None else on):
        return list(rows)
    queued = {r.get("name"): r for r in reversed(rows) if lane_of(r, want) == GATE}
    out, done = [], set()
    for r in rows:
        name, mine = r.get("name"), lane_of(r, want) == GATE
        if name in done and mine:
            continue
        if not mine and name not in done and needs(conn, r, want, before):
            done.add(name)
            out.append(queued.get(name) or {**r, "lane": GATE})
        elif mine:
            done.add(name)
        out.append(r)
    return out


def blocked(conn, row: dict, want: str = "") -> str:
    """Why `row` is not measured now: a gated comparison waits on a repo-lane win; "" when it may run."""
    lane = lane_of(row, want)
    if not needs(conn, row, want) or not active():
        return ""
    got = verdict(conn, row.get("name", ""))
    return (f"{row.get('name', '')}: no {GATE}-lane win ({got or 'not measured there'}), "
            f"so its {lane} comparison does not run")


def args_for(a, row: dict):
    """The measure args for `row`: a repo row is measured in the repo lane whatever lane the sweep is scoped to."""
    if lane_of(row) != GATE or (getattr(a, "lane", "") or "").strip().lower() == GATE:
        return a
    return argparse.Namespace(**{**vars(a), "lane": GATE})
