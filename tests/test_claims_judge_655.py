"""A judge for unmatched claims counts only once it separates reviewed and planted claims. #655."""
import json

import pytest

from evals import claims_judge as J
from evals.core import Case
from harness.checks import claims as C

SCHEMA = {"type": "object", "properties": {"c": {"type": "array", "items": {"type": "array"}}}, "required": ["c"]}
SECRET = "zebra quokka narwhal"


def _case(n, reviews):
    lines = [f"[1] member-a{n}b2: The fan header on board {n} runs at 12 volts.",
             f"[2] member-c{n}d4: Jumper J{n} selects the boot ROM, {SECRET}.",
             f"[3] member-a{n}b2: Pin 2 is ground on revision {n}."]
    return Case(id=f"claims-t{n}", modality="claims", prompt="\n".join(lines),
                params={"schema": SCHEMA, "system": "list claims"}, assertions={"reviews": reviews})


def _cases(negatives=6, goods=30):
    out = []
    for n in range(goods):
        reviews = [{"user": f"member-a{n}b2", "claim": f"The board {n} fan header runs at 12 volts.",
                    "refs": [1], "verdict": "good"}]
        if n < negatives:
            reviews.append({"user": f"member-c{n}d4", "claim": f"Jumper J{n} erases the flash chip.", "refs": [2],
                            "verdict": "made_up" if n % 2 else "wrong"})
        out.append(_case(n, reviews))
    return out


def _truth(cases):
    """An oracle that knows every reviewed verdict and every plant."""
    known = {}
    for item in J.reviewed(cases) + J.plants(cases):
        known[(item["case"].id, item["user"], item["claim"], tuple(item["refs"]))] = (
            "wrong" if J.CLASSES[item["cls"]] else "good")
    return lambda case, user, claim, refs: known[(case.id, user, claim, tuple(refs))]


def test_judge_that_calls_everything_good_is_not_calibrated():
    got = J.calibrate(_cases(), lambda *a: "good", "fake")
    assert not got["calibrated"]
    assert got["classes"]["reviewed_negative"]["k"] == 0
    assert got["classes"]["reviewed_good"]["k"] == got["classes"]["reviewed_good"]["n"] == 30


def test_judge_that_misses_one_reviewed_negative_is_not_calibrated():
    cases = _cases()
    truth = _truth(cases)
    miss = "claims-t0#1"

    def ask(case, user, claim, refs):
        return "good" if (case.id, claim) == ("claims-t0", "Jumper J0 erases the flash chip.") else truth(case, user, claim, refs)
    got = J.calibrate(cases, ask, "fake")
    neg = got["classes"]["reviewed_negative"]
    assert (neg["k"], neg["n"], neg["missed"]) == (5, 6, [miss])
    assert neg["ci95"][0] < J.AGREE_MIN and not got["calibrated"]


def test_judge_that_separates_every_class_is_calibrated():
    cases = _cases()
    got = J.calibrate(cases, _truth(cases), "fake", now=1.0)
    assert got["calibrated"] and J.counts(got)
    for c in got["classes"].values():
        assert c["k"] == c["n"] > 0 and c["ci95"][0] >= J.AGREE_MIN
    assert set(got["plants"]) == {"cited_line", "flipped", "moved"}


def test_planted_claims_carry_the_expected_verdicts():
    cases = _cases()
    planted = J.plants(cases)
    right = [p for p in planted if p["kind"] == "cited_line"]
    assert right and all(p["claim"] in p["case"].prompt and p["cls"] == "planted_right" for p in right)
    flipped = [p for p in planted if p["kind"] == "flipped"]
    assert flipped and all("25 volts" in p["claim"] for p in flipped)
    moved = [p for p in planted if p["kind"] == "moved"]
    assert moved and all(p["claim"] not in p["case"].prompt for p in moved)
    assert all(p["cls"] == "planted_wrong" for p in flipped + moved)


