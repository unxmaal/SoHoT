"""A rubric judge for claims no reviewer saw, counted only once it separates the reviewed ones. #655.

    uv run python -m evals.claims_judge calibrate [--cases DIR]
    uv run python -m evals.claims_judge judge [--run ID] [--cases DIR]
    uv run python -m evals.claims_judge show [--cases DIR]

The judge is the decide lane's served model. Nothing here writes or prints case or
claim text: the calibration file holds counts and case ids, a judgment a digest.
"""
from __future__ import annotations

import argparse
import functools
import hashlib
import json
import random
import re
import sys
import time
from pathlib import Path

from harness.checks import claims as claims_check
from harness.intervals import wilson

#: Bumped whenever the question or the rubric changes: a calibration counts only for its own version.
RUBRIC_VERSION = 1
CALIBRATION_FILE = "judge_calibration.json"
JUDGMENTS_FILE = "judgments.jsonl"
#: The 95% Wilson lower bound each calibration class must reach before the judge counts. #655.
AGREE_MIN = 0.6
#: Each class and whether the judge must call its claims negative (made_up or wrong).
CLASSES = {"reviewed_negative": True, "reviewed_good": False, "planted_wrong": True, "planted_right": False}
SEED = 655
RUBRIC = {
    "good": "the transcript lines it cites support it, and it is a durable, useful technical fact",
    "not_useful": "supported by the cited lines, but trivial, vague or not worth keeping",
    "made_up": "the cited lines do not say it: invented, or from somewhere else",
    "wrong": "the cited lines say something else, or the opposite",
}
SCHEMA = {"verdict": {"type": "enum", "choices": list(claims_check.VERDICTS),
                      "description": "How a careful reviewer would grade this claim against the cited lines.",
                      "choice_descriptions": dict(RUBRIC)}}
_LINE = re.compile(r"^\[(\d+)\]\s+([^:\s]+):\s*(.+)$")
_FLIPS = {"is": "is not", "are": "are not", "can": "cannot", "cannot": "can", "does": "does not",
          "will": "will not", "not": "", "always": "never", "never": "always", "before": "after",
          "after": "before", "higher": "lower", "lower": "higher", "more": "less", "less": "more"}


def question(user: str, claim: str, refs) -> str:
    lines = ", ".join(str(r) for r in refs)
    return (f"Grade one claim extracted from the chat transcript. Speaker: {user}. "
            f"Cited lines: {lines}. Claim: {claim}")


