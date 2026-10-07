"""Re-run each wanted lane's served model when its runtime moves, when it ages, or when real use regresses. #480, #486.

A served model is measured once, at adoption. This queues a normal job to run it
again, reads the run that job stores, and flags the lane when it failed or lost
to its last pass beyond the paired noise. It never changes what a lane serves.
"""
from __future__ import annotations

import json
import re
import time
from collections import Counter

from harness import lanes as L

#: Days without a passing run before a served model is due again; per lane in meta.
DEFAULT_DAYS = 7.0
DAYS_KEY = "reverify_days:{}"
REQUESTED_BY = "reverify"
#: Below the default 0, so anything a person queued runs first.
PRIORITY = -10

VERSIONS, AGE, USAGE = "versions", "age", "usage"
PASSED, FAILED, REGRESSED, CANCELLED = "passed", "failed", "regressed", "cancelled"
#: The harness could not deliver the re-run: flagged, but never a verdict on the model. #408.
UNRUN = "unrun"
FLAGGED = (FAILED, REGRESSED, UNRUN)

_TEXT_MLX = ("mlx", "mlx-lm", "litellm")
_TEXT_LLAMA = ("llama.cpp", "litellm")
_TEXT_VLLM = ("vllm-mlx", "vllm-metal", "vllm", "litellm")
#: Runtimes each non-text lane runs through; text lanes ask serving.engine_for.
_LANE_RUNTIMES = {"video": ("diffusers", "torch"), "music": ("ace-step", "torch"),
                  "tts": ("mlx-audio", "mlx"), "stt": ("mlx-audio", "mlx")}
_MACOS = re.compile(r"macOS-(\d+(?:\.\d+)*)")


def days_for(conn, lane: str) -> float:
    got = conn.execute("SELECT value FROM meta WHERE key = ?",
                       (DAYS_KEY.format(L.canonical(lane)),)).fetchone()
    try:
        return float(got[0]) if got else DEFAULT_DAYS
    except (TypeError, ValueError):
        return DEFAULT_DAYS


def set_days(conn, lane: str, days: float) -> None:
    if float(days) <= 0:
        raise ValueError("the threshold is a number of days above 0")
    conn.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)",
                 (DAYS_KEY.format(L.canonical(lane)), str(float(days))))
    conn.commit()


def runtimes_for(lane: str, spec: str) -> tuple[str, ...]:
    """The version keys whose change can change what this lane's spec does."""
    lane = L.canonical(lane)
    if lane == "image":
        got = ("mflux", "mlx") if spec.startswith("mflux:") else ("diffusers", "torch")
    elif lane in _LANE_RUNTIMES:
        got = _LANE_RUNTIMES[lane]
    elif lane not in (*L.TEXT_SERVED, "decide"):
        from harness import machine
        got = (*machine.WATCHED, "llama.cpp")
    else:
        from harness import serving
        try:
            engine = serving.engine_for(spec)
        except Exception:  # noqa: BLE001
            engine = ""
        got = (_TEXT_LLAMA if engine == serving.LLAMACPP else
               _TEXT_VLLM if engine in serving.VLLM_ENGINES else _TEXT_MLX)
    return (*got, "macos")


def _macos(text) -> str:
    m = _MACOS.search(str(text or ""))
    return m.group(1) if m else ""


def versions_now(facts: dict) -> dict:
    """This machine's runtime versions as machines.versions records them, plus macOS."""
    got = {k: str(v) for k, v in (facts.get("versions") or {}).items() if v}
    mac = _macos(facts.get("os"))
    if mac:
        got["macos"] = mac
    return got


def versions_of(run: dict) -> dict:
    """The versions a stored run's environment recorded."""
    try:
        env = json.loads(run.get("environment") or "{}")
    except ValueError:
        env = {}
    got = {k: str(v) for k, v in (env.get("versions") or {}).items() if v}
    mac = str(env.get("macos") or "") or _macos(env.get("os"))
    if mac:
        got["macos"] = mac
    return got


def moved(before: dict, after: dict, keys) -> list[str]:
    """'pkg old -> new' per watched key both sides recorded and that differs."""
    return [f"{k} {before[k]} -> {after[k]}" for k in keys
            if before.get(k) and after.get(k) and before[k] != after[k]]


