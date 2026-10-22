"""The repo lane gates code adoption: a code challenger meets the repo lane first, and only a win there goes on. #889."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from harness import lanes

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
    own = lanes.canonical(row.get("lane"))
    want = (want or "").strip().lower()
    if own == GATE:
        return GATE
    return want if want and lanes.serves(row.get("lane"), want) else own


def verdict(conn, name: str) -> str | None:
    """The outcome of the proposal's latest repo-lane verdict at adopt, None when it has none."""
    from harness import adopt
    got = conn.execute("SELECT v.outcome FROM verdicts v JOIN proposals p ON p.id = v.proposal_id "
                       "WHERE p.name = ? AND v.tier = ? AND v.detail LIKE ? ORDER BY v.id DESC LIMIT 1",
                       (name, adopt.TIER, f"{GATE}:%")).fetchone()
    return got[0] if got else None


def owed(conn) -> list[dict]:
    """Proposals whose latest verdict is a repo-lane win: their code comparison is still to run."""
    from harness import adopt
    rows = conn.execute("SELECT p.name, p.lane, p.attaches_to FROM proposals p "
                        "JOIN verdicts v ON v.id = p.state_verdict_id "
                        "WHERE p.state = 'measured' AND v.tier = ? AND v.detail LIKE ? ORDER BY v.id",
                        (adopt.TIER, f"{GATE}:%")).fetchall()
    return [{**dict(r), "lane": GATED[0]} for r in rows
            if any(lanes.serves(r["lane"], g) for g in GATED)]


def order(rows, conn, want: str = "") -> list[dict]:
    """Repo-lane comparisons first: each row measured in a gated lane gets one ahead of all else; owed rows join."""
    if not active():
        return list(rows)
    rows, owing = list(rows), owed(conn)
    names = {r.get("name") for r in rows}
    rows += [r for r in owing if r["name"] not in names]
    won = {r["name"] for r in owing}
    first = [r for r in rows if lane_of(r, want) == GATE]
    have = {r.get("name") for r in first}
    first += [{**r, "lane": GATE} for r in rows
              if lane_of(r, want) in GATED and r.get("name") not in have | won]
    return first + [r for r in rows if lane_of(r, want) != GATE]


def blocked(conn, row: dict, want: str = "") -> str:
    """Why `row` is not measured now: a gated comparison waits on a repo-lane win; "" when it may run."""
    lane = lane_of(row, want)
    if lane not in GATED or not active():
        return ""
    got = verdict(conn, row.get("name", ""))
    if got == "measured":
        return ""
    return (f"{row.get('name', '')}: no {GATE}-lane win ({got or 'not measured there'}), "
            f"so its {lane} comparison does not run")


def args_for(a, row: dict):
    """The measure args for `row`: a repo row is measured in the repo lane whatever lane the sweep is scoped to."""
    if lane_of(row) != GATE or (getattr(a, "lane", "") or "").strip().lower() == GATE:
        return a
    return argparse.Namespace(**{**vars(a), "lane": GATE})