def key(case_id: str, user: str, claim: str, refs) -> str:
    raw = json.dumps([case_id, user, claim, sorted(int(r) for r in refs)], ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def judge_spec() -> str:
    from harness import delegate
    return delegate.lane_model("decide")


def ask_local(case, user: str, claim: str, refs) -> str:
    """The decide lane's verdict on one claim, read against the whole transcript."""
    from harness import delegate, exclusive
    got = delegate.decide(question(user, claim, refs), SCHEMA, context=case.prompt)
    exclusive.beat()
    return str((got.get("answers") or {}).get("verdict") or "")


def _holding():
    """The machine lock for a run of asks, so a queued run waits behind a router restart rather than being refused. #1349."""
    from harness import exclusive
    return exclusive.held("eval", announce=lambda m: print(m, file=sys.stderr, flush=True))


def negative(verdict: str) -> bool:
    return verdict in claims_check.NEGATIVE


def _lines(case) -> dict[int, tuple[str, str]]:
    out = {}
    for line in str(case.prompt or "").splitlines():
        m = _LINE.match(line.strip())
        if m:
            out[int(m.group(1))] = (m.group(2), m.group(3).strip())
    return out


def flip(claim: str) -> str:
    """The claim with every number n made 2n+1 and every flippable word turned; the claim itself when nothing turns."""
    out = re.sub(r"\d+", lambda m: str(2 * int(m.group()) + 1), claim)
    words = out.split(" ")
    words = [_FLIPS[w.lower()] if w.lower() in _FLIPS else w for w in words]
    return re.sub(r"\s+", " ", " ".join(words)).strip()


def reviewed(cases) -> list[dict]:
    """Every reviewed good or negative claim, with the class it calibrates."""
    out = []
    for case in sorted(cases, key=lambda c: c.id):
        for n, r in enumerate(case.assertions.get("reviews") or []):
            cls = ("reviewed_negative" if negative(r["verdict"]) else
                   "reviewed_good" if r["verdict"] == "good" else "")
            if cls:
                out.append({"cls": cls, "case": case, "id": f"{case.id}#{n}",
                            "user": r["user"], "claim": r["claim"], "refs": list(r["refs"])})
    return out


def plants(cases, seed: int = SEED) -> list[dict]:
    """Planted claims with a known verdict: a good claim moved to another transcript or flipped (wrong), a cited line itself (right)."""
    cases = sorted((c for c in cases if c.assertions.get("reviews")), key=lambda c: c.id)
    goods = [g for g in reviewed(cases) if g["cls"] == "reviewed_good"]
    rng = random.Random(seed)
    out = []
    for g in goods:
        lines = _lines(g["case"])
        ref = min(g["refs"])
        if ref in lines and lines[ref][0] == g["user"]:
            out.append({"cls": "planted_right", "kind": "cited_line", "case": g["case"], "id": g["id"],
                        "user": g["user"], "claim": lines[ref][1], "refs": [ref]})
        turned = flip(g["claim"])
        if turned != g["claim"]:
            out.append({"cls": "planted_wrong", "kind": "flipped", "case": g["case"], "id": g["id"],
                        "user": g["user"], "claim": turned, "refs": list(g["refs"])})
        others = [c for c in cases if c.id != g["case"].id and _lines(c)]
        if others:
            host = rng.choice(others)
            n, (user, _) = sorted(_lines(host).items())[0]
            out.append({"cls": "planted_wrong", "kind": "moved", "case": host, "id": g["id"],
                        "user": user, "claim": g["claim"], "refs": [n]})
    return out


def calibrate(cases, ask, judge: str = "", now: float | None = None) -> dict:
    """Each class as k agreeing of n with its interval; calibrated only when every class's lower bound reaches AGREE_MIN."""
    items = reviewed(cases) + plants(cases)
    got = {cls: {"k": 0, "n": 0, "missed": []} for cls in CLASSES}
    kinds: dict[str, dict] = {}
    for item in items:
        verdict = ask(item["case"], item["user"], item["claim"], item["refs"])
        agrees = negative(verdict) == CLASSES[item["cls"]]
        c = got[item["cls"]]
        c["n"] += 1
        c["k"] += agrees
        if not agrees:
            c["missed"].append(item["id"])
        if "kind" in item:
            k = kinds.setdefault(item["kind"], {"k": 0, "n": 0})
            k["n"] += 1
            k["k"] += agrees
    for c in got.values():
        c["ci95"] = list(wilson(c["k"], c["n"]))
        c["missed"] = sorted(c["missed"])
    passed = all(c["n"] and c["ci95"][0] >= AGREE_MIN for c in got.values())
    return {"judge": judge, "rubric_version": RUBRIC_VERSION, "agree_min": AGREE_MIN,
            "at": time.time() if now is None else now, "classes": got, "plants": kinds,
            "calibrated": passed}


def root_of(cases_dir=None) -> Path:
    from evals.core import local_root
    return Path(cases_dir) if cases_dir is not None else local_root() / "claims"


def write_calibration(result: dict, cases_dir=None) -> Path:
    path = root_of(cases_dir) / CALIBRATION_FILE
    path.write_text(json.dumps(result, sort_keys=True, indent=1) + "\n", encoding="utf-8")
    return path


def _stamp(path: Path) -> int:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return 0


def calibration(cases_dir=None) -> dict:
    path = root_of(cases_dir) / CALIBRATION_FILE
    return _read_calibration(str(path), _stamp(path))


@functools.lru_cache(maxsize=4)
def _read_calibration(path: str, stamp: int) -> dict:
    if not stamp:
        return {}
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def counts(cal: dict) -> bool:
    """Whether a stored calibration lets the judge count: it passed, under this rubric."""
    return bool(cal.get("calibrated")) and cal.get("rubric_version") == RUBRIC_VERSION and bool(cal.get("judge"))


def record(judgments: list[dict], cases_dir=None) -> Path:
    path = root_of(cases_dir) / JUDGMENTS_FILE
    with open(path, "a", encoding="utf-8") as f:
        for j in judgments:
            f.write(json.dumps(j, sort_keys=True) + "\n")
    return path


@functools.lru_cache(maxsize=4)
def _read_judgments(path: str, stamp: int) -> dict:
    out: dict[tuple, str] = {}
    if not stamp:
        return out
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        try:
            j = json.loads(line)
        except ValueError:
            continue
        if isinstance(j, dict) and j.get("key"):
            out[(j.get("judge"), j.get("rubric_version"), j["key"])] = str(j.get("verdict") or "")
    return out


def lookup(case_id: str, cases_dir=None):
    """A (user, claim, refs) -> verdict reader over stored judgments by the calibrated judge, or None when the judge does not count."""
    cal = calibration(cases_dir)
    if not counts(cal):
        return None
    path = root_of(cases_dir) / JUDGMENTS_FILE
    stored = _read_judgments(str(path), _stamp(path))
    judge, version = cal["judge"], RUBRIC_VERSION
    return lambda user, claim, refs: stored.get((judge, version, key(case_id, user, claim, refs)))


def unmatched(case, artifact) -> list[tuple]:
    """The claims a reply emitted that match no reviewed claim of the case."""
    emitted = claims_check.parse(artifact, case.params["schema"]) or []
    return claims_check.unmatched(emitted, case.assertions.get("reviews") or [])


def judge_run(conn, run_id: int, cases, ask, judge: str, cases_dir=None) -> list[dict]:
    """Judgments of every unmatched claim in a stored claims run's replies not judged before; digests only."""
    from harness import runs
    by = {c.id: c for c in cases}
    path = root_of(cases_dir) / JUDGMENTS_FILE
    have = _read_judgments(str(path), _stamp(path))
    out, seen = [], set()
    for row in runs.rows(conn, run_id):
        case = by.get(str(row.get("case_id") or "").split("#", 1)[0])
        if case is None or case.assertions.get("expect_empty"):
            continue
        for user, claim, refs in unmatched(case, row.get("output") or ""):
            k = key(case.id, user, claim, refs)
            if k in seen or (judge, RUBRIC_VERSION, k) in have:
                continue
            seen.add(k)
            out.append({"key": k, "case": case.id, "judge": judge, "rubric_version": RUBRIC_VERSION,
                        "verdict": ask(case, user, claim, refs)})
    return out


def _claims_cases(cases_dir=None):
    from evals.core import load_cases, local_root
    root = Path(cases_dir) if cases_dir is not None else local_root()
    return [c for c in load_cases(root, private=True) if c.modality == "claims"]


def render(cal: dict) -> str:
    if not cal:
        return "no judge calibration stored: claims scoring is matched-claims only"
    lines = [f"judge {cal.get('judge')} rubric {cal.get('rubric_version')} agree_min {cal.get('agree_min')}"]
    for cls, c in (cal.get("classes") or {}).items():
        lo, hi = c.get("ci95") or (0.0, 1.0)
        lines.append(f"  {cls}: {c.get('k')}/{c.get('n')} [{lo:.3f}, {hi:.3f}]")
    for kind, c in sorted((cal.get("plants") or {}).items()):
        lines.append(f"  planted {kind}: {c['k']}/{c['n']}")
    lines.append("calibrated: the judge counts" if counts(cal) else
                 "not calibrated: claims scoring stays matched-claims only")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m evals.claims_judge", description=__doc__.splitlines()[0])
    ap.add_argument("action", choices=("calibrate", "judge", "show"))
    ap.add_argument("--cases", default=None, help="local cases root (default $LOCALHARNESS_HOME/cases)")
    ap.add_argument("--run", type=int, default=None, help="claims run id (default the newest)")
    a = ap.parse_args(argv)
    claims_dir = Path(a.cases) / "claims" if a.cases else None
    if a.action == "show":
        print(render(calibration(claims_dir)))
        return 0
    cases = _claims_cases(a.cases)
    if not cases:
        print("no local claims cases", file=sys.stderr)
        return 1
    if a.action == "calibrate":
        from harness import paths
        paths.eval_home(reads_live=True)
        with _holding():
            result = calibrate(cases, ask_local, judge_spec())
        write_calibration(result, claims_dir)
        print(render(result))
        return 0
    cal = calibration(claims_dir)
    if not counts(cal):
        print(render(cal), file=sys.stderr)
        return 1
    if cal["judge"] != judge_spec():
        print(f"the decide lane now serves {judge_spec()}, not the calibrated {cal['judge']}: calibrate again",
              file=sys.stderr)
        return 1
    from harness import memory_store as ms, runs
    conn = ms.connect()
    try:
        run_id = a.run or (runs.newest(conn, lane="claims", tier=runs.MEASURE) or {}).get("id")
        if not run_id:
            print("no claims run stored", file=sys.stderr)
            return 1
        with _holding():
            made = judge_run(conn, int(run_id), cases, ask_local, cal["judge"], claims_dir)
    finally:
        conn.close()
    record(made, claims_dir)
    print(f"{len(made)} unmatched claims judged in run {run_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
