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


def spec_of(conn, run: dict, rows, key: str) -> str:
    """The stored spec a run's receipt key ran as: the run's specs map, else its rows' candidates row, else "". #1122."""
    import json
    got = (json.loads(run.get("specs") or "{}") or {}).get(key)
    if got or conn is None:
        return got or ""
    for cid in {r.get("candidate_id") for r in rows if r.get("candidate") == key} - {None}:
        row = conn.execute("SELECT spec FROM candidates WHERE id = ?", (cid,)).fetchone()
        if row and row["spec"]:
            return row["spec"]
    return ""


def can_default(lane: str, spec: str) -> bool:
    """Whether a lane can serve `spec` as its default: a stored spec, not a workflow, and a method only on its lanes, never a control. #1122."""
    from harness import methods, models
    if not spec or spec.startswith(models.WORKFLOW_PREFIXES):
        return False
    try:
        parsed = methods.parse(spec)
    except ValueError:
        return False
    return parsed is None or (lane in parsed.method.lanes and not methods.is_control(spec))


#: Which lanes a default is an engine spec for.
FAMILIES = {
    "svg": "alias", "web": "alias", "code": "alias", "extract": "alias",
    "decide": "alias", "agent": "alias", "claims": "alias",
    # Every repo candidate is an engine spec, and #1110 adopts one by measurement. #1120.
    "repo": "engine",
    "image": "engine", "video": "engine", "music": "engine", "ocr": "engine",
    "retrieval": "engine", "pii": "engine",
    "tts": "speech", "stt": "speech",
}


def from_receipts(conn, plain_only: bool = True, exam_of=None) -> dict[str, dict]:
    """The best candidate per lane over the stored measure runs of its current exam. #410, #1120.

    plain_only keeps only a candidate whose stored spec the lane can serve as its default (can_default). #1122.
    """
    from harness import runs
    entries: dict[str, list] = {}
    memo: dict = {}
    for run, summary, rows in runs.summaries(conn, tier=runs.MEASURE):
        for candidate, row in summary.items():
            if plain_only and not can_default(run["lane"], spec_of(conn, run, rows, candidate)):
                continue
            if not on_exam(run, rows, candidate, exam_of, memo):
                continue
            entries.setdefault(run["lane"], []).append({
                "candidate": candidate, "row": {**row, "cases_digest": run.get("cases_digest") or ""},
                "pass_rate": float(row.get("pass_rate") or 0.0),
                "median_s": float(row.get("median_s") or 0.0),
                "total": int(row.get("total") or 0), "run": run["path"],
                "run_id": run["id"], "cases_digest": run.get("cases_digest") or ""})
    return {lane: _pick(newest_exam(got), lane=lane) for lane, got in entries.items()}


def on_exam(run: dict, rows, candidate: str, exam_of=None, memo=None) -> bool:
    """Whether the run's rows for `candidate` are a whole sitting of the lane's current exam. #1120."""
    from harness import baseline
    return baseline.sat(run, rows, candidate, exam_of, memo)


def newest_exam(entries: list[dict]) -> list[dict]:
    """The entries on the cases digest of the newest run among them (runs.find order), so a lane ranks on one exam. #1120."""
    return [e for e in entries if e["cases_digest"] == entries[0]["cases_digest"]] if entries else []


class ExamMismatch(ValueError):
    """Two rows ranked against each other sat different exams. #1120."""


class OrderKey(tuple):
    """An order_key that refuses to be compared with one taken on another cases digest. #1120."""

    def __new__(cls, parts, exam=None):
        key = super().__new__(cls, parts)
        key.exam = exam
        return key

    def _same(self, other):
        theirs = getattr(other, "exam", None)
        if self.exam is not None and theirs is not None and self.exam != theirs:
            raise ExamMismatch(f"refusing to rank across exams: cases digest {self.exam or '(none)'} against "
                               f"{theirs or '(none)'}; a pass rate on one says nothing about the other")

    def __lt__(self, other):
        self._same(other)
        return tuple.__lt__(self, other)

    def __le__(self, other):
        self._same(other)
        return tuple.__le__(self, other)

    def __gt__(self, other):
        self._same(other)
        return tuple.__gt__(self, other)

    def __ge__(self, other):
        self._same(other)
        return tuple.__ge__(self, other)

    def __eq__(self, other):
        self._same(other)
        return tuple.__eq__(self, other)

    def __ne__(self, other):
        self._same(other)
        return tuple.__ne__(self, other)

    __hash__ = tuple.__hash__


#: Lanes ranked on a pooled metric before pass rate: an exact-case rate is roughly acc^fields, and stt's is exact orthography. #701.
#: claims balances case recall and specificity, since most cases expect nothing and silence passes them. #791.
PRIMARY = {"decide": "decide_accuracy", "stt": "wer", "claims": "claims_balanced", "repo": "resolved"}
#: Lanes whose primary metric is a summary of strata, paired per stratum rather than per row. #791.
STRATIFIED = {"claims"}
#: Each lane's metrics in rank order after its first key and pass rate; shared names not listed follow by name. #717.
ORDER = {
    "claims": ("claims_balanced", "claims_case_recall", "claims_case_specificity", "claims_empty_rate",
               "claims_schema_valid", "claims_judged_bad"),
    "decide": ("decide_accuracy", "decide_brier", "decide_ece"),
    "music": ("wer", "duration_error_s"),
    "pii": ("pii_f1", "pii_recall", "pii_precision"),
    "repo": ("resolved", "patch_applied", "agent_valid_call_rate"),
    "retrieval": ("retrieval_ndcg", "retrieval_recall"),
    "tts": ("wer", "speaker_similarity"),
}
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


