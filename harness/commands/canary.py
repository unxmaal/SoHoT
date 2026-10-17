"""`soh canary`: planted candidates with known verdicts, run for real under an isolated home, one receipt per run. #919."""
from __future__ import annotations

from harness.commands.common import emit, err, note


def cmd_canary(a) -> int:
    from harness import canary
    what = getattr(a, "canary_cmd", "") or "run"
    if what == "spend":
        return _spend(a)
    plants = [p for p in canary.PLANTS if not a.plant or p.name in a.plant]
    unknown = sorted(set(a.plant or ()) - {p.name for p in canary.PLANTS})
    if unknown:
        return err(f"no such plant: {', '.join(unknown)}; plants are "
                   f"{', '.join(p.name for p in canary.PLANTS)}")
    if what == "check":
        return _check(plants)
    if not a.run:
        for row in canary.plant_rows():
            if row["name"] not in {p.name for p in plants}:
                continue
            note(f"{row['name']:18} {row['lane']:5} {row['challenger']}  expect {'/'.join(row['expect'])}"
                 + (f"  UNSAFE: {row['unsafe']}" if row["unsafe"] else ""))
            for s in row["steps"]:
                note(f"    soh {s}")
        note("\n--run to plant them, each in its own home under the canary directory")
        emit(plants=canary.plant_rows())
        return 0
    try:
        r = canary.run(plants, wait_h=canary.WAIT_H if a.wait_h is None else a.wait_h)
    except (ValueError, RuntimeError) as exc:
        return err(str(exc))
    for p in r["plants"]:
        o = p["observed"]
        note(f"{'ok  ' if p['ok'] else 'MISS'} {p['plant']:18} expected {'/'.join(p['expected'])}, "
             f"observed {o.get('outcome')}/{o.get('tier')}/{o.get('reason')} (verdict {o.get('id')})")
    if r.get("skipped"):
        note(f"not run: {r['skipped']}")
    note(f"leaked into the live store: {r['leaked']}\nreceipt {r['path']}")
    emit(r["ok"], **r)
    return 0 if r["ok"] else 1


def _check(plants) -> int:
    """Whether the adopt gate separates each measured plant's pair on this store's stored results."""
    import sqlite3

    from harness import canary, paths
    live = paths.home() / "discovery.db"
    conn = sqlite3.connect(f"file:{live}?mode=ro", uri=True)
    try:
        got = [canary.separable(conn, p) for p in plants]
    finally:
        conn.close()
    for g in got:
        note(f"{'ok  ' if g['ok'] else 'MISS'} {g['plant']:18} run {g.get('run_id', '-')}: {g['why']}")
    emit(all(g["ok"] for g in got), plants=got)
    return 0 if all(g["ok"] for g in got) else 1


def _spend(a) -> int:
    """The loop's spend (fetch, screen, measure, adopt) in an isolated home; refused in the live one."""
    import argparse

    from harness import ceiling, cli, heartbeat, paths, power
    from harness.commands import loop as loop_cmd
    if paths.is_live(paths.home() / "discovery.db"):
        return err("soh canary spend runs only under an isolated LOCALHARNESS_HOME; soh canary --run makes one")
    sub = cli.build_parser().parse_args(["discover", "--loop", "--run", "--lane", a.lane, "--top", str(a.top)])
    sub = argparse.Namespace(**{**vars(sub), "json": False})
    sweep = ceiling.Sweep(float(power.SWEEP_CEILING_H) * 3600)
    heartbeat.start(lane=a.lane, total=loop_cmd.LOOP_TOTAL)
    try:
        rc = loop_cmd._spend_and_settle(sub, 0, [], sweep)
    except BaseException as exc:
        heartbeat.finish(None, error=f"{type(exc).__name__}: {exc}")
        raise
    heartbeat.finish(rc)
    return rc
