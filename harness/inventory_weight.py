"""`soh inventory weight`: each case, test, unit, knob and check scored on its cost against the work it has done. #1148."""
from __future__ import annotations

import ast
import calendar
import importlib.util
import json
import plistlib
import re
import subprocess
import tempfile
import time
import xml.etree.ElementTree as ET
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from harness import local_catches, paths

KINDS = ("cases", "tests", "units", "knobs", "checks")
#: Candidates that must have sat a case on the current exam before its discrimination is judged.
MIN_MODELS = 3
#: The slowest share of tests a never-failed test must sit in to be flagged.
SLOW_SHARE = 0.10
#: How long one gh or git call may take; a timeout reports that source unavailable.
GH_TIMEOUT_S = 600.0
#: CI runs listed; above the repo's count, so every run is read, and a full page is reported as truncated.
CI_LIMIT = 5000
#: Failed-run logs fetched at once; every failed run is read either way.
CI_WORKERS = 8
WORKFLOW = "ci.yml"
JUNIT_ARTIFACT = "junit-macos"
MAIN_EVENTS = ("push", "schedule", "workflow_dispatch")
RESIDENT_WAKES = 1440.0
DAY = 86400.0

#: Parts whose failure would be silent, so they are load-bearing whatever their firing rate.
FUSES = {
    ("units", "watchdog"): "the only thing that stops a wedged or daytime GPU job; idle is its normal state (#814)",
    ("units", "audit"): "checks the store's invariants nightly; a silent break shows nowhere else (#492)",
    ("units", "sweep-check"): "says when tonight's sweep did not start or stalled, which no other unit notices (#1062)",
    ("checks", "deploy_guard"): "refuses a deploy of a main commit whose own CI run did not pass (#870)",
    ("checks", "sweep_guard"): "refuses a deploy while a sweep or eval runs on the code it imported (#1000)",
}

#: A serving unit's rows are the gateway requests to aliases routed to the port its serve script binds.
PORT = "@port"
#: unit -> (store table, time column, extra SQL condition, words a report surface names its output by).
UNIT_OUTPUTS = {
    "gateway": ("gateway_requests", "at", "", ("gateway_requests",)),
    "mlx": ("gateway_requests", "at", PORT, ()),
    "eval": ("gateway_requests", "at", PORT, ()),
    "tts": ("gateway_requests", "at", PORT, ()),
    "mcp": ("delegations", "at", "", ("delegations", "mcp.log")),
    "discover": ("verdicts", "decided_at", "", ("verdicts", "discover.log")),
    "worker": ("jobs", "finished_at", "", ("jobs",)),
    "audit": ("", "", "", ("audit.log", "live_audit")),
    "ds4": ("gateway_requests", "at", PORT, ()),
    "watchdog": ("watchdog_actions", "at", "criterion != 'sweep_check'", ("watchdog_actions",)),
    "energy": ("ledger_days", "recorded_at", "energy_kwh IS NOT NULL", ("power.jsonl", "energy_kwh")),
    "ledger": ("ledger_days", "recorded_at", "", ("ledger_days",)),
    "morning": ("", "", "", ("morning.log",)),
    "claude-news": ("", "", "", ("claude-news", "claude_news")),
    "otel": ("otel_events", "received_at", "", ("otel_events",)),
    "canary": ("", "", "", ("canary",)),
    "sweep-check": ("watchdog_actions", "at", "criterion = 'sweep_check'", ("sweep_check", "sweep-check.log")),
    "fetch": ("downloads", "started_at", "origin = 'fetch'", ("downloads",)),
    "delegations": ("delegations", "outcome_at", "", ("delegations",)),
}
#: Where a person or a report reads a unit's output: commands, the morning brief, the audit, the published reports.
REPORT_SURFACES = ("harness/commands/*.py", "harness/morning.py", "harness/live_audit.py", "harness/publish.py",
                   "harness/report*.py", "harness/lane_feed.py")
#: Where a direct client of a serving unit's port would live.
CLIENT_SOURCES = ("harness/*.py", "harness/commands/*.py", "evals/**/*.py", "voice/**/*.py", "voice/**/*.sh",
                  "scripts/*.sh", "gateway/*.yaml")

_PORT = re.compile(r"PORT:-(\d+)")
_SERVICES = re.compile(r'^SERVICES="([^"]+)"', re.M)
_HEADER = re.compile(r"^_+ (?:(?:ERROR|FAILURE) at (?:setup|teardown|collection) of )?(\S+?)(?:\[.*\])? _+$")
_FRAME = re.compile(r"^(tests/[\w./-]+\.py):\d+:")
_STAMP = re.compile(r"^(?:[^\t]*\t){0,2}\ufeff?\d{4}-\d\d-\d\dT[\d:.]+Z ?")
_AUDIT_AT = re.compile(r"^=== audit (\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ) ===")
_AUDIT_LINE = re.compile(r"^  (FAIL|warn) (\w+)(?::|$)")
_REFS = re.compile(r"#(\d+)")


