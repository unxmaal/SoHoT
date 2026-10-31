"""`soh inventory time`: the machine's hours by category, the hours Eric was blocked, local work done, effort by area. #1152."""
from __future__ import annotations

import datetime as _dt
import json
import re
import subprocess
from pathlib import Path

from harness import delegations

WORK, MEASUREMENT, DISCOVERY, INFOVORE, OPS, OTHER = (
    "work", "measurement", "discovery", "infovore", "ops", "other")
LOADED_IDLE, IDLE, IDLE_UNRECORDED = "idle-but-loaded", "idle", "idle-unrecorded"
#: Busy categories in precedence order: a second two of them claim goes to the earlier.
BUSY = (WORK, MEASUREMENT, INFOVORE, OPS, DISCOVERY, OTHER)
CATEGORIES = BUSY + (LOADED_IDLE, IDLE, IDLE_UNRECORDED)
#: Hour categories in which the GPU or RAM is held by something other than Eric's work.
TAKEN = (MEASUREMENT, DISCOVERY, INFOVORE, OPS, OTHER, LOADED_IDLE)

HOUR = 3600
#: A power sample whose GPU active ratio is at or above this reads the GPU busy.
GPU_BUSY_RATIO = 0.5
#: Before macmon reported an active ratio (#1005), GPU watts at or above this read busy.
GPU_BUSY_WATTS = 10.0
#: A sweep start line with no later sign of life is charged this many seconds.
SWEEP_FLOOR_SECONDS = 600.0
#: How long after the morning unit's start line a delegation counts as the morning brief's.
MORNING_SPAN_SECONDS = 300.0
#: The recent window of the effort account.
RECENT_DAYS = 14

INFOVORE_CLIENT = "Python-urllib"
PENDING = "pending"
OUTCOMES = (*delegations.OUTCOMES, *delegations.INFERRED, PENDING)

_SWEEP = re.compile(r"^=== sweep (\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ) ")
_SWEEP_KILLED = re.compile(r"^=== sweep killed by SIG\w+ (\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ) ")
_MORNING = re.compile(r"^=== morning (\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ) ")
_RICH_AT = re.compile(r"^\[(\d\d/\d\d/\d\d \d\d:\d\d:\d\d)\]")
_RICH_SRC = re.compile(r"\s+\S+\.py:\d+\s*$")
REFUSAL = "this machine is busy with"


# --- classifying what a source says the machine did -----------------------------------------------

def request_category(purpose: str, client: str) -> str:
    if purpose == "work":
        return WORK
    if purpose == "eval":
        return MEASUREMENT
    if purpose == "discover":
        return DISCOVERY
    if purpose in ("smoke", "watchdog", "internal"):
        return OPS
    # Infovore sends no purpose tag; its client is urllib (FINDING #466).
    if (client or "").startswith(INFOVORE_CLIENT):
        return INFOVORE
    return OTHER


def job_category(kind: str, argv, requested_by: str = "") -> str:
    text = " ".join(argv) if isinstance(argv, (list, tuple)) else str(argv or "")
    if "infovore" in text:
        return INFOVORE
    if re.search(r"\b(soh|lh) discover\b", text):
        return DISCOVERY
    if "evals." in text or requested_by == "reverify":
        return MEASUREMENT
    if kind in ("image", "video"):
        return WORK
    if requested_by == "migration":
        return OPS
    return OTHER


def _iso(s: str) -> float:
    return _dt.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=_dt.timezone.utc).timestamp()


def log_marks(text: str, pattern: re.Pattern) -> list[float]:
    return sorted(_iso(m.group(1)) for line in text.splitlines() if (m := pattern.match(line)))


def sweeps(starts: list[float], killed: list[float], activity: list[tuple], span: float) -> list[tuple]:
    """(start, end) of each sweep: to its kill line, else its last sign of life before the next start, within `span`."""
    out = []
    for i, s in enumerate(starts):
        nxt = starts[i + 1] if i + 1 < len(starts) else float("inf")
        cap = min(nxt, s + span)
        ends = [k for k in killed if s < k <= cap]
        if ends:
            out.append((s, min(ends)))
            continue
        alive = [e for b, e, _ in activity if s <= b < cap]
        out.append((s, min(cap, max([_charged(s), *alive]))))
    return out


