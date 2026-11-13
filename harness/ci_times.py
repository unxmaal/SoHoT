"""CI, merge and deploy latency per merged PR and per CI job against its timeout, from gh. #1685."""
from __future__ import annotations

import json
import statistics
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

import yaml

from harness import ci_budget, ci_history

REPO = ci_history.REPO
WORKFLOW = ci_history.WORKFLOW
JOB = ci_history.JOB
DEPLOYED = "deployed"
#: gh calls in flight at once; one PR or run each.
FETCHERS = 8
PR_FIELDS = "number,title,createdAt,mergedAt,mergeCommit,headRefName,statusCheckRollup"


def _ts(s: str | None) -> float | None:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp() if s else None


def _min(a: float | None, b: float | None) -> float | None:
    return round((b - a) / 60, 1) if a is not None and b is not None and b >= a else None


def base(name: str) -> str:
    """A matrix leg's job: `mutation (harness/adopt.py)` is `mutation`."""
    return name.split(" (", 1)[0]


def _ran(c: dict) -> bool:
    return (c.get("conclusion") or "").lower() not in ("skipped", "neutral", "") and _min(
        _ts(c.get("startedAt")), _ts(c.get("completedAt"))) is not None


def final_checks(rollup: list[dict]) -> list[dict]:
    """The newest check run of each name that ran, from a PR's statusCheckRollup."""
    newest: dict[str, dict] = {}
    for c in rollup or []:
        if c.get("__typename", "CheckRun") != "CheckRun" or not _ran(c):
            continue
        if c["name"] not in newest or _ts(c["startedAt"]) > _ts(newest[c["name"]]["startedAt"]):
            newest[c["name"]] = c
    return list(newest.values())


def rounds(runs: list[dict], opened: float, merged: float) -> tuple[int, int]:
    """(CI rounds, rounds that did not pass) of ci.yml on the PR's branch while it was open; a rerun is a round."""
    total = bad = 0
    for r in runs:
        t = _ts(r.get("created_at"))
        if not (r.get("path") or "").endswith("/" + WORKFLOW) or t is None or not opened - 60 <= t <= merged:
            continue
        n = int(r.get("run_attempt") or 1)
        total += n
        bad += n - 1 + (r.get("conclusion") != "success")
    return total, bad


def main_order(shas: list[str]) -> dict[str, int]:
    """sha -> position on main, newest 0, from repos/<r>/commits?sha=main (main is squash-merged, so linear)."""
    return {s: i for i, s in enumerate(shas)}


def deploys(home: Path) -> list[dict]:
    """This home's deploy records that served their commit, oldest finish first, read without the store."""
    out = []
    for f in sorted((home / "deploys").glob("*.json")):
        try:
            rec = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if rec.get("outcome") == DEPLOYED and rec.get("sha") and rec.get("finished_at"):
            out.append({"id": rec.get("id"), "sha": rec["sha"], "at": float(rec["finished_at"])})
    return sorted(out, key=lambda d: d["at"])


def shipped(sha: str, merged: float, order: dict[str, int], recs: list[dict]) -> dict | None:
    """The first deploy whose commit has `sha` in it: on main at or after it, finished after the merge."""
    pos = order.get(sha)
    if pos is None:
        return None
    for d in recs:
        at = order.get(d["sha"])
        if at is not None and at <= pos and d["at"] >= merged:
            return d
    return None


