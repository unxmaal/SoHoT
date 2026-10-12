"""What the receipts say won each lane, against what the code has typed in.

harness/cli.py carries four constants -- DEFAULT_SVG_MODEL and friends -- above
a thirty-line comment recording the run that chose them. The run is real and
the comment is careful. It is still a HAND COPY of a number that lives
somewhere else, which is this project's most-bitten failure class: one question
with two answers, and nothing that notices when they drift.

WHY NOT DERIVE THE DEFAULT DIRECTLY. A default that changes because somebody
ran an eval last night is a CLI whose behaviour depends on local history, and
two machines would then disagree about what `lh svg` does. The constant stays:
it is stable, reviewable, and arrives with the argument for it. What changes is
that a drift is now VISIBLE instead of silent -- `lh discover --winners` shows
both answers side by side, and a test reports disagreement.

AN INVENTORY, NOT A GATE. Stored runs exist only where the suite ran, so on CI
this compares nothing and must not fail.
"""
from __future__ import annotations


#: A candidate spec that is not a bare model: `repair:<model>` is a
#: WORKFLOW built on a model, and `trace/mflux/...` a composition. Both can win
#: a lane on merit, and neither is what a `--model` default can be set to.
_COMPOSITE = (":", "/")


def is_plain_model(candidate: str) -> bool:
    return not any(mark in candidate for mark in _COMPOSITE)


#: Which lanes a default is an engine spec for, so a composite key can win.
FAMILIES = {
    "svg": "alias", "web": "alias", "code": "alias", "extract": "alias",
    "decide": "alias", "agent": "alias", "claims": "alias",
    "image": "engine", "video": "engine", "music": "engine", "ocr": "engine",
    "retrieval": "engine", "pii": "engine",
    "tts": "speech", "stt": "speech",
}


def from_receipts(conn, plain_only: bool = True) -> dict[str, dict]:
    """The best candidate per lane over every stored measure run. #410."""
    from harness import runs
    entries: dict[str, list] = {}
    for run, summary, _ in runs.summaries(conn, tier=runs.MEASURE):
        for candidate, row in summary.items():
            if plain_only and not is_plain_model(candidate):
                continue
            entries.setdefault(run["lane"], []).append({
                "candidate": candidate, "row": row,
                "pass_rate": float(row.get("pass_rate") or 0.0),
                "median_s": float(row.get("median_s") or 0.0),
                "total": int(row.get("total") or 0), "run": run["path"],
                "run_id": run["id"]})
    return {lane: _pick(got, lane=lane) for lane, got in entries.items()}


#: Lanes ranked on a pooled metric before pass rate: an exact-case rate is roughly acc^fields, and stt's is exact orthography. #701.
#: claims balances case recall and specificity, since most cases expect nothing and silence passes them. #791.
PRIMARY = {"decide": "decide_accuracy", "stt": "wer", "claims": "claims_balanced"}
#: Lanes whose primary metric is a summary of strata, paired per stratum rather than per row. #791.
STRATIFIED = {"claims"}
#: Metrics that measure probabilities, meaningless on a row whose answers were one-hot. #701.
CALIBRATION = frozenset({"decide_brier", "decide_ece"})


def ranked_metrics(row: dict) -> dict[str, float]:
    """The row's non-neutral metrics, signed so larger is better; no calibration metric on an uncalibrated row."""
    from evals.core import direction_of

    metrics = row.get("metrics") or {}
    uncalibrated = float(metrics.get("calibrated", 1.0) or 0.0) < 1.0
    out = {}
    for name, value in metrics.items():
        way = direction_of(name)
        if way != "neutral" and not (uncalibrated and name in CALIBRATION):
            out[name] = float(value or 0.0) * (1 if way == "higher" else -1)
    return out