def _charged(start: float) -> float:
    return start + SWEEP_FLOOR_SECONDS


def refusals(text: str, tz=None) -> list[dict]:
    """Each local_complete/local_decide that mcp.log says failed, with whether it was refused for a held machine."""
    lines, out, at = text.splitlines(), [], None
    for i, line in enumerate(lines):
        if m := _RICH_AT.match(line):
            at = _dt.datetime.strptime(m.group(1), "%m/%d/%y %H:%M:%S").replace(tzinfo=tz).timestamp()
        if "Tool 'local_" not in line or "failed" not in line or at is None:
            continue
        tool = line.split("Tool '", 1)[1].split("'", 1)[0]
        parts = [_RICH_SRC.sub("", line.split("failed:", 1)[1])]
        for nxt in lines[i + 1:i + 12]:
            if _RICH_AT.match(nxt) or nxt.lstrip().startswith(("INFO", "WARNING", "ERROR")):
                break
            parts.append(_RICH_SRC.sub("", nxt))
        said = " ".join(" ".join(parts).split())
        out.append({"at": at, "tool": tool, "refused": REFUSAL in said, "text": said[:300]})
    return out


# --- the hour account --------------------------------------------------------------------------------

def _union(spans: list[tuple]) -> list[tuple]:
    out: list[list] = []
    for b, e in sorted(spans):
        if e <= b:
            continue
        if out and b <= out[-1][1]:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([b, e])
    return [tuple(x) for x in out]


def _minus(spans: list[tuple], taken: list[tuple]) -> float:
    total = sum(e - b for b, e in spans)
    for b, e in spans:
        for tb, te in taken:
            total -= max(0.0, min(e, te) - max(b, tb))
    return total


def _gpu_busy(sample: dict) -> bool:
    if isinstance(sample.get("gpu_active_ratio"), (int, float)):
        return sample["gpu_active_ratio"] >= GPU_BUSY_RATIO
    return float(sample.get("gpu_power") or 0.0) >= GPU_BUSY_WATTS


def _residency(probes: list[dict]) -> str:
    if any(p["outcome"] in ("up", "slow") for p in probes):
        return LOADED_IDLE
    if any("not resident" in (p.get("reason") or "") for p in probes):
        return IDLE
    return IDLE_UNRECORDED