@pytest.mark.gauntlet("a-closed-table-fronting-an-open-set", site="evals/claims_judge.py:_FLIPS")
def test_a_word_the_flip_table_does_not_list_is_kept_and_a_claim_with_nothing_to_flip_is_not_planted():
    assert J.flip("Thermistor is hot at 40") == "Thermistor is not hot at 81"
    assert J.flip("Thermistor drifts upward") == "Thermistor drifts upward"
    case = _case(0, [{"user": "member-a0b2", "claim": "Thermistor drifts upward", "refs": [1], "verdict": "good"}])
    assert not [p for p in J.plants([case]) if p["kind"] == "flipped"]


def test_calibration_file_holds_no_case_text(tmp_path):
    cases = _cases()
    # A judge that rejects everything misses every good and right claim, so each lands in a missed list.
    path = J.write_calibration(J.calibrate(cases, lambda *a: "made_up", "fake"), tmp_path)
    text = path.read_text(encoding="utf-8")
    assert "claims-t0#0" in text
    for c in cases:
        for line in c.prompt.splitlines():
            assert line.split(": ", 1)[1] not in text
        for r in c.assertions["reviews"]:
            assert r["claim"] not in text and r["user"] not in text
    assert SECRET not in text


def _judged(tmp_path, verdict, judge="fake", calibrated=True):
    case = _cases(negatives=0, goods=1)[0]
    claim = ("member-c0d4", "Jumper J0 bricks the board.", [2])
    J.write_calibration({"judge": "fake", "rubric_version": J.RUBRIC_VERSION, "calibrated": calibrated}, tmp_path)
    J.record([{"key": J.key(case.id, *claim), "case": case.id, "judge": judge,
               "rubric_version": J.RUBRIC_VERSION, "verdict": verdict}], tmp_path)
    reply = json.dumps({"c": [list(r) for r in [("member-a0b2", "The board 0 fan header runs at 12 volts.", [1]), claim]]})
    return C.check(reply, SCHEMA, case.assertions["reviews"], judged=J.lookup(case.id, tmp_path))


def test_uncalibrated_judgments_leave_scoring_matched_only(tmp_path):
    got = _judged(tmp_path, "made_up", calibrated=False)
    assert got.ok, got.reason
    assert got.metrics["claims_judge_calibrated"] == 0 and "claims_judged_bad" not in got.metrics


def test_calibrated_judged_negative_fails_the_case(tmp_path):
    got = _judged(tmp_path, "made_up")
    assert not got.ok and "judge" in got.reason and "Jumper" not in got.reason
    assert got.metrics["claims_judge_calibrated"] == 1
    assert (got.metrics["claims_judged_bad"], got.metrics["claims_judged_good"]) == (1, 0)


def test_the_lane_scorer_reads_the_stored_judgments():
    from evals import core
    root = core.local_root() / "claims"
    root.mkdir(parents=True)
    case = _cases(negatives=0, goods=1)[0]
    claim = ("member-c0d4", "Jumper J0 bricks the board.", [2])
    reply = json.dumps({"c": [["member-a0b2", "The board 0 fan header runs at 12 volts.", [1]], list(claim)]})
    assert core.score(case, reply).passed
    J.write_calibration({"judge": "fake", "rubric_version": J.RUBRIC_VERSION, "calibrated": True}, root)
    J.record([{"key": J.key(case.id, *claim), "case": case.id, "judge": "fake",
               "rubric_version": J.RUBRIC_VERSION, "verdict": "wrong"}], root)
    got = core.score(case, reply)
    assert not got.passed and got.metrics["claims_judged_bad"] == 1


def test_judgments_from_another_judge_model_are_ignored(tmp_path):
    got = _judged(tmp_path, "made_up", judge="other")
    assert got.ok, got.reason
    assert got.metrics["claims_judge_calibrated"] == 1 and got.metrics["claims_judged_bad"] == 0
    assert got.metrics["claims_unjudged"] == 1
