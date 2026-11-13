"""A CI job's wall time over recent runs, by path and runner class, and the slowest tests in their logs. #1520, #1588."""
from __future__ import annotations

import argparse
import json
import re
import statistics
import subprocess
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

REPO = "unxmaal/SoHoT"
WORKFLOW = "ci.yml"
JOB = "check-macos"
#: The step timed is the job's first `make ...` step: make check, make test-postgres-suite, make mutation.
STEP = "make "
_STAMP = r"^\S+Z "
_RUNNER = re.compile(r"Apple (M\d[\w ]*?) \(Virtual\)\s*\n" + _STAMP + r"(\d+)", re.M)
_REAL = re.compile(_STAMP + r"real (\d+(?:\.\d+)?)\s*$", re.M)
_PCT = re.compile(r"\[\s*(\d{1,3})%\]")
_FAST = re.compile(r"^\S+Z\s+SOHOT_FAST_PATH: 1\s*$", re.M)
_SCOPED = re.compile(_STAMP + r"selection: (\d+) of (\d+) test files", re.M)
_DUR = re.compile(_STAMP + r"(\d+\.\d+)s (?:call|setup|teardown) +(\S+::\S+)", re.M)
_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def _ts(s: str | None) -> float | None:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp() if s else None


def _gh(argv: list[str]) -> str:
    for attempt in (1, 2):
        got = subprocess.run(["gh", *argv], capture_output=True, text=True, timeout=300)
        if got.returncode == 0:
            return got.stdout
    raise RuntimeError(f"gh {' '.join(argv[:3])} failed: {(got.stderr or got.stdout).strip()[:300]}")


def _cached(f: Path, fetch) -> str | None:
    if not f.is_file():
        try:
            f.write_text(fetch(), encoding="utf-8")
        except RuntimeError as exc:
            print(exc, file=sys.stderr)
            return None
    return f.read_text(encoding="utf-8", errors="replace")


def from_log(log: str) -> dict:
    """runner class, `time -p` real seconds, last progress %, fast path, test files selected, per-test seconds, from a log."""
    log = _ANSI.sub("", log)
    m = _RUNNER.search(log)
    real = _REAL.findall(log)
    pct = _PCT.findall(log)
    scoped = _SCOPED.search(log)
    tests: dict[str, float] = defaultdict(float)
    for sec, test in _DUR.findall(log):
        tests[test] += float(sec)
    return {"runner": f"{m.group(1).strip()} {m.group(2)}cpu" if m else "unknown",
            "real_s": float(real[-1]) if real else None, "pct": int(pct[-1]) if pct else None,
            "fast": bool(_FAST.search(log)), "selected": int(scoped.group(1)) if scoped else None,
            "tests": dict(tests)}


def named(job_name: str, name: str) -> bool:
    """A job is its name, or one matrix leg of it: `mutation` is `mutation (harness/adopt.py)` too."""
    return job_name == name or job_name.startswith(name + " (")


def from_job(job: dict, run: dict, name: str = JOB) -> dict | None:
    """One row for a completed attempt of the job, or None when it never ran its make step."""
    if not named(job.get("name", ""), name) or job.get("status") != "completed" or job.get("conclusion") == "skipped":
        return None
    if "steps" in job and not job["steps"]:
        return None
    step = next((s for s in job.get("steps") or [] if (s.get("name") or "").startswith(STEP)), None)
    start, end = _ts(job.get("started_at")), _ts(job.get("completed_at"))
    s0, s1 = (_ts(step.get("started_at")), _ts(step.get("completed_at"))) if step else (None, None)
    return {"run": run["databaseId"], "attempt": job.get("run_attempt", 1), "job": job["id"], "name": job["name"],
            "event": run.get("event", ""), "sha": run.get("headSha", "")[:8], "conclusion": job.get("conclusion"),
            "job_min": round((end - start) / 60, 2) if start and end else None,
            "check_min": round((s1 - s0) / 60, 2) if s0 and s1 else None}


def outcome(row: dict, limit_min: float) -> str:
    """passed, failed, timeout (cancelled at the limit in force for that run), or superseded (cancelled earlier)."""
    c = row.get("conclusion")
    if c == "success":
        return "passed"
    if c == "cancelled":
        return "timeout" if (row.get("job_min") or 0) >= (row.get("limit_min") or limit_min) else "superseded"
    return "failed"