def judged(row: dict) -> int:
    """Rows a model was asked: total less the NEVER_RAN rows; total for a summary that predates the count. #1116."""
    return int(row.get("judged", row.get("total")) or 0)


def judged_rate(row: dict) -> float:
    """Passes over judged rows, so a harness fault is not a failure; pass_rate for a summary without the count. #1116."""
    if "judged" not in row:
        return float(row.get("pass_rate") or 0.0)
    n = judged(row)
    return round(int(row.get("passed") or 0) / n, 3) if n else 0.0


def primary(row: dict, lane: str = "") -> tuple:
    """The first rank key: the lane's pooled metric, else pass rate; a row missing it, or with it over fewer of its judged cases, sorts below."""
    name = PRIMARY.get(lane)
    if not name:
        return (True, 1.0, judged_rate(row))
    got = ranked_metrics(row)
    n, total = (row.get("metric_n") or {}).get(name), judged(row)
    covered = round(min(1.0, n / total), 3) if n is not None and total else 1.0
    return (name in got, covered, got.get(name, 0.0))


def shared_metrics(rows, lane: str = "") -> tuple[str, ...]:
    """Metric names shared by the top rows that report any, so a crashed row cannot erase the lane's metric (#690), in the lane's ORDER (#717)."""
    rows = list(rows)
    top = max((primary(r, lane) for r in rows), default=(True, 0.0))
    names = None
    for row in rows:
        mine = set(ranked_metrics(row))
        if not mine or primary(row, lane) < top:
            continue
        names = mine if names is None else names & mine
    want = ORDER.get(lane, ())
    return tuple(sorted(names or (), key=lambda n: (want.index(n) if n in want else len(want), n)))


def _pick(entries: list[dict], prefer=lambda e: False, lane: str = "") -> dict:
    """The best entry, keyed on the metrics all entries share; exact ties go to `prefer`, then the lowest name."""
    names = shared_metrics((e["row"] for e in entries), lane)
    for e in entries:
        e["key"] = order_key(e.pop("row"), names, lane)
    top = max((e["key"], prefer(e)) for e in entries)
    return min((e for e in entries if (e["key"], prefer(e)) == top),
               key=lambda e: (str(e["candidate"]), int(e.get("run_id") or 0)))


def order_key(row: dict, names, lane: str = "") -> OrderKey:
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

    A row carrying `cases_digest` gives a key that refuses comparison with a key from another digest. #1120.
    """
    ranked = ranked_metrics(row)
    rate = judged_rate(row)
    median = float(row.get("median_s") or 0.0)
    # A candidate that passed less often is worse whatever its metric says: a
    # model that fails half the cases and scores well on the rest is scoring on
    # a different, easier subset.
    # A row missing a shared metric sorts below every row that reports it.
    return OrderKey((primary(row, lane), rate, tuple((n in ranked, ranked.get(n, 0.0)) for n in names), -median),
                    row.get("cases_digest"))


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
            "repo": build_here(cli.DEFAULT_REPO_MODEL),
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


def beaten_in(conn, exam_of=None) -> dict[str, dict]:
    """Per lane, the best candidate from stored runs THE SERVED DEFAULT WAS IN.

    Only within one comparison: a default that was never in the room did not
    lose. "In the room" is its candidate id among the run's rows. #429.
    Only rooms of the lane's current exam, each candidate on all of it. #1120.
    """
    from harness import runs
    wanted = served_ids(conn)
    entries: dict[str, list] = {}
    memo: dict = {}
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
        sitting = {cid: next(iter(runs.summarize(group).items())) for cid, group in groups.items()}
        sitting = {cid: got for cid, got in sitting.items() if on_exam(run, groups[cid], got[0], exam_of, memo)}
        if wanted[lane] not in sitting:
            continue
        for cid, (candidate, row) in sitting.items():
            served = cid == wanted[lane]
            if not served and not can_default(lane, spec_of(conn, run, groups[cid], candidate)):
                continue
            entries.setdefault(lane, []).append({
                "candidate": candidate, "row": {**row, "cases_digest": run.get("cases_digest") or ""},
                "cases_digest": run.get("cases_digest") or "",
                "pass_rate": float(row.get("pass_rate") or 0.0),
                "median_s": float(row.get("median_s") or 0.0),
                "metrics": dict(row.get("metrics") or {}),
                "run": run["path"], "run_id": run["id"],
                "total": int(row.get("total") or 0),
                "match": "exact" if served else "",
                "candidate_id": cid if isinstance(cid, int) else None,
                "family": family})
    # A served default that ties was not beaten.
    return {lane: _pick(newest_exam(got), prefer=lambda e: bool(e["match"]), lane=lane)
            for lane, got in entries.items()}


def disagreements(conn, exam_of=None) -> list[dict]:
    """Where a typed default lost a comparison it was actually in.

    A default in no stored run of the current exam is `unmeasured`, not a disagreement.
    """
    from harness import adopt
    best = beaten_in(conn, exam_of)
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
