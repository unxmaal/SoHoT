"""`soh blame`: what share of terminal verdicts are the harness's fault, sampled, labelled from evidence and reported. #918."""
from __future__ import annotations

import csv
import json
import random
from collections import Counter
from pathlib import Path

from harness import intervals

TERMINAL = ("broken", "declined", "ignored")
#: Tiers whose every terminal state verdict is labelled: the evidence is a run and the harm is highest.
CENSUS_TIERS = ("screen", "adopt", "measure")
DRAW_TOTAL = 40
DRAW_MINIMUM = 5
PLANT_HARNESS = 10
PLANT_MODEL = 5
SECOND_N = 20
HARNESS, MODEL, MACHINE, UNDECIDABLE = "harness", "model", "machine-correct", "undecidable"

CODEBOOK = {
    HARNESS: "with a correct harness on this machine the verdict would differ or be non-terminal: wrong lane "
             "or runner, a loadable runtime not tried, our incomplete download, a limit we chose, a reason "
             "whose until cannot fire",
    MODEL: "the candidate's own result: it ran under a fair harness and lost, failed or is not what it claims",
    MACHINE: "a true fact about this machine with an until that can fire: needs-cuda, over the memory ceiling",
    UNDECIDABLE: "the evidence that would decide it is missing; the evidence column names the missing file or row",
}
#: Decision rules, in order; the first that fits decides. Revised after the 2026-10-17 first labelling.
RULES = (
    "not a standalone model (adapter or LoRA, speculative draft head, tool, course or paper repo) or a repo with "
    "no weights: model, whatever the reason column says; a method proposal that ran is judged by the rules below",
    "attachment by a stray word: attaches_to from a tag or prose word on a full model (a merged fine-tune "
    "shipping GGUFs, a whole pipeline, a ComfyUI repo of the main weights even without a VAE): harness",
    "wrong family or route: a VLM, audio, any-to-any, OCR or extractor checkpoint sent to mlx-lm, a GGUF-first "
    "repo sent to "
    "mlx-lm, a diffusers pipeline sent to the TTS runner, a lane taken from a stray tag: harness",
    "a runtime SoHoT already runs on this machine (mlx-lm, llama-server, mflux, the diffusers or hf-task venvs, "
    "mlx-audio) loads the weights natively but was not tried: harness; check models/<model_type> in the venv",
    "runner gap: no runner of ours loads the layout (unknown model_type with custom code, a pipeline class "
    "diffusers lacks, no model_index.json, no safetensors, a vendor format, remote code our policy refuses, a "
    "backend abort on a natively supported model_type): "
    "harness, because the project queues runner gaps (fetching.py, #798)",
    "too big: machine-correct when the smallest runnable set (one GGUF quant, or one checkpoint plus the "
    "components it needs, from its base if the repo lacks them) exceeds the ceiling of the machine that "
    "judged it; a repo total over several variants is harness",
    "needs cuda or vllm: machine-correct when the format needs that runtime (gemlite, ModelOpt NVFP4) and the "
    "repo ships no config.json + model.safetensors a local runtime loads; otherwise harness",
    "a limit we set binds the outcome, judged from the outputs (answers cut off mid-work, or none because the "
    "limit stopped the run before it answered), not the reason column "
    "(max_tokens 4000 before #628, the #803 length refusal, a download cap, a saturated or 3-case holdout read "
    "as underpowered or as a loss): harness",
    "the candidate's own output under the same settings its incumbent finished in (a paired loss or futility "
    "stop, degenerate or never-ending generation): model",
    "upstream idle (upstream_idle_days, a commit_after until): model",
    "ignored at inspect (a retired named weight): model when no lane measures it or another proposal names the "
    "same repo (case aside; a sibling version is not the same); harness when it is a runnable model of a "
    "measured lane with no other proposal",
    "a load failure whose server log is not in the run directory (llama-server 'failed to load'): "
    "undecidable, naming the missing log",
)
EVIDENCE = ("run directory (results.json receipt, stderr, checkpoint), files under the HF cache, the proposal "
            "and verdict columns other than detail, downloads rows, the code at the receipt's git_sha; "
            "never the verdict's detail string")
