"""The shots lane: generated clips with exact truth, its engines, knobs and controls (#1208)."""
import shutil
import subprocess
from collections import Counter
from pathlib import Path

import pytest

from evals import core, importers
from evals.core import load_cases, score
from evals.importers import shots_synth
from harness import engines, knobs, lanes, shot_detect

CASES = importers.CASES / "shots" / "shots_synth"
FFMPEG = pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
                            reason="needs ffmpeg and ffprobe")


@pytest.fixture(scope="module")
def committed():
    return load_cases(CASES)


def gray(clip: Path, w=64, h=36) -> list[bytes]:
    raw = subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-i", str(clip), "-vf", f"scale={w}:{h}",
                          "-pix_fmt", "gray", "-f", "rawvideo", "-"], check=True, capture_output=True).stdout
    return [raw[i:i + w * h] for i in range(0, len(raw), w * h)]


def jumps(frames: list[bytes]) -> list[float]:
    """Mean absolute change from frame i-1 to frame i, index i; 0 at frame 0."""
    return [0.0] + [sum(abs(a - b) for a, b in zip(x, y)) / len(x) for x, y in zip(frames, frames[1:])]


def luma(frame: bytes) -> float:
    return sum(frame) / len(frame)


# --- the generator ---------------------------------------------------------

def test_the_generator_is_deterministic_for_a_seed():
    assert shots_synth.fetch() == shots_synth.fetch()
    assert shots_synth.fetch() != shots_synth.fetch(seed=shots_synth.SEED + 1)


def test_join_kinds_and_lengths_are_allocated_exactly_across_the_set():
    rows = [r for r in shots_synth.fetch() if r["role"] == "exam"]
    got = Counter((j["kind"], j["frames"]) for r in rows for j in r["spec"]["joins"])
    per = shots_synth.JOINS_PER_CLIP * shots_synth.CLIPS
    assert got[("cut", 0)] == round(per * shots_synth.CUT_SHARE)
    gradual = {k: v for k, v in got.items() if k[0] != "cut"}
    assert set(gradual) == {(k, n) for k in ("dissolve", "fade") for n in shots_synth.GRADUAL_FRAMES}
    assert len(set(gradual.values())) == 1
    assert all(len(r["spec"]["joins"]) == shots_synth.JOINS_PER_CLIP for r in rows)


def test_truth_follows_the_spec():
    spec = {"fps": 24, "width": 64, "height": 36,
            "segments": [{"frames": 40, "flash": [[10, 11]]}, {"frames": 50}, {"frames": 60, "whip": [[20, 25]]}],
            "joins": [{"kind": "cut", "frames": 0}, {"kind": "fade", "frames": 12}]}
    got = shots_synth.truth(spec)
    assert got["transitions"] == [{"kind": "cut", "first": 40, "last": 40},
                                  {"kind": "fade", "first": 78, "last": 89}]
    assert got["negatives"] == [{"kind": "flash", "first": 10, "last": 11},
                                {"kind": "whip", "first": 98, "last": 103}]
    assert got["frames"] == 40 + 50 + 60 - 12


def test_every_shot_keeps_clean_frames_around_its_transitions():
    for row in shots_synth.fetch():
        spec = row["spec"]
        joins = [{"frames": 0}, *spec["joins"], {"frames": 0}]
        for i, seg in enumerate(spec["segments"]):
            assert seg["frames"] >= joins[i]["frames"] + joins[i + 1]["frames"] + shots_synth.CLEAN_FRAMES
            for kind in ("flash", "whip"):
                for a, b in seg.get(kind) or ():
                    assert joins[i]["frames"] + shots_synth.CLEAN_FRAMES // 2 <= a <= b
                    assert b < seg["frames"] - joins[i + 1]["frames"] - shots_synth.CLEAN_FRAMES // 2


def test_the_controls_are_an_all_cut_and_a_no_cut_clip(committed):
    by = {c.id: c for c in committed}
    allcut, nocut = by["shots-control-all-cut"], by["shots-control-no-cut"]
    assert allcut.assertions["transitions"] and {t["kind"] for t in allcut.assertions["transitions"]} == {"cut"}
    assert nocut.assertions["transitions"] == [] and len(nocut.assertions["negatives"]) >= 3


