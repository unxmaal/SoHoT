"""`soh morning`: last night's sweep, watchdog, nightly CI, ledger row, stale lanes and deploy in one report. #867."""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
NIGHTLY_WORKFLOW = "ci.yml"
#: A nightly run older than this is reported as not last night's.
CI_FRESH_S = 30 * 3600
GH_TIMEOUT_S = 60.0
GIT_TIMEOUT_S = 60.0
MODEL_LANE = "extract"
MODEL_TIMEOUT_S = 90.0
MODEL_MAX_TOKENS = 220
HEADLINE_LINES = 3
#: A ranked-head candidate waiting undownloaded in one state this many days needs a person. #925.
STALL_DAYS = 14.0
#: How much of each wanted lane's ranked head the stall line watches.
STALL_HEAD = 10
HEADLINE_CHARS = 400
NOTIFY_TITLE = "SoHoT morning"
FAILED = ("failure", "cancelled", "timed_out", "startup_failure", "action_required")
SYSTEM = ("You condense a machine's overnight report for its owner. Use only facts in the report. "
          "Cover every item that needs a person, grouping alike items into one phrase (three watchdog stops "
          "are one phrase). Write 2 or 3 short plain lines, most urgent first, no preamble, no markdown, no advice.")


def snapshot():
    """A connection the report may use freely without writing the live store: a copy for SQLite."""
    from harness import ledger, store
    from harness import memory_store as ms
    if store.backend() == store.POSTGRES:
        return ms.connect()
    path = ms.db_path()
    mem = sqlite3.connect(":memory:")
    if path.exists():
        ro = ledger.open_ro(path)
        try:
            ro.backup(mem)
        finally:
            ro.close()
    mem.row_factory = sqlite3.Row
    return mem


def _has(conn, table: str) -> bool:
    try:
        conn.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchall()
    except Exception:  # noqa: BLE001
        return False
    return True


def _counts(conn, tier: str, since: float) -> dict:
    rows = conn.execute("SELECT outcome, COUNT(*) AS n FROM verdicts WHERE tier = ? AND decided_at >= ? "
                        "GROUP BY outcome ORDER BY outcome", (tier, since)).fetchall()
    return {r["outcome"]: r["n"] for r in rows}


def sweep(conn, since: float, beat: dict | None) -> dict:
    """What the sweep screened, measured, paused, stopped and settled since `since`, and how the loop ended."""
    out = {"screened": {}, "measured": {"runs": [], "verdicts": {}}, "paused": [], "stopped": [],
           "settled": {"verdicts": {}, "adopted": []}, "loop": None}
    if _has(conn, "verdicts"):
        out["screened"] = _counts(conn, "screen", since)
        out["measured"]["verdicts"] = _counts(conn, "measure", since)
        out["settled"]["verdicts"] = _counts(conn, "adopt", since)
    if _has(conn, "runs"):
        out["measured"]["runs"] = [dict(r) for r in conn.execute(
            "SELECT lane, path, recorded_at FROM runs WHERE tier = 'measure' AND recorded_at >= ? "
            "ORDER BY recorded_at", (since,))]
    if _has(conn, "paused_runs"):
        out["paused"] = [dict(r) for r in conn.execute(
            "SELECT id, lane, challenger, state, done, total, paused_at FROM paused_runs "
            "WHERE paused_at >= ? OR state = 'paused' ORDER BY paused_at", (since,))]
    if _has(conn, "adoptions"):
        out["settled"]["adopted"] = [dict(r) for r in conn.execute(
            "SELECT a.lane, c.spec, a.how, a.adopted_at FROM adoptions a JOIN candidates c "
            "ON c.id = a.candidate_id WHERE a.adopted_at >= ? ORDER BY a.adopted_at", (since,))]
    out["stopped"] = [w for w in watchdog(conn, since) if w["action"] == "stop"]
    if beat:
        started = float(beat.get("started") or 0)
        out["loop"] = {"status": beat.get("status", ""), "rc": beat.get("rc"), "error": beat.get("error", ""),
                       "started": started, "finished": beat.get("finished"),
                       "in_window": started >= since, "line": beat.get("line", ""),
                       "commit": beat.get("commit", ""), "finished_commit": beat.get("finished_commit", "")}
    return out