def served(conn) -> dict[str, dict]:
    """lane -> what each wanted, unparked lane serves here, with any incumbent to re-run beside it."""
    from harness import adopt, candidates, report, winners
    typed = winners.typed()
    held = adopt.current(conn)
    out = {}
    for lane in L.WANTED:
        if L.parked(lane)[0]:
            continue
        row = held.get(lane) or {}
        spec = row.get("spec") or typed.get(lane, "")
        if not spec:
            continue
        cid = row.get("candidate_id") or report._candidate_of(conn, lane, spec)
        incumbent = ""
        if row.get("how") == adopt.MEASURED and row.get("incumbent_id"):
            inc = conn.execute("SELECT spec FROM candidates WHERE id = ?",
                               (row["incumbent_id"],)).fetchone()
            if inc and inc["spec"] != spec and not adopt.is_reference(inc["spec"]):
                incumbent = inc["spec"]
        from harness import screen
        run_spec = row.get("spec") or screen.candidate_for(lane, spec) or spec
        out[lane] = {"lane": lane, "spec": run_spec, "candidate_id": cid,
                     "incumbent": incumbent,
                     "incumbent_id": (candidates.get(conn, incumbent) or {}).get("id")
                     if incumbent else None}
    return out


def _flagged_runs(conn) -> set[int]:
    return {r["run_id"] for r in conn.execute(
        "SELECT run_id FROM reverifications WHERE run_id IS NOT NULL AND outcome IN "
        f"({','.join('?' * len(FLAGGED))})", FLAGGED)}


def baseline(conn, lane: str, cid, machines) -> dict | None:
    """The newest run here in which the served candidate passed a case and was not flagged."""
    from harness import runs
    if cid is None:
        return None
    skip = _flagged_runs(conn)
    for run in runs.find(conn, lane=lane, tier=runs.MEASURE, machines=machines,
                         candidate_id=cid):
        if run["id"] in skip or run.get("generated_at") is None:
            continue
        if any(r["passed"] for r in runs.rows(conn, run["id"], cid)):
            return run
    return None


def _same(cid) -> tuple[str, tuple]:
    return ("candidate_id IS NULL", ()) if cid is None else ("candidate_id = ?", (cid,))


def _latest(conn, lane: str, cid, settled: bool = False) -> dict | None:
    same, args = _same(cid)
    done = " AND outcome != ''" if settled else ""
    row = conn.execute(f"SELECT * FROM reverifications WHERE lane = ? AND {same}{done} "
                       "ORDER BY id DESC LIMIT 1", (lane, *args)).fetchone()
    return dict(row) if row else None


def _usage_trigger(conn, lane: str, now: float) -> tuple[str, float] | None:
    """(warning, switched_at) when real use regressed after the lane's newest switch. #481."""
    from harness import usage
    try:
        comps = usage.around_switches(conn, lane=lane, now=now)
    except Exception:  # noqa: BLE001
        return None
    if not comps:
        return None
    warn = usage.regressions(comps[-1:])
    return (warn[0], comps[-1]["switch"]["switched_at"]) if warn else None


def triggers(conn, item: dict, *, now: float, current: dict, machines) -> tuple[list, dict | None]:
    """[[kind, why], ...] for one lane, and the baseline run they were read against."""
    lane, cid = item["lane"], item["candidate_id"]
    base = baseline(conn, lane, cid, machines)
    out = []
    if base is not None:
        changed = moved(versions_of(base), current, runtimes_for(lane, item["spec"]))
        out += [[VERSIONS, why] for why in changed]
    days = days_for(conn, lane)
    if base is None:
        out.append([AGE, "no passing run on this machine"])
    else:
        age = (now - base["generated_at"]) / 86400.0
        if age > days:
            out.append([AGE, f"last passed {age:.0f} days ago"])
    use = _usage_trigger(conn, lane, now)
    if use is not None:
        last = _latest(conn, lane, cid)
        if not last or last["queued_at"] < use[1]:
            out.append([USAGE, use[0]])
    return out, base