def _sh(run, argv, cwd=None) -> str:
    got = run(argv, capture_output=True, text=True, timeout=GH_TIMEOUT_S, cwd=cwd)
    if got.returncode:
        raise RuntimeError(f"{' '.join(argv[:3])}: {(got.stderr or got.stdout or '').strip()[:300]}")
    return got.stdout or ""


def _iso(s: str) -> float:
    return float(calendar.timegm(time.strptime(s[:19], "%Y-%m-%dT%H:%M:%S")))


def _base(case_id: str) -> str:
    return case_id.split("#", 1)[0]


# --- tests: one name for a test function, whatever reported it ------------------------------------------

def test_key(path: str, qualified: str) -> str:
    """'tests/x.py::Class.test_y' or 'tests/x.py::test_y', parameters dropped."""
    return f"{path.replace(chr(92), '/')}::{qualified.split('[', 1)[0].replace('::', '.')}"


def node_key(node: str) -> str:
    path, _, name = node.partition("::")
    return test_key(path, name)


def junit_times(path) -> dict[str, float]:
    """test function -> seconds summed over its parameters, from a JUnit XML report."""
    out: dict[str, float] = defaultdict(float)
    for case in ET.parse(path).getroot().iter("testcase"):
        parts = (case.get("classname") or "").split(".")
        cut = next((i for i, p in enumerate(parts) if p[:1].isupper()), len(parts))
        if not parts[:cut]:
            continue
        name = ".".join(parts[cut:] + [case.get("name", "")])
        out[test_key("/".join(parts[:cut]) + ".py", name)] += float(case.get("time") or 0)
    return dict(out)


def failed_tests(log: str) -> set[str]:
    """The test functions a failed run's log names, read from its FAILURES headers and their first test frame."""
    got, name = set(), None
    for raw in log.splitlines():
        line = _STAMP.sub("", raw, count=1).rstrip()
        m = _HEADER.match(line)
        if m:
            name = m.group(1)
            continue
        f = _FRAME.match(line.replace("\\", "/"))
        if name and f:
            got.add(test_key(f.group(1), name))
            name = None
    return got


# --- git history: who added what, and when a constant's value moved -------------------------------------

def history(text: str) -> list[dict]:
    """`git log --reverse -p --unified=0 --format='@@COMMIT %h %ct %s'` as commits with added and removed lines per file."""
    commits, cur, path = [], None, None
    for line in text.splitlines():
        if line.startswith("@@COMMIT "):
            sha, at, subject = (line[9:].split(" ", 2) + ["", ""])[:3]
            cur = {"sha": sha, "at": float(at or 0), "subject": subject, "files": {}}
            commits.append(cur)
            path = None
        elif cur is None:
            continue
        elif line.startswith("+++ "):
            path = line[6:] if line.startswith("+++ b/") else None
        elif line.startswith("--- ") or line.startswith("@@"):
            continue
        elif path and line[:1] in "+-":
            cur["files"].setdefault(path, ([], []))[0 if line[0] == "+" else 1].append(line[1:])
    return commits


def origin(c: dict) -> dict:
    return {"sha": c["sha"], "at": c["at"], "issues": [int(n) for n in _REFS.findall(c["subject"])][:1],
            "subject": c["subject"][:120]}


def test_origins(commits: list[dict]) -> dict[str, dict]:
    """'file::name' (bare function name) -> the commit that first added `def name`."""
    out: dict[str, dict] = {}
    for c in commits:
        for path, (added, _) in c["files"].items():
            if not path.startswith("tests/"):
                continue
            for line in added:
                m = re.match(r"\s*(?:async\s+)?def (test_\w+)\(", line)
                if m:
                    out.setdefault(f"{path}::{m.group(1)}", origin(c))
    return out


def first_added(commits: list[dict], path: str, needle: str) -> dict | None:
    for c in commits:
        added = c["files"].get(path, ([], []))[0]
        if any(needle in line for line in added):
            return origin(c)
    return None


def value_changes(commits: list[dict], site: str) -> int | None:
    """Commits that changed a module constant's value at `rel:NAME`; None for a site form history cannot read."""
    rel, _, name = site.partition(":")
    if not re.fullmatch(r"[A-Z][A-Z0-9_]*", name):
        return None
    pat = re.compile(rf"^\s*{name}\s*(?::[^=]+)?=\s*(.+?)\s*(?:#.*)?$")
    n = 0
    for c in commits:
        added, removed = c["files"].get(rel, ([], []))
        new = {m.group(1) for m in map(pat.match, added) if m}
        old = {m.group(1) for m in map(pat.match, removed) if m}
        if any(v[-1:] in "{([" for v in new | old):
            return None
        if new and old and new != old:
            n += 1
    return n