def watchdog(conn, since: float) -> list[dict]:
    if not _has(conn, "watchdog_actions"):
        return []
    return [dict(r) for r in conn.execute(
        "SELECT id, at, criterion, subject, action, escalated, dry_run, outcome FROM watchdog_actions "
        "WHERE at >= ? ORDER BY at", (since,))]


def ledger_row(conn, now: float) -> dict | None:
    """Last night's ledger_days row in tokens, read from its detail so a row from before #976 reads too."""
    if not _has(conn, "ledger_days"):
        return None
    day = datetime.fromtimestamp(now - 86400).strftime("%Y-%m-%d")
    r = conn.execute("SELECT day, recorded_at, energy_kwh, detail FROM ledger_days WHERE day = ?",
                     (day,)).fetchone()
    if not r:
        return {"day": day, "missing": True}
    try:
        d = json.loads(r["detail"] or "{}")
    except ValueError:
        d = {}
    lanes = (d.get("displaced") or {}).get("lanes") or []
    displaced = {k: sum(x.get(k) or 0 for x in lanes) for k in ("requests", "input", "output")}
    e = (d.get("energy") or {})
    return {"day": r["day"], "recorded_at": r["recorded_at"], "energy_kwh": r["energy_kwh"],
            "energy": {k: e.get(k) for k in ("partial", "lower_bound_kwh", "why")} if e.get("partial") else {},
            "cloud": (d.get("cloud") or {}).get("tokens"), "plan": d.get("headroom") or {}, "displaced": displaced}


def stale_lanes(conn) -> list[dict]:
    """What `soh verify` would run: lanes with no recent receipt here."""
    from harness import report, verify
    tasks = verify.plan(report.lanes_state(conn))
    return [{"lane": t.lane, "candidate": t.candidate, "why": t.why, "skip": t.skip} for t in tasks]


def stalled(conn, days: float | None = None, head: int | None = None) -> list[dict]:
    """The ranked head of a wanted lane, not downloaded, in its state past STALL_DAYS. #925."""
    from harness import funnel
    got = funnel.stalls(funnel.proposals(conn), STALL_DAYS if days is None else days,
                        STALL_HEAD if head is None else head)
    return [{k: r[k] for k in ("name", "lane", "lane_rank", "stage", "in_state_days", "age_days", "reason", "why")}
            for r in got]


def _gh(argv: list[str]) -> str:
    got = subprocess.run(["gh", *argv], cwd=REPO, capture_output=True, text=True, timeout=GH_TIMEOUT_S)
    if got.returncode != 0:
        raise RuntimeError(f"gh {argv[0]} {argv[1]}: rc {got.returncode}: {(got.stderr or '').strip()[:200]}")
    return got.stdout


def ci(now: float, gh=_gh) -> dict:
    """The newest scheduled nightly run and each job's conclusion; unavailable when gh cannot say."""
    try:
        runs = json.loads(gh(["run", "list", "--workflow", NIGHTLY_WORKFLOW, "--event", "schedule", "-L", "1",
                              "--json", "databaseId,status,conclusion,createdAt,headSha,url"]) or "[]")
        if not runs:
            return {"available": False, "why": f"no scheduled {NIGHTLY_WORKFLOW} run"}
        run = runs[0]
        jobs = json.loads(gh(["run", "view", str(run["databaseId"]), "--json", "jobs"]) or "{}").get("jobs") or []
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        return {"available": False, "why": str(exc)[:300]}
    created = datetime.fromisoformat(str(run.get("createdAt", "")).replace("Z", "+00:00")).timestamp()
    return {"available": True, "id": run.get("databaseId"), "status": run.get("status"),
            "conclusion": run.get("conclusion") or "", "created": created, "sha": run.get("headSha", ""),
            "url": run.get("url", ""), "fresh": now - created <= CI_FRESH_S,
            "jobs": [{"name": j.get("name", ""), "status": j.get("status", ""),
                      "conclusion": j.get("conclusion") or "", "url": j.get("url", "")} for j in jobs]}


def _git(argv: list[str]) -> str:
    got = subprocess.run(["git", *argv], capture_output=True, text=True, timeout=GIT_TIMEOUT_S)
    if got.returncode != 0:
        raise RuntimeError(f"git {' '.join(argv[2:4])}: rc {got.returncode}: {(got.stderr or '').strip()[:200]}")
    return got.stdout.strip()


