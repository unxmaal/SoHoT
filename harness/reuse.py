"""The incumbent's stored draws under a matching content identity, used in place of a fresh paired run of it. #1094."""
from __future__ import annotations

import json
import re
from pathlib import Path

#: Stored draws a (case, repeat) cell needs under the same identity before the incumbent is not run on it.
MIN_DRAWS = 1
#: The file a measure step writes in a run's directory naming the incumbent cells it takes from the store.
REUSE_FILE = "reuse.json"


def _runs_with(conn, lane: str, digest: str, exclude=(), parts=None) -> dict[int, tuple[str, float, dict]]:
    """run id -> (the receipt key whose recorded identity is `digest`, when it ran, its per-case digests).

    With `parts`, a run recorded before a knob was is matched when that knob's unrecorded value gives `digest`. #1353.
    """
    from harness import identity, runs
    skip = {runs.path_key(p) for p in exclude}
    out = {}
    like = f"%{digest}%" if parts is None else "%identities%"
    for r in conn.execute("SELECT id, path, environment, COALESCE(generated_at, recorded_at) AS at "
                          "FROM runs WHERE lane = ? AND environment LIKE ?", (lane, like)):
        if r["path"] in skip:
            continue
        try:
            env = json.loads(r["environment"] or "{}")
        except ValueError:
            continue
        for key, ident in (env.get("identities") or {}).items():
            if not isinstance(ident, dict):
                continue
            if ident.get("digest") == digest or (
                    parts is not None and isinstance(ident.get("parts"), dict)
                    and identity.as_now(ident["parts"], parts) == digest):
                out[r["id"]] = (key, float(r["at"] or 0.0), ident.get("cases") or {})
    return out


def draws(conn, lane: str, digest: str, exclude=(), cases=None, parts=None) -> dict[tuple[str, int], list[tuple]]:
    """(base case, repeat index) -> [(when, run id, stored case id, candidate, seconds, reply tokens, case digest)] newest first.

    A draw counts only where its run recorded the same per-case digest as `cases` gives now; harness refusals are left out.
    """
    from harness import reasons
    found = _runs_with(conn, lane, digest, exclude, parts) if digest else {}
    out: dict = {}
    for run_id, (key, at, theirs) in found.items():
        for r in conn.execute("SELECT case_id, candidate, failure_class, seconds, metrics FROM results "
                              "WHERE run_id = ? AND candidate = ?", (run_id, key)):
            if (r["failure_class"] or "") in reasons.NEVER_RAN:
                continue
            base, _, n = str(r["case_id"]).partition("#")
            if cases is not None and (not theirs.get(base) or theirs.get(base) != cases.get(base)):
                continue
            try:
                tokens = (json.loads(r["metrics"] or "{}") or {}).get("completion_tokens")
            except ValueError:
                tokens = None
            out.setdefault((base, int(n) if n.isdigit() else 1), []).append(
                (at, run_id, r["case_id"], r["candidate"], float(r["seconds"] or 0.0), tokens, theirs.get(base, "")))
    return {k: sorted(v, key=lambda d: (d[0], d[1]), reverse=True) for k, v in out.items()}


def plan(conn, lane: str, digest: str, cells, *, cases=None, min_draws: int | None = None, exclude=(),
         parts=None) -> dict:
    """Which incumbent cells come from the store: the newest matching draw where a cell has at least min_draws."""
    from harness import holdout, paired
    need = max(1, int(MIN_DRAWS if min_draws is None else min_draws))
    stored = draws(conn, lane, digest, exclude, cases, parts)
    taken: dict = {}
    short = 0
    for cell in cells:
        got = stored.get((holdout.base_id(cell), paired.repeat_index(cell))) or []
        if len(got) >= need:
            taken[cell] = list(got[0][1:])
        elif got:
            short += 1
    if short:
        from harness import cuts
        cuts.cut("incumbent_reuse_min_draws", f"{lane}: incumbent cells with too few stored draws to reuse",
                 value=need, kept=len(taken), dropped=short, conn=conn)
    by: dict[str, int] = {}
    for run_id, *_ in taken.values():
        by[str(run_id)] = by.get(str(run_id), 0) + 1
    return {"digest": digest, "min_draws": need, "cells": taken, "runs": by,
            "reused": len(taken), "fresh": len(list(cells)) - len(taken)}


def line(got: dict | None) -> str:
    """'incumbent: N cell(s) reused from run 521 (60), ...; M fresh' or ''."""
    if not got or not got.get("digest"):
        return ""
    if not got.get("reused"):
        return f"incumbent: no stored draws match its identity, {got.get('fresh', 0)} cell(s) fresh"
    runs = ", ".join(f"run {k} ({v})" for k, v in sorted(got["runs"].items(), key=lambda kv: -kv[1]))
    return f"incumbent: {got['reused']} cell(s) reused from {runs}; {got.get('fresh', 0)} fresh"