FIELDS = ("verdict_id", "label", "evidence")

POPULATION_SQL = (
    "SELECT v.id, p.name, p.state, v.tier, v.reason, v.until, p.lane, p.hf_task, v.decided_at FROM proposals p "
    "JOIN verdicts v ON v.id = p.state_verdict_id WHERE p.state IN ({}) AND v.decided_at > ? ORDER BY v.id"
).format(", ".join(f"'{s}'" for s in TERMINAL))
RETRACTED_SQL = (
    "SELECT DISTINCT o.id, p.name, o.outcome AS state, o.tier, o.reason FROM verdicts r "
    "JOIN verdicts o ON o.id = r.reopens LEFT JOIN proposals p ON p.id = o.proposal_id "
    "WHERE r.reopen_kind = 'retraction' AND o.outcome IN ({}) "
    # A machine refusal reopened for a bigger machine is its until firing, not a fault.
    "AND o.reason <> 'machine' "
    # Known only when the re-ask answered, and answered differently.
    "AND EXISTS (SELECT 1 FROM verdicts n WHERE n.proposal_id = o.proposal_id AND n.id > r.id "
    "AND n.outcome <> 'queued') "
    "AND NOT EXISTS (SELECT 1 FROM verdicts n WHERE n.proposal_id = o.proposal_id AND n.id > o.id "
    "AND n.outcome = o.outcome AND n.tier = o.tier AND n.reason = o.reason AND n.until = o.until) ORDER BY o.id"
).format(", ".join(f"'{s}'" for s in TERMINAL))
MODEL_PLANT_SQL = (
    "SELECT v.id, p.name, v.outcome AS state, v.tier, v.reason, x.lane AS run_lane, x.receipt FROM verdicts v "
    "JOIN runs x ON x.id = v.run_id "
    "LEFT JOIN proposals p ON p.id = v.proposal_id WHERE v.tier = 'adopt' AND v.outcome = 'declined' "
    "AND v.reason = 'candidate' AND v.run_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM verdicts r "
    "WHERE r.reopens = v.id AND r.reopen_kind = 'retraction') ORDER BY v.id")
FLOOR_SQL = (
    "SELECT COUNT(*) AS n, SUM(EXISTS (SELECT 1 FROM verdicts r WHERE r.reopens = o.id "
    "AND r.reopen_kind = 'retraction')) AS retracted FROM verdicts o WHERE o.outcome IN ({})"
).format(", ".join(f"'{s}'" for s in TERMINAL))


def stratum(row) -> str:
    return f"{row['tier'] or '-'}/{row['reason'] or '-'}"


def since(text: str) -> float:
    """'YYYY-MM-DD' or 'YYYY-MM-DD HH:MM', read as UTC, in epoch seconds. #1293."""
    import calendar
    import time
    for shape in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return float(calendar.timegm(time.strptime(str(text).strip(), shape)))
        except ValueError:
            continue
    raise ValueError(f"cannot read {text!r} as a date; use YYYY-MM-DD or 'YYYY-MM-DD HH:MM' (UTC)")


def utc(ts: float) -> str:
    import time
    return time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(float(ts)))


def population(conn, after: float | None = None) -> list[dict]:
    """The current state verdict of every terminal proposal, or of those decided after `after`."""
    return [dict(r) for r in conn.execute(POPULATION_SQL, (float("-inf") if after is None else float(after),))]


def allocate(sizes: dict, total: int = DRAW_TOTAL, minimum: int = DRAW_MINIMUM) -> dict:
    """Rows per stratum: at least `minimum` (or all), the rest by largest remainder of what is left."""
    got = {s: min(minimum, n) for s, n in sizes.items()}
    spare = max(0, total - sum(got.values()))
    left = {s: sizes[s] - got[s] for s in sizes}
    room = sum(left.values())
    if spare and room:
        spare = min(spare, room)
        share = {s: spare * left[s] / room for s in sizes}
        for s in sizes:
            got[s] += int(share[s])
        rest = spare - sum(int(v) for v in share.values())
        for s in sorted(sizes, key=lambda s: (-(share[s] - int(share[s])), s))[:rest]:
            got[s] += 1
    return {s: min(got[s], sizes[s]) for s in sizes}


