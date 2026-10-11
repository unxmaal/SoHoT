"""Where a pytest run's time goes, read from its JUnit XML: top tests, top files, the slowest 1%'s share. #720."""
from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path


def times(path) -> dict[str, float]:
    """test id -> seconds, setup and teardown included, as JUnit records them."""
    out: dict[str, float] = {}
    for case in ET.parse(path).getroot().iter("testcase"):
        cls = case.get("classname", "")
        name = case.get("name", "")
        module = cls.replace(".", "/") + ".py" if cls else ""
        out[f"{module}::{name}"] = out.get(f"{module}::{name}", 0.0) + float(case.get("time") or 0)
    return out


def summary(got: dict[str, float], top: int = 15) -> dict:
    ranked = sorted(got.items(), key=lambda kv: kv[1], reverse=True)
    total = sum(got.values())
    n_slow = max(1, len(ranked) // 100) if ranked else 0
    slow = sum(s for _, s in ranked[:n_slow])
    files: dict[str, float] = defaultdict(float)
    for test, s in got.items():
        files[test.split("::", 1)[0]] += s
    return {"tests": len(got), "total_s": round(total, 2),
            "slowest_1pct": {"tests": n_slow, "seconds": round(slow, 2),
                             "share": round(slow / total, 3) if total else 0.0},
            "top_tests": [(t, round(s, 2)) for t, s in ranked[:top]],
            "top_files": [(f, round(s, 2)) for f, s in
                          sorted(files.items(), key=lambda kv: kv[1], reverse=True)[:top]]}


def render(s: dict) -> str:
    one = s["slowest_1pct"]
    lines = [f"{s['tests']} tests, {s['total_s']} s of test time (summed over workers)",
             f"slowest 1%: {one['tests']} tests, {one['seconds']} s, {one['share']:.1%} of the total",
             "", "top tests:"]
    lines += [f"  {sec:8.2f}s  {t}" for t, sec in s["top_tests"]]
    lines += ["", "top files:"]
    lines += [f"  {sec:8.2f}s  {f}" for f, sec in s["top_files"]]
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m harness.suite_time", description=__doc__)
    ap.add_argument("junit", type=Path)
    ap.add_argument("--top", type=int, default=15)
    a = ap.parse_args(argv)
    if not a.junit.is_file():
        print(f"no JUnit XML at {a.junit}", file=sys.stderr)
        return 1
    print(render(summary(times(a.junit), a.top)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