# --- units ----------------------------------------------------------------------------------------------

def services(text: str) -> list[str]:
    m = _SERVICES.search(text or "")
    return m.group(1).split() if m else []


def wakes_per_day(plist: dict) -> float | None:
    """How often launchd starts the unit a day; None when it is resident (kept alive) or has no schedule."""
    cal = plist.get("StartCalendarInterval")
    if cal is not None:
        total = 0.0
        for e in cal if isinstance(cal, list) else [cal]:
            n = (60.0 if "Minute" not in e else 1.0) * (24.0 if "Hour" not in e else 1.0)
            total += n / (7.0 if "Weekday" in e else 1.0) / (30.0 if "Day" in e else 1.0)
        return total
    if plist.get("StartInterval"):
        return DAY / float(plist["StartInterval"])
    return None


def log_runs(text: str, unit: str, since: float) -> int | None:
    """Starts the unit's serve script wrote to its log in the window; None when it writes no start line."""
    starts = [_iso(m.group(1)) for m in re.finditer(rf"^=== {re.escape(unit)} (\d{{4}}-\d\d-\d\dT[\d:]+Z)", text or "",
                                                     re.M)]
    return sum(t >= since for t in starts) if starts else None


def readers(root: Path, words, own: str = "", surfaces=REPORT_SURFACES) -> list[str]:
    """Report surfaces whose source names any of `words`, the unit's own command left out."""
    out = []
    for pattern in surfaces:
        for p in sorted(root.glob(pattern)):
            rel = p.relative_to(root).as_posix()
            if rel == own or rel in out or not p.is_file():
                continue
            if any(w in p.read_text(encoding="utf-8", errors="replace") for w in words):
                out.append(rel)
    return out


# --- checks ---------------------------------------------------------------------------------------------

def audit_firings(text: str) -> tuple[int, dict[str, list[float]]]:
    """(audit runs, check -> times it printed FAIL or warn) from the audit unit's log."""
    runs, at, got = 0, 0.0, defaultdict(list)
    for line in (text or "").splitlines():
        m = _AUDIT_AT.match(line)
        if m:
            runs, at = runs + 1, _iso(m.group(1))
            continue
        f = _AUDIT_LINE.match(line)
        if f:
            got[f.group(2)].append(at)
    return runs, dict(got)


def _module_literal(path: Path, name: str):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == name for t in node.targets):
            return ast.literal_eval(node.value)
    return None