def _skip(conn, item: dict, found: list, now: float) -> str:
    last = _latest(conn, item["lane"], item["candidate_id"])
    if last and not last["outcome"]:
        return f"already queued as job {last['job_id'] or '(gone)'}"
    if not found:
        return "nothing moved"
    if last and last["outcome"] in FLAGGED and \
            now - (last["settled_at"] or 0) < days_for(conn, item["lane"]) * 86400.0:
        return f"flagged {last['outcome']}: {last['detail']}; waiting for a person"
    return ""


def argv(item: dict) -> list[str]:
    """The evals.run command the job runs: the served spec, and its incumbent when there is one."""
    from harness import screen
    specs = [item["spec"]] + ([item["incumbent"]] if item["incumbent"] else [])
    out = ["uv", "run", "python", "-m", "evals.run", "--modality", item["lane"],
           "--candidates", ",".join(specs)]
    route = screen.routed_gateway(item["spec"])
    if route:
        out += ["--gateway", route]
    return out


def plan(conn, *, now: float, facts: dict, lane: str = "") -> list[dict]:
    """Every participating lane with its triggers and why it would not be queued."""
    from harness import runs
    want = L.canonical(lane)
    machines = runs.here(conn)
    current = versions_now(facts)
    out = []
    for name, item in served(conn).items():
        if want and name != want:
            continue
        found, base = triggers(conn, item, now=now, current=current, machines=machines)
        out.append({**item, "triggers": found, "skip": _skip(conn, item, found, now),
                    "baseline_run_id": base["id"] if base else None,
                    "last_pass_days": None if base is None
                    else round((now - base["generated_at"]) / 86400.0, 1),
                    "days": days_for(conn, name), "argv": argv(item)})
    return out


def _queue(conn, entry: dict, now: float, add) -> dict:
    from harness import memory_store as ms, paths
    job = add(entry["argv"], title=f"reverify {entry['lane']}: {entry['spec']}",
              cwd=str(paths.REPO), priority=PRIORITY, requested_by=REQUESTED_BY,
              conn=conn)
    conn.execute(
        "INSERT INTO reverifications (lane, candidate_id, spec, incumbent, triggers, "
        "job_id, baseline_run_id, machine_id, queued_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (entry["lane"], entry["candidate_id"], entry["spec"], entry["incumbent"],
         json.dumps(entry["triggers"]), int(job["id"]), entry["baseline_run_id"],
         ms.machine_row(conn), now))
    conn.commit()
    return {**entry, "job": job["id"]}


def _paired(before: list[dict], after: list[dict]):
    """The served candidate against itself across two runs, cell by case and repeat."""
    from harness import paired

    def cells(rows):
        seen: Counter = Counter()
        out = {}
        for r in rows:
            seen[r["case_id"]] += 1
            out[(r["case_id"], seen[r["case_id"]])] = r
        return out
    a, b = cells(before), cells(after)
    keys = a.keys() & b.keys()
    lost = [k for k in keys if a[k]["passed"] and not b[k]["passed"]]
    gained = sum(1 for k in keys if not a[k]["passed"] and b[k]["passed"])
    cell = paired.Cell("", len(lost), gained, len(keys) - len(lost) - gained)
    return cell, [b[k] for k in lost]


def _class_of(rows: list[dict]) -> str:
    got = Counter(r.get("failure_class") or "" for r in rows if not r["passed"])
    got.pop("", None)
    return got.most_common(1)[0][0] if got else ""


def _reason(cls: str) -> str:
    from harness import reasons
    return reasons.CLASSES.get(cls, ("", reasons.CANDIDATE))[1]


