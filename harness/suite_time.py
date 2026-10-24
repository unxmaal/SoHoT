"""Where a pytest run's time goes, read from its JUnit XML: top tests, top files, the slowest 1%'s share. #720."""
from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

#: How many times its time on the earlier run a test must take to be named slower. #1146.
SLOWER_RATIO = 5.0
#: How many seconds more than on the earlier run a test must take to be named slower. #1146.
SLOWER_ADDED_S = 30.0


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


def log_times(path) -> tuple[dict[str, float], dict[str, float], float]:
    """(finished test -> seconds, test still running -> epoch it started, last epoch) from the suite's test log."""
    done: dict[str, float] = {}
    running: dict[str, float] = {}
    last = 0.0
    for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        parts = line.split("\t", 3)
        if len(parts) != 4:
            continue
        try:
            at = float(parts[0])
            spent = float(parts[2]) if parts[1] == "end" else 0.0
        except ValueError:
            continue
        last = max(last, at)
        if parts[1] == "start":
            running[parts[3]] = at
        elif parts[1] == "end":
            running.pop(parts[3], None)
            done[parts[3]] = done.get(parts[3], 0.0) + spent
    return done, running, last


def slower(now: dict[str, float], before: dict[str, float], ratio: float = SLOWER_RATIO,
           added_s: float = SLOWER_ADDED_S) -> list[tuple[str, float, float]]:
    """(test, seconds before, seconds now) for each test that ran in both and got `ratio` times and `added_s` slower."""
    out = [(t, before[t], s) for t, s in now.items()
           if t in before and s >= ratio * before[t] and s - before[t] >= added_s]
    return sorted(out, key=lambda r: r[2] - r[1], reverse=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m harness.suite_time", description=__doc__)
    ap.add_argument("junit", type=Path)
    ap.add_argument("--top", type=int, default=15)
    ap.add_argument("--log", type=Path, help="the test log conftest writes under SOHOT_TEST_LOG; read when the run "
                                             "left no JUnit XML, and for the tests still running when it ended")
    ap.add_argument("--against", type=Path, help="an earlier run's JUnit XML; name the tests that got much slower")
    a = ap.parse_args(argv)
    logged = log_times(a.log) if a.log and a.log.is_file() else None
    if a.junit.is_file():
        got = times(a.junit)
    elif logged is not None:
        print(f"no JUnit XML at {a.junit}: the run did not finish; times from {a.log}")
        got = logged[0]
    else:
        print(f"no JUnit XML at {a.junit}", file=sys.stderr)
        return 1
    print(render(summary(got, a.top)))
    if logged is not None and logged[1]:
        print(f"\nstill running when the log ends: {len(logged[1])}")
        for test, start in sorted(logged[1].items(), key=lambda kv: kv[1]):
            print(f"  {logged[2] - start:8.1f}s  {test}")
    if a.against:
        if not a.against.is_file():
            print(f"\nno earlier run to compare at {a.against}")
            return 0
        rows = slower(got, times(a.against))
        print(f"\n{len(rows)} test(s) {SLOWER_RATIO:g}x and {SLOWER_ADDED_S:g} s slower than {a.against}")
        for test, before, now in rows:
            print(f"::warning title=Slower test::{test}: {before:.1f} s before, {now:.1f} s now (#1146)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