def gauntlet_index(root: Path) -> dict:
    spec = importlib.util.spec_from_file_location("_gauntlet_classes", root / "tests" / "gauntlet" / "classes.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.INDEX


# --- gathering: every read is read-only ----------------------------------------------------------------

def _rows(conn, sql: str, args=()) -> list[dict]:
    try:
        return [dict(r) for r in conn.execute(sql, args)]
    except Exception as exc:  # noqa: BLE001
        if "no such" in str(exc):
            return []
        raise


def gather_cases(conn, exam_of=None) -> dict:
    """Stored measure rows, those on the lane's current exam marked, references and controls left out."""
    from harness import adopt, baseline, methods
    memo: dict = {}
    if exam_of is None:
        from evals import core
        suite = core.load_suite(core.SHIPPED, core.local_root())

        def exam_of(lane, split, repeat):
            return baseline.exam(lane, split, repeat, suite=suite)
    current = set()
    for r in _rows(conn, "SELECT id, lane, split, repeat_count, cases_digest, receipt FROM runs WHERE tier = 'measure'"):
        receipt = json.loads(r["receipt"] or "{}")
        key = ((r["lane"] or "").lower(), r["split"] or receipt.get("split") or "all", int(r["repeat_count"] or 1))
        if key not in memo:
            memo[key] = exam_of(*key)
        ids, digest = memo[key]
        if digest and r["cases_digest"] == digest and (receipt.get("harness") or "patch") == "patch":
            current.add(r["id"])
    rows = []
    for x in _rows(conn, "SELECT x.run_id, x.candidate, x.case_id, x.passed, x.seconds, r.lane, r.specs "
                         "FROM results x JOIN runs r ON r.id = x.run_id WHERE r.tier = 'measure'"):
        spec = (json.loads(x["specs"] or "{}") or {}).get(x["candidate"]) or x["candidate"]
        if adopt.is_reference(spec) or methods.is_control(spec):
            continue
        rows.append({"lane": (x["lane"] or "").lower(), "case": _base(x["case_id"]), "candidate": spec,
                     "passed": bool(x["passed"]), "seconds": float(x["seconds"] or 0), "current": x["run_id"] in current})
    return {"rows": rows, "current_runs": len(current)}


def ci_runs(run) -> dict:
    got = json.loads(_sh(run, ["gh", "run", "list", "--workflow", WORKFLOW, "--limit", str(CI_LIMIT), "--json",
                              "databaseId,conclusion,headBranch,event,createdAt"]) or "[]")
    return {"runs": got, "truncated": len(got) >= CI_LIMIT}


def ci_failures(run, runs: list[dict], cache: Path | None = None) -> list[dict]:
    """Each failed run with the tests its log names; a run whose log cannot be read says why."""
    def one(r):
        rid = str(r["databaseId"])
        hit = cache / f"{rid}.json" if cache else None
        if hit and hit.is_file():
            return json.loads(hit.read_text(encoding="utf-8"))
        try:
            got = {"id": rid, "failed": sorted(failed_tests(_sh(run, ["gh", "run", "view", rid, "--log-failed"])))}
        except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
            return {"id": rid, "failed": [], "why": str(exc)[:200]}
        if hit:
            hit.write_text(json.dumps(got), encoding="utf-8")
        return got
    failed = [r for r in runs if r.get("conclusion") == "failure"]
    with ThreadPoolExecutor(CI_WORKERS) as pool:
        logs = list(pool.map(one, failed))
    return [{**got, "main": r.get("headBranch") == "main" and r.get("event") in MAIN_EVENTS,
             "at": r.get("createdAt", "")} for r, got in zip(failed, logs)]


def ci_junit(run, path: str = "") -> dict[str, float]:
    if path:
        return junit_times(path)
    rid = _sh(run, ["gh", "run", "list", "--workflow", WORKFLOW, "--branch", "main", "--event", "push", "--status",
                    "success", "-L", "1", "--json", "databaseId", "-q", ".[0].databaseId"]).strip()
    if not rid:
        raise RuntimeError("no successful main push run to read test times from")
    with tempfile.TemporaryDirectory() as d:
        _sh(run, ["gh", "run", "download", rid, "-n", JUNIT_ARTIFACT, "-D", d])
        return junit_times(Path(d) / "junit.xml")


def git_history(run, root: Path) -> list[dict]:
    return history(_sh(run, ["git", "-C", str(root), "log", "--reverse", "-p", "--unified=0",
                             "--format=@@COMMIT %h %ct %s", "HEAD", "--", "tests", "harness", "evals", "scripts",
                             "gateway", ":(exclude)evals/cases"]))


def agents_dir() -> Path:
    return Path.home() / "Library" / "LaunchAgents"


def _launchctl(unit: str, run, platform: str | None):
    from harness import sweep_check
    return sweep_check.launchd(service=unit, run=run, platform=platform)


def gather_units(conn, home: Path, root: Path, since: float, run=subprocess.run, agents: Path | None = None,
                 platform: str | None = None) -> list[dict]:
    from harness import volume
    agents = agents or agents_dir()
    out = []
    for unit in services((root / "scripts" / "launchd.sh").read_text(encoding="utf-8")):
        plist_path = agents / f"{volume.PREFIX}.{unit}.plist"
        try:
            plist = plistlib.loads(plist_path.read_bytes())
        except (OSError, plistlib.InvalidFileException):
            plist = None
        decl = UNIT_OUTPUTS.get(unit)
        script = root / "scripts" / f"serve-{unit}.sh"
        try:
            script_text = script.read_text(encoding="utf-8")
        except OSError:
            script_text = ""
        rows, args, read = None, [since], []
        if decl and decl[0]:
            table, col, cond, words = decl
            if cond == PORT:
                aliases = routed(root, unit)
                cond = f"alias IN ({','.join('?' * len(aliases))})" if aliases else "0"
                args += aliases
                port = _PORT.search(script_text)
                clients = readers(root, (f":{port.group(1)}",), script.relative_to(root).as_posix(),
                                  CLIENT_SOURCES) if port else []
                read = sorted(set(clients) - {f"harness/{unit}.py"} | ({"gateway/config.yaml"} if aliases else set()))
            where = f"{col} >= ?" + (f" AND ({cond})" if cond else "")
            got = _rows(conn, f"SELECT COUNT(*) AS n, MAX({col}) AS last FROM {table} WHERE {where}", args)
            rows = got[0] if got else {"n": 0, "last": None}
        if decl and decl[3]:
            read = readers(root, decl[3], f"harness/commands/{unit.replace('-', '_')}.py")
        if "--notify" in script_text:
            read.append("a person (--notify)")
        log = Path(plist.get("StandardOutPath")) if plist and plist.get("StandardOutPath") else \
            paths.logs() / f"{unit}.log"
        try:
            st = log.stat()
            logged = {"bytes": st.st_size, "mtime": st.st_mtime,
                      "runs": log_runs(log.read_text(encoding="utf-8", errors="replace"), unit, since)}
        except OSError:
            logged = None
        out.append({"unit": unit, "declared": decl is not None, "table": decl[0] if decl else "",
                    "rows": rows, "log": logged,
                    "resident": bool(plist and plist.get("KeepAlive")),
                    "wakes": wakes_per_day(plist) if plist else None, "plist": plist is not None,
                    "launchd": _launchctl(unit, run, platform), "readers": read})
    return out


def routed(root: Path, unit: str) -> list[str]:
    """Gateway aliases whose api_base is the port the unit's serve script binds by default."""
    import yaml
    try:
        port = _PORT.search((root / "scripts" / f"serve-{unit}.sh").read_text(encoding="utf-8"))
        conf = yaml.safe_load((root / "gateway" / "config.yaml").read_text(encoding="utf-8")) or {}
    except OSError:
        return []
    if not port:
        return []
    return sorted({m["model_name"] for m in conf.get("model_list") or []
                   if f":{port.group(1)}/" in str((m.get("litellm_params") or {}).get("api_base", ""))})


def gather_knobs(conn, commits: list[dict] | None) -> list[dict]:
    from harness import knobs
    sweeps = {r["knob"]: r["n"] for r in _rows(conn, "SELECT knob, COUNT(*) AS n FROM knob_sweeps GROUP BY knob")}
    cuts = {r["knob"]: r["n"] for r in _rows(conn, "SELECT knob, COUNT(*) AS n FROM limit_cuts GROUP BY knob")}
    hits = defaultdict(int)
    for r in _rows(conn, "SELECT hit_limit, COUNT(*) AS n FROM results WHERE hit_limit != '' GROUP BY hit_limit"):
        hits[re.split(r"[><=]", r["hit_limit"], maxsplit=1)[0]] += r["n"]
    recorded = defaultdict(set)
    for r in _rows(conn, "SELECT receipt FROM runs WHERE receipt LIKE '%\"knobs\"%'"):
        for k, v in ((json.loads(r["receipt"] or "{}") or {}).get("knobs") or {}).items():
            recorded[k].add(json.dumps(v, sort_keys=True))
    out = []
    for name, k in sorted(knobs.KNOBS.items()):
        limits = {k.limit.replace("{lane}", lane) for lane in (k.lanes or ("",))} if k.limit else set()
        changes = [value_changes(commits, s) for s in k.sites] if commits is not None else []
        out.append({"name": name, "sites": list(k.sites), "sweeps": sweeps.get(name, 0),
                    "cuts": cuts.get(name, 0) + sum(cuts.get(s, 0) for s in k.sites),
                    "hits": sum(hits.get(lim, 0) for lim in limits), "values": len(recorded.get(name, ())),
                    "changes": None if commits is None or all(c is None for c in changes)
                    else sum(c or 0 for c in changes)})
    return out


def gather_checks(conn, home: Path, root: Path, commits: list[dict] | None) -> dict:
    from harness import live_audit, watchdog
    fired = {r["criterion"]: r for r in _rows(
        conn, "SELECT criterion, COUNT(*) AS n, MAX(at) AS last FROM watchdog_actions GROUP BY criterion")}
    try:
        audit_text = (paths.logs() / "audit.log").read_text(encoding="utf-8", errors="replace")
    except OSError:
        audit_text = ""
    audit_runs, audit_fired = audit_firings(audit_text)
    found = (lambda path, needle: first_added(commits, path, needle)) if commits is not None else (lambda *_: None)
    rows = []
    for c in watchdog.CRITERIA:
        f = fired.get(c.id) or {}
        rows.append({"family": "watchdog", "name": c.id, "firings": f.get("n", 0), "last": f.get("last"),
                     "origin": found("harness/watchdog.py", f'Criterion("{c.id}"')})
    for name in live_audit.CHECKS:
        at = audit_fired.get(name, [])
        rows.append({"family": "audit", "name": name, "firings": len(at), "last": max(at) if at else None,
                     "evaluations": audit_runs,
                     "origin": found("harness/live_audit.py", f'"{name}"') or found("harness/migration_check.py",
                                                                                    f'"{name}"')})
    scanners: dict[str, dict] = {}
    for cls, entry in gauntlet_index(root).items():
        for node in entry.get("scanners", ()):
            s = scanners.setdefault(node_key(node), {"family": "scanner", "name": node_key(node), "class": [],
                                                     "instances": 0})
            s["class"].append(cls)
            s["instances"] += len(entry.get("instances", ()))
    rows += list(scanners.values())
    for name in ("deploy_guard", "sweep_guard"):
        rows.append({"family": "guard", "name": name, "firings": None,
                     "origin": found(f"harness/{name}.py", '"""')})
    return {"rows": rows}


# --- scoring: pure, from what was gathered -------------------------------------------------------------

def _row(kind, name, cost, unit, evidence, work, load=False, why="", flagged=None, **extra) -> dict:
    load = load or (kind, name) in FUSES
    why = why or FUSES.get((kind, name), "")
    rank = 0.0 if load or evidence is None else round(float(cost or 0) * (1.0 - evidence), 3)
    if flagged is None:
        flagged = not load and evidence == 0
    return {"kind": kind, "name": name, "cost": cost, "unit": unit, "evidence": evidence, "work": work,
            "load_bearing": load, "why": why, "flagged": bool(flagged), "rank": rank, **extra}


def score_cases(src: dict, min_models: int = MIN_MODELS) -> list[dict]:
    seconds, draws = defaultdict(float), defaultdict(lambda: defaultdict(list))
    for r in src.get("rows", ()):
        seconds[(r["lane"], r["case"])] += r["seconds"]
        if r["current"]:
            draws[(r["lane"], r["case"])][r["candidate"]].append(r["passed"])
    out = []
    for key in sorted(draws):
        rates = [sum(v) / len(v) for v in draws[key].values()]
        n, ok, bad = len(rates), sum(x == 1 for x in rates), sum(x == 0 for x in rates)
        if n < min_models:
            ev, work = None, f"sat by {n} candidate(s), under {min_models}: not judged"
        elif ok == n:
            ev, work = 0.0, f"every one of {n} candidates passed"
        elif bad == n:
            ev, work = 0.0, f"none of {n} candidates passed"
        else:
            ev, work = 1.0, f"{ok} always passed, {bad} always failed, {n - ok - bad} mixed, of {n}"
        out.append(_row("cases", f"{key[0]}/{key[1]}", round(seconds[key], 1), "case s", ev, work,
                        direction="all-pass" if ev == 0 and ok == n else "all-fail" if ev == 0 else "",
                        candidates=n))
    return out


def score_tests(junit: dict[str, float], failures: list[dict], origins: dict | None = None,
                mutation: dict | None = None, slow_share: float = SLOW_SHARE, local_runs: int = 0) -> list[dict]:
    failed = defaultdict(lambda: {"main": 0, "pr": 0, "local": 0, "last": ""})
    for run in failures:
        for key in run.get("failed", ()):
            f = failed[key]
            f["local" if run.get("local") else "main" if run.get("main") else "pr"] += 1
            f["last"] = max(f["last"], f"{run.get('at', '')} run {run['id']}")
    selected = defaultdict(list)
    for module, files in (mutation or {}).items():
        for f in files:
            selected[f].append(module)
    ranked = sorted(junit.values(), reverse=True)
    cut = ranked[max(0, int(len(ranked) * slow_share) - 1)] if ranked else 0.0
    out = []
    for key, s in junit.items():
        path, _, name = key.partition("::")
        f = failed.get(key)
        mods = selected.get(path, [])
        never = "never failed in CI or a local make check" if local_runs else "never failed in CI"
        if f:
            ev, work = 1.0, (f"failed in {f['main']} main and {f['pr']} PR run(s)"
                             + (f" and {f['local']} local make check(s)" if f["local"] else "") + f", last {f['last']}")
        elif mods:
            ev, work = 0.5, f"{never}; runs against mutants of {', '.join(mods)} (kills not recorded)"
        else:
            ev, work = 0.0, f"{never}; in no mutation selection"
        o = (origins or {}).get(f"{path}::{name.rsplit('.', 1)[-1]}")
        out.append(_row("tests", key, round(s, 2), "s per run", ev, work, load=bool(f),
                        why=("has caught a failure in CI" if f["main"] + f["pr"] else
                             "has caught a failure in a local make check") if f else "",
                        flagged=not f and not mods and s >= cut and s > 0,
                        origin=o["issues"][0] if o and o["issues"] else None))
    return out


def score_units(units: list[dict], since: float, now: float) -> list[dict]:
    out = []
    for u in units:
        rows, log = u.get("rows"), u.get("log")
        if rows is not None:
            wrote = bool(rows.get("n"))
        elif log and log.get("runs") is not None:
            wrote = bool(log["runs"])
        else:
            wrote = bool(log and log["mtime"] >= since and log["bytes"])
        read = bool(u.get("readers"))
        bits = []
        if not u.get("declared"):
            bits.append("no declared output")
        elif rows is not None:
            bits.append(f"{rows.get('n', 0)} {u['table']} row(s) in the window")
        if log:
            bits.append(f"log {log['bytes'] // 1024} KiB" + (f", {log['runs']} start(s) in the window"
                                                              if log.get("runs") is not None else ""))
        bits.append(f"read by {', '.join(u['readers'])}" if read else "no report reads its output")
        ld = u.get("launchd") or {}
        if ld.get("loaded"):
            bits.append(f"runs {ld.get('runs')}, last exit {ld.get('rc')}")
        elif ld.get("loaded") is False:
            bits.append("not loaded")
        cost = RESIDENT_WAKES if u.get("resident") else u.get("wakes")
        ev = 0.5 * wrote + 0.5 * read if u.get("declared") else 0.0
        load = ("units", u["unit"]) in FUSES
        out.append(_row("units", u["unit"], None if cost is None else round(cost, 2), "wakes/day", ev, "; ".join(bits),
                        flagged=not load and ev < 1))
    return out


def score_knobs(knobs: list[dict]) -> list[dict]:
    out = []
    for k in knobs:
        moved = [f"{k[f]} {label}" for f, label in (("sweeps", "sweep(s)"), ("cuts", "cut(s)"), ("hits", "hit row(s)"))
                 if k.get(f)]
        if k.get("values", 0) > 1:
            moved.append(f"{k['values']} recorded values")
        if k.get("changes"):
            moved.append(f"default changed in {k['changes']} commit(s)")
        known = "" if k.get("changes") is not None else "; site history not readable"
        out.append(_row("knobs", k["name"], 1, "knob", 1.0 if moved else 0.0,
                        (", ".join(moved) if moved else "never swept, cut, hit or changed") + known,
                        info="folding a knob into a constant is Eric's call"))
    return out


def score_checks(checks: dict, failures: list[dict], ci_total: int, days: float, watchdog_wakes: float | None) -> list[dict]:
    caught, local = defaultdict(int), defaultdict(int)
    for run in failures:
        for key in run.get("failed", ()):
            caught[key] += 1
            local[key] += bool(run.get("local"))
    out = []
    for c in checks.get("rows", ()):
        fam = c["family"]
        n = caught.get(c["name"], 0) if fam == "scanner" else c.get("firings")
        evals = {"watchdog": None if watchdog_wakes is None else round(watchdog_wakes * days),
                 "audit": c.get("evaluations"), "scanner": ci_total}.get(fam)
        o = c.get("origin") or {}
        if n is None:
            ev, work = None, "firings not recorded"
        elif n:
            ev, work = 1.0, f"fired {n} time(s)" + (f", last {time.strftime('%Y-%m-%d', time.localtime(c['last']))}"
                                                    if c.get("last") else "")
            if fam == "scanner" and local.get(c["name"]):
                work += f", {local[c['name']]} in a local make check"
        else:
            ev, work = 0.0, "never fired" + (f" in {evals} evaluation(s)" if evals else "")
        if fam == "scanner":
            work += f"; bound to {', '.join(c['class'])}, {c['instances']} instance(s)"
        out.append(_row("checks", c["name"], evals, "evaluations", ev, work,
                        load=bool(n), why="has a recorded catch" if n else "", family=fam,
                        origin=(o.get("issues") or [None])[0]))
    return out


def build(src: dict, min_models: int = MIN_MODELS, slow_share: float = SLOW_SHARE) -> dict:
    """Each kind's rows, ranked by cost x (1 - evidence of work), load-bearing ones last."""
    now, since = src["now"], src["since"]
    ci = src.get("ci") or {}
    local = src.get("local") or {}
    failures = ci.get("failures", []) + local.get("failures", [])
    kinds = {}
    if "cases" in src:
        kinds["cases"] = score_cases(src["cases"], min_models)
    if "junit" in src:
        kinds["tests"] = score_tests(src["junit"], failures, src.get("test_origins"), src.get("mutation"), slow_share,
                                     local.get("runs", 0))
    if "units" in src:
        kinds["units"] = score_units(src["units"], since, now)
    if "knobs" in src:
        kinds["knobs"] = score_knobs(src["knobs"])
    if "checks" in src:
        kinds["checks"] = score_checks(src["checks"], failures, len(ci.get("runs", [])) + local.get("runs", 0),
                                       (now - since) / DAY,
                                       src.get("watchdog_wakes"))
    out = {}
    for kind, rows in kinds.items():
        rows.sort(key=lambda r: (r["load_bearing"], not r["flagged"], -r["rank"], r["name"]))
        out[kind] = {"rows": rows, "flagged": sum(r["flagged"] for r in rows),
                     "load_bearing": sum(r["load_bearing"] for r in rows), "total": len(rows)}
    ci_failed = ci.get("failures", [])
    return {"window": {"since": since, "now": now}, "kinds": out, "unavailable": src.get("unavailable", {}),
            "ci": {"runs": len(ci.get("runs", [])), "failed": len(ci_failed), "truncated": ci.get("truncated", False),
                   "unreadable": [f["id"] for f in ci_failed if f.get("why")]},
            "local": {"runs": local.get("runs", 0), "failed": len(local.get("failures", [])),
                      "unreadable": local.get("unreadable", 0)}}


def gather(conn, home: Path, now: float, since: float | None = None, kinds=KINDS, run=subprocess.run,
           root: Path | None = None, junit: str = "", ci: bool = True, ci_cache: Path | None = None,
           agents: Path | None = None, platform: str | None = None, exam_of=None) -> dict:
    """What each kind needs, read from the store (read-only), the logs, launchd, CI and git; a source that cannot be read says why."""
    root = root or paths.REPO
    src: dict = {"now": now, "unavailable": {}}
    first = _rows(conn, "SELECT MIN(first_seen) AS t FROM machines")
    src["since"] = since if since is not None else float((first[0]["t"] if first else None) or now - 30 * DAY)

    def guard(name, fn):
        try:
            return fn()
        except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
            src["unavailable"][name] = str(exc)[:300]
            return None
    commits = guard("git", lambda: git_history(run, root)) if {"tests", "knobs", "checks"} & set(kinds) else None
    if ci and {"tests", "checks"} & set(kinds):
        listed = guard("ci", lambda: ci_runs(run))
        if listed:
            if since is not None:
                listed["runs"] = [r for r in listed["runs"] if not r.get("createdAt") or _iso(r["createdAt"]) >= since]
            listed["failures"] = ci_failures(run, listed["runs"], ci_cache)
            src["ci"] = listed
    if {"tests", "checks"} & set(kinds):
        src["local"] = local_catches.read(home / local_catches.FILE, src["since"])
    if "cases" in kinds:
        src["cases"] = gather_cases(conn, exam_of)
    if "tests" in kinds:
        got = guard("junit", lambda: ci_junit(run, junit))
        if got is not None:
            src["junit"] = got
            src["test_origins"] = test_origins(commits) if commits else {}
            src["mutation"] = guard("mutation", lambda: _module_literal(root / "tests" / "gauntlet" / "mutation.py",
                                                                         "MODULES")) or {}
    if "units" in kinds or "checks" in kinds:
        units = gather_units(conn, home, root, src["since"], run, agents, platform)
        if "units" in kinds:
            src["units"] = units
        wd = next((u for u in units if u["unit"] == "watchdog"), None)
        src["watchdog_wakes"] = wd["wakes"] if wd else None
    if "knobs" in kinds:
        src["knobs"] = gather_knobs(conn, commits)
    if "checks" in kinds:
        src["checks"] = gather_checks(conn, home, root, commits)
    return src


def _cost(r) -> str:
    return "--" if r["cost"] is None else f"{r['cost']:g}"


def _ev(r) -> str:
    return "--" if r["evidence"] is None else f"{r['evidence']:g}"


def render(L: dict, top: int = 15, markdown: bool = False) -> str:
    """Each kind's cut list: its flagged rows by rank, then how many are load-bearing."""
    out = []
    ci = L.get("ci") or {}
    head = (f"CI: {ci.get('runs', 0)} runs, {ci.get('failed', 0)} failed"
            + (", the run list was truncated" if ci.get("truncated") else "")
            + (f", {len(ci['unreadable'])} failed run log(s) unreadable" if ci.get("unreadable") else ""))
    out.append(head)
    lo = L.get("local") or {}
    out.append(f"local make check: {lo.get('runs', 0)} run(s) recorded, {lo.get('failed', 0)} failed"
               + (f", {lo['unreadable']} unreadable line(s)" if lo.get("unreadable") else "")
               + ("" if lo.get("runs") else "; runs before #1261 left no record"))
    for name, why in (L.get("unavailable") or {}).items():
        out.append(f"unavailable: {name}: {why}")
    for kind, k in L["kinds"].items():
        flagged = [r for r in k["rows"] if r["flagged"]]
        title = f"{kind}: {k['flagged']} flagged, {k['load_bearing']} load-bearing, of {k['total']}"
        if markdown:
            out += ["", f"### {title}", "", "| rank | name | cost | evidence | work |", "|---:|---|---:|---:|---|"]
            out += [f"| {r['rank']:g} | `{r['name']}` | {_cost(r)} {r['unit']} | {_ev(r)} | {r['work']} |"
                    for r in flagged[:top]]
        else:
            out += ["", title, f"  {'rank':>10} {'cost':>10} {'ev':>4}  name: work"]
            out += [f"  {r['rank']:>10g} {_cost(r):>10} {_ev(r):>4}  {r['name']}: {r['work']}" for r in flagged[:top]]
        if len(flagged) > top:
            out.append(f"  ... {len(flagged) - top} more flagged")
        held = [r for r in k["rows"] if r["load_bearing"] and r["why"] and (kind, r["name"]) in FUSES]
        for r in held:
            out.append(f"  load-bearing {r['name']}: {r['why']}")
    return "\n".join(out)
