"""A knob that sets what counts as a pass is calibrated against labels, never swept by the grade it produces. #1228."""
import pytest

from harness import knobs, sweeps
from tests.test_knob_sweeps import NOW, conn, record, serving  # noqa: F401

GRADERS = {"claims_match_threshold", "claims_min_recall", "craft_geometry_tolerance",
           "craft_render_difference", "runaway_rate", "ocr_max_cer", "stt_max_wer", "tts_max_wer",
           "contamination_hit", "shots_min_f1", "shots_tolerance"}


@pytest.mark.parametrize("knob,lane,limit", [
    ("claims_match_threshold", "claims", "claims_match_threshold>0.5"),
    ("claims_min_recall", "claims", "claims_min_recall>0.5"),
    ("runaway_rate", "tts", "seconds_per_word>0.95"),
    ("craft_geometry_tolerance", "craft", "craft_geometry_tolerance_px>1.0"),
])
def test_a_binding_grader_knob_plans_no_values_and_says_why(conn, serving, knob, lane, limit):
    serving(lane=lane)
    record(conn, lane, 5, 10, limit=limit)
    got = [p for p in sweeps.plan(conn, now=NOW) if p["knob"] == knob]
    assert len(got) == 1 and got[0]["argv"] == {}
    assert "sets the grade" in got[0]["skip"] and "calibrated" in got[0]["skip"]


def test_a_check_timeout_still_plans_its_values(conn, serving):
    record(conn, "code", 5, 10, limit="code_check_timeout_s>15")
    got = [p for p in sweeps.plan(conn, now=NOW) if p["knob"] == "code_check_timeout"]
    assert len(got) == 1 and not got[0]["skip"]
    assert sorted(got[0]["argv"]) == sorted(knobs.KNOBS["code_check_timeout"].values)


def test_the_grader_knobs_are_the_ones_flagged():
    assert {k.name for k in knobs.KNOBS.values() if k.grades} == GRADERS


def test_a_checker_knob_an_eval_can_set_is_a_grade_or_a_time_limit():
    """A new tolerance in harness/checks given a receipt must say it sets the grade. RULE #900."""
    loose = [k.name for k in knobs.KNOBS.values()
             if k.receipt and k.sites[0].startswith("harness/checks/") and not k.grades and k.unit != "s"]
    assert loose == []
