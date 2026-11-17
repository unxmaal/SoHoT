"""Split check-postgres's test files across runners by recorded seconds when there are many (#2060).

python -m tests.gauntlet.shard [--listing FILE] [--junit FILE] [--tests "T ..."] [--github-output FILE]
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from statistics import median

from tests.gauntlet import scope

#: Test files one check-postgres runner takes before the selection is split: 594-787 ran 36-44 min on one (#2060).
FILES_PER_SHARD = 270
#: Most check-postgres runners one run takes; macOS standard runners are shared with check-macos and mutation (#2060).
MAX_SHARDS = 3


def count(files) -> int:
    return max(1, min(MAX_SHARDS, math.ceil(len(files) / FILES_PER_SHARD)))


def weights(files, secs) -> dict[str, float]:
    """Each file's recorded seconds; one never recorded weighs the median of those that were."""
    known = [secs[f] for f in files if f in secs] or list(secs.values())
    guess = median(known) if known else 1.0
    return {f: secs.get(f, guess) for f in files}


def split(files, n, secs) -> list[list[str]]:
    """The longest file first onto the lightest shard, ties to the lower shard: the same split for the same input."""
    w = weights(sorted(set(files)), secs)
    load = [0.0] * n
    parts: list[list[str]] = [[] for _ in range(n)]
    for f in sorted(w, key=lambda f: (-w[f], f)):
        i = min(range(n), key=lambda i: (load[i], i))
        parts[i].append(f)
        load[i] += w[f]
    return [sorted(p) for p in parts]


def plan(listing, junit, tracked=None, tests="") -> dict[str, str]:
    """Matrix leg ("1".."n") to the test files it runs; no listing means the whole suite, named tests one leg."""
    if tests.strip():
        return {"1": ""}
    if listing is not None and Path(listing).is_file():
        files = [line.strip() for line in Path(listing).read_text(encoding="utf-8").splitlines() if line.strip()]
    else:
        files = [p for p in (scope.tracked() if tracked is None else tracked) if scope.is_test(p)]
    secs = scope.suite_seconds(junit) if junit is not None and Path(junit).is_file() else {}
    parts = split(files, count(files), secs)
    return {str(i + 1): "".join(f + "\n" for f in p) for i, p in enumerate(parts)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tests.gauntlet.shard", description=__doc__)
    ap.add_argument("--listing", type=Path, help="the test files scope selected; absent, the whole suite")
    ap.add_argument("--junit", type=Path, help="weigh each file by its seconds in this JUnit XML")
    ap.add_argument("--tests", default="", help="a dispatch's named tests, which run on one leg")
    ap.add_argument("--github-output", type=Path, help="append the legs (shards) and their files (plan) here")
    a = ap.parse_args(argv)
    out = plan(a.listing, a.junit, tests=a.tests)
    for leg, files in out.items():
        print(f"shard {leg}: {len(files.split())} test files")
    if a.github_output:
        with a.github_output.open("a", encoding="utf-8") as f:
            f.write(f"shards={json.dumps([int(k) for k in out])}\nplan<<EOF\n{json.dumps(out)}\nEOF\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
