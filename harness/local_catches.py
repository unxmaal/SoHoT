"""Local `make check` runs, one JSONL line each, so a test or scanner that caught a defect before the push has a record. #1261."""
from __future__ import annotations

import json
import re
import subprocess
import time
from pathlib import Path

from harness import paths

#: Set by `make test`; tests/conftest.py records a run only when it is 1 and CI is unset.
ENV = "SOHOT_CATCHES"
#: In the home root, not logs/, which paths.logs() calls deletable at any time.
FILE = "local-catches.jsonl"
#: How long `git rev-parse HEAD` may take; a timeout records the run with no commit.
GIT_TIMEOUT_S = 10.0
_KEY = re.compile(r"[\w][\w/.-]*\.py::[\w.]+")


def path() -> Path:
    return paths.home() / FILE


def head(root: Path | None = None) -> str:
    try:
        got = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=GIT_TIMEOUT_S,
                             cwd=root or paths.REPO)
    except (OSError, subprocess.SubprocessError):
        return ""
    sha = got.stdout.strip()
    return sha if re.fullmatch(r"[0-9a-f]{40}", sha) else ""


def keys(nodeids) -> tuple[list[str], int]:
    """Repo-relative test functions, parameters dropped; anything else (an absolute or parent path) only counted."""
    from harness.inventory_weight import node_key
    kept, other = set(), 0
    for node in nodeids:
        k = node_key(node)
        if _KEY.fullmatch(k) and ".." not in k.split("::", 1)[0].split("/"):
            kept.add(k)
        else:
            other += 1
    return sorted(kept), other


def record(target: Path, sha: str, tests: int, exit: int, failed) -> None:
    kept, other = keys(failed)
    line = json.dumps({"at": round(time.time(), 3), "head": sha, "tests": tests, "exit": exit,
                       "failed": kept, "other": other})
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def read(target: Path, since: float) -> dict:
    """Runs since `since`, and each failed one shaped like a CI failure; a line that does not parse is counted."""
    try:
        text = Path(target).read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        text = ""
    runs, failures, bad = 0, [], 0
    for raw in text.splitlines():
        try:
            row = json.loads(raw)
            at = float(row["at"])
        except (ValueError, KeyError, TypeError):
            bad += 1
            continue
        if at < since:
            continue
        runs += 1
        if row.get("failed"):
            stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(at))
            failures.append({"id": f"local {str(row.get('head', ''))[:12]}", "local": True, "at": stamp,
                             "failed": list(row["failed"])})
    return {"runs": runs, "failures": failures, "unreadable": bad}