def test_the_committed_cases_are_what_the_generator_writes():
    want = {f"{c['id']}.yaml": importers._dump(shots_synth, c)
            for c in (shots_synth.case_of(r) for r in shots_synth.fetch())}
    have = {p.name: p.read_text(encoding="utf-8") for p in CASES.glob("*.yaml")}
    assert have == want


def test_the_set_is_registered_and_carries_no_film_material(committed):
    assert importers.Source("shots_synth", "shots") in importers.REGISTRY
    for c in committed:
        assert all(s["source"] in shots_synth.SOURCES for s in c_spec(c)["segments"])


def c_spec(case):
    import yaml
    return yaml.safe_load(case.source.read_text(encoding="utf-8"))["attribution"]["spec"]


@FFMPEG
def test_the_hard_cuts_in_a_generated_clip_are_where_the_truth_says(tmp_path):
    spec = shots_synth.control_spec("all-cut", seed=3, shots=6)
    clip = tmp_path / "c.mp4"
    truth = shots_synth.build(spec, clip)
    j = jumps(gray(clip))
    for t in truth["transitions"]:
        at = t["first"]
        assert all(j[at] > j[i] for i in range(at - 3, at + 4) if i != at), (at, j[at - 3:at + 4])


@FFMPEG
def test_a_fade_in_a_generated_clip_goes_black_inside_its_truth_window(tmp_path):
    spec = {"fps": 24, "width": 128, "height": 72,
            "segments": [shots_synth.segment("testsrc2", 60, seed=1), shots_synth.segment("mandelbrot", 60, seed=2)],
            "joins": [{"kind": "fade", "frames": 24}]}
    clip = tmp_path / "f.mp4"
    (fade,) = shots_synth.build(spec, clip)["transitions"]
    frames = gray(clip)
    darkest = min(range(len(frames)), key=lambda i: luma(frames[i]))
    assert fade["first"] < darkest < fade["last"] and luma(frames[darkest]) < 20
    # ffmpeg's fadeblack is not symmetric: it reaches black a few frames in, then fades up to the last frame.
    assert abs(luma(frames[fade["first"]]) - luma(frames[fade["first"] - 1])) < 5
    assert luma(frames[fade["last"]]) > luma(frames[fade["last"] - 4]) + 10


@FFMPEG
def test_a_planted_flash_is_where_the_truth_says(tmp_path):
    seg = {**shots_synth.segment("mandelbrot", 48, seed=4), "flash": [[20, 21]]}
    spec = {"fps": 24, "width": 128, "height": 72, "segments": [seg], "joins": []}
    clip = tmp_path / "w.mp4"
    shots_synth.build(spec, clip)
    frames = gray(clip)
    assert luma(frames[20]) > 200 and luma(frames[21]) > 200 and luma(frames[18]) < 180


@FFMPEG
def test_every_committed_clip_has_the_frame_count_its_truth_says(committed):
    for c in committed:
        got = subprocess.run(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries",
                              "stream=nb_read_frames,width,height", "-of", "csv=p=0", str(c.input_file)],
                             check=True, capture_output=True, text=True).stdout.strip().split(",")
        assert int(got[-1]) == c.assertions["frames"], c.id


def test_committed_clips_stay_small(committed):
    sizes = [c.input_file.stat().st_size for c in committed]
    assert max(sizes) <= shots_synth.MAX_CLIP_BYTES and sum(sizes) <= 12 * shots_synth.MAX_CLIP_BYTES


# --- scoring the committed set ---------------------------------------------

def test_the_negative_control_separates_reference_from_responders(committed):
    got = importers.negative_control(committed, shots_synth.RESPONDERS, shots_synth.passes)
    n = len(committed)
    assert {k: v[0] for k, v in got.items()} == {"reference": n, "nothing": 1, "every-frame": 0}


def test_a_case_scores_through_the_lane_checker(committed, tmp_path):
    case = next(c for c in committed if c.id == "shots-control-all-cut")
    out = tmp_path / "x.json"
    out.write_text(shots_synth.RESPONDERS["reference"](case), encoding="utf-8")
    got = score(case, out)
    assert got.passed and got.metrics["shots_cut_recall"] == 1.0


