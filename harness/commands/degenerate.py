"""`soh degenerate fit|redecide`: fit the #955 threshold on labelled rows, and re-decide budget-limit screens."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from harness import degenerate as dg
from harness import reasons
from harness.commands.common import emit, err, note

#: The store state verdicts a reclassified row can change.
HELD = ("SELECT v.id, v.proposal_id, p.name, v.outcome, v.reason, v.until, v.run_id, v.candidate_id, "
        "r.path, r.lane FROM proposals p JOIN verdicts v ON v.id = p.state_verdict_id "
        "JOIN runs r ON r.id = v.run_id WHERE v.tier = 'screen' AND v.until LIKE 'limit:max\\_tokens%' "
        "ESCAPE '\\' ORDER BY v.id")


def _results(path: Path) -> dict | None:
    try:
        with open(path / "results.json", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def reclassed(rows: list[dict], lane: str) -> list[dict]:
    """The rows as today's runner would class them: a budget-cut code reply that loops is degenerate."""
    out = []
    for r in rows:
        if (not r.get("passed") and r.get("failure_class") == reasons.TOKEN_BUDGET_EXHAUSTED
                and lane in dg.LANES):
            got = dg.measure(r.get("output") or "")
            if dg.is_degenerate(got):
                r = {**r, "failure_class": reasons.DEGENERATE, "limit": "",
                     "metrics": {**(r.get("metrics") or {}), **got}}
        out.append(r)
    return out


def resummed(summary: dict, rows: list[dict]) -> dict:
    """The stored summary with failure_classes and limits recounted from `rows`."""
    out = {}
    for key, v in summary.items():
        mine = [r for r in rows if r.get("candidate") == key and not r.get("passed")]
        out[key] = {**v, "failure_classes": dict(Counter(r["failure_class"] for r in mine if r.get("failure_class"))),
                    "limits": sorted({r["limit"] for r in mine if r.get("limit")})}
    return out


def changes(conn, root: Path | None = None) -> list[dict]:
    """Each held screen verdict on a max_tokens limit that its degenerate rows, reclassed, decide differently."""
    from harness import runs, screen
    found = []
    for v in conn.execute(HELD).fetchall():
        path = (Path(root) / v["path"]) if root else runs.run_dir(v["path"])
        stored = _results(path)
        base = {"verdict_id": v["id"], "name": v["name"], "run": v["path"],
                "was": [v["outcome"], v["reason"], v["until"]]}
        if not stored or len(stored.get("summary") or {}) != 1:
            found.append({**base, "skipped": "no results.json with one candidate's summary"})
            continue
        rows = stored.get("rows") or []
        before = screen.outcome(0, resummed(stored["summary"], rows))
        got = screen.outcome(0, resummed(stored["summary"], reclassed(rows, v["lane"])))
        now = [got.outcome, got.reason, got.until]
        # Only what the reclassification moves; other rule changes since the verdict are not this one's. #955.
        if now != [before.outcome, before.reason, before.until] and now != base["was"]:
            found.append({**base, "now": now, "detail": got.detail, "proposal_id": v["proposal_id"],
                          "run_id": v["run_id"], "candidate_id": v["candidate_id"]})
    return found


def apply(conn, found: list[dict]) -> list[int]:
    """Write each changed verdict through the one state writer; returns the new verdict ids."""
    from harness import memory_store as ms
    ids = []
    for c in found:
        if "now" not in c:
            continue
        outcome, reason, until = c["now"]
        ids.append(ms.decide(conn, c["name"], outcome, tier=ms.SCREEN, run_id=c["run_id"],
                             detail=f"re-decided from its stored rows (#955): {c['detail']}"[:600],
                             reason=reason, until=until, candidate_id=c["candidate_id"]))
    conn.commit()
    return ids


