"""Every shipped code case must be passable by a correct implementation.

A case whose checks no correct answer can satisfy penalises every model
identically and looks exactly like all of them being bad at it. The reference
solutions in cases/code/reference/ are the red-proof: if one of them fails, the
CASE is wrong, not the model.

They also pin down what the prompt actually means. Writing the reference is
where an ambiguous prompt gets found -- twice here, once for whether touching
intervals merge and once for what an empty duration string should do.
"""
from pathlib import Path

import pytest

from evals.core import load_cases
from harness.checks import code

CASES = Path(__file__).resolve().parents[1] / "evals" / "cases"
REFERENCE = CASES / "code" / "reference"

# Load ONLY the code cases, not the whole tree. Loading everything made this
# module hostage to every other lane: the generated stt cases point at audio on
# an external drive, and when that drive did not come back after a reboot,
# `load_cases` raised during COLLECTION and took all 600+ tests with it. A test
# about code cases should not be able to fail because a disk is unplugged.
code_cases = [c for c in load_cases(CASES / "code") if c.modality == "code"]


@pytest.mark.parametrize("case", code_cases, ids=lambda c: c.id)
def test_a_reference_solution_exists(case):
    assert (REFERENCE / f"{case.id}.py").exists(), (
        f"no reference solution for {case.id}; a case nobody has solved is a "
        f"case nobody has checked")


@pytest.mark.parametrize("case", code_cases, ids=lambda c: c.id)
def test_the_reference_solution_passes_every_check(case):
    source = (REFERENCE / f"{case.id}.py").read_text(encoding="utf-8")
    r = code.check(source, case.assertions["checks"])
    assert r.ok, f"{case.id}: {r.reason}"


@pytest.mark.parametrize("case", code_cases, ids=lambda c: c.id)
def test_the_case_has_enough_checks_to_be_discriminating(case):
    """One assertion cannot tell a correct answer from a lucky one."""
    assert len(case.assertions["checks"]) >= 3, case.id


#: The answer a capable-but-careless model writes. The harder tier exists to
#: separate models that all pass the rest, so each must fail its case.
PLAUSIBLY_WRONG = {
    "topo-order": '''
def topo_order(deps):
    out, seen = [], set()
    def visit(n):
        if n in seen:
            return
        seen.add(n)
        for d in sorted(deps.get(n, [])):
            visit(d)
        out.append(n)
    for n in sorted(deps):
        visit(n)
    return out
''',
    "evaluate-expr": '''
def evaluate(s):
    return float(eval(s, {"__builtins__": {}}, {})) if s.strip() else 0.0
''',
    "semver-compare": '''
def compare(a, b):
    def key(v):
        v = v.split("+")[0]
        core, _, pre = v.partition("-")
        return tuple(int(x) for x in core.split(".")), pre or "~"
    ka, kb = key(a), key(b)
    return (ka > kb) - (ka < kb)
''',
    "roman-strict": '''
def to_roman(n):
    if not 1 <= n <= 3999:
        raise ValueError(n)
    vals = [(1000,"M"),(900,"CM"),(500,"D"),(400,"CD"),(100,"C"),(90,"XC"),
            (50,"L"),(40,"XL"),(10,"X"),(9,"IX"),(5,"V"),(4,"IV"),(1,"I")]
    out = ""
    for v, g in vals:
        while n >= v:
            out, n = out + g, n - v
    return out

def from_roman(s):
    m = {"I":1,"V":5,"X":10,"L":50,"C":100,"D":500,"M":1000}
    if not s:
        raise ValueError(s)
    total = 0
    for i, c in enumerate(s):
        v = m[c]
        total += -v if i + 1 < len(s) and m[s[i+1]] > v else v
    return total
''',
    "glob-match": '''
import fnmatch

def match(pattern, s):
    return fnmatch.fnmatchcase(s, pattern)
''',
}


@pytest.mark.parametrize("case_id", sorted(PLAUSIBLY_WRONG))
def test_a_plausible_wrong_answer_fails_the_harder_tier(case_id):
    case = next(c for c in code_cases if c.id == case_id)
    r = code.check(PLAUSIBLY_WRONG[case_id], case.assertions["checks"])
    assert not r.ok, f"{case_id} does not separate a careless answer"