def primary(row: dict, lane: str = "") -> tuple:
    """The first rank key: the lane's pooled metric, else pass rate; a row missing it, or with it over fewer of its cases, sorts below."""
    name = PRIMARY.get(lane)
    if not name:
        return (True, 1.0, float(row.get("pass_rate") or 0.0))
    got = ranked_metrics(row)
    n, total = (row.get("metric_n") or {}).get(name), int(row.get("total") or 0)
    covered = round(min(1.0, n / total), 3) if n is not None and total else 1.0
    return (name in got, covered, got.get(name, 0.0))


def shared_metrics(rows, lane: str = "") -> tuple[str, ...]:
    """Metric names shared by the top rows that report any, so a crashed row cannot erase the lane's metric. #690."""
    rows = list(rows)
    top = max((primary(r, lane) for r in rows), default=(True, 0.0))
    names = None
    for row in rows:
        mine = set(ranked_metrics(row))
        if not mine or primary(row, lane) < top:
            continue
        names = mine if names is None else names & mine
    return tuple(sorted(names or ()))


def _pick(entries: list[dict], prefer=lambda e: False, lane: str = "") -> dict:
    """The best entry, keyed on the metrics all entries share; exact ties go to `prefer`, then the lowest name."""
    names = shared_metrics((e["row"] for e in entries), lane)
    for e in entries:
        e["key"] = order_key(e.pop("row"), names, lane)
    top = max((e["key"], prefer(e)) for e in entries)
    return min((e for e in entries if (e["key"], prefer(e)) == top),
               key=lambda e: (str(e["candidate"]), int(e.get("run_id") or 0)))


def order_key(row: dict, names, lane: str = "") -> tuple:
    """How good a summary row is, best LAST so `max` picks the winner.

    THE LANE'S OWN METRIC COMES FIRST, and getting that wrong is not
    hypothetical: ranking on pass rate and then latency reported that
    parakeet-ctc had beaten parakeet-tdt-v2 in the stt lane. Both passed 300 of
    300, and ctc has the faster median -- so on those two statistics ctc wins,
    and on the one the lane is actually about it loses:

        parakeet-tdt-0.6b-v2   wer 0.0162   median 0.135   <- adopted
        parakeet-ctc-0.6b      wer 0.0225   median 0.116

    A statistic blind to the effect under test reports a null, or worse an
    inversion, with no visible symptom. METRIC_DIRECTION exists for exactly
    this and says which way each metric runs; `neutral` ones are reported and
    never ranked on.
    """
    ranked = ranked_metrics(row)
    rate = float(row.get("pass_rate") or 0.0)
    median = float(row.get("median_s") or 0.0)
    # A candidate that passed less often is worse whatever its metric says: a
    # model that fails half the cases and scores well on the rest is scoring on
    # a different, easier subset.
    # A row missing a shared metric sorts below every row that reports it.
    return (primary(row, lane), rate, tuple((n in ranked, ranked.get(n, 0.0)) for n in names), -median)


def typed() -> dict[str, str]:
    """What the code has written down, by the modality each default serves.

    ALL OF THEM, not the four that happened to be in one file. The image engine
    is the one #148 phase 5 names by hand and the one #141 and #142 are both
    about, and it lived two modules away from the others.

    The speech defaults are chosen by platform, so this reports the one THIS
    machine would use: comparing a Mac's receipts against a Windows constant
    would be the accelerator mistake in another costume.
    """
    from harness import audio, cli
    from harness.models import build_here
    # A text default is a model id; a machine whose gateway serves another build of it uses that. #670.
    return {"svg": build_here(cli.DEFAULT_SVG_MODEL), "web": build_here(cli.DEFAULT_WEB_MODEL),
            "code": build_here(cli.DEFAULT_CODE_MODEL),
            "extract": build_here(cli.DEFAULT_EXTRACT_MODEL),
            "decide": build_here(cli.DEFAULT_DECIDE_MODEL),
            "claims": build_here(cli.DEFAULT_CLAIMS_MODEL),
            "agent": build_here(cli.DEFAULT_AGENT_MODEL),
            "image": cli.DEFAULT_IMAGE_ENGINE,
            "video": cli.DEFAULT_VIDEO_ENGINE,
            "music": cli.DEFAULT_MUSIC_ENGINE,
            "ocr": cli.DEFAULT_OCR_ENGINE,
            "retrieval": cli.DEFAULT_RETRIEVAL_ENGINE,
            "pii": cli.DEFAULT_PII_ENGINE,
            "tts": audio.DEFAULT_TTS_MODEL, "stt": audio.DEFAULT_STT_MODEL}