def account(intervals: list[tuple], start: float, end: float, power=(), probes=()) -> list[dict]:
    """Each clock hour in [start, end): seconds per category and the category that held most of it."""
    first = int(start // HOUR) * HOUR
    keys = range(first, int(-(-end // HOUR)) * HOUR, HOUR)
    spans: dict = {h: {} for h in keys}
    for b, e, cat in intervals:
        b, e = max(b, start), min(e, end)
        h = int(b // HOUR) * HOUR
        while b < e:
            cut = min(e, h + HOUR)
            spans[h].setdefault(cat, []).append((b, cut))
            b, h = cut, h + HOUR
    samples: dict = {}
    for s in power:
        if start <= s["at"] < end:
            samples.setdefault(int(s["at"] // HOUR) * HOUR, []).append(s)
    seen: dict = {}
    for p in probes:
        if start <= p["at"] < end:
            seen.setdefault(int(p["at"] // HOUR) * HOUR, []).append(p)
    out = []
    for h in keys:
        width = min(h + HOUR, end) - max(h, start)
        secs, claimed = {}, []
        for cat in BUSY:
            mine = _union(spans[h].get(cat, []))
            if mine:
                secs[cat] = _minus(mine, claimed)
                claimed = _union(claimed + mine)
        got = samples.get(h, [])
        gpu = sum(_gpu_busy(s) for s in got) / len(got) if got else None
        if not any(secs.values()) and gpu:
            secs[OTHER] = gpu * width
        idle = max(0.0, width - sum(secs.values()))
        if idle:
            secs[_residency(seen.get(h, []))] = idle
        cat = max(secs, key=lambda c: (secs[c], -CATEGORIES.index(c)))
        out.append({"hour": h, "category": cat, "seconds": {c: round(v, 1) for c, v in secs.items() if v},
                    "gpu_busy": None if gpu is None else round(gpu, 3)})
    return out


def pareto(hours: list[dict]) -> list[dict]:
    """Categories by the hours they held, largest first, with the cumulative share."""
    n = len(hours) or 1
    held = {c: sum(1 for h in hours if h["category"] == c) for c in CATEGORIES}
    busy = {c: sum(h["seconds"].get(c, 0.0) for h in hours) / HOUR for c in CATEGORIES}
    gpu = {c: sum(h["gpu_busy"] or 0.0 for h in hours if h["category"] == c) for c in CATEGORIES}
    rows, run = [], 0
    for c in sorted(CATEGORIES, key=lambda c: (-held[c], -busy[c], CATEGORIES.index(c))):
        if not held[c] and not busy[c]:
            continue
        run += held[c]
        rows.append({"category": c, "hours": held[c], "share": held[c] / n, "cumulative": run / n,
                     "busy_hours": round(busy[c], 1), "gpu_busy_hours": round(gpu[c], 1)})
    return rows


# --- hours Eric was blocked ----------------------------------------------------------------------------

def _daytime(h: int, tz) -> bool:
    from harness import watchdog
    return watchdog.DAY_START_HOUR <= _dt.datetime.fromtimestamp(h, tz).hour < watchdog.DAY_END_HOUR


def blocked(hours: list[dict], actions=(), clearances=(), paused=(), refused=(), tz=None) -> dict:
    """Which hours something stood between Eric and the machine, by reason, and the daytime hours taken by non-work."""
    reasons: dict = {h["hour"]: set() for h in hours}

    def mark(at: float, why: str):
        h = int(at // HOUR) * HOUR
        if h in reasons:
            reasons[h].add(why)

    for a in actions:
        if a.get("dry_run"):
            continue
        if a["criterion"] in ("memory", "memory_warn"):
            mark(a["at"], "memory")
        if a["action"] in ("pause", "stop"):
            mark(a["at"], "watchdog")
        if a["criterion"] == "daytime_gpu":
            mark(a["at"], "day_limit")
    for p in paused:
        if "stop time" in (p.get("why") or ""):
            mark(p["paused_at"], "day_limit")
    for c in clearances:
        stop = min(x for x in (c["until"], c.get("revoked_at")) if x is not None)
        for h in reasons:
            if h < stop and h + HOUR > c["cleared_at"]:
                reasons[h].add("day_clearance")
    for r in refused:
        if r.get("refused"):
            mark(r["at"], "refused")
    for h in hours:
        if h["category"] == LOADED_IDLE:
            reasons[h["hour"]].add("idle_models")
    by_reason = {}
    for whys in reasons.values():
        for w in whys:
            by_reason[w] = by_reason.get(w, 0) + 1
    day = [h for h in hours if _daytime(h["hour"], tz)]
    taken = [h for h in day if h["category"] in TAKEN or reasons[h["hour"]] & {"memory", "watchdog"}]
    by_cat: dict = {}
    for h in taken:
        by_cat[h["category"]] = by_cat.get(h["category"], 0) + 1
    return {"by_reason": dict(sorted(by_reason.items(), key=lambda kv: -kv[1])),
            "any": sum(1 for w in reasons.values() if w),
            "daytime_hours": len(day), "daytime_any": sum(1 for h in day if reasons[h["hour"]]),
            "daytime_taken": len(taken), "daytime_taken_by": dict(sorted(by_cat.items(), key=lambda kv: -kv[1])),
            "refused": sum(1 for r in refused if r.get("refused")), "failed": len(list(refused))}


# --- local work done -----------------------------------------------------------------------------------

def percentile(values: list[float], q: float) -> float | None:
    """Nearest-rank percentile; None for no values."""
    vals = sorted(v for v in values if v is not None)
    if not vals:
        return None
    k = max(0, min(len(vals) - 1, int(-(-q * len(vals) // 1)) - 1))
    return vals[k]


def _lat(values) -> dict:
    vals = list(values)
    return {f"p{int(q * 100)}": percentile(vals, q) for q in (0.5, 0.9, 0.99)}


def local_work(requests: list[dict], delegations: list[dict], mornings=()) -> dict:
    """Work requests by client and lane, delegations by caller and lane, latency percentiles and outcome states."""
    groups: dict = {}
    for r in requests:
        if r["purpose"] != "work":
            continue
        groups.setdefault((r["client"], r["lane"]), []).append(r)
    req = [{"client": c, "lane": lane, "requests": len(rs),
            "prompt_tokens": sum(r["prompt_tokens"] or 0 for r in rs),
            "completion_tokens": sum(r["completion_tokens"] or 0 for r in rs),
            "seconds": _lat(r["total_s"] for r in rs), "ttft": _lat(r["ttft_s"] for r in rs)}
           for (c, lane), rs in sorted(groups.items(), key=lambda kv: -len(kv[1]))]
    by: dict = {}
    for d in delegations:
        morning = any(m <= d["at"] < m + MORNING_SPAN_SECONDS for m in mornings)
        caller = "morning unit" if morning else (d.get("client") or d["id_source"])
        by.setdefault((caller, d["lane"]), []).append(d)
    dels = [{"caller": c, "lane": lane, "delegations": len(ds),
             "outcomes": {o: sum(1 for d in ds if (d["outcome"] or PENDING) == o) for o in OUTCOMES},
             "seconds": _lat(d["seconds"] for d in ds)}
            for (c, lane), ds in sorted(by.items(), key=lambda kv: -len(kv[1]))]
    states = {o: sum(1 for d in delegations if (d["outcome"] or PENDING) == o) for o in OUTCOMES}
    return {"requests": req, "delegations": dels, "outcomes": states}


# --- engineering effort ----------------------------------------------------------------------------------

AREAS = ("measurement", "discovery", "serving", "guards", "workloads", "meta")
#: Source path prefix -> area; first match wins, tests are mapped through the module they name.
PATH_AREAS = (
    ("tests/gauntlet/", "meta"), (".github/", "meta"), ("Makefile", "meta"), ("harness/knob", "meta"),
    ("harness/audit", "meta"), ("harness/live_audit", "meta"), ("harness/sensitivity", "meta"),
    ("harness/ledger", "meta"), ("harness/trends", "meta"), ("harness/usage", "meta"),
    ("harness/otel", "meta"), ("harness/context", "meta"), ("harness/statusline", "meta"),
    ("harness/inventory", "meta"), ("harness/suite_time", "meta"), ("harness/coverage", "meta"),
    ("harness/covdiff", "meta"), ("harness/blame", "meta"), ("harness/assertions", "meta"),
    ("harness/watchdog", "guards"), ("harness/deploy_guard", "guards"), ("harness/sweep_guard", "guards"),
    ("harness/sweep_check", "guards"), ("harness/canary", "guards"), ("harness/pressure", "guards"),
    ("harness/memory.", "guards"), ("harness/throttle", "guards"), ("harness/availability", "guards"),
    ("harness/lane_probe", "guards"), ("harness/privacy", "guards"), ("harness/migration_check", "guards"),
    ("harness/heartbeat", "guards"), ("harness/chaos", "guards"), ("harness/paused", "guards"),
    ("harness/checks/", "guards"), ("harness/venv_drift", "guards"), ("harness/morning", "guards"),
    ("harness/discover", "discovery"), ("harness/feeds", "discovery"), ("harness/candidates", "discovery"),
    ("harness/neighbors", "discovery"), ("harness/inspect", "discovery"), ("harness/fetch", "discovery"),
    ("harness/downloads", "discovery"), ("harness/funnel", "discovery"), ("harness/famil", "discovery"),
    ("harness/rank", "discovery"), ("harness/lexical_rank", "discovery"), ("harness/papers", "discovery"),
    ("harness/quants", "discovery"), ("harness/obtainable", "discovery"), ("harness/sweeps", "discovery"),
    ("harness/yield_stop", "discovery"), ("harness/adopt", "discovery"), ("harness/winners", "discovery"),
    ("harness/ceiling", "discovery"), ("harness/day_fetch", "discovery"), ("harness/proposals", "discovery"),
    ("harness/convertible", "discovery"), ("harness/variants", "discovery"), ("harness/reuse", "discovery"),
    ("harness/delegat", "workloads"), ("harness/mcp_server", "workloads"), ("harness/lanes", "workloads"),
    ("harness/claude_news", "workloads"), ("harness/audio", "workloads"), ("harness/image_", "workloads"),
    ("harness/voices", "workloads"), ("voice/", "workloads"), ("harness/label", "workloads"),
    ("harness/headless", "workloads"), ("harness/needle", "workloads"), ("harness/clips", "workloads"),
    ("harness/serving", "serving"), ("harness/router", "serving"), ("harness/mlx_server", "serving"),
    ("harness/vllm", "serving"), ("harness/gateway", "serving"), ("harness/nodes", "serving"),
    ("harness/lease", "serving"), ("harness/exclusive", "serving"), ("harness/workqueue", "serving"),
    ("harness/memory_store", "serving"), ("harness/store", "serving"), ("harness/machine", "serving"),
    ("harness/env", "serving"), ("harness/paths", "serving"), ("harness/engines", "serving"),
    ("harness/gguf", "serving"), ("harness/ds4", "serving"), ("harness/completion", "serving"),
    ("harness/slot_probe", "serving"), ("harness/lanprobe", "serving"), ("harness/proc", "serving"),
    ("harness/batch", "serving"), ("gateway/", "serving"), ("deploy/", "serving"), ("scripts/smoke", "guards"),
    ("scripts/", "serving"), ("Dockerfile", "serving"), ("pyproject.toml", "serving"), ("uv.lock", "serving"),
    ("evals/", "measurement"), ("harness/", "measurement"),
)
#: Title pattern -> area, for an item with no source path; first match wins, the rest is meta.
TITLE_AREAS = (
    (r"watchdog|guard|canary|pressure|orphan|\bpause|overrun|smoke|outage|alert|notif|morning", "guards"),
    (r"gauntlet|knob|audit|mutation|\bci\b|make check|nightly|flak|test suite|ledger|inventory|"
     r"reassess|lint|readme|docs?\b|claude\.md|skill", "meta"),
    (r"eval|exam|case|screen|measur|judge|rubric|holdout|grad|bench|repo lane|score|metric|"
     r"pass rate|contamina|verdict|runner|broken", "measurement"),
    (r"gateway|serving|serve|llama|mlx|vllm|router|node|lease|\block|store|schema|migration|deploy|"
     r"launchd|ds4|engine|install|linux|windows", "serving"),
    (r"discover|sweep|feed|candidate|fetch|lineage|famil|funnel|adopt|neighbo|quant|"
     r"proposal|hugging ?face|\bhf\b", "discovery"),
    (r"local_complete|local_decide|delegat|\bmcp\b|image|video|tts|stt|voice|svg|web lane|music|"
     r"claude-news|news|extract lane|transcri|audio|player|speech", "workloads"),
)


#: Paths nearly every change touches; they decide an item's area only when nothing else does.
INCIDENTAL = ("harness/cli.py", "harness/memory_store", "README.md", "PLAN.md", "ASSERTIONS.md",
              "uv.lock", "pyproject.toml", "harness/commands/common.py")


def _path_area(path: str) -> str | None:
    if path.startswith("tests/gauntlet/"):
        return "meta"
    named = path.startswith("tests/") or path.startswith("harness/commands/")
    if named:
        stem = Path(path).stem
        if path.startswith("tests/"):
            if not stem.startswith("test_"):
                return None
            stem = re.sub(r"_\d+$", "", re.sub(r"^(harness|evals)_", "", stem[5:]))
        path = f"harness/{stem}"
    for prefix, area in PATH_AREAS:
        if path.startswith(prefix) and not (named and prefix == "harness/"):
            return area
    return None


def title_match(title: str, labels=()) -> str | None:
    if "measurement" in labels:
        return "measurement"
    low = (title or "").lower()
    for pattern, area in TITLE_AREAS:
        if re.search(pattern, low):
            return area
    return None


def title_area(title: str, labels=()) -> str:
    return title_match(title, labels) or "meta"


def pr_area(pr: dict) -> str:
    """The area holding most of a PR's source churn, else its tests', else incidental files', else its title's."""
    churn: dict = {}
    tests: dict = {}
    side: dict = {}
    for f in pr.get("files") or []:
        area = _path_area(f["path"])
        if area is None:
            continue
        into = (side if f["path"].startswith(INCIDENTAL) else
                tests if f["path"].startswith("tests/") else churn)
        into[area] = into.get(area, 0) + (f.get("additions") or 0) + (f.get("deletions") or 0)
    pick = churn or tests or side
    if pick:
        return max(pick, key=lambda a: (pick[a], -AREAS.index(a)))
    return title_area(pr.get("title", ""), _labels(pr))


def _labels(item: dict) -> list[str]:
    return [lb["name"] for lb in item.get("labels") or []]


def classify(prs: list[dict], issues: list[dict]) -> dict:
    """number -> area: the title's when it names one, else a PR's paths, an issue's closing PR's, else meta."""
    out, closed_by = {}, {}
    for pr in prs:
        paths_ = pr_area(pr)
        out[pr["number"]] = title_match(pr.get("title", ""), _labels(pr)) or paths_
        if pr.get("state") == "MERGED":
            for ref in pr.get("closingIssuesReferences") or []:
                closed_by.setdefault(ref["number"], paths_)
    for i in issues:
        out[i["number"]] = (title_match(i.get("title", ""), _labels(i)) or closed_by.get(i["number"])
                            or "meta")
    return out


def _ts(s: str | None) -> float | None:
    return _dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp() if s else None


def effort(prs: list[dict], issues: list[dict], now: float, sample: dict | None = None) -> dict:
    """Issues and PRs by area since the repo began and in the recent window, lines changed by merged PRs."""
    areas = classify(prs, issues)
    recent = now - RECENT_DAYS * 86400

    def table(since: float) -> dict:
        rows = {a: {"issues": 0, "prs": 0, "merged": 0, "lines": 0} for a in AREAS}
        for i in issues:
            if (_ts(i.get("createdAt")) or 0) >= since:
                rows[areas[i["number"]]]["issues"] += 1
        for p in prs:
            if (_ts(p.get("createdAt")) or 0) >= since:
                r = rows[areas[p["number"]]]
                r["prs"] += 1
                if p.get("state") == "MERGED":
                    r["merged"] += 1
                    r["lines"] += (p.get("additions") or 0) + (p.get("deletions") or 0)
        return rows

    out = {"all": table(0.0), "recent": table(recent), "recent_days": RECENT_DAYS}
    if sample:
        checked = {int(n): a for n, a in sample.items() if int(n) in areas}
        agree = [n for n, a in checked.items() if areas[n] == a]
        out["sample"] = {"checked": len(checked), "agree": len(agree),
                         "rate": len(agree) / len(checked) if checked else None,
                         "disagree": {n: {"hand": a, "rule": areas[n]} for n, a in sorted(checked.items())
                                      if areas[n] != a}}
    return out


SAMPLE = Path(__file__).with_name("effort_sample.json")


def load_sample(path: Path = SAMPLE) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def gh_items(run=subprocess.run, limit: int = 5000) -> tuple[list, list]:
    """(PRs, issues) from GitHub through the gh CLI."""
    def ask(argv):
        got = run(argv, capture_output=True, text=True, timeout=600)
        if got.returncode:
            raise RuntimeError(f"{' '.join(argv[:3])}: {got.stderr.strip()[:300]}")
        return json.loads(got.stdout or "[]")
    prs = ask(["gh", "pr", "list", "--state", "all", "--limit", str(limit), "--json",
               "number,title,labels,files,additions,deletions,createdAt,mergedAt,state,closingIssuesReferences"])
    issues = ask(["gh", "issue", "list", "--state", "all", "--limit", str(limit), "--json",
                  "number,title,labels,createdAt,closedAt,state"])
    return prs, issues


# --- reading the sources, read-only --------------------------------------------------------------------

def _rows(conn, sql: str, args=()) -> list[dict]:
    try:
        return [dict(r) for r in conn.execute(sql, args)]
    except Exception as exc:  # noqa: BLE001
        if "no such" in str(exc):
            return []
        raise


def _run_span(path: Path, generated: float | None) -> tuple | None:
    try:
        prog = json.loads((path / "progress.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        prog = {}
    if isinstance(prog, dict) and prog.get("started_at") and prog.get("last_progress_at"):
        return float(prog["started_at"]), float(prog["last_progress_at"])
    if generated is None:
        return None
    try:
        rows = json.loads((path / "results.json").read_text(encoding="utf-8")).get("rows") or []
        spent = sum(float(r.get("seconds") or 0) for r in rows if isinstance(r, dict))
    except (OSError, ValueError, AttributeError):
        spent = 0.0
    return generated - spent, generated


def _text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def gather(conn, home: Path, now: float, since: float | None = None) -> dict:
    """Every source once: the store through `conn` (read-only), the ledger, run dirs and logs under `home`."""
    from harness import ledger, power as power_mod
    from harness import memory_store as ms
    mid = ms.machine_row(conn)
    first = _rows(conn, "SELECT first_seen FROM machines WHERE id = ?", (mid,))
    start = since if since is not None else (first[0]["first_seen"] if first else now - 14 * 86400)
    mine = "(machine_id = ? OR machine_id IS NULL)"
    reqs = _rows(conn, "SELECT at, client, lane, purpose, total_s, ttft_s, prompt_tokens, completion_tokens, "
                       "call_id FROM gateway_requests WHERE at >= ?", (start,))
    intervals = [(r["at"], r["at"] + (r["total_s"] or 0.0), request_category(r["purpose"], r["client"]))
                 for r in reqs]
    for j in _rows(conn, f"SELECT kind, argv, requested_by, started_at, finished_at, state FROM jobs "
                         f"WHERE started_at IS NOT NULL AND {mine}", (mid,)):
        try:
            argv = json.loads(j["argv"])
        except ValueError:
            argv = j["argv"]
        stop = j["finished_at"] or (now if j["state"] == "running" else j["started_at"])
        intervals.append((j["started_at"], stop, job_category(j["kind"], argv, j["requested_by"])))
    runs_dir = home / "runs"
    for r in _rows(conn, f"SELECT path, generated_at FROM runs WHERE {mine} AND "
                         f"(generated_at IS NULL OR generated_at >= ?)", (mid, start)):
        p = Path(r["path"])
        span = _run_span(p if p.is_absolute() else runs_dir / p, r["generated_at"])
        if span:
            intervals.append((*span, MEASUREMENT))
    logs = home / "logs"
    disc = "\n".join(_text(p) for p in sorted(logs.glob("discover*.log")))
    sweep = sweeps(log_marks(disc, _SWEEP), log_marks(disc, _SWEEP_KILLED),
                   [i for i in intervals if i[2] in (MEASUREMENT, DISCOVERY)],
                   float(power_mod.SWEEP_CEILING_H) * HOUR)
    intervals += [(b, e, DISCOVERY) for b, e in sweep]
    dels = _rows(conn, "SELECT d.call_id, d.at, d.lane, d.id_source, d.seconds, d.outcome, g.client "
                       "FROM delegations d LEFT JOIN gateway_requests g ON g.call_id = d.call_id "
                       "WHERE d.at >= ?", (start,))
    return {
        "start": start, "end": now, "machine_id": mid, "intervals": intervals, "requests": reqs,
        "sweeps": sum(1 for b, _ in sweep if b >= start),
        "power": [s for s in ledger.read_jsonl(home / "ledger" / "power.jsonl") if s.get("at", 0) >= start],
        "probes": _rows(conn, f"SELECT at, outcome, reason FROM lane_probes WHERE at >= ? AND {mine}",
                        (start, mid)),
        "actions": _rows(conn, f"SELECT at, criterion, action, dry_run FROM watchdog_actions "
                               f"WHERE at >= ? AND {mine}", (start, mid)),
        "clearances": _rows(conn, f"SELECT cleared_at, until, revoked_at FROM day_clearances WHERE {mine}", (mid,)),
        "paused": _rows(conn, f"SELECT paused_at, why FROM paused_runs WHERE paused_at >= ? AND {mine}",
                        (start, mid)),
        "refused": [r for r in refusals(_text(logs / "mcp.log")) if r["at"] >= start],
        "mornings": log_marks(_text(logs / "morning.log"), _MORNING),
        "delegations": dels,
    }


def build(src: dict, tz=None, prs=None, issues=None, sample=None) -> dict:
    hours = account(src["intervals"], src["start"], src["end"], src["power"], src["probes"])
    out = {"window": {"start": src["start"], "end": src["end"], "hours": len(hours)},
           "pareto": pareto(hours),
           "blocked": blocked(hours, src["actions"], src["clearances"], src["paused"], src["refused"], tz),
           "local": local_work(src["requests"], src["delegations"], src["mornings"]),
           "sweeps": src.get("sweeps", 0), "hours": hours}
    if prs is not None:
        out["effort"] = effort(prs, issues or [], src["end"], sample)
    return out
