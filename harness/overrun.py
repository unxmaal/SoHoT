"""The per-case cells of a paired run's checkpoint and the challenger/incumbent ratio the overrun criterion judges."""
from __future__ import annotations


def cells(run: dict):
    """(incumbent key, {key: {case: [wall_s, reply tokens or None, rows]}}) from a paired run's checkpoint, else None. #864."""
    from evals.watch import read
    got = read(run["_dir"]) if run.get("_dir") else None
    if not got:
        return None
    ident, rows = got
    key_of = {spec: key for key, spec in (run.get("specs") or {}).items()}
    order = [key_of.get(c, c) for c in ident.get("candidates") or []]
    if len(order) < 2:
        return None
    from harness import reasons
    budget = ident.get("max_tokens")
    by: dict = {}
    for r in rows:
        if r.get("candidate") is None or r.get("case_id") is None:
            continue
        toks = (r.get("metrics") or {}).get("completion_tokens")
        if not toks and r.get("failure_class") == "token_budget_exhausted":
            toks = budget
        cell = by.setdefault(r["candidate"], {}).setdefault(r["case_id"], [0.0, 0, 0])
        took = r.get("wall_s") or r.get("seconds")
        # A harness_error row, or one with no time, measured nothing about the model: its cell has no seconds. #1654.
        measured = took and r.get("failure_class") != reasons.HARNESS_ERROR
        cell[0] = cell[0] + float(took) if measured and cell[0] is not None else None
        cell[1] = cell[1] + toks if toks and cell[1] is not None else None
        cell[2] += 1
    if ident.get("reuse"):
        # The incumbent cells taken from stored draws keep their stored time, so a challenger is still judged against it. #1094.
        from harness import reuse
        for case, (seconds, toks) in reuse.timing(run["_dir"]).items():
            by.setdefault(order[0], {}).setdefault(case, [float(seconds) if seconds else None, toks or None, 1])
    return order[0], by


def unmeasured(by: dict, inc: str, ch: str) -> int:
    """Cases both candidates finished where either cell carries no measured seconds. #1654."""
    mine, theirs = by.get(ch) or {}, by.get(inc) or {}
    return sum(1 for c in mine if c in theirs and mine[c][2] == theirs[c][2] and None in (mine[c][0], theirs[c][0]))


def paired(by: dict, inc: str, ch: str, minimum: int | None = None):
    """(observed challenger/incumbent ratio, basis, pairs) on the cases both finished, or None below the minimum. #864."""
    from harness import watchdog
    minimum = watchdog.OVERRUN_MIN_PAIRS if minimum is None else minimum
    mine, theirs = by.get(ch) or {}, by.get(inc) or {}
    pairs = [c for c in mine if c in theirs and mine[c][2] == theirs[c][2]
             and mine[c][0] is not None and theirs[c][0] is not None]
    tok = [c for c in pairs if mine[c][1] and theirs[c][1]]
    if len(tok) >= minimum:
        a, at = sum(mine[c][0] for c in tok), sum(mine[c][1] for c in tok)
        b, bt = sum(theirs[c][0] for c in tok), sum(theirs[c][1] for c in tok)
        return ((a / at) / (b / bt) if b else None), "seconds per reply token", len(tok)
    if len(pairs) >= minimum:
        b = sum(theirs[c][0] for c in pairs)
        return (sum(mine[c][0] for c in pairs) / b if b else None), "seconds", len(pairs)
    return None
