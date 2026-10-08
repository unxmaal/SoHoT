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
CHECKS = mc.INVARIANTS + SERVING + SCHEDULE


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
    from harness import usage
    return [f"sohot-{lane}: {s['error_rate']:.0%} of {s['requests']} requests failed"
            for lane, s in sorted(usage.real_use(conn).items())
            if s["requests"] >= MIN_REQUESTS and (s["error_rate"] or 0) > ERROR_RATE_MAX]


def _sweep_on_schedule() -> list:
    from harness import heartbeat
    late = heartbeat.overdue()
    return [late] if late else []


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
        have = mc.schema(conn)
    finally:
        conn.close()
    return {"source": str(path), "schema": have, "ok": all(c.ok for c in checks),
            "checks": [{"name": c.name, "ok": c.ok, "detail": c.detail} for c in checks]}


def report_text(got: dict) -> str:
    lines = [f"audit of {got['source']} (schema {got['schema']}, read-only)"]
    lines += [f"  {'ok  ' if c['ok'] else 'FAIL'} {c['name']}" + (f": {c['detail']}" if c["detail"] else "")
              for c in got["checks"]]
    lines.append("OK" if got["ok"] else "NOT OK")
    return "\n".join(lines)