def limit_at(text: str | None, name: str) -> float | None:
    """The job's timeout-minutes in a ci.yml text, the one a run ran under; None when it cannot be read."""
    import yaml
    try:
        jobs = (yaml.safe_load(text or "") or {}).get("jobs") or {}
        return float(jobs[name].get("timeout-minutes", 360))
    except (yaml.YAMLError, AttributeError, KeyError, TypeError, ValueError):
        return None


def path(row: dict) -> str:
    if row.get("fast"):
        return "scoped (PR)" if row.get("selected") else "fast (PR)"
    return "full (main)"


def pctl(xs: list[float], q: float) -> float:
    xs = sorted(xs)
    if len(xs) == 1:
        return xs[0]
    return statistics.quantiles(xs, n=100, method="inclusive")[round(q * 100) - 1]


def projected(row: dict) -> float | None:
    """The job minutes a run cut at its limit would have taken, from the last progress % its log reached."""
    if not row.get("pct") or not row.get("check_min") or not row.get("job_min"):
        return None
    return round(row["job_min"] + row["check_min"] * (100 / row["pct"] - 1), 1)


def table(rows: list[dict], limit_min: float) -> list[dict]:
    """Per (path, runner): runs, outcomes, make step minutes p50/p95/max over runs that ended, and timeouts projected."""
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        groups[(path(r), r.get("runner", "unknown"))].append(r)
    out = []
    for (p, runner), rs in sorted(groups.items()):
        kinds = defaultdict(int)
        for r in rs:
            kinds[outcome(r, limit_min)] += 1
        ended = [r for r in rs if outcome(r, limit_min) in ("passed", "failed")]
        mins = [r["check_min"] for r in ended if r.get("check_min")]
        jobs = [r["job_min"] for r in ended if r.get("job_min")]
        cut = [x for r in rs if outcome(r, limit_min) == "timeout" and (x := projected(r)) is not None]
        whole = jobs + [projected(r) or r["job_min"] for r in rs if outcome(r, limit_min) == "timeout" and r.get("job_min")]
        out.append({"path": p, "runner": runner, "runs": len(rs), **{k: kinds.get(k, 0) for k in
                    ("passed", "failed", "timeout", "superseded")},
                    "p50": round(statistics.median(mins), 1) if mins else None,
                    "p95": round(pctl(mins, 0.95), 1) if mins else None, "max": round(max(mins), 1) if mins else None,
                    "job_p95": round(pctl(jobs, 0.95), 1) if jobs else None,
                    "job_max": round(max(jobs), 1) if jobs else None,
                    "job_p95_cut": round(pctl(whole, 0.95), 1) if whole else None,
                    "cut_projected_max": max(cut) if cut else None})
    return out


def slowest(rows: list[dict], top: int = 30, fast: bool = False) -> list[tuple[str, float, float, int]]:
    """(test, median s, max s, runs seen) over the full runs' logs, or the PR fast path's with fast."""
    seen: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        if bool(r.get("fast")) != fast:
            continue
        for t, s in (r.get("tests") or {}).items():
            seen[t].append(s)
    ranked = sorted(((t, statistics.median(v), max(v), len(v)) for t, v in seen.items()), key=lambda x: -x[1])
    return [(t, round(m, 1), round(x, 1), n) for t, m, x, n in ranked[:top]]


def rule_line(job: str, row: dict, limit_min: float) -> str:
    """What the job's timeout rule asks of one table row's p95, and whether ci.yml's limit is below it. #1590."""
    from harness import ci_budget
    want = ci_budget.rule_minutes(job, row["job_p95_cut"]) if row.get("job_p95_cut") else None
    if want is None:
        return ""
    verdict = f"below its rule, raise it to {want}" if limit_min < want else "meets its rule"
    return (f"rule ({row['path']}, {row['runner']}): {ci_budget.HOST_FACTOR[job]:g} x job p95 {row['job_p95_cut']} = "
            f"{want} min; timeout-minutes {limit_min:g} {verdict}")


