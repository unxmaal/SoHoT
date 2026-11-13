"""What an unstamped (NULL machine_id) row means to each question asked of the store, declared once. #1769."""
from __future__ import annotations

#: An unstamped row is every machine's: a legacy row from before stamping, or a pool any machine may take.
EVERY = "every"
#: An unstamped row is this machine's only while it has no machines row, which is when it would have written one.
UNKNOWN = "unknown"
#: An unstamped row is nobody's, and a machine with no row owns nothing.
NOBODY = "nobody"
MEANINGS = (EVERY, UNKNOWN, NOBODY)

#: Each question asked of a table's machine_id, named table.question, and what an unstamped row answers to it.
RULES = {
    "adoptions.served": EVERY,       # a legacy adoption serves everywhere (#412, #485)
    "day_clearances.mine": UNKNOWN,
    "deploys.mine": NOBODY,          # _insert stamps the machine; an unstamped deploy is no machine's to settle or follow
    "holds.mine": UNKNOWN,
    "jobs.claimable": EVERY,         # an unowned pending job is any worker's; _claim's CAS runs it once (#703)
    "jobs.claimed": NOBODY,          # _claim stamps the runner, so an unstamped job ran nowhere known (#703, #697)
    "jobs.twin": UNKNOWN,            # a job carries another's work on only the machine stamped on both (#1770)
    "knob_sweeps.mine": UNKNOWN,
    "lane_probes.mine": UNKNOWN,
    "leases.mine": UNKNOWN,
    "limit_cuts.shown": EVERY,       # a cut recorded before the machine had a row is shown to every machine
    "paused_runs.mine": NOBODY,
    "reverifications.mine": UNKNOWN,  # _queue stamps machine_row, None before this machine had a row
    "runs.ran_here": NOBODY,         # as runs.here: a run is this machine's by its stamp alone
    "verdicts.decided_here": NOBODY, # an unstamped verdict is from before #266 and was decided nowhere known
    "watchdog_actions.mine": UNKNOWN,
}


def table(rule: str) -> str:
    return rule.split(".")[0]


def _ids(mid) -> list[int]:
    if mid is None:
        return []
    if isinstance(mid, (list, tuple, set, frozenset)):
        return [int(m) for m in mid]
    return [int(mid)]


def holds(rule: str, stamped, mid) -> bool:
    """where() asked of one row already read: is a row stamped `stamped` machine `mid`'s under `rule`."""
    ids = _ids(mid)
    if stamped is None:
        return RULES[rule] == EVERY or (RULES[rule] == UNKNOWN and not ids)
    return int(stamped) in ids


def where(rule: str, mid, column: str = "machine_id") -> tuple[str, tuple]:
    """The predicate and its args for the rows of machine `mid` (an id, several ids, or None for no row) under `rule`."""
    null = RULES[rule]
    ids = _ids(mid)
    if not ids:
        return ("1 = 0", ()) if null == NOBODY else (f"{column} IS NULL", ())
    stamped = f"{column} = ?" if len(ids) == 1 else f"{column} IN ({','.join('?' * len(ids))})"
    if null == EVERY:
        return f"({stamped} OR {column} IS NULL)", tuple(ids)
    return stamped, tuple(ids)


def here(conn, rule: str, column: str = "machine_id") -> tuple[str, tuple]:
    """where() for this machine's row in `conn`'s store."""
    from harness import memory_store as ms
    return where(rule, ms.machine_row(conn), column)
