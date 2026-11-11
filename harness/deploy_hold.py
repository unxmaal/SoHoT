"""A sha rolled back on audit checks that would read unchanged inputs is held, not retried. #1805."""
from __future__ import annotations

import json
import re

# Stdlib only at import: deploy_switch runs it under the base interpreter with -I (#1610).

#: An audit check's failing line as live_audit.report_text prints it; smoke's `FAIL  x` lines do not match.
FAIL_LINE = re.compile(r"^  FAIL (\w+)(?::\s*(.*))?$")
VERDICT = re.compile(r"\bverdict (\d+)\b")
#: Machine columns that move on every connect, not a fact an until is judged by.
VOLATILE = ("first_seen", "last_seen")


def failed(text: str) -> dict:
    """{check: [verdict ids its FAIL lines name]} for every audit check that failed in text."""
    out: dict = {}
    for line in text.splitlines():
        m = FAIL_LINE.match(line)
        if m:
            ids = out.setdefault(m.group(1), [])
            ids += [int(v) for v in VERDICT.findall(m.group(2) or "") if int(v) not in ids]
    return out


def _norm(v):
    return json.loads(json.dumps(v, sort_keys=True, default=str))


def inputs(conn, checks: dict, data=...) -> dict | None:
    """What each failing check reads, as it stands now; None when one is a check whose inputs are not known here."""
    from harness import heartbeat, live_audit
    from harness import memory_store as ms
    if not checks or any(c not in live_audit.VERDICTS for c in checks):
        return None
    data = (heartbeat.read() if data is ... else data) or {}
    mid = ms.machine_row(conn)
    facts = {k: v for k, v in (ms.recorded_facts(conn, mid) if mid is not None else {}).items() if k not in VOLATILE}
    upto = conn.execute("SELECT MAX(id) FROM verdicts").fetchone()[0]
    out = {}
    for check, ids in sorted(checks.items()):
        key = live_audit.REPAIRED_BY.get(check)
        held = {}
        if ids:
            marks = ",".join("?" * len(ids))
            held = {str(r[0]): r[1] for r in conn.execute(
                f"SELECT v.id, p.state_verdict_id FROM verdicts v LEFT JOIN proposals p ON p.id = v.proposal_id "
                f"WHERE v.id IN ({marks})", [int(i) for i in ids]).fetchall()}
        # A check no loop step repairs is cleared by whatever writes the next verdict.
        out[check] = {"repair": data.get(key) if key else None, "upto": None if key else upto,
                      "met": data.get(heartbeat.REVISIT_MET), "cases": data.get(heartbeat.REVISIT_CASES),
                      "verdicts": held, "facts": facts}
    return _norm(out)


def held(conn, job_id, rec: dict | None = None, data=...) -> dict | None:
    """The hold on a failed deploy job: its rollback failed audit checks whose inputs have not changed since; else None."""
    from harness import deploy
    if rec is None:
        row = conn.execute("SELECT id FROM deploys WHERE job_id = ?", (int(job_id),)).fetchone()
        rec = deploy._read(deploy.record_path(row[0])) if row else {}
    was = rec.get("held_inputs")
    if rec.get("outcome") != deploy.ROLLED_BACK or not was:
        return None
    if inputs(conn, rec.get("audit_failed") or {}, data) != was:
        return None
    checks = ", ".join(sorted(was))
    return {"deploy": rec.get("id"), "job": job_id, "checks": checks,
            "why": (f"held: deploy {rec.get('id')} rolled back on audit check(s) {checks}, and what they read has not "
                    f"changed since; waiting for a newer sha or that change (soh deploy now deploys it anyway)")}
