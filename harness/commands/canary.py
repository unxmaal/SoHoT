"""`soh canary`: planted candidates with known verdicts, run for real under an isolated home, one receipt per run. #919."""
from __future__ import annotations

from dataclasses import asdict

from harness.commands.common import emit, err, note


def cmd_canary(a) -> int:
    from harness import canary
    what = getattr(a, "canary_cmd", "") or "run"
    if what == "spend":
        return _spend(a)
    plants = [p for p in canary.PLANTS if not a.plant or p.name in a.plant]
    replays = tuple(r for r in canary.REPLAYS if not a.plant or r.name in a.plant)
    names = [p.name for p in canary.PLANTS] + [r.name for r in canary.REPLAYS]
    unknown = sorted(set(a.plant or ()) - set(names))
    if unknown:
        return err(f"no such plant: {', '.join(unknown)}; plants are {', '.join(names)}")
    if what == "check":
        return _check(plants, replays)
    if not a.run:
        for row in canary.plant_rows():
            if row["name"] not in {p.name for p in plants}:
                continue
            note(f"{row['name']:18} {row['lane']:5} {row['challenger']}  expect {'/'.join(row['expect'])}"
                 + (f"  UNSAFE: {row['unsafe']}" if row["unsafe"] else ""))
            for s in row["steps"]:
                note(f"    soh {s}")
        for r in replays:
            note(f"{r.name:18} {r.lane:5} {r.challenger} over {r.incumbent}  expect {'/'.join(r.expect)}"
                 f"\n    replay of stored runs {r.runs[0]} and {r.runs[1]} through adopt.decide, no GPU")
        note("\n--run to plant them, each in its own home under the canary directory")
        emit(plants=canary.plant_rows(), replays=[asdict(r) for r in replays])
        return 0
    try:
        r = canary.run(plants, wait_h=canary.WAIT_H if a.wait_h is None else a.wait_h, replays=replays)
    except (ValueError, RuntimeError) as exc:
        return err(str(exc))
    for p in r["plants"]:
        o = p["observed"]
        if p.get("invalid"):
            note(f"INVALID {p['plant']:15} plant invalid: {p['invalid']}")
            continue
        note(f"{'ok  ' if p['ok'] else 'MISS'} {p['plant']:18} expected {'/'.join(p['expected'])}, "
             f"observed {o.get('outcome')}/{o.get('tier')}/{o.get('reason')} "
             + (f"(replay of runs {'/'.join(map(str, p['runs']))})" if p.get("replay") else f"(verdict {o.get('id')})"))
    if r.get("skipped"):
        note(f"not run: {r['skipped']}")
    note(f"leaked into the live store: {r['leaked']}\nreceipt {r['path']}")
    emit(**r)
    return 0 if r["ok"] else 1


def _check(plants, replays=()) -> int:
    """Whether the adopt gate separates each measured plant's pair, and gives each replay its answer, on stored results."""
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
    for g in canary.replay_all(replays):
        why = g["invalid"] or (g.get("observed") or {}).get("why", "")
        tag = "INVALID" if g["invalid"] else "ok  " if g["ok"] else "MISS"
        note(f"{tag} {g['plant']:18} runs {'/'.join(map(str, g.get('runs') or ()))}: {why}")
        got.append({**g, "why": why})
    emit(all(g["ok"] for g in got), plants=got)
    return 0 if all(g["ok"] for g in got) else 1


def _spend(a) -> int:
    """The loop's spend (fetch, screen, measure, adopt) in an isolated home; refused in the live one."""
    from harness import ceiling, heartbeat, paths, power
    from harness.commands import common, loop as loop_cmd
    if paths.is_live(paths.home() / "discovery.db"):
        return err("soh canary spend runs only under an isolated LOCALHARNESS_HOME; soh canary --run makes one")
    sub = common.parsed("discover", "--loop", "--run", "--lane", a.lane, "--top", str(a.top), json=False)
    sweep = ceiling.Sweep(float(power.SWEEP_CEILING_H) * 3600)
    heartbeat.start(lane=a.lane, total=loop_cmd.LOOP_TOTAL)
    try:
        rc = loop_cmd._spend_and_settle(sub, 0, [], sweep)
    except BaseException as exc:
        heartbeat.finish(None, error=f"{type(exc).__name__}: {exc}")
        raise
    heartbeat.finish(rc)
    return rc