def pr_row(pr: dict, runs: list[dict], main_checks: list[dict], order: dict[str, int], recs: list[dict]) -> dict:
    opened, merged = _ts(pr["createdAt"]), _ts(pr["mergedAt"])
    sha = (pr.get("mergeCommit") or {}).get("oid", "")
    final = final_checks(pr.get("statusCheckRollup"))
    macos = next((c for c in final if c["name"] == JOB), None)
    starts = [_ts(c["startedAt"]) for c in final]
    ends = [_ts(c["completedAt"]) for c in final]
    total, bad = rounds(runs, opened, merged)
    own = [c for c in main_checks if c.get("name") == JOB and c.get("started_at")]
    own = max(own, key=lambda c: _ts(c["started_at"])) if own else None
    dep = shipped(sha, merged, order, recs)
    return {"pr": pr["number"], "title": pr.get("title", ""), "sha": sha[:8],
            "open_to_merge_min": _min(opened, merged),
            "macos_min": _min(_ts(macos["startedAt"]), _ts(macos["completedAt"])) if macos else None,
            "macos": (macos["conclusion"].lower() if macos else None),
            "ci_wall_min": _min(min(starts), max(ends)) if final else None,
            "rounds": total, "rounds_failed": bad,
            "main_ci_min": _min(merged, _ts(own["completed_at"])) if own else None,
            "main_macos_min": _min(_ts(own["started_at"]), _ts(own["completed_at"])) if own else None,
            "main_macos": own["conclusion"] if own else None,
            "deploy": dep["id"] if dep else None, "merge_to_deploy_min": _min(merged, dep["at"]) if dep else None}


def job_rows(runs: list[dict], jobs_of: dict) -> list[dict]:
    """One row per job attempt that ran, from each run's jobs listing."""
    out = []
    for run in runs:
        for j in jobs_of.get(run["databaseId"]) or []:
            if j.get("status") != "completed" or j.get("conclusion") == "skipped":
                continue
            m = _min(_ts(j.get("started_at")), _ts(j.get("completed_at")))
            if m is None:
                continue
            out.append({"job": base(j.get("name", "")), "event": run.get("event", ""), "run": run["databaseId"],
                        "conclusion": j.get("conclusion"), "min": m})
    return out


def pctl(xs: list[float], q: float) -> float | None:
    return round(ci_history.pctl(xs, q), 1) if xs else None


def limits(workflow: Path | None = None) -> dict[str, float]:
    """Each job's timeout-minutes in this checkout's ci.yml."""
    workflow = workflow or ci_budget.WORKFLOW
    doc = yaml.safe_load(workflow.read_text(encoding="utf-8")) or {}
    return {job: ci_budget.limit_minutes(job, workflow) for job in doc.get("jobs") or {}}


def job_table(rows: list[dict], caps: dict[str, float] | None = None) -> list[dict]:
    """Per (job, event): attempts, outcomes, minutes p50/p95/max, its timeout (None: not in ci.yml) and p95's share."""
    caps = limits() if caps is None else caps
    groups: dict[tuple, list[dict]] = {}
    for r in rows:
        groups.setdefault((r["job"], r["event"]), []).append(r)
    out = []
    for (job, event), rs in sorted(groups.items()):
        mins = [r["min"] for r in rs]
        cap = caps.get(job)
        p95 = pctl(mins, 0.95)
        out.append({"job": job, "event": event, "runs": len(rs),
                    "passed": sum(r["conclusion"] == "success" for r in rs),
                    "failed": sum(r["conclusion"] == "failure" for r in rs),
                    "cancelled": sum(r["conclusion"] == "cancelled" for r in rs),
                    "p50": round(statistics.median(mins), 1), "p95": p95, "max": max(mins), "timeout": cap,
                    "p95_share": round(p95 / cap, 2) if cap and p95 is not None else None})
    return out


def summary(rows: list[dict]) -> dict:
    """p50/p95 of each latency column over the PRs that have it."""
    out = {}
    for k in ("open_to_merge_min", "macos_min", "ci_wall_min", "main_ci_min", "merge_to_deploy_min"):
        xs = [r[k] for r in rows if r[k] is not None]
        out[k] = {"n": len(xs), "p50": round(statistics.median(xs), 1) if xs else None, "p95": pctl(xs, 0.95)}
    return out


def _json(gh, argv: list[str]):
    return json.loads(gh(argv) or "null")


def main_commits(gh, since: str) -> list[str]:
    """main's commit shas from an hour before `since` to now, newest first."""
    start = datetime.fromisoformat(since.replace("Z", "+00:00")) - timedelta(hours=1)
    q = f"repos/{REPO}/commits?sha=main&per_page=100&since={start.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}"
    return [s for s in gh(["api", "--paginate", q, "--jq", ".[].sha"]).split() if s]


