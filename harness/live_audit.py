"""`soh audit`: what a store must hold and what the gateway must serve, checked on the live store read-only. #492.

The store is opened with SQLite's mode=ro, so the audit can neither migrate nor
write it: an older store is reported, never upgraded. The checks are #478's
migration invariants, four about serving and one about the sweep schedule.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from harness import migration_check as mc

#: An alias needs this many requests in the window before its error rate says anything.
MIN_REQUESTS = 20
ERROR_RATE_MAX = 0.10

SERVING = ("adoptions_pass_here", "no_reference_served", "served_matches_adoption", "gateway_errors")
SCHEDULE = ("sweep_on_schedule",)
VERDICTS = ("too_big_ceiling_current", "too_big_names_variant", "terminal_reason_coherent", "no_ranking_verdict",
            "load_log_kept", "runner_gap_until_current", "broken_runner_layout")
CHECKS = mc.INVARIANTS + SERVING + SCHEDULE + VERDICTS


def open_readonly(path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"{Path(path).resolve().as_uri()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _adoptions_pass_here(conn) -> list:
    from harness import adopt
    ids = adopt.here(conn)
    if not ids:
        return ["this machine has no machines row, so nothing it serves was measured here"]
    marks = ",".join("?" * len(ids))
    bad = []
    for lane, row in sorted(adopt.current(conn).items()):
        # A by-hand adoption is judged by a person, so having run here is the bar.
        passed = "" if row["how"] == adopt.BY_HAND else "AND r.passed = 1"
        hit = conn.execute(
            f"SELECT 1 FROM results r JOIN runs x ON x.id = r.run_id WHERE r.candidate_id = ? "
            f"AND x.machine_id IN ({marks}) {passed} LIMIT 1", (row["candidate_id"], *ids)).fetchone()
        if hit is None:
            bad.append(f"{lane}: {row['spec']} has no {'passing ' if passed else ''}run on this machine")
    return bad


def _no_reference_served(conn, served: dict) -> list:
    from harness import adopt
    bad = [f"{r['lane']}: adoption {r['id']} names reference model {r['spec']}" for r in conn.execute(
        "SELECT a.id, a.lane, c.spec FROM adoptions a JOIN candidates c ON c.id = a.candidate_id ORDER BY a.id")
        if adopt.is_reference(r["spec"])]
    bad += [f"sohot-{lane} serves reference model {params.get('model')}"
            for lane, params in sorted(served.items()) if adopt.is_reference(str(params.get("model") or ""))]
    return bad


def _served_matches(served: dict, wanted: dict) -> list:
    from harness import gateway
    return [f"{gateway.LANE_ALIAS.format(lane)} serves {served.get(lane, {}).get('model')!r}, "
            f"the adoption is {wanted.get(lane, {}).get('model')!r}"
            for lane in sorted(set(served) | set(wanted))
            if served.get(lane, {}).get("model") != wanted.get(lane, {}).get("model")]


def _gateway_errors(conn) -> list:
    import time

    from harness import usage
    # Rates over a window the writer dropped rows from are not rates of real use. #700.
    out = usage.drop_warning(conn, time.time() - usage.parse_since(usage.DEFAULT_SINCE))
    for lane, s in sorted(usage.real_use(conn).items()):
        if s["requests"] < MIN_REQUESTS:
            continue
        if (s["error_rate"] or 0) > ERROR_RATE_MAX:
            out.append(f"sohot-{lane}: {s['error_rate']:.0%} of {s['requests']} requests failed in the model")
        if (s.get("gateway_error_rate") or 0) > ERROR_RATE_MAX:
            out.append(f"sohot-{lane}: the gateway or client refused {s['gateway_error_rate']:.0%} "
                       f"of {s['requests']} requests (rate limit, auth, budget or bad request)")
    return out


def _too_big_ceiling_current(conn, ceiling_gb: float | None = None, reopened_at=...) -> tuple[list, list]:
    """(failures, warnings) for too-big refusals judged under this machine's ceiling. #880, #904.
    The backlog is an inventory until a loop's requeue has run since it was decided; one that survives fails."""
    from harness import heartbeat, memory_store as ms
    here = ms.this_machine()["ceiling_gb"] if ceiling_gb is None else ceiling_gb
    swept = heartbeat.reopened_too_big() if reopened_at is ... else reopened_at
    stale = ms.stale_too_big(conn, here)
    survived = [r for r in stale if swept and float(r["decided_at"] or 0) < swept]
    fresh = [r for r in stale if r not in survived]

    def say(rows, what):
        named = ", ".join(f"{r['name']} ({r['ceiling_gb']:g} GiB)" for r in rows[:5])
        return [f"{len(rows)} too-big verdict(s) judged against a ceiling under this machine's "
                f"{here:g} GiB {what}, e.g. {named}"] if rows else []
    return (say(survived, f"survived the loop's requeue at {_when(swept)}"),
            say(fresh, "await the next loop's requeue"))


