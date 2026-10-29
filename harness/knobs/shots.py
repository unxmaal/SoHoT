"""Knobs of the shots lane: matching tolerance, the pass bar, and each detector's thresholds (#1208)."""
from harness.knobs.base import _k

_LANE = dict(lanes=("shots",), receipt="knobs")
#: A detector setting shows binding only as a clip falling under the F1 bar.
_DETECTOR = dict(_LANE, binds_via="shots_min_f1")

KNOBS = [
    _k("shots_adaptive_threshold", ["harness/shot_detect.py:ADAPTIVE_THRESHOLD"], [1.5, 2.0, 3.0, 3.5, 5.0],
       unit="factor", **_DETECTOR,
       note="PySceneDetect AdaptiveDetector's ratio of a frame's content change to its neighbours' mean; 3.0 is "
            "scenedetect 0.7.2's default; kubrick #2 chose 3.5 on real film with a flash guard (hard-cut F1 0.985 "
            "held out), and the baseline here runs unguarded at the library default (#1208)"),
    _k("shots_content_threshold", ["harness/shot_detect.py:CONTENT_THRESHOLD"], [15.0, 20.0, 27.0, 35.0],
       unit="score", **_DETECTOR,
       note="PySceneDetect ContentDetector's HSV change score a cut needs; 27 is scenedetect 0.7.2's default; "
            "kubrick #2 swept 15 to 40 on film (#1208)"),
    _k("shots_cut_run", ["harness/shot_detect.py:CUT_RUN_FRAMES"], [1, 2, 3],
       unit="frames", **_DETECTOR,
       note="a TransNetV2 above-threshold run this long or shorter is a cut placed after it, longer a gradual "
            "placed at its midpoint (KB RULE #1058); on the prototype clip every one of 15 transitions landed "
            "within tolerance at 2 (#1208)"),
    _k("shots_gap_close", ["harness/shot_detect.py:GAP_CLOSE_FRAMES"], [0, 4, 8],
       unit="frames", **_DETECTOR,
       note="below-threshold frames between two TransNetV2 runs that still make one transition; kubrick #2 "
            "closed 4 so a dissolve whose probability dips mid-way is one event, not two (#1208)"),
    _k("shots_min_f1", ["harness/checks/shots.py:MIN_F1"], [0.8, 0.9, 0.95],
       unit="share", grades=True, limit="shots_min_f1", **_LANE,
       note="boundary F1 a clip passes at; prototype clip 2026-10-25: TransNetV2 on CPU 0.91 (15 of 15 found, "
            "3 false) and PySceneDetect adaptive 0.75 (9 of 15, 0 false), so 0.9 separates finding the gradual "
            "transitions from missing them (#1208)"),
    _k("shots_min_shot", ["harness/shot_detect.py:MIN_SHOT_FRAMES"], [1, 4, 8, 12],
       unit="frames", **_DETECTOR,
       note="frames a detected shot must last, applied to both detectors; kubrick #2 used 8, PySceneDetect's own "
            "default is 15; the committed clips' shortest shot is 12 frames, so 8 never drops a true one (#1208)"),
    _k("shots_mps_max_prob_diff", ["harness/shot_detect.py:MPS_MAX_PROB_DIFF"], [0.01, 0.05, 0.1],
       unit="share", limit="shots_mps_max_prob_diff", **_LANE,
       note="largest per-frame probability gap between MPS and CPU under which an MPS run is recorded; measured "
            "2026-10-25 with torch 2.6.0: MPS (CPU fallback for conv3d) differs by up to 0.998, mean 0.129, over "
            "1058 frames; CPU against itself 0 (#1208)"),
    _k("shots_tolerance", ["harness/checks/shots.py:TOLERANCE_FRAMES"], [0, 1, 2, 4],
       unit="frames", grades=True, limit="shots_tolerance_frames", **_LANE,
       note="frames a detection may sit outside a transition and still find it; TransNetV2's span head stays high "
            "1-2 frames past a gradual's last frame (KB RULE #1058); 2 frames is 83 ms at 24 fps, and kubrick's "
            "known sets scored at 2 (#1208)"),
    _k("shots_transnet_span_threshold", ["harness/shot_detect.py:SPAN_THRESHOLD"], [0.2, 0.3, 0.4, 0.5],
       unit="share", **_DETECTOR,
       note="TransNetV2 whole-transition head probability that marks a frame inside a transition; kubrick #2 "
            "combined span > 0.3 with the single head and reached dissolve recall 0.83 and fade 1.0 on an "
            "untouched real-film set (#1208)"),
    _k("shots_transnet_threshold", ["harness/shot_detect.py:SINGLE_THRESHOLD"], [0.3, 0.4, 0.5, 0.6],
       unit="share", **_DETECTOR,
       note="TransNetV2 single-frame head probability that marks a boundary; 0.5 is the package's default and "
            "kubrick #2's, hard-cut F1 0.959 on real film (#1208)"),
]

#: The generator's set shape: written into the committed cases, so a change is a new exam digest, never a run's outcome.
_SET = "sizes the generated shots set; the committed cases carry it and the case digest changes with it"
NOT_GATING = {
    "evals/importers/shots_synth.py:MAX_CLIP_BYTES": "a test's ceiling on a committed clip's size; no case's "
                                                     "outcome reads it",
    "evals/importers/shots_synth.py:CLIPS": _SET,
    "evals/importers/shots_synth.py:JOINS_PER_CLIP": _SET,
    "evals/importers/shots_synth.py:FLASH_SHARE": _SET,
    "evals/importers/shots_synth.py:WHIP_SHARE": _SET,
    "evals/importers/shots_synth.py:WHIP_FRAMES": _SET,
}