def collect(last: int, runs_n: int, home: Path, gh=None) -> dict:
    """Everything `soh ci-times` shows, read through gh and this home's deploy records."""
    gh = gh or ci_history._gh
    prs = _json(gh, ["pr", "list", "-R", REPO, "--state", "merged", "-L", str(last), "--json", PR_FIELDS]) or []
    prs = sorted((p for p in prs if p.get("mergedAt")), key=lambda p: p["mergedAt"], reverse=True)
    runs = _json(gh, ["run", "list", "-R", REPO, "--workflow", WORKFLOW, "-L", str(runs_n), "--status", "completed",
                      "--json", "databaseId,event,conclusion,createdAt"]) or []

    def branch_runs(p: dict) -> list[dict]:
        q = f"repos/{REPO}/actions/runs?branch={quote(p['headRefName'], safe='')}&event=pull_request&per_page=100"
        return (_json(gh, ["api", q]) or {}).get("workflow_runs") or []

    def own(p: dict) -> list[dict]:
        sha = (p.get("mergeCommit") or {}).get("oid")
        if not sha:
            return []
        return (_json(gh, ["api", f"repos/{REPO}/commits/{sha}/check-runs?per_page=100"]) or {}).get("check_runs") or []

    def jobs(r: dict) -> list[dict]:
        q = f"repos/{REPO}/actions/runs/{r['databaseId']}/jobs?filter=all&per_page=100"
        return (_json(gh, ["api", q]) or {}).get("jobs") or []

    with ThreadPoolExecutor(FETCHERS) as pool:
        b, o, j = list(pool.map(branch_runs, prs)), list(pool.map(own, prs)), list(pool.map(jobs, runs))
    order = main_order(main_commits(gh, prs[-1]["mergedAt"])) if prs else {}
    recs = deploys(home)
    rows = [pr_row(p, bs, cs, order, recs) for p, bs, cs in zip(prs, b, o)]
    jrows = job_rows(runs, {r["databaseId"]: js for r, js in zip(runs, j)})
    return {"prs": rows, "summary": summary(rows), "jobs": job_table(jrows), "runs_read": len(runs)}


def _cell(v) -> str:
    return "-" if v is None else str(v)


def render(got: dict) -> str:
    lines = [f"merged PRs, newest first (minutes; check-macos and CI wall on the PR's final run; main CI is merge to "
             f"main's own {JOB} done; deploy is merge to the first deploy serving it)", "",
             "| PR | open->merge | check-macos | CI wall | rounds (failed) | main CI | deploy | merge->deploy | title |",
             "|---|---|---|---|---|---|---|---|---|"]
    for r in got["prs"]:
        lines.append(f"| #{r['pr']} | {_cell(r['open_to_merge_min'])} | {_cell(r['macos_min'])} | "
                     f"{_cell(r['ci_wall_min'])} | {r['rounds']} ({r['rounds_failed']}) | {_cell(r['main_ci_min'])} | "
                     f"{_cell(r['deploy'])} | {_cell(r['merge_to_deploy_min'])} | {r['title'][:50]} |")
    lines += ["", "| over PRs | n | p50 | p95 |", "|---|---|---|---|"]
    for k, s in got["summary"].items():
        lines.append(f"| {k.removesuffix('_min')} | {s['n']} | {_cell(s['p50'])} | {_cell(s['p95'])} |")
    lines += ["", f"{WORKFLOW} jobs over the newest {got['runs_read']} completed runs (minutes per attempt that ran)", "",
              "| job | event | runs | passed | failed | cancelled | p50 | p95 | max | timeout | p95/timeout |",
              "|---|---|---|---|---|---|---|---|---|---|---|"]
    for t in got["jobs"]:
        share = f"{t['p95_share']:.0%}" if t["p95_share"] is not None else "-"
        lines.append(f"| {t['job']} | {t['event']} | {t['runs']} | {t['passed']} | {t['failed']} | {t['cancelled']} | "
                     f"{t['p50']} | {_cell(t['p95'])} | {t['max']} | {_cell(t['timeout'])} | {share} |")
    return "\n".join(lines)