def scan(root: Path) -> tuple[list[dict], list[dict]]:
    """(budget-cut code rows with visible output, passing rows over MIN_CHARS) from every results.json under root."""
    cut, ok = [], []
    for p in sorted(Path(root).glob("*/results.json")):
        stored = _results(p.parent)
        if not isinstance(stored, dict):
            continue
        lane = (stored.get("receipt") or {}).get("modality", "")
        for r in stored.get("rows") or []:
            text = r.get("output") if isinstance(r.get("output"), str) else ""
            row = {"run": p.parent.name, "candidate": r.get("candidate"), "case_id": r.get("case_id"),
                   "tail": text[-dg.TAIL_CHARS:]}
            if r.get("failure_class") == reasons.TOKEN_BUDGET_EXHAUSTED and text and lane in dg.LANES:
                cut.append(row)
            elif r.get("passed") and len(text) >= dg.MIN_CHARS:
                ok.append({**row, "label": dg.NATURAL})
    return cut, ok


def _ids(rows: list[dict]) -> list[dict]:
    return [{k: r[k] for k in ("run", "candidate", "case_id")} for r in rows]


def _fit(a) -> int:
    labelled = dg.load(Path(a.rows) if a.rows else dg.ROWS)
    fitted = dg.fit(labelled)
    wrong = dg.agreement(labelled)
    note(f"{fitted['counts']} labelled rows; repeat >= {dg.REPEAT_SHARE} (fit {fitted['repeat']}, margin "
         f"{fitted['repeat_margin']}: others max {fitted['repeat_range']['other_max']}, loops min "
         f"{fitted['repeat_range']['degenerate_min']}); entropy <= {dg.ENTROPY_BITS} (fit {fitted['entropy']}, "
         f"margin {fitted['entropy_margin']}: others min {fitted['entropy_range']['other_min']}, degenerate max "
         f"{fitted['entropy_range']['degenerate_max']}); {len(wrong)} disagree with their label")
    unlabelled, near, flagged = [], [], []
    if a.runs:
        known = {(r["run"], r["case_id"], r["candidate"]) for r in labelled}
        cut, ok = scan(Path(a.runs))
        unlabelled = [r for r in cut if (r["run"], r["case_id"], r["candidate"]) not in known]
        near = [r for r in unlabelled + ok if dg.inside_margin(dg.measure(r["tail"]), fitted)]
        flagged = [r for r in ok if dg.is_degenerate(dg.measure(r["tail"]))]
        note(f"{a.runs}: {len(cut)} budget-cut code rows ({len(unlabelled)} unlabelled), {len(ok)} passing rows; "
             f"{len(near)} inside the margin, {len(flagged)} passing rows read as degenerate")
    good = not wrong and not near and not flagged
    emit(good, fitted=fitted, repeat=dg.REPEAT_SHARE, entropy=dg.ENTROPY_BITS, disagree=wrong,
         unlabelled=_ids(unlabelled), inside_margin=_ids(near), passing_flagged=_ids(flagged))
    return 0 if good else 1


def _redecide(a) -> int:
    import sqlite3

    from harness import live_audit
    from harness import memory_store as ms
    db = Path(a.db) if a.db else ms.db_path()
    if not db.is_file():
        return err(f"degenerate redecide: no store at {db}")
    try:
        conn = ms.connect(db) if a.apply else live_audit.open_readonly(db)
    except (OSError, sqlite3.Error, RuntimeError) as exc:
        return err(f"degenerate redecide: {exc}")
    try:
        found = changes(conn, Path(a.runs) if a.runs else None)
        ids = apply(conn, found) if a.apply else []
    finally:
        conn.close()
    for c in found:
        note(f"  {c['verdict_id']} {c['name']} ({c['run']}): {' / '.join(c['was'])} -> "
             f"{' / '.join(c['now']) if 'now' in c else c['skipped']}")
    note(f"{sum('now' in c for c in found)} verdict(s) decide differently from their stored rows"
         + (f"; wrote {ids}" if a.apply else "; --apply writes them"))
    emit(True, changes=found, written=ids)
    return 0


def cmd_degenerate(a) -> int:
    try:
        return _fit(a) if a.action == "fit" else _redecide(a)
    except (OSError, ValueError) as exc:
        return err(f"degenerate {a.action}: {exc}")