def deploy(where: Path | None, git=_git) -> dict:
    """The deploy checkout's commit against origin/main, after a fetch."""
    if where is None or not (Path(where) / ".git").exists():
        return {"available": False, "why": "no deploy checkout on this machine"}
    d = ["-C", str(where)]
    try:
        git([*d, "fetch", "-q", "origin", "main"])
        head = git([*d, "rev-parse", "HEAD"])
        main = git([*d, "rev-parse", "origin/main"])
        behind = int(git([*d, "rev-list", "--count", "HEAD..origin/main"]) or 0)
        missing = git([*d, "log", "--format=%h %s", "-n", "5", "HEAD..origin/main"]).splitlines() if behind else []
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        return {"available": False, "why": str(exc)[:300]}
    return {"available": True, "path": str(where), "head": head, "main": main, "behind": behind, "missing": missing}


def lane_health(lane: str = MODEL_LANE) -> dict:
    """Whether the server behind `lane` can generate: False when mlx_lm.server says its generation thread died (#912)."""
    from harness import delegate, mlx_server, serving
    out = {"lane": lane, "spec": "", "base": "", "generating": None, "why": ""}
    try:
        out["spec"], where = delegate.route(lane)
        out["base"], _ = delegate.upstream(where)
        engine = serving.engine_at(out["base"]) if out["base"] else ""
    except Exception as exc:  # noqa: BLE001 - an unknown route is a fact for the report, not a crash
        out["why"] = f"{type(exc).__name__}: {exc}"[:300]
        return out
    if engine != serving.DEFAULT:
        out["why"] = f"served by {engine or 'an unknown server'}, which has no generation-thread health"
        return out
    from harness import watchdog
    out["generating"] = mlx_server.generating(out["base"], watchdog.PROBE_TIMEOUT_S)
    if out["generating"] is None:
        out["why"] = f"{out['base']}{mlx_server.HEALTH_PATH} did not answer"
    return out


def incidents(conn, since: float, now: float) -> list[dict]:
    """Every lane outage the watchdog's probes recorded that was open at or after `since` (#924)."""
    from harness import availability
    if not availability.has_table(conn):
        return []
    return availability.report(conn, since, now, machine_id=availability.here(conn))["incidents"]


def open_incident(r: dict, lane: str) -> dict | None:
    return next((i for i in r.get("incidents") or [] if i["lane"] == lane and i["open"]), None)


def lane_dead(r: dict) -> bool:
    lane = (r.get("lane") or {}).get("lane") or MODEL_LANE
    return (r.get("lane") or {}).get("generating") is False or open_incident(r, lane) is not None


def needs(r: dict) -> list[str]:
    """What needs a person, one line each; empty on a quiet night."""
    from harness.availability import incident_line
    out = [f"lane {incident_line(i)}" for i in r.get("incidents") or [] if i["open"]]
    h = r.get("lane") or {}
    if h.get("generating") is False and open_incident(r, h["lane"]) is None:
        out.append(f"the {h['lane']} lane cannot generate: {h['spec']} at {h['base']} says its generation thread "
                   "died; the watchdog restarts the mlx unit, or run `scripts/launchd.sh restart mlx`")
    loop = r["sweep"].get("loop")
    if loop is None or not loop["in_window"]:
        out.append("no discovery sweep ran last night")
    elif loop["status"] == "stalled":
        out.append(f"the sweep stalled: {loop['line']}")
    elif loop["status"] == "finished" and loop["rc"] != 0:
        out.append(f"the sweep exited {loop['rc'] if loop['rc'] is not None else 'with ' + loop['error']}")
    if loop is not None and loop["in_window"] and loop.get("code_moved"):
        out.append(loop["code_moved"])
    for w in r["watchdog"]:
        if w["action"] == "stop" or w["escalated"]:
            dry = " (dry run)" if w["dry_run"] else ""
            out.append(f"watchdog {w['action']}{dry}: {w['criterion']} on {w['subject']} at "
                       f"{datetime.fromtimestamp(w['at']).strftime('%H:%M')}")
    c = r["ci"]
    if c.get("available") and c["fresh"]:
        bad = [j["name"] for j in c["jobs"] if j["conclusion"] in FAILED]
        if bad:
            out.append(f"nightly CI failed: {', '.join(bad)}")
    d = r["deploy"]
    if d.get("available") and d["behind"]:
        out.append(f"deploy is {d['behind']} commit(s) behind origin/main")
    if r["stale"]:
        out.append(f"stale lanes: {', '.join(s['lane'] for s in r['stale'])}")
    if r.get("stalled"):
        out.append("ranked head not fetched: " + "; ".join(
            f"{s['lane']} #{s['lane_rank']} {s['name']} {s['in_state_days']:.0f}d ({s['reason']})"
            for s in r["stalled"]))
    if r.get("canary"):
        out.append(r["canary"])
    return out