def typed_anywhere() -> dict[str, tuple[str, ...]]:
    """lane -> every value typed() returns on any platform, here first. #516."""
    from harness import audio
    out = {}
    for lane, name in typed().items():
        others = sorted(set(audio.SPEECH_DEFAULTS.get(lane, {}).values()) - {name})
        out[lane] = (name, *others)
    return out


def served_ids(conn) -> dict[str, int]:
    """lane -> the candidates row of what it serves: adopted here, else typed.

    #429; the adopted row comes from `adoptions`, by id. #412.
    """
    from harness import adopt, candidates, screen
    held = adopt.current(conn)
    out = {lane: row["candidate_id"] for lane, row in held.items()}
    for lane, name in typed().items():
        if lane in out:
            continue
        spec = screen.candidate_for(lane, name) or name
        cid = candidates.served(conn, spec, lane=lane)
        if cid:
            out[lane] = cid
    return out


def beaten_in(conn) -> dict[str, dict]:
    """Per lane, the best candidate from stored runs THE SERVED DEFAULT WAS IN.

    Only within one comparison: a default that was never in the room did not
    lose. "In the room" is its candidate id among the run's rows. #429.
    """
    from harness import runs
    wanted = served_ids(conn)
    entries: dict[str, list] = {}
    for run, _, rows in runs.summaries(conn, tier=runs.MEASURE):
        lane = run["lane"]
        if lane not in wanted or not any(
                r["candidate_id"] == wanted[lane] for r in rows):
            continue
        family = FAMILIES.get(lane, "alias")
        groups: dict = {}
        for r in rows:
            groups.setdefault(r["candidate_id"] or ("key", r["candidate"]),
                              []).append(r)
        for cid, group in groups.items():
            candidate, row = next(iter(runs.summarize(group).items()))
            served = cid == wanted[lane]
            if family != "engine" and not is_plain_model(candidate) \
                    and not served:
                continue
            entries.setdefault(lane, []).append({
                "candidate": candidate, "row": row,
                "pass_rate": float(row.get("pass_rate") or 0.0),
                "median_s": float(row.get("median_s") or 0.0),
                "metrics": dict(row.get("metrics") or {}),
                "run": run["path"], "run_id": run["id"],
                "total": int(row.get("total") or 0),
                "match": "exact" if served else "",
                "candidate_id": cid if isinstance(cid, int) else None,
                "family": family})
    # A served default that ties was not beaten.
    return {lane: _pick(got, prefer=lambda e: bool(e["match"]), lane=lane)
            for lane, got in entries.items()}


def disagreements(conn) -> list[dict]:
    """Where a typed default lost a comparison it was actually in.

    A default in no stored run is `unmeasured`, not a disagreement.
    """
    from harness import adopt
    best = beaten_in(conn)
    out = []
    for modality, name in sorted(adopt.lane_defaults(conn).items()):
        got = best.get(modality)
        if not got:
            out.append({"modality": modality, "typed": name,
                        "state": "unmeasured", "measured": "", "run": ""})
        elif not got["match"]:
            out.append({"modality": modality, "typed": name, "state": "beaten",
                        "measured": got["candidate"],
                        "pass_rate": got["pass_rate"],
                        "median_s": got["median_s"], "run": got["run"]})
    return out