def _too_big_names_variant(conn, reopened_at=...) -> tuple[list, list]:
    """(failures, warnings) for too-big refusals sized by the listing's sum; one that survived a requeue fails. #947."""
    from harness import heartbeat, memory_store as ms
    swept = heartbeat.reopened_too_big() if reopened_at is ... else reopened_at
    rows = ms.sized_by_repo_total(conn)
    survived = [r for r in rows if swept and float(r["decided_at"] or 0) < swept]
    fresh = [r for r in rows if r not in survived]

    def say(group, what):
        return [f"{len(group)} too-big verdict(s) name no variant {what}, e.g. "
                + ", ".join(r["name"] for r in group[:5])] if group else []
    return (say(survived, f"after the loop's requeue at {_when(swept)}"),
            say(fresh, "and await the next loop's requeue"))


#: Reasons that name a fact outside the candidate, so the verdict needs a condition that can reopen it.
CONDITIONAL = ("runtime", "machine", "limit")


#: Incoherent rows the check started with (store of 2026-10-17); they warn until fixed, any other fails.
PINNED_INCOHERENT = frozenset({686, 687, 9143, 11513})


def _terminal_reason_coherent(conn, pinned=None) -> tuple[list, list]:
    """(failures, warnings): terminal state verdicts whose reason contradicts the outcome or nothing can reopen. #918."""
    pinned = PINNED_INCOHERENT if pinned is None else pinned
    bad, known = [], []
    for r in conn.execute(
            "SELECT v.id, p.name, p.state, v.reason, v.until, p.next_retest_at FROM proposals p "
            "JOIN verdicts v ON v.id = p.state_verdict_id "
            "WHERE p.state IN ('broken', 'declined', 'ignored') ORDER BY v.id"):
        if r["reason"] == "harness":
            why = "a harness fault holds a terminal state"
        elif r["state"] == "broken" and r["reason"] != "candidate":
            why = f"broken with reason {r['reason'] or 'empty'}"
        elif r["reason"] in CONDITIONAL and not r["until"] and r["next_retest_at"] is None:
            why = f"reason {r['reason']} with no until and no retest"
        else:
            continue
        (known if r["id"] in pinned else bad).append(f"verdict {r['id']} {r['name']}: {why}")
    return bad, known


def _no_ranking_verdict(conn) -> list:
    """Terminal states a parent's download ranking wrote, held at 0. #954."""
    from harness import memory_store as ms
    return [f"verdict {r['verdict_id']} {r['name']}: ignored because a parent stopped ranking it"
            for r in ms.unranked_terminal(conn)]


#: Held llama.cpp load failures decided before #953 kept the child's log; they warn until `soh load-log --apply`.
PINNED_UNKEPT = frozenset({9144, 9289})


def _load_log_kept(conn, pinned=None) -> tuple[list, list]:
    """(failures, warnings): held llama.cpp runtime verdicts whose run directory has no server-load.log. #953."""
    from harness import load_log
    pinned = PINNED_UNKEPT if pinned is None else pinned
    bad, known = [], []
    for r in load_log.unkept(conn):
        (known if r["id"] in pinned else bad).append(
            f"verdict {r['id']} {r['name']}: no {load_log.FILE} in {r['dir'] or 'any run directory'}")
    return bad, known


def _runner_gap_until_current(conn) -> list:
    """Live screen runtime declines whose until is not what their detail and card name: a release that cannot help. #950."""
    from harness.memory_store.revisit import runner_gap_rewrites
    return [f"verdict {r['id']} {r['name']}: {r['until']}, its cause names {r['new']}"
            for r in runner_gap_rewrites(conn)]


def _broken_runner_layout(conn) -> list:
    """Live broken screens whose runner could not open the repo's layout: a runner gap written as a verdict. #951."""
    from harness import reasons
    return [f"verdict {r['id']} {r['name']}: {reasons.LOAD_FAILED_LAYOUT} recorded broken"
            for r in conn.execute(
                "SELECT v.id, p.name, v.detail, coalesce(c.spec, p.name) AS spec FROM proposals p "
                "JOIN verdicts v ON v.id = p.state_verdict_id LEFT JOIN candidates c ON c.id = v.candidate_id "
                "WHERE p.state = 'broken' AND v.tier = 'screen' ORDER BY v.id")
            if reasons.classify(r["detail"] or "", reasons.RUNNER, r["spec"]) == reasons.LOAD_FAILED_LAYOUT]


def _when(at) -> str:
    import time
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(at)) if at else "never"


def _sweep_on_schedule() -> list:
    from harness import heartbeat
    late = heartbeat.overdue()
    return [late] if late else []


#: How far back the audit looks for requests a serving node handed to this machine. #739.
FALLBACK_WINDOW_S = 3600.0


