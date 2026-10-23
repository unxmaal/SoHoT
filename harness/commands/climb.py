"""`soh climb` and `soh yield-stop`: what more room and the yield stop would do for a lane-model, from the stored rows, read-only. #1124, #1127."""
from __future__ import annotations

import json

from harness.commands.common import emit, err, note


def add_parser(sub) -> None:
    p = sub.add_parser("climb", help="of a candidate's replies cut at a rung, how many passed with more room in the "
                       "stored runs, and its yield stop point, read-only (#1124)")
    p.add_argument("lane", help="the lane, e.g. repo")
    p.add_argument("spec", help="the candidate spec, e.g. llamacpp:Ornith-1.5-35B-Q4_K_M")
    p.add_argument("--rung", type=int, default=None, help="the rung a reply was cut at (default: the lane's reply budget)")
    p.add_argument("--runs", default="", help="only these stored run ids, comma-separated")
    p.add_argument("--store", default="", help="a discovery.db to read read-only (default: a copy of this home's)")
    p.set_defaults(func=cmd_climb)
    y = sub.add_parser("yield-stop", help="a lane-model's stop point in generated tokens from the stored rows, and "
                       "a stored run or checkpoint re-scored under it without re-running, read-only (#1127)")
    y.add_argument("lane")
    y.add_argument("spec")
    y.add_argument("--run", type=int, default=None, help="re-score this stored run's rows of the spec's model")
    y.add_argument("--checkpoint", default="", help="re-score the rows of a run directory's checkpoint.jsonl")
    y.add_argument("--ratio", type=float, default=None, help="yield_stop_ratio (default: the knob's)")
    y.add_argument("--store", default="", help="a discovery.db to read read-only (default: a copy of this home's)")
    y.set_defaults(func=cmd_yield_stop)


def _connect(store: str):
    from harness import ledger, morning
    if not store:
        return morning.snapshot()
    from pathlib import Path
    if not Path(store).is_file():
        raise FileNotFoundError(f"no store at {store}")
    return ledger.open_ro(Path(store))


def _ids(text: str) -> set[int]:
    return {int(n) for n in text.split(",") if n.strip()}


def cmd_climb(a) -> int:
    from harness import completion, convertible, runs, yield_stop
    rung = a.rung if a.rung is not None else completion.budget(a.lane)
    if not rung:
        return err(f"{a.lane} generates no text, so it has no ladder")
    try:
        only = _ids(a.runs)
    except ValueError:
        return err(f"--runs takes comma-separated run ids, not {a.runs!r}")
    try:
        conn = _connect(a.store)
    except FileNotFoundError as exc:
        return err(str(exc))
    try:
        found = convertible.stored(conn, a.lane, a.spec, runs.here(conn))
        stop = yield_stop.point(conn, a.lane, a.spec)
    finally:
        conn.close()
    if only:
        found = [f for f in found if f["run_id"] in only]
    s = convertible.best(found, a.spec, rung)
    if s is None:
        said = f"no stored reply cut at {rung} was given more room"
    else:
        said = (f"{s['passed']} of {s['cut']} cuts at {rung} converted ({s['where']}"
                f"{', confounded: ' + s['confounded'] if s['confounded'] else ''}); "
                f"{s['wrong']} finished wrong, {s['again']} cut again")
    note(f"{a.lane} {a.spec}: {said}")
    note(f"  yield stop: {yield_stop.said(stop)}")
    emit(lane=a.lane, spec=a.spec, rung=rung, runs=sorted({f["run_id"] for f in found}),
         converted=s["passed"] if s else 0, cuts=s["cut"] if s else 0, where=s["where"] if s else "",
         yield_stop=stop)
    return 0


def cmd_yield_stop(a) -> int:
    from harness import convertible, runs, yield_stop
    try:
        conn = _connect(a.store)
    except FileNotFoundError as exc:
        return err(str(exc))
    try:
        stop = yield_stop.point(conn, a.lane, a.spec, a.ratio)
        rows = (runs.rows(conn, a.run) if a.run is not None else [])
    finally:
        conn.close()
    note(f"{a.lane} {a.spec}: {yield_stop.said(stop)}")
    out = {"lane": a.lane, "spec": a.spec, "yield_stop": stop}
    base = convertible.base_of(a.spec)
    for name, got in (("run", rows), ("checkpoint", _checkpoint(a.checkpoint))):
        mine = [r for r in got if convertible.base_of(r.get("candidate") or "") == base]
        if not mine:
            continue
        r = yield_stop.rescore(mine, stop["tokens"])
        note(f"  {name} {a.run if name == 'run' else a.checkpoint} ({len(mine)} rows) re-scored: "
             f"{r['kept']} passes kept, {r['lost']} lost, {r['stopped']} stopped, "
             f"{r['saved_share']:.0%} of {r['seconds'] / 3600:.1f} GPU-h saved")
        out[name] = {k: v for k, v in r.items() if k != "rows"}
    emit(**out)
    return 0


def _checkpoint(path: str) -> list[dict]:
    if not path:
        return []
    from pathlib import Path
    rows = []
    for ln in Path(path).read_text(encoding="utf-8").splitlines():
        got = json.loads(ln) if ln.strip() else {}
        if "row" in got:
            rows.append(got["row"])
    return rows
