"""The shot detector child: TransNetV2 runs to transitions, the MPS agreement refusal, PySceneDetect (#1208)."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from harness import shot_detect


def above(n, *spans):
    out = [False] * n
    for a, b in spans:
        out[a:b + 1] = [True] * (b - a + 1)
    return out


def test_transnetv2_places_a_gradual_run_at_its_midpoint_and_a_cut_after_its_run():
    got = shot_detect.runs(above(200, (49, 49), (72, 97)), cut_run=2)
    assert [(r["at"], r["kind"]) for r in got] == [(50, "cut"), (85, "gradual")]


def test_a_run_touching_the_first_frame_is_no_transition():
    assert shot_detect.runs(above(50, (0, 3), (20, 20)), cut_run=2) == [
        {"at": 21, "kind": "cut", "first": 20, "last": 20}]


def test_gaps_up_to_the_knob_close_into_one_run():
    flags = above(60, (10, 12), (17, 20))
    assert len(shot_detect.runs(shot_detect.close_gaps(flags, 4), 2)) == 1
    assert len(shot_detect.runs(shot_detect.close_gaps(flags, 3), 2)) == 2


def test_a_shot_shorter_than_the_minimum_drops_the_later_transition():
    got = shot_detect.drop_short([{"at": 10}, {"at": 15}, {"at": 30}], 8)
    assert [t["at"] for t in got] == [10, 30]


def test_heads_combine_on_either_threshold():
    n = 120
    single = [0.0] * n
    span = [0.0] * n
    single[40] = 0.9
    for i in range(70, 90):
        span[i] = 0.6
    got = shot_detect.transnet_transitions(single, span, threshold=0.5, span_threshold=0.3, gap=4,
                                           cut_run=2, min_shot=8)
    assert [(t["at"], t["kind"]) for t in got] == [(41, "cut"), (80, "gradual")]
    assert shot_detect.transnet_transitions(single, span, threshold=0.95, span_threshold=0.7, gap=4,
                                            cut_run=2, min_shot=8) == []


def fake_probs(table):
    def probabilities(clip, device):
        return table[device]
    return probabilities


def run_child(tmp_path, monkeypatch, table, device):
    monkeypatch.setattr(shot_detect, "probabilities", fake_probs(table))
    out = tmp_path / "out.json"
    shot_detect.main(["transnetv2", "--device", device, "--clip", str(tmp_path / "c.mp4"), "--out", str(out)])
    return json.loads(out.read_text(encoding="utf-8"))


def probs(n, cut_at):
    single = [0.0] * n
    single[cut_at - 1] = 0.9
    return single, [0.0] * n


def test_an_mps_run_that_disagrees_with_cpu_is_refused(tmp_path, monkeypatch):
    got = run_child(tmp_path, monkeypatch, {"cpu": probs(100, 40), "mps": probs(100, 60)}, "mps")
    assert "transitions" not in got
    assert "mps" in got["refused"] and "cpu" in got["refused"]


def test_an_mps_run_that_agrees_with_cpu_is_recorded(tmp_path, monkeypatch):
    cpu = probs(100, 40)
    mps = ([p + 0.01 for p in cpu[0]], cpu[1])
    got = run_child(tmp_path, monkeypatch, {"cpu": cpu, "mps": mps}, "mps")
    assert "refused" not in got
    assert got["transitions"] == [{"at": 40, "kind": "cut", "first": 39, "last": 39}]
    assert got["device"] == "mps" and got["agreement"]["max_prob_diff"] == pytest.approx(0.01)


def test_the_agreement_bound_is_the_knob(monkeypatch):
    cpu = probs(100, 40)
    mps = ([p + 0.04 for p in cpu[0]], cpu[1])
    assert shot_detect.disagreement(cpu, mps, max_diff=0.05) == ""
    assert "0.04" in shot_detect.disagreement(cpu, mps, max_diff=0.03)


def test_a_cpu_run_never_computes_mps(tmp_path, monkeypatch):
    got = run_child(tmp_path, monkeypatch, {"cpu": probs(100, 40)}, "cpu")
    assert got["device"] == "cpu" and [t["at"] for t in got["transitions"]] == [40]


def test_the_thresholds_on_the_command_line_reach_the_detector(tmp_path, monkeypatch):
    monkeypatch.setattr(shot_detect, "probabilities", fake_probs({"cpu": probs(100, 40)}))
    out = tmp_path / "out.json"
    shot_detect.main(["transnetv2", "--device", "cpu", "--clip", "c.mp4", "--out", str(out), "--threshold", "0.95"])
    assert json.loads(out.read_text(encoding="utf-8"))["transitions"] == []


SHOTS_PYTHON = os.environ.get("SHOTS_PYTHON", "")


@pytest.mark.skipif(not (SHOTS_PYTHON and shutil.which("ffmpeg")),
                    reason="needs SHOTS_PYTHON, an interpreter with transnetv2-pytorch, and ffmpeg")
def test_real_transnetv2_mps_against_cpu_on_a_generated_clip(tmp_path):
    from evals.importers import shots_synth
    spec = shots_synth.control_spec("all-cut", seed=7, shots=6)
    clip = tmp_path / "c.mp4"
    shots_synth.build(spec, clip)
    out = tmp_path / "out.json"
    repo = Path(__file__).resolve().parent.parent
    r = subprocess.run([SHOTS_PYTHON, "-m", "harness.shot_detect", "transnetv2", "--device", "mps",
                        "--clip", str(clip), "--out", str(out)], cwd=repo, capture_output=True, text=True,
                       env={**os.environ, "PYTHONPATH": str(repo)})
    assert r.returncode == 0, r.stderr[-2000:]
    got = json.loads(out.read_text(encoding="utf-8"))
    if "agreement" not in got:
        assert sys.platform != "darwin" and "not available" in got["refused"]
        return
    agree = got["agreement"]
    agreed = agree["max_prob_diff"] <= shot_detect.MPS_MAX_PROB_DIFF and agree["same_transitions"]
    assert ("refused" in got) == (not agreed)


@pytest.mark.gauntlet("each-half-verified-against-its-own-spec-the-seam-against-nothing", site="env:SHOTS_BIN")
def test_the_engine_argv_is_what_the_detector_child_accepts(monkeypatch, tmp_path):
    from harness import engines
    repo = Path(__file__).resolve().parent.parent
    monkeypatch.delenv("SHOTS_BIN", raising=False)
    out = tmp_path / "o.json"
    argv = engines.resolve("transnetv2:mps").argv("p", out, {"input": "c.mp4"})
    assert Path(argv[0]) == repo / "scripts" / "shots.sh"
    assert 'exec "$PY" -m harness.shot_detect "$@"' in (repo / "scripts" / "shots.sh").read_text(encoding="utf-8")
    monkeypatch.setattr(shot_detect, "probabilities", fake_probs({"cpu": probs(100, 40), "mps": probs(100, 40)}))
    assert shot_detect.main(argv[1:]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["agreement"]["same_transitions"]
    content = engines.resolve("scenedetect:content").argv("p", out, {"input": "c.mp4"})
    got = shot_detect.parser().parse_args(content[1:])
    assert (got.engine, got.detector, got.threshold) == ("scenedetect", "content", shot_detect.CONTENT_THRESHOLD)