def node_fallbacks(conn, config=None, now=None) -> list[dict]:
    """{node, requests, aliases} per node whose requests this machine answered in the window."""
    import time

    from harness import gateway, nodes
    now = time.time() if now is None else now
    path = gateway.served_path(config)
    entries = {str(e.get("model_name", "")): e for e in (gateway.load(path) if path.exists() else {})
               .get("model_list") or []}
    by: dict = {}
    for r in conn.execute("SELECT alias FROM gateway_requests WHERE at >= ? AND alias LIKE ?",
                          (now - FALLBACK_WINDOW_S, f"%{nodes.LOCAL_SUFFIX}")):
        asked = r["alias"].removesuffix(nodes.LOCAL_SUFFIX)
        node = str(entries.get(asked, {}).get(nodes.NODE_KEY) or "an unlisted node")
        got = by.setdefault(node, {"node": node, "requests": 0, "aliases": set()})
        got["requests"] += 1
        got["aliases"].add(asked)
    return [{**v, "aliases": sorted(v["aliases"])} for _, v in sorted(by.items())]


def serving(conn, config=None) -> tuple[dict, dict]:
    """(what the served config's sohot-<lane> aliases name, what the adoptions say they should)."""
    from harness import adopt, gateway
    from harness.gateway_switch import _aliases
    path = gateway.served_path(config)
    served = _aliases(gateway.load(path)) if path.exists() else {}
    wanted = _aliases(gateway.served(config, adopt.lane_defaults(conn)))
    return served, wanted


def audit(path=None, config=None) -> dict:
    """Every check on the store at `path` (default: this home's), opened read-only."""
    from harness import memory_store as ms, store
    if store.backend() != store.SQLITE:
        raise RuntimeError("soh audit reads a SQLite store; this home uses another backend")
    path = Path(path if path is not None else ms.db_path())
    if not path.is_file():
        raise FileNotFoundError(f"no store at {path}")
    conn = open_readonly(path)
    try:
        with ms.lend(conn):
            served, wanted = serving(conn, config)
        checks = mc.invariants(conn) + [
            mc._check("adoptions_pass_here", _adoptions_pass_here(conn)),
            mc._check("no_reference_served", _no_reference_served(conn, served)),
            mc._check("served_matches_adoption", _served_matches(served, wanted)),
            mc._check("gateway_errors", _gateway_errors(conn)),
            mc._check("sweep_on_schedule", _sweep_on_schedule()),
        ]
        stale, backlog = _too_big_ceiling_current(conn)
        checks.append(mc._check("too_big_ceiling_current", stale))
        summed, unswept = _too_big_names_variant(conn)
        checks.append(mc._check("too_big_names_variant", summed))
        incoherent, pinned = _terminal_reason_coherent(conn)
        checks.append(mc._check("terminal_reason_coherent", incoherent))
        checks.append(mc._check("no_ranking_verdict", _no_ranking_verdict(conn)))
        unkept, waiting = _load_log_kept(conn)
        checks.append(mc._check("load_log_kept", unkept))
        checks.append(mc._check("runner_gap_until_current", _runner_gap_until_current(conn)))
        checks.append(mc._check("broken_runner_layout", _broken_runner_layout(conn)))
        warnings = {"too_big_ceiling_current": mc._say(backlog)} if backlog and not stale else {}
        if unswept and not summed:
            warnings["too_big_names_variant"] = mc._say(unswept)
        if pinned and not incoherent:
            warnings["terminal_reason_coherent"] = "pinned, awaiting a fix: " + mc._say(pinned)
        if waiting and not unkept:
            warnings["load_log_kept"] = "pinned, awaiting soh load-log --apply: " + mc._say(waiting)
        have = mc.schema(conn)
        bound = _binding(conn)
        fell = node_fallbacks(conn, config)
    finally:
        conn.close()
    return {"source": str(path), "schema": have, "ok": all(c.ok for c in checks),
            "checks": [{"name": c.name, "ok": c.ok, "detail": c.detail or warnings.get(c.name, ""),
                        "warn": c.name in warnings} for c in checks],
            "binding": bound, "fallbacks": fell}


def _binding(conn) -> list[dict]:
    """Knobs this machine's recent runs keep hitting; reported, never a failed check. #636."""
    from harness import binding, memory_store as ms
    mid = ms.machine_row(conn)
    return binding.binding(binding.count(conn, machines=[mid] if mid is not None else []))


def report_text(got: dict) -> str:
    lines = [f"audit of {got['source']} (schema {got['schema']}, read-only)"]
    lines += [f"  {'FAIL' if not c['ok'] else 'warn' if c.get('warn') else 'ok  '} {c['name']}" + (f": {c['detail']}" if c["detail"] else "")
              for c in got["checks"]]
    if "binding" in got:
        from harness import binding
        lines.append("binding knobs:")
        lines.append(binding.render(got["binding"]))
    if "fallbacks" in got:
        lines.append("node fallbacks in the last hour:" + ("" if got["fallbacks"] else " none"))
        lines += [f"  node {f['node']}: {f['requests']} request(s) answered here instead "
                  f"({', '.join(f['aliases'])})" for f in got["fallbacks"]]
    lines.append("OK" if got["ok"] else "NOT OK")
    return "\n".join(lines)
