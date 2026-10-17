"""Task fairness labels for repo cases on SWE-bench Verified's two axes, two labellers, Cohen's kappa. #920."""
from __future__ import annotations

import json
from pathlib import Path

from evals import repo

LABELS = Path(__file__).resolve().parent / "cases" / "repo" / "labels.json"
AXES = ("spec", "tests")
#: A score at or above this on either axis drops the case or rewrites its prompt.
FLAG = 2
QUESTIONS = {
    "spec": "Is the issue specified well enough to know what a correct fix is? "
            "0 well specified, 1 some blanks but a sensible reading is clear, "
            "2 vague enough that a correct fix is unclear, 3 nearly impossible to know what is asked.",
    "tests": "Do the hidden tests accept every reasonable fix the issue allows? "
             "0 they accept all reasonable fixes, 1 they accept most and miss some unusual ones, "
             "2 they reject many reasonable fixes (a name, a layout, a detail the issue never asks for), "
             "3 they check something the issue does not ask for at all.",
}


def load(path: Path = LABELS) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def check(labels: dict, case_ids) -> list[str]:
    """What is wrong with the labels for these cases: a missing labeller, a score off the scale, a flag with no reason."""
    out = []
    names = labels.get("labellers") or []
    if len(names) != 2:
        out.append(f"two labellers needed, found {names}")
    for cid in case_ids:
        got = (labels.get("labels") or {}).get(cid) or {}
        for who in names:
            mine = got.get(who)
            if not mine:
                out.append(f"{cid}: no label from {who}")
                continue
            for axis in AXES:
                score = mine.get(axis)
                if score not in (0, 1, 2, 3):
                    out.append(f"{cid}: {who} {axis} score {score!r} is not 0 to 3")
                elif score >= FLAG and not str((mine.get("why") or {}).get(axis) or "").strip():
                    out.append(f"{cid}: {who} scored {axis} {score} with no reason")
    return out


def kappa(a: list, b: list) -> float | None:
    """Cohen's kappa between two raters' labels of the same items; None where chance agreement is total."""
    if len(a) != len(b) or not a:
        raise ValueError("kappa needs two equal, non-empty label lists")
    n = len(a)
    seen = sorted(set(a) | set(b))
    observed = sum(x == y for x, y in zip(a, b)) / n
    expected = sum((a.count(k) / n) * (b.count(k) / n) for k in seen)
    return None if expected == 1 else (observed - expected) / (1 - expected)


def summary(labels: dict, case_ids) -> dict:
    """{kappa, flagged: case -> axes both flag (or Eric settled high), disputed: case -> axes only one flags}."""
    a, b = labels["labellers"]
    rows = [(cid, labels["labels"][cid]) for cid in sorted(case_ids)]
    out = {"kappa": {}, "flagged": {}, "disputed": {}}
    for axis in AXES:
        out["kappa"][axis] = kappa([r[a][axis] for _, r in rows], [r[b][axis] for _, r in rows])
        for cid, r in rows:
            high = [r[a][axis] >= FLAG, r[b][axis] >= FLAG]
            settled = ((labels.get("settled") or {}).get(cid) or {}).get(axis)
            if settled is not None:
                high = [settled >= FLAG] * 2
            if all(high):
                out["flagged"].setdefault(cid, []).append(axis)
            elif any(high):
                out["disputed"].setdefault(cid, []).append(axis)
    return out


def packet(case) -> str:
    """What a labeller reads for one case: the prompt, the reference fix and the hidden tests, no results."""
    p = case.params
    m = repo.mirror(str(p["source_repo"]), need=(p["base"], p["fix"]))
    tests = [path for _, path in repo.changed(m, p["base"], p["fix"]) if repo.is_test_path(path)]
    hidden = repo._git(["--git-dir", str(m), "diff", "--no-renames", p["base"], p["fix"], "--", *tests]
                       ).stdout.decode("utf-8") if tests else ""
    return "\n\n".join([
        f"# Case {case.id}", "## Questions", *(f"{k}: {q}" for k, q in QUESTIONS.items()),
        "## The prompt the model is given (it also sees these files at the base commit: "
        f"{', '.join(p['context_files'])})", case.prompt.strip(),
        "## The reference fix (non-test changes of the fix commit)", repo.reference_diff(m, p["base"], p["fix"]),
        "## The hidden tests (test changes of the fix commit); graded ids: "
        + ", ".join(p["fail_to_pass"]), hidden])
