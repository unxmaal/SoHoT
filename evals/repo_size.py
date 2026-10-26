"""Reference-fix size of a repo case: non-test lines base..fix changes, its case selector and a size-quartile table. #890."""
from __future__ import annotations

from evals import repo

#: Largest reference fix --max-fix-lines keeps when it names none; 0 keeps every case.
MAX_FIX_LINES = 0
#: Smallest reference fix --min-fix-lines keeps when it names none; 0 keeps every case.
MIN_FIX_LINES = 0


def fix_lines(params: dict, memo: dict | None = None) -> int:
    """Lines added plus removed by base..fix outside test files (git diff --numstat; a binary file counts 0)."""
    key = (str(params["source_repo"]), str(params["base"]), str(params["fix"]))
    if memo is not None and key in memo:
        return memo[key]
    m = repo.mirror(key[0], need=key[1:])
    got = repo._git(["--git-dir", str(m), "diff", "--numstat", "--no-renames", key[1], key[2]])
    total = 0
    for line in got.stdout.decode("utf-8", errors="replace").splitlines():
        added, removed, path = (line.split("\t", 2) + ["", ""])[:3]
        if path and not repo.is_test_path(path) and added.isdigit() and removed.isdigit():
            total += int(added) + int(removed)
    if memo is not None:
        memo[key] = total
    return total


def sizes(cases, memo: dict | None = None) -> dict[str, int]:
    """case id -> fix lines, for every repo case that names a fix."""
    memo = {} if memo is None else memo
    return {c.id: fix_lines(c.params, memo) for c in cases if (c.params or {}).get("fix")}


def at_most(cases, limit: int, by: dict | None = None) -> list:
    """The cases whose reference fix changes at most `limit` non-test lines; limit 0 keeps every case."""
    if not limit:
        return list(cases)
    by = sizes(cases) if by is None else by
    return [c for c in cases if c.id in by and by[c.id] <= limit]


def at_least(cases, floor: int, by: dict | None = None) -> list:
    """The cases whose reference fix changes at least `floor` non-test lines; floor 0 keeps every case."""
    if not floor:
        return list(cases)
    by = sizes(cases) if by is None else by
    return [c for c in cases if c.id in by and by[c.id] >= floor]


def quartiles(rows, by: dict[str, int]) -> list[dict]:
    """Four equal groups of the rows' cases by fix size (smallest first), each with its line range and passes per candidate."""
    ids = sorted({r["case_id"] for r in rows if r["case_id"] in by}, key=lambda i: (by[i], i))
    n = len(ids)
    groups = 4 if n >= 4 else 1
    out = []
    for q in range(groups):
        part = ids[q * n // groups:(q + 1) * n // groups]
        if not part:
            continue
        mine = set(part)
        per: dict[str, list] = {}
        for r in rows:
            if r["case_id"] in mine:
                per.setdefault(r["candidate"], [0, 0])
                per[r["candidate"]][0] += bool(r.get("passed"))
                per[r["candidate"]][1] += 1
        out.append({"quartile": q + 1 if groups == 4 else 0, "lines": (by[part[0]], by[part[-1]]), "cases": len(part),
                    "passed": {c: tuple(v) for c, v in sorted(per.items())}})
    return out


def text(table: list[dict]) -> str:
    """The quartile table as printed after a repo run and in soh repo-report."""
    if not table:
        return ""
    lines = ["by reference-fix size (non-test lines changed):"]
    for q in table:
        lo, hi = q["lines"]
        got = "  ".join(f"{c} {k}/{n}" for c, (k, n) in q["passed"].items())
        lines.append(f"  {'Q' + str(q['quartile']) if q['quartile'] else 'all'} {lo:>4}-{hi:<4} lines  {q['cases']:>3} case(s)  {got}")
    return "\n".join(lines)