def gather(conn, now: float, since: float, *, beat=None, gh=None, git=None, where=None, lanes=None,
           health=None, stalls=None, canary=None) -> dict:
    """`health` probes the headline's lane (lane_health), `canary` reads its receipts (canary.morning_line); None skips either."""
    r = {"lane": health(MODEL_LANE) if health else {"lane": MODEL_LANE, "generating": None, "why": "not probed"},
         "generated": now, "since": since, "sweep": sweep(conn, since, beat), "watchdog": watchdog(conn, since),
         "ci": ci(now, gh=gh or _gh), "ledger": ledger_row(conn, now), "stale": (lanes or stale_lanes)(conn),
         "stalled": (stalls or stalled)(conn), "deploy": deploy(where, git=git or _git),
         "canary": canary(now) if canary else "", "incidents": incidents(conn, since, now)}
    if r["sweep"]["loop"] is not None:
        from harness import heartbeat
        r["sweep"]["loop"]["code_moved"] = heartbeat.code_moved(beat, r["deploy"].get("head", ""))
    r["needs"] = needs(r)
    return r


def deterministic_headline(r: dict) -> str:
    if not r["needs"]:
        s = r["sweep"]
        return (f"Quiet night: {sum(s['screened'].values())} screened, {len(s['measured']['runs'])} measured, "
                f"{sum(s['settled']['verdicts'].values())} settled; nothing needs you.")
    head = r["needs"][:HEADLINE_LINES]
    more = len(r["needs"]) - len(head)
    return "\n".join(head) + (f"\n(+{more} more below)" if more > 0 else "")


def _ask(prompt: str) -> str:
    from harness import delegate
    held = delegate.busy()
    if held:
        raise delegate.Refused(f"the machine is busy with {held}; the morning report does not wait")
    return delegate.complete(MODEL_LANE, prompt, system=SYSTEM, max_tokens=MODEL_MAX_TOKENS,
                             timeout=MODEL_TIMEOUT_S, thinking=False)["text"]


def headline(r: dict, facts: str, ask=_ask) -> dict:
    """2-3 lines the local model condensed from the report; the deterministic lines when it refuses or fails."""
    fallback = deterministic_headline(r)
    if not r["needs"]:
        return {"text": fallback, "by": "deterministic", "why": "a quiet night needs no model"}
    if ask is None:
        return {"text": fallback, "by": "deterministic", "why": "model not asked"}
    if lane_dead(r):
        return {"text": fallback, "by": "deterministic", "why": f"the {MODEL_LANE} lane cannot generate"}
    prompt = (f"Things that need a person ({len(r['needs'])}):\n"
              + ("\n".join(f"- {n}" for n in r["needs"]) or "- none")
              + f"\n\nFull report:\n{facts}\n\nWrite the 2-3 line headline.")
    try:
        text = ask(prompt) or ""
    except Exception as exc:  # noqa: BLE001
        return {"text": fallback, "by": "deterministic", "why": f"{type(exc).__name__}: {exc}"[:300]}
    lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip()][:HEADLINE_LINES]
    got = "\n".join(lines)[:HEADLINE_CHARS]
    if not got:
        return {"text": fallback, "by": "deterministic", "why": "the model returned nothing"}
    return {"text": got, "by": "model", "why": ""}


def notify(r: dict, text: str, run=subprocess.run, platform: str | None = None) -> str | None:
    """A desktop notification when something needs a person (#818 path); None on a quiet night."""
    if not r["needs"]:
        return None
    from harness import watchdog as wd
    return wd.desktop(NOTIFY_TITLE, text, f"{len(r['needs'])} thing(s) need you", run=run,
                      platform=sys.platform if platform is None else platform)