def sample(conn, seed: int, total: int = DRAW_TOTAL, minimum: int = DRAW_MINIMUM,
           since: float | None = None) -> tuple[list[dict], dict]:
    """(rows, population sizes): census of CENSUS_TIERS plus a seeded draw from the other strata."""
    rows = population(conn, since)
    by: dict = {}
    for r in rows:
        by.setdefault(stratum(r), []).append(r)
    sizes = {s: len(v) for s, v in sorted(by.items())}
    draw = {s: n for s, n in sizes.items() if s.split("/")[0] not in CENSUS_TIERS}
    take = allocate(draw, total, minimum)
    rng = random.Random(seed)
    out = []
    for s in sorted(by):
        group = by[s]
        picked = group if s not in take else sorted(rng.sample(group, take[s]), key=lambda r: r["id"])
        out += [{**r, "stratum": s, "census": s not in take} for r in picked]
    return out, sizes


def _round_robin(rows: list[dict], n: int, rng) -> list[dict]:
    by: dict = {}
    for r in rows:
        by.setdefault(r["tier"], []).append(r)
    for group in by.values():
        rng.shuffle(group)
    out = []
    while len(out) < n and any(by.values()):
        for tier in sorted(by):
            if by[tier] and len(out) < n:
                out.append(by[tier].pop())
    return out


def _fair_run(row) -> bool:
    """A paired run that could have shown a win: the lane's current reply budget and enough distinct cases."""
    from evals.core import legacy_budget
    from harness import completion, holdout
    try:
        receipt = json.loads(row["receipt"] or "{}")
    except ValueError:
        return False
    lane = receipt.get("modality") or row["run_lane"] or ""
    cases = {str(c).split("#")[0] for c in receipt.get("case_ids") or []}
    ran = receipt.get("max_tokens")
    ran = legacy_budget(lane) if ran is None else int(ran)
    return len(cases) >= holdout.MIN_HOLDOUT + holdout.MIN_DEV and ran >= completion.budget(lane)


def plants(conn, seed: int, exclude, harness_n: int = PLANT_HARNESS, model_n: int = PLANT_MODEL) -> list[dict]:
    """Known-label rows for recall: retractions that changed the verdict (harness), adopt losses on a fair run (model)."""
    rng = random.Random(seed + 1)
    skip = set(exclude)
    retracted = [dict(r) for r in conn.execute(RETRACTED_SQL) if r["id"] not in skip]
    losses = [dict(r) for r in conn.execute(MODEL_PLANT_SQL) if r["id"] not in skip and _fair_run(r)]
    for r in losses:
        r.pop("receipt", None)
        r.pop("run_lane", None)
    got = [{**r, "plant": HARNESS} for r in _round_robin(retracted, harness_n, rng)]
    got += [{**r, "plant": MODEL} for r in rng.sample(losses, min(model_n, len(losses)))]
    return [{**r, "stratum": stratum(r)} for r in got]


def max_verdict(conn) -> int:
    return int(conn.execute("SELECT COALESCE(MAX(id), 0) FROM verdicts").fetchone()[0])


def _decided(conn, ids) -> dict:
    ids = list(ids)
    if not ids:
        return {}
    return {r[0]: utc(r[1]) for r in conn.execute(
        f"SELECT id, decided_at FROM verdicts WHERE id IN ({','.join('?' * len(ids))})", ids)}