def test_lane_ratios_pool_over_counts():
    for name in ("shots_cut_recall", "shots_dissolve_recall", "shots_fade_recall", "shots_cut_precision",
                 "shots_gradual_precision", "shots_boundary_f1", "shots_negatives_triggered"):
        assert name in core.RATIO_METRICS and core.METRIC_DIRECTION[name] in ("higher", "lower")
    assert core.METRIC_DIRECTION["shots_negatives_triggered"] == "lower"


def test_the_lane_ranks_on_pooled_boundary_f1_then_gradual_recall():
    from harness import winners
    better = {"metrics": {"shots_boundary_f1": 0.95, "shots_dissolve_recall": 0.9}, "total": 12, "passed": 1}
    worse = {"metrics": {"shots_boundary_f1": 0.80, "shots_dissolve_recall": 1.0}, "total": 12, "passed": 12}
    assert winners.primary(better, "shots") > winners.primary(worse, "shots")
    assert winners.ORDER["shots"][:2] == ("shots_boundary_f1", "shots_dissolve_recall")
    assert all(core.METRIC_DIRECTION[m] != "neutral" for m in winners.ORDER["shots"])


# --- engines ---------------------------------------------------------------

def test_transnetv2_engines_name_their_device_and_carry_the_knobs(monkeypatch):
    cpu = engines.resolve("transnetv2:cpu")
    assert cpu.modality == "shots" and cpu.output_suffix == ".json" and cpu.name == "transnetv2/cpu"
    monkeypatch.setattr(shot_detect, "SINGLE_THRESHOLD", 0.42)
    argv = cpu.argv("find the boundaries", Path("o.json"), {"input": "c.mp4"})
    assert argv[1:6] == ["transnetv2", "--device", "cpu", "--clip", "c.mp4"]
    assert argv[argv.index("--threshold") + 1] == "0.42"
    assert engines.resolve("transnetv2:mps").name == "transnetv2/mps"
    with pytest.raises(ValueError, match="device"):
        engines.resolve("transnetv2:cuda")


def test_scenedetect_engines_name_their_detector():
    got = engines.resolve("scenedetect:adaptive")
    assert got.name == "scenedetect/adaptive" and got.modality == "shots"
    argv = got.argv("p", Path("o.json"), {"input": "c.mp4"})
    assert argv[1:4] == ["scenedetect", "--detector", "adaptive"]
    assert argv[argv.index("--threshold") + 1] == str(shot_detect.ADAPTIVE_THRESHOLD)
    with pytest.raises(ValueError, match="detector"):
        engines.resolve("scenedetect:histogram")
    with pytest.raises(ValueError, match="input"):
        got.argv("p", Path("o.json"), {})


# --- the lane --------------------------------------------------------------

def test_shots_is_an_eval_lane_discovery_never_searches():
    assert "shots" in lanes.BY_HAND and "shots" not in lanes.ALL
    assert "shots" in core.MODALITIES and "shots" in core.INPUT_MODALITIES


def test_every_shots_limit_is_a_registered_knob_with_a_unit_and_evidence():
    reg = knobs.KNOBS
    for name, site in (("shots_tolerance", "harness/checks/shots.py:TOLERANCE_FRAMES"),
                       ("shots_min_f1", "harness/checks/shots.py:MIN_F1"),
                       ("shots_transnet_threshold", "harness/shot_detect.py:SINGLE_THRESHOLD"),
                       ("shots_transnet_span_threshold", "harness/shot_detect.py:SPAN_THRESHOLD"),
                       ("shots_gap_close", "harness/shot_detect.py:GAP_CLOSE_FRAMES"),
                       ("shots_cut_run", "harness/shot_detect.py:CUT_RUN_FRAMES"),
                       ("shots_min_shot", "harness/shot_detect.py:MIN_SHOT_FRAMES"),
                       ("shots_adaptive_threshold", "harness/shot_detect.py:ADAPTIVE_THRESHOLD"),
                       ("shots_content_threshold", "harness/shot_detect.py:CONTENT_THRESHOLD"),
                       ("shots_mps_max_prob_diff", "harness/shot_detect.py:MPS_MAX_PROB_DIFF")):
        k = reg[name]
        assert k.sites[0] == site and k.unit and len(k.note) > 40 and len(k.values) >= 3, name
        assert k.lanes == ("shots",) and k.receipt == "knobs", name