def render(tab: list[dict], slow: list, limit_min: float, fast: bool = False, name: str = JOB) -> str:
    lines = [f"{name} make step minutes (job limit {limit_min:g} min; p50/p95/max over runs that finished; "
             "a timeout's job minutes projected from its last progress %)", "",
             "| path | runner | runs | passed | failed | timeout | superseded | p50 | p95 | max | job p95 | job max "
             "| timeout projected | job p95 with timeouts projected |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for t in tab:
        lines.append("| " + " | ".join(str(t[k] if t[k] is not None else "-") for k in
                     ("path", "runner", "runs", "passed", "failed", "timeout", "superseded", "p50", "p95", "max", "job_p95",
                      "job_max", "cut_projected_max", "job_p95_cut")) + " |")
    rules = [line for t in tab if (line := rule_line(name, t, limit_min))]
    lines += ["", *rules] if rules else []
    if slow:
        lines += ["", f"slowest tests on {'PR fast-path' if fast else 'full'} runs (call+setup+teardown seconds, median):", "",
                  "| median s | max s | runs | test |", "|---|---|---|---|"]
        lines += [f"| {m} | {x} | {n} | `{t}` |" for t, m, x, n in slow]
    return "\n".join(lines)


def collect(limit: int, cache: Path, gh=None, branch: str = "", name: str = JOB, event: str = "") -> list[dict]:
    """Every attempt of the job in the newest `limit` runs, with its log parsed; logs cached under `cache`."""
    gh = gh or _gh
    cache.mkdir(parents=True, exist_ok=True)
    argv = ["run", "list", "-R", REPO, "--workflow", WORKFLOW, "-L", str(limit), "--status", "completed",
            "--json", "databaseId,event,headSha,conclusion"]
    rows = []
    filters = (["--branch", branch] if branch else []) + (["--event", event] if event else [])
    for run in json.loads(gh(argv + filters) or "[]"):
        jobs = _cached(cache / f"run-{run['databaseId']}.json", lambda: gh(
            ["api", f"repos/{REPO}/actions/runs/{run['databaseId']}/jobs?filter=all&per_page=100"]))
        listed = (json.loads(jobs).get("jobs") or []) if jobs else []
        for job in listed:
            row = from_job(job, run, name)
            if row is None:
                continue
            sha = run.get("headSha", "")
            url = f"repos/{REPO}/contents/.github/workflows/{WORKFLOW}?ref={sha}"
            row["limit_min"] = limit_at(_cached(cache / f"ci-{sha}.yml", lambda: gh(
                ["api", "-H", "Accept: application/vnd.github.raw", url])), name) if sha else None
            log = _cached(cache / f"{job['id']}.log", lambda: gh(
                ["api", "--allow-escape-sequences", f"repos/{REPO}/actions/jobs/{job['id']}/logs"]))
            if log is not None:
                row.update(from_log(log))
            rows.append(row)
    return rows


def main(argv=None) -> int:
    from harness import ci_budget
    ap = argparse.ArgumentParser(prog="python -m harness.ci_history", description=__doc__)
    ap.add_argument("--limit", type=int, default=30, help="newest completed workflow runs to read")
    ap.add_argument("--branch", default="", help="only runs on this branch")
    ap.add_argument("--job", default=JOB, help="check-linux, check-windows, check-postgres, mutation (every leg) ...")
    ap.add_argument("--event", default="", help="only runs of this event: schedule, push, pull_request")
    ap.add_argument("--cache", type=Path, required=True, help="directory for downloaded job logs")
    ap.add_argument("--top", type=int, default=30)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--fast", action="store_true", help="rank the slowest tests over PR fast-path runs")
    a = ap.parse_args(argv)
    limit_min = ci_budget.limit_minutes(a.job)
    rows = collect(a.limit, a.cache, branch=a.branch, name=a.job, event=a.event)
    tab, slow = table(rows, limit_min), slowest(rows, a.top, a.fast)
    if a.json:
        print(json.dumps({"rows": [{k: v for k, v in r.items() if k != "tests"} for r in rows],
                          "table": tab, "slowest": slow}, indent=1))
    else:
        print(render(tab, slow, limit_min, a.fast, a.job))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