def build(conn, seed: int, since: float | None = None) -> dict:
    """The labelling queue (shuffled, unmarked) and its key, for one store snapshot, seed and window."""
    rows, sizes = sample(conn, seed, since=since)
    # Plants test the labeller, not the window, so they come from the whole store.
    planted = plants(conn, seed, [r["id"] for r in rows])
    when = _decided(conn, [r["id"] for r in rows + planted])
    key = [{"verdict_id": r["id"], "role": "sample", "stratum": r["stratum"],
            "census": int(r["census"]), "plant": "", "decided_at": when.get(r["id"], "")} for r in rows]
    key += [{"verdict_id": r["id"], "role": "plant", "stratum": r["stratum"], "census": 0,
             "plant": r["plant"], "decided_at": when.get(r["id"], "")} for r in planted]
    names = {r["id"]: r["name"] for r in rows + planted}
    order = [k["verdict_id"] for k in key]
    random.Random(seed + 2).shuffle(order)
    sampled = [k["verdict_id"] for k in key if k["role"] == "sample"]
    if len(sampled) > SECOND_N:
        from harness import cuts
        cuts.cut("blame_second_n", "sampled verdicts left out of the second labeller's set",
                 kept=SECOND_N, dropped=len(sampled) - SECOND_N, conn=conn)
    second = sorted(random.Random(seed + 3).sample(sampled, min(SECOND_N, len(sampled))))
    header = {"seed": seed, "max_verdict_id": max_verdict(conn), "population": sizes}
    if since is not None:
        header["since"] = utc(since)
    return {"header": header,
            "queue": [{"verdict_id": v, "name": names[v] or ""} for v in order],
            "second": [{"verdict_id": v, "name": names[v] or ""} for v in second],
            "key": key}


