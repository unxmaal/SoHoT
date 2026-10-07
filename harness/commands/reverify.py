"""`soh reverify`: re-run served models whose runtime moved, that aged, or whose real use regressed. #480, #486."""
from __future__ import annotations

from harness.commands.common import emit, err, note


def _line(e: dict) -> str:
    why = "; ".join(f"{k}: {w}" for k, w in e["triggers"]) or "no trigger"
    last = "never passed here" if e["last_pass_days"] is None \
        else f"last pass {e['last_pass_days']:g}d ago"
    state = e["skip"] or "queue"
    return f"  {e['lane']:7} {e['spec'][:36]:36} {last:22} [{state}]\n           {why}"


def report(got: dict) -> None:
    """Print what a check settled, found and queued."""
    for s in got["settled"]:
        note(f"  settled {s['lane']} {s['spec']}: {s['outcome']} ({s['reason']}"
             f"{', ' + s['failure_class'] if s['failure_class'] else ''}): {s['detail']}")
    for e in got["planned"]:
        note(_line(e))
    dry = got.get("dry_run", False)
    verb = "would queue" if dry else "queued"
    note(f"  {verb} {sum(1 for e in got['planned'] if e['triggers'] and not e['skip'])}"
         f" re-run(s)" + ("" if dry else
                          "".join(f"\n    job {q['job']}: {q['lane']}" for q in got["queued"])))


def cmd_reverify(a) -> int:
    """Evaluate the triggers and queue re-runs, or with --dry-run only say what it would."""
    from harness import reverify
    from harness import memory_store as ms

    lane = (a.lane or "").strip().lower()
    if a.days is not None and not lane:
        return err("--days sets one lane's threshold: soh reverify --lane code --days 3")
    conn = ms.connect()
    try:
        if a.days is not None:
            try:
                reverify.set_days(conn, lane, a.days)
            except ValueError as exc:
                return err(str(exc))
            note(f"{lane}: due again after {a.days:g} days without a passing run")
            emit(lane=lane, days=float(a.days))
            return 0
        got = reverify.check(conn, lane=lane, dry_run=a.dry_run)
        flags = reverify.flags(conn)
    finally:
        conn.close()
    report(got)
    for name, row in sorted(flags.items()):
        note(f"  FLAGGED {name}: {row['outcome']}: {row['detail']} (served model unchanged)")
    emit(**got, flagged=flags)
    return 0
