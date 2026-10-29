"""The shot-boundary checker: per-type recall, precision by claimed label, pooled boundary F1 (#1208)."""
import json

import pytest

from harness import reasons
from harness.checks import shots

TRUTH = {"fps": 24, "frames": 400,
         "transitions": [{"kind": "cut", "first": 50, "last": 50},
                         {"kind": "dissolve", "first": 100, "last": 111},
                         {"kind": "fade", "first": 200, "last": 223},
                         {"kind": "cut", "first": 300, "last": 300}],
         "negatives": [{"kind": "flash", "first": 350, "last": 351}]}


def record(*found):
    return json.dumps({"transitions": [{"at": at, "kind": kind} for at, kind in found]})


def perfect(truth):
    return record(*[(t["first"] if t["kind"] == "cut" else (t["first"] + t["last"]) // 2,
                     "cut" if t["kind"] == "cut" else "gradual") for t in truth["transitions"]])


def test_a_perfect_detector_scores_one_on_every_case():
    got = shots.check(perfect(TRUTH), TRUTH)
    assert got.ok
    m = got.metrics
    assert m["shots_boundary_f1"] == 1.0
    assert m["shots_cut_recall"] == m["shots_dissolve_recall"] == m["shots_fade_recall"] == 1.0
    assert m["shots_cut_precision"] == m["shots_gradual_precision"] == 1.0
    assert m["shots_false"] == 0 and m["shots_negatives_triggered"] == 0.0


def test_a_detector_that_reports_nothing_scores_zero_recall():
    got = shots.check(record(), TRUTH)
    assert not got.ok
    m = got.metrics
    assert m["shots_cut_recall"] == m["shots_dissolve_recall"] == m["shots_fade_recall"] == 0.0
    assert m["shots_boundary_f1"] == 0.0
    assert "shots_cut_precision" not in m and "shots_gradual_precision" not in m


def test_a_detector_that_reports_every_frame_fails_on_precision():
    got = shots.check(record(*[(i, "cut") for i in range(TRUTH["frames"])]), TRUTH)
    assert not got.ok
    assert got.metrics["shots_cut_recall"] == 1.0
    assert got.metrics["shots_cut_precision"] < 0.01
    assert got.metrics["shots_negatives_triggered"] == 1.0


def test_a_detection_matches_at_most_one_transition():
    truth = {"fps": 24, "frames": 100, "negatives": [],
             "transitions": [{"kind": "cut", "first": 10, "last": 10},
                             {"kind": "cut", "first": 12, "last": 12}]}
    got = shots.check(record((11, "cut")), truth).metrics
    assert (got["shots_cut_found"], got["shots_cut_total"]) == (1, 2)
    assert shots.match(truth["transitions"], [9, 13], 2) == [(0, 0), (1, 1)]


def test_tolerance_widens_the_match_window_by_the_knob(monkeypatch):
    truth = {"fps": 24, "frames": 100, "negatives": [],
             "transitions": [{"kind": "dissolve", "first": 40, "last": 51}]}
    assert shots.check(record((54, "gradual")), truth).metrics["shots_dissolve_recall"] == 0.0
    monkeypatch.setattr(shots, "TOLERANCE_FRAMES", 3)
    assert shots.check(record((54, "gradual")), truth).metrics["shots_dissolve_recall"] == 1.0
    assert shots.check(record((54, "gradual")), truth, tol=0).metrics["shots_dissolve_recall"] == 0.0


def test_precision_counts_a_claim_right_only_against_its_own_kind():
    # A cut-labelled detection inside a dissolve finds the dissolve but is a wrong cut claim.
    got = shots.check(record((50, "cut"), (105, "cut"), (210, "gradual"), (300, "")), TRUTH).metrics
    assert got["shots_dissolve_recall"] == 1.0
    assert (got["shots_cut_right"], got["shots_cut_claimed"]) == (2, 3)
    assert (got["shots_gradual_right"], got["shots_gradual_claimed"]) == (1, 1)


def test_boundary_f1_is_a_pooled_ratio():
    got = shots.check(record((50, "cut"), (120, "cut")), TRUTH).metrics
    assert (got["shots_2tp"], got["shots_f1_den"]) == (2, 2 + 1 + 3)
    assert got["shots_boundary_f1"] == round(2 / 6, 4)


def test_a_case_with_no_transitions_passes_only_with_nothing_found():
    truth = {"fps": 24, "frames": 200, "transitions": [],
             "negatives": [{"kind": "whip", "first": 80, "last": 87}]}
    quiet = shots.check(record(), truth)
    assert quiet.ok and quiet.metrics["shots_boundary_f1"] == 1.0
    assert "shots_cut_recall" not in quiet.metrics
    noisy = shots.check(record((83, "cut")), truth)
    assert not noisy.ok and noisy.metrics["shots_negatives_triggered"] == 1.0


def test_the_pass_bar_is_the_min_f1_knob(monkeypatch):
    got = record((50, "cut"), (105, "gradual"), (210, "gradual"))
    assert not shots.check(got, TRUTH).ok
    monkeypatch.setattr(shots, "MIN_F1", 0.85)
    assert shots.check(got, TRUTH).ok


def test_a_refused_record_fails_as_a_backend_fault_with_no_metrics():
    got = shots.check(json.dumps({"refused": "mps disagrees with cpu"}), TRUTH)
    assert not got.ok and got.failure_class == reasons.BACKEND_FAULT
    assert "mps disagrees" in got.reason and not got.metrics


def test_a_failed_clip_names_the_knob_that_bound():
    under_bar = shots.check(record((50, "cut"), (105, "gradual"), (210, "gradual")), TRUTH)
    assert under_bar.limit == "shots_min_f1>0.9"
    near = shots.check(record((50, "cut"), (115, "gradual"), (210, "gradual"), (300, "cut")), TRUTH)
    assert near.limit == "shots_tolerance_frames>2"
    assert shots.check(perfect(TRUTH), TRUTH).limit == ""
    refused = {"refused": "mps differs", "agreement": {"max_prob_diff": 0.9, "bound": 0.05}}
    assert shots.check(json.dumps(refused), TRUTH).limit == "shots_mps_max_prob_diff>0.05"


@pytest.mark.parametrize("bad",["not json", json.dumps({"transitions": [{"at": "x"}]}),
                                 json.dumps({"transitions": [{"at": 3, "kind": "wipe"}]})])
def test_a_malformed_record_fails_and_names_why(bad):
    got = shots.check(bad, TRUTH)
    assert not got.ok and got.reason