def judge(conn, rv: dict, job: dict | None) -> tuple[str, str, str, str, int | None]:
    """(outcome, reason, failure_class, detail, run_id) for one finished re-run."""
    from harness import adopt, paired, reasons, runs
    if job is None:
        return CANCELLED, reasons.HARNESS, "", "the job was cancelled before it ran", None
    run = conn.execute("SELECT * FROM runs WHERE job_id = ? ORDER BY id DESC LIMIT 1",
                       (job["id"],)).fetchone()
    if run is None:
        return (UNRUN, reasons.HARNESS, "",
                f"job {job['id']} {job['state']} rc={job['rc']} and stored no run", None)
    rid = run["id"]
    mine = runs.rows(conn, rid, rv["candidate_id"])
    if not mine:
        return UNRUN, reasons.HARNESS, "", f"run {rid} has no row for {rv['spec']}", rid
    if not any(r["passed"] for r in mine):
        cls = _class_of(mine)
        why = _reason(cls)
        return (UNRUN if why == reasons.HARNESS else FAILED, why, cls,
                f"{rv['spec']} passed 0 of {len(mine)} in run {rid}", rid)
    if rv["baseline_run_id"]:
        before = runs.rows(conn, rv["baseline_run_id"], rv["candidate_id"])
        cell, lost = _paired(before, mine)
        if cell.lost > cell.gained and cell.p <= adopt.ALPHA:
            cls = _class_of(lost)
            return (REGRESSED, _reason(cls), cls,
                    f"{rv['spec']} {cell.lost} lost against {cell.gained} gained vs run "
                    f"{rv['baseline_run_id']}, p={cell.p:.3f}", rid)
    inc = conn.execute("SELECT id FROM candidates WHERE spec = ?",
                       (rv["incumbent"],)).fetchone() if rv["incumbent"] else None
    theirs = runs.rows(conn, rid, inc["id"]) if inc else []
    if theirs:
        key_s, key_i = mine[0]["candidate"], theirs[0]["candidate"]
        cell = paired.head_to_head(mine + theirs, key_s, key_i)
        if cell.gained > cell.lost and cell.p <= adopt.ALPHA:
            return (REGRESSED, reasons.CANDIDATE, "",
                    f"the incumbent {rv['incumbent']} now beats {rv['spec']}, "
                    f"{cell.gained} gained against {cell.lost} lost, p={cell.p:.3f}", rid)
    passed = sum(r["passed"] for r in mine)
    return PASSED, reasons.CANDIDATE, "", f"{rv['spec']} passed {passed} of {len(mine)}", rid


def settle(conn, *, now: float, write: bool = True) -> list[dict]:
    """Judge every queued re-run whose job is no longer pending or running."""
    from harness import workqueue as wq
    out = []
    for r in conn.execute("SELECT * FROM reverifications WHERE outcome = '' ORDER BY id").fetchall():
        rv = dict(r)
        job = wq.get(rv["job_id"], conn=conn) if rv["job_id"] is not None else None
        if job is not None and job["state"] in (wq.PENDING, wq.RUNNING):
            continue
        outcome, reason, cls, detail, rid = judge(conn, rv, job)
        if write:
            conn.execute("UPDATE reverifications SET outcome = ?, reason = ?, "
                         "failure_class = ?, detail = ?, run_id = ?, settled_at = ? "
                         "WHERE id = ?", (outcome, reason, cls, detail[:300], rid, now, rv["id"]))
        out.append({"id": rv["id"], "lane": rv["lane"], "spec": rv["spec"],
                    "outcome": outcome, "reason": reason, "failure_class": cls,
                    "detail": detail, "run_id": rid})
    if write:
        conn.commit()
    return out


def flags(conn) -> dict[str, dict]:
    """lane -> its newest settled re-run, for lanes whose served model it failed or regressed."""
    found = served(conn)
    out = {}
    for lane, item in found.items():
        row = _latest(conn, lane, item["candidate_id"], settled=True)
        if row and row["outcome"] in FLAGGED:
            out[lane] = row
    return out


def check(conn, *, now: float | None = None, facts: dict | None = None, lane: str = "",
          dry_run: bool = False, add=None) -> dict:
    """Settle finished re-runs, then queue one for each lane a trigger fired on."""
    from harness import memory_store as ms
    from harness import workqueue as wq
    now = time.time() if now is None else now
    facts = facts if facts is not None else ms.this_machine()
    if not dry_run:
        ms.remember_machine(conn, facts)
    settled = settle(conn, now=now, write=not dry_run)
    planned = plan(conn, now=now, facts=facts, lane=lane)
    queued = []
    if not dry_run:
        for entry in planned:
            if entry["triggers"] and not entry["skip"]:
                queued.append(_queue(conn, entry, now, add or wq.add))
    return {"settled": settled, "planned": planned, "queued": queued, "dry_run": dry_run}
