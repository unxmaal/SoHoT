"""A claims run read back per candidate: reviewed cases pooled, expect_empty cases per origin. #654.

    uv run python -m evals.claims_report [RESULTS.JSON | --run ID]

With no argument it reads the newest claims run in the store. Rows are joined to
this machine's local cases by id; nothing here prints case text.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for k of n, rounded to 4 places."""
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = (z / denom) * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (max(0.0, round(center - half, 4)), min(1.0, round(center + half, 4)))


def _slice(kept: int, n: int) -> dict:
    return {"kept": kept, "n": n, "rate": round(kept / n, 4) if n else 0.0,
            "ci95": list(wilson(kept, n))}


def report(rows: list[dict], cases) -> dict:
    """candidate -> reviewed pooled metrics, expect_empty per origin and overall."""
    from harness.holdout import base_id
    by_id = {c.id: c for c in cases}
    out: dict = {}
    for r in rows:
        mine = out.setdefault(r["candidate"], {"reviewed": [], "empty": {}, "unknown_cases": 0})
        case = by_id.get(base_id(r["case_id"]))
        if case is None:
            mine["unknown_cases"] += 1
        elif case.assertions.get("expect_empty"):
            origin = str(case.assertions.get("origin") or "unspecified")
            for key in (origin, "all"):
                got = mine["empty"].setdefault(key, [0, 0])
                got[0] += int(bool(r["passed"]))
                got[1] += 1
        else:
            mine["reviewed"].append(r)
    for mine in out.values():
        reviewed = mine["reviewed"]
        total = lambda name: sum(int((x.get("metrics") or {}).get(name) or 0) for x in reviewed)
        good, matched, wanted = (total("claims_good_found"), total("claims_reviewed_matched"),
                                 total("claims_good_total"))
        mine["reviewed"] = {"cases": len(reviewed), "passed": sum(1 for x in reviewed if x["passed"]),
                            "recall": round(good / wanted, 4) if wanted else 0.0,
                            "precision": round(good / matched, 4) if matched else 0.0,
                            "bad_matched": total("claims_bad_matched"),
                            "schema_invalid": sum(1 for x in reviewed
                                                  if not (x.get("metrics") or {}).get("claims_schema_valid"))}
        mine["empty"] = {k: _slice(*v) for k, v in sorted(mine["empty"].items())}
    return out


def render(got: dict) -> str:
    lines = []
    for cand, mine in sorted(got.items()):
        rv = mine["reviewed"]
        lines.append(f"{cand}")
        lines.append(f"  reviewed  {rv['passed']}/{rv['cases']} pass  recall {rv['recall']:.3f}  "
                     f"precision {rv['precision']:.3f}  bad matched {rv['bad_matched']}  "
                     f"schema invalid {rv['schema_invalid']}")
        for origin, s in mine["empty"].items():
            lo, hi = s["ci95"]
            lines.append(f"  empty {origin:<14} {s['kept']}/{s['n']}  {s['rate']:.3f}  "
                         f"95% [{lo:.3f}, {hi:.3f}]")
        if mine["unknown_cases"]:
            lines.append(f"  {mine['unknown_cases']} rows name a case this machine does not hold")
    return "\n".join(lines)


def _rows(a) -> list[dict]:
    if a.results:
        return json.loads(Path(a.results).read_text(encoding="utf-8"))["rows"]
    from harness import runs
    with runs.store(None) as conn:
        run = runs.get(conn, a.run) if a.run else runs.newest(conn, lane="claims")
        if not run:
            raise SystemExit("no claims run in the store")
        return runs.rows(conn, run["id"])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="evals.claims_report")
    ap.add_argument("results", nargs="?", default=None, help="a run's results.json")
    ap.add_argument("--run", type=int, default=None, help="a stored run id")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    from evals import private
    got = report(_rows(a), private.local_cases())
    print(json.dumps(got, indent=1, sort_keys=True) if a.json else render(got))
    return 0


if __name__ == "__main__":
    sys.exit(main())