def write(out, spec: str, got: dict) -> Path:
    path = Path(out) / REUSE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"spec": spec, **got}, sort_keys=True), encoding="utf-8")
    return path


def read(path) -> dict:
    try:
        got = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return got if isinstance(got, dict) else {}


def rows(conn, applied: dict | None, inc_key: str) -> tuple[list[dict], list[str]]:
    """(the stored rows for the applied cells, relabelled as this run's incumbent cells; cells whose row is gone)."""
    from harness import runs
    cells = (applied or {}).get("cells") or {}
    by_run: dict[int, list] = {}
    for cell, (run_id, case_id, candidate, *_) in cells.items():
        by_run.setdefault(int(run_id), []).append((cell, case_id, candidate))
    out, gone = [], []
    for run_id, wanted in sorted(by_run.items()):
        held = {(r["case_id"], r["candidate"]): r for r in runs.rows(conn, run_id)}
        for cell, case_id, candidate in wanted:
            r = held.get((case_id, candidate))
            if r is None:
                gone.append(cell)
                continue
            out.append({**r, "candidate": inc_key, "case_id": cell, "reused_from": run_id})
    return out, sorted(gone)


def summary(rows_: list[dict], key: str) -> dict | None:
    """The summary entry for `key` over merged rows, as runs.summarize computes one."""
    from harness import runs
    mine = [r for r in rows_ if r.get("candidate") == key]
    if not mine:
        return None
    got = runs.summarize([{**r, "warnings": r.get("warnings") or [], "metrics": r.get("metrics") or {},
                           "peak_kb": r.get("peak_kb") or 0, "seconds": r.get("seconds") or 0.0,
                           "detail": r.get("detail") or ""} for r in mine])
    return {**(got.get(key) or {}), "candidate": key}


def narrowed(head: dict | None, planned: dict | None) -> dict | None:
    """The planned reuse narrowed to the cells a run's checkpoint says it skipped, None when it skipped none."""
    planned, head = planned or {}, head or {}
    if not planned.get("digest") or head.get("digest") != planned["digest"]:
        return None
    cells = {c: planned["cells"][c] for c in head.get("cells") or [] if c in (planned.get("cells") or {})}
    by: dict[str, int] = {}
    for run_id, *_ in cells.values():
        by[str(run_id)] = by.get(str(run_id), 0) + 1
    return {**planned, "cells": cells, "runs": by, "reused": len(cells)} if cells else None


def timing(outdir) -> dict:
    """cell -> (seconds, reply tokens) of the stored draws a run took for its incumbent, from its reuse file."""
    head = ((_checkpoint_head(outdir) or {}).get("reuse")) or {}
    got = read(Path(outdir) / REUSE_FILE)
    if not head or got.get("digest") != head.get("digest"):
        return {}
    cells = got.get("cells") or {}
    return {c: tuple(cells[c][3:5]) for c in head.get("cells") or [] if c in cells and len(cells[c]) >= 5}


def _checkpoint_head(outdir) -> dict | None:
    from evals import watch
    got = watch.read(outdir)
    return got[0] if got else None


def evidence(applied: dict | None, gone=()) -> dict:
    if not applied or not applied.get("digest"):
        return {}
    return {"digest": applied["digest"], "reused": applied.get("reused", 0) - len(gone),
            "fresh": applied.get("fresh", 0), "runs": applied.get("runs") or {},
            **({"missing": list(gone)} if gone else {})}


def legacy(receipt: dict, env: dict, key: str) -> dict:
    """What a run from before #1094 recorded of a candidate's conditions: version labels, not bytes."""
    lane = receipt.get("modality") or ""
    versions = env.get("versions") or {}
    return {"lane": lane, "max_tokens": receipt.get("max_tokens"),
            "budget_ladder": list(receipt.get("budget_ladder") or []),
            "sampling": (receipt.get("sampling") or {}).get(lane),
            "template": (receipt.get("template") or {}).get(lane),
            "knobs": receipt.get("knobs") or {},
            "server_sampling": (receipt.get("server_sampling") or {}).get(key),
            "served": (receipt.get("served") or {}).get(key),
            "resolved": (receipt.get("resolved") or {}).get(key),
            "split_version": receipt.get("split_version"),
            "llama.cpp": versions.get("llama.cpp"), "hw_model": env.get("hw_model"),
            "macos": env.get("macos"), "memory_gb": env.get("memory_gb")}


_LOOK = re.compile(r"look (\d+) at (\d+)/(\d+)")