def _write_csv(path: Path, header: dict | None, fields, rows) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        if header is not None:
            f.write(f"# {json.dumps(header, sort_keys=True)}\n")
        w = csv.DictWriter(f, fieldnames=list(fields), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def read_csv(path: Path) -> tuple[dict, list[dict]]:
    """(header, rows) of a file this module wrote; a label file has no header."""
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    header = json.loads(lines.pop(0)[2:]) if lines and lines[0].startswith("# ") else {}
    return header, list(csv.DictReader(lines))


def write(got: dict, out: Path) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    paths = [out / "queue.csv", out / "second-queue.csv", out / "key.csv"]
    _write_csv(paths[0], got["header"], ("verdict_id", "name"), got["queue"])
    _write_csv(paths[1], got["header"], ("verdict_id", "name"), got["second"])
    _write_csv(paths[2], got["header"], ("verdict_id", "role", "stratum", "census", "plant", "decided_at"),
               got["key"])
    return paths


def kappa(a: dict, b: dict) -> tuple[float | None, int]:
    """(Cohen's kappa, rows) over the verdict ids both labellers labelled."""
    common = sorted(set(a) & set(b))
    n = len(common)
    if not n:
        return None, 0
    seen = sum(a[v] == b[v] for v in common) / n
    ca, cb = Counter(a[v] for v in common), Counter(b[v] for v in common)
    chance = sum(ca[k] * cb[k] for k in set(ca) | set(cb)) / (n * n)
    return (1.0 if chance == 1 else round((seen - chance) / (1 - chance), 4)), n


def _labels(path: Path) -> dict:
    _, rows = read_csv(path)
    bad = [r for r in rows if r["label"] not in CODEBOOK]
    if bad:
        raise ValueError(f"{path}: unknown label(s) {sorted({r['label'] for r in bad})}; known: {', '.join(CODEBOOK)}")
    return {int(r["verdict_id"]): r["label"] for r in rows}


def report(key_path: Path, labels_path: Path, second_path: Path | None = None, conn=None) -> dict:
    """Harness share per stratum (Wilson), the population share (stratified, FPC), plant recall, kappa, the floor."""
    header, key = read_csv(key_path)
    labels = _labels(labels_path)
    missing = [int(k["verdict_id"]) for k in key if int(k["verdict_id"]) not in labels]
    strata: dict = {}
    for k in key:
        if k["role"] != "sample" or int(k["verdict_id"]) not in labels:
            continue
        s = strata.setdefault(k["stratum"], Counter())
        s[labels[int(k["verdict_id"])]] += 1
    rows, cells = [], []
    for name, c in sorted(strata.items()):
        N = int(header["population"].get(name, 0))
        decided = sum(c.values()) - c[UNDECIDABLE]
        rows.append({"stratum": name, "N": N, "labelled": sum(c.values()), "decided": decided,
                     "harness": c[HARNESS], "model": c[MODEL], "machine": c[MACHINE],
                     "undecidable": c[UNDECIDABLE], "share": round(c[HARNESS] / decided, 4) if decided else None,
                     "ci95": list(intervals.wilson(c[HARNESS], decided))})
        cells.append((N, decided, c[HARNESS]))
    sampled = {int(k["verdict_id"]) for k in key if k["role"] == "sample"}
    out = {"header": header, "strata": rows, "population": list(intervals.stratified(cells)),
           "recall": _recall(key, labels), "unlabelled": missing}
    if second_path is not None and Path(second_path).is_file():
        second = _labels(second_path)
        both = {v: labels[v] for v in labels if v in sampled}
        k, n = kappa(both, second)
        out["kappa"] = {"kappa": k, "n": n, "disagree": [
            {"verdict_id": v, "first": labels[v], "second": second[v]}
            for v in sorted(set(both) & set(second)) if labels[v] != second[v]]}
        out["recall_second"] = _recall(key, second, only_labelled=True)
    if conn is not None:
        f = conn.execute(FLOOR_SQL).fetchone()
        out["floor"] = {"retracted": int(f["retracted"] or 0), "n": int(f["n"] or 0),
                        "ci95": list(intervals.wilson(int(f["retracted"] or 0), int(f["n"] or 0))),
                        **retraction_outcomes(conn)}
        out["store_max_verdict_id"] = max_verdict(conn)
    return out


def _recall(key, labels: dict, only_labelled: bool = False) -> dict:
    out = {}
    for want in (HARNESS, MODEL):
        ids = [int(k["verdict_id"]) for k in key if k["plant"] == want
               and (not only_labelled or int(k["verdict_id"]) in labels)]
        out[want] = {"hit": sum(labels.get(v) == want for v in ids), "n": len(ids),
                     "missed": [v for v in ids if labels.get(v) != want]}
    return out


def retraction_outcomes(conn) -> dict:
    """Of the retracted terminal verdicts: how many re-asks wrote the same outcome again, a different one, or none yet."""
    got = Counter()
    for o in conn.execute(
            "SELECT DISTINCT o.id, o.proposal_id, o.outcome, o.tier, o.reason, MIN(r.id) AS rid FROM verdicts r "
            "JOIN verdicts o ON o.id = r.reopens WHERE r.reopen_kind = 'retraction' AND o.outcome IN ({}) "
            "GROUP BY o.id".format(", ".join(f"'{s}'" for s in TERMINAL))):
        nxt = conn.execute("SELECT outcome, tier, reason FROM verdicts WHERE proposal_id = ? AND id > ? "
                           "AND outcome <> 'queued' ORDER BY id LIMIT 1", (o["proposal_id"], o["rid"])).fetchone()
        if nxt is None:
            got["pending"] += 1
        elif (nxt["outcome"], nxt["tier"], nxt["reason"]) == (o["outcome"], o["tier"], o["reason"]):
            got["reproduced"] += 1
        else:
            got["changed"] += 1
    return {k: got[k] for k in ("reproduced", "changed", "pending")}


def report_text(got: dict) -> str:
    h = got["header"]
    lines = [f"blame audit, seed {h.get('seed')}, store max verdict {h.get('max_verdict_id')}",
             f"  window: {window(h)}"]
    if got.get("store_max_verdict_id") not in (None, h.get("max_verdict_id")):
        lines.append(f"  note: the store has moved on to verdict {got['store_max_verdict_id']}; the population "
                     f"sizes are the sample's")
    lines.append(f"  {'stratum':<20} {'N':>4} {'lab':>4} {'harn':>4} {'model':>5} {'mach':>4} {'und':>4}  share [95%]")
    for r in got["strata"]:
        share = "  -  " if r["share"] is None else f"{r['share']:.2f}"
        lines.append(f"  {r['stratum']:<20} {r['N']:>4} {r['labelled']:>4} {r['harness']:>4} {r['model']:>5} "
                     f"{r['machine']:>4} {r['undecidable']:>4}  {share} [{r['ci95'][0]:.2f}, {r['ci95'][1]:.2f}]")
    p = got["population"]
    lines.append(f"population harness share (stratified, FPC): {p[0]:.2f} [{p[1]:.2f}, {p[2]:.2f}]")
    for who, rec in (("first", got["recall"]), ("second", got.get("recall_second") or {})):
        for want, r in rec.items():
            if r["n"]:
                lines.append(f"plant recall {want} ({who} labeller): {r['hit']}/{r['n']}"
                             + (f", missed {r['missed']}" if r["missed"] else ""))
    if "kappa" in got:
        k = got["kappa"]
        lines.append(f"kappa {k['kappa']} over {k['n']} shared sampled rows, {len(k['disagree'])} disagreement(s)")
        lines += [f"  {d['verdict_id']}: first {d['first']}, second {d['second']}" for d in k["disagree"]]
    if "floor" in got:
        f = got["floor"]
        lines.append(f"retraction floor: {f['retracted']} of {f['n']} terminal verdicts later retracted "
                     f"[{f['ci95'][0]:.3f}, {f['ci95'][1]:.3f}]; re-asked since: {f['reproduced']} reproduced, "
                     f"{f['changed']} changed, {f['pending']} pending")
    if got["unlabelled"]:
        lines.append(f"unlabelled: {len(got['unlabelled'])} row(s), e.g. {got['unlabelled'][:5]}")
    return "\n".join(lines)


def window(header: dict) -> str:
    return (f"state verdicts decided after {header['since']}" if header.get("since")
            else "every terminal state verdict")


def compare(new: dict, old: dict) -> dict:
    """This audit's shares beside an earlier one's; moved when the new upper bound is under the old lower one."""
    def cell(r):
        return {"share": r["share"], "ci95": r["ci95"], "decided": r["decided"]} if r else None
    a, b = {r["stratum"]: r for r in new["strata"]}, {r["stratum"]: r for r in old["strata"]}
    strata = [{"stratum": s, "new": cell(a.get(s)), "old": cell(b.get(s))} for s in sorted(set(a) | set(b))]
    pn, po = list(new["population"]), list(old["population"])
    return {"new_window": window(new["header"]), "old_window": window(old["header"]), "strata": strata,
            "population": {"new": pn, "old": po}, "moved": pn[2] < po[1]}


def compare_text(got: dict) -> str:
    def fmt(c):
        if not c or c["share"] is None:
            return "-"
        return f"{c['share']:.2f} [{c['ci95'][0]:.2f}, {c['ci95'][1]:.2f}]"
    lines = [f"against: {got['old_window']}", f"  {'stratum':<20} {'this audit':<19} earlier"]
    lines += [f"  {s['stratum']:<20} {fmt(s['new']):<19} {fmt(s['old'])}" for s in got["strata"]]
    pn, po = got["population"]["new"], got["population"]["old"]
    lines.append(f"  {'population':<20} {pn[0]:.2f} [{pn[1]:.2f}, {pn[2]:.2f}]  {po[0]:.2f} [{po[1]:.2f}, {po[2]:.2f}]")
    lines.append(f"moved: {'yes' if got['moved'] else 'no'}, this audit's upper bound {pn[2]:.2f} "
                 f"{'is' if got['moved'] else 'is not'} below the earlier lower bound {po[1]:.2f}")
    return "\n".join(lines)


def codebook_text() -> str:
    lines = ["One label per row, from primary evidence only.", f"Evidence: {EVIDENCE}.",
             f"Label file columns: {', '.join(FIELDS)}; evidence cites the file path or SQL that decides it.", ""]
    lines += [f"{k}: {v}" for k, v in CODEBOOK.items()]
    lines += ["", "Rules, first match decides:"] + [f"{i}. {r}" for i, r in enumerate(RULES, 1)]
    return "\n".join(lines)