def replay(conn, run_id: int) -> dict:
    """Replay a paused paired run's looks with the incumbent's draws taken from earlier runs matching it, where they exist."""
    from harness import adopt, holdout, looks, runs
    run = runs.get(conn, run_id)
    if not run:
        raise ValueError(f"no run {run_id}")
    pause = conn.execute("SELECT * FROM paused_runs WHERE run_id = ? ORDER BY id DESC LIMIT 1",
                         (run_id,)).fetchone()
    if pause is None:
        raise ValueError(f"run {run_id} was never paused, so it has no looks to replay")
    receipt, env = json.loads(run["receipt"] or "{}"), json.loads(run["environment"] or "{}")
    specs = json.loads(run["specs"] or "{}")
    key_of = {spec: key for key, spec in specs.items()}
    lane = run["lane"]
    inc_key = key_of.get(pause["incumbent"], pause["incumbent"])
    ch_key = key_of.get(pause["challenger"], pause["challenger"])
    plan_ = json.loads(pause["plan"] or "{}")
    taken = json.loads(pause["looks"] or "[]")
    points = [int(m.group(2)) for m in (_LOOK.search(t.get("text", "")) for t in taken) if m]
    final = _LOOK.search(pause["why"] or "")
    if final and (not points or int(final.group(2)) != points[-1]):
        points.append(int(final.group(2)))
    stored = conn.execute("SELECT outcome, detail FROM verdicts WHERE run_id = ? AND tier = ? "
                          "ORDER BY id DESC LIMIT 1", (run_id, adopt.TIER)).fetchone()
    want = legacy(receipt, env, inc_key)
    sources: dict[int, str] = {}
    for r in conn.execute("SELECT id, receipt, environment, specs FROM runs WHERE lane = ? AND id != ? "
                          "AND COALESCE(generated_at, recorded_at) < ?",
                          (lane, run_id, run["generated_at"] or run["recorded_at"])):
        their = json.loads(r["specs"] or "{}")
        key = next((k for k, s in their.items() if s == pause["incumbent"]), inc_key)
        if legacy(json.loads(r["receipt"] or "{}"), json.loads(r["environment"] or "{}"), key) == want:
            sources[r["id"]] = key
    from harness import reasons
    pool: dict = {}
    for src, key in sources.items():
        at = runs.get(conn, src)["generated_at"] or 0.0
        for r in runs.rows(conn, src):
            if r["candidate"] != key or (r.get("failure_class") or "") in reasons.NEVER_RAN:
                continue
            base, _, n = r["case_id"].partition("#")
            pool.setdefault((base, int(n) if n.isdigit() else 1), []).append((at, src, r))
    own = runs.rows(conn, run_id)
    challenger = [r for r in own if r["candidate"] == ch_key]
    split = holdout.for_lane(lane)
    need = max(1, MIN_DRAWS)
    reused: dict[str, tuple] = {}
    for r in challenger:
        got = sorted(pool.get((holdout.base_id(r["case_id"]), _repeat(r["case_id"])), []),
                     key=lambda x: (x[0], x[1]), reverse=True)
        if len(got) >= need:
            reused[r["case_id"]] = (got[0][1], got[0][2])

    def done(part) -> int:
        cell, _, _ = adopt.paired_p(holdout.rows_on(part, split, "holdout"), inc_key, ch_key, lane)
        return cell.gained + cell.lost + cell.unchanged
    # Each look saw a prefix of the run's rows in the order they ran: the shortest one with its cell count.
    prefixes = [next((n for n in range(len(own) + 1) if done(own[:n]) >= want_), len(own)) for want_ in points]

    def walk(with_reuse: bool) -> dict:
        spent, out, verdict = 0.0, [], None
        alpha = float(plan_.get("alpha") or adopt.ALPHA)
        for n, end in enumerate(prefixes, 1):
            part = own[:end]
            if with_reuse:
                ch = [r for r in part if r["candidate"] == ch_key]
                ran = {r["case_id"]: r for r in part if r["candidate"] == inc_key}
                part = ch + [x for x in ({**reused[c["case_id"]][1], "candidate": inc_key,
                                          "case_id": c["case_id"], "reused_from": reused[c["case_id"]][0]}
                                         if c["case_id"] in reused else ran.get(c["case_id"]) for c in ch) if x]
            look, v = looks.look(part, lane=lane, inc_key=inc_key, ch_key=ch_key, split=split, plan=plan_,
                                 alpha=alpha, spent_before=spent, n=n)
            spent = look.spent
            out.append(look.text)
            if v is not None:
                verdict = {"adopt": v.adopt, "why": v.why, "decision": look.decision}
                break
        return {"looks": out, "verdict": verdict}
    control, replayed = walk(False), walk(True)
    by: dict[str, int] = {}
    for src, _ in reused.values():
        by[str(src)] = by.get(str(src), 0) + 1
    return {"run_id": run_id, "lane": lane, "incumbent": inc_key, "challenger": ch_key,
            "stored_looks": [t.get("text", "") for t in taken] + ([pause["why"]] if final else []),
            "stored_verdict": dict(stored) if stored else None,
            "matching_runs": sorted(sources), "reused": len(reused), "fresh": len(challenger) - len(reused),
            "runs": by, "control": control, "replay": replayed}


def _repeat(case_id: str) -> int:
    from harness import paired
    return paired.repeat_index(case_id)
