"""Shot-boundary detectors as a child process: TransNetV2 and PySceneDetect over one clip (#1208).

Runs in the shots venv (scripts/shots.sh); torch, transnetv2_pytorch and
scenedetect are imported only there. Writes {"transitions": [{"at", "kind",
"first", "last"}], "device", "frames", "seconds"} or {"refused": why}.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

#: TransNetV2 single-frame head probability above which a frame is a boundary.
SINGLE_THRESHOLD = 0.5
#: TransNetV2 whole-transition head probability above which a frame is inside a transition.
SPAN_THRESHOLD = 0.3
#: Below-threshold frames between two runs that still join them into one transition.
GAP_CLOSE_FRAMES = 4
#: A run this long or shorter is a cut, reported at the first frame after it; longer is gradual, at its midpoint.
CUT_RUN_FRAMES = 2
#: Frames a shot must last; a transition closer than this to the previous one is dropped.
MIN_SHOT_FRAMES = 8
#: PySceneDetect AdaptiveDetector's adaptive_threshold (its library default).
ADAPTIVE_THRESHOLD = 3.0
#: PySceneDetect ContentDetector's threshold (its library default).
CONTENT_THRESHOLD = 27.0
#: Largest per-frame probability gap between MPS and CPU under which an MPS run counts as TransNetV2's.
MPS_MAX_PROB_DIFF = 0.05
#: CPU is TransNetV2's reference device; an MPS run counts only where it matches it.
REFERENCE_DEVICE, CHECKED_DEVICE = "cpu", "mps"
TRANSNET_DEVICES = (REFERENCE_DEVICE, CHECKED_DEVICE)
DETECTORS = ("adaptive", "content")
#: TransNetV2's input frame size, width x height.
_W, _H = 48, 27


def close_gaps(above: list[bool], gap: int) -> list[bool]:
    """`above` with every run of at most `gap` False frames between two True frames set True."""
    out = list(above)
    idx = [i for i, a in enumerate(above) if a]
    for a, b in zip(idx, idx[1:]):
        if 1 < b - a <= gap + 1:
            out[a:b] = [True] * (b - a)
    return out


def runs(above: list[bool], cut_run: int) -> list[dict]:
    """Each run of True frames as a transition; a run starting at frame 0 is the clip's start, not a boundary."""
    out, start = [], None
    for i, a in enumerate([*above, False]):
        if a and start is None:
            start = i
        elif not a and start is not None:
            if start > 0:
                cut = i - start <= cut_run
                out.append({"at": i if cut else (start + i) // 2, "kind": "cut" if cut else "gradual",
                            "first": start, "last": i - 1})
            start = None
    return out


def drop_short(transitions: list[dict], frames: int) -> list[dict]:
    """Transitions at least `frames` after the one kept before them (the first after frame 0)."""
    kept, last = [], -frames
    for t in transitions:
        if t["at"] - last >= frames:
            kept.append(t)
            last = t["at"]
    return kept


def transnet_transitions(single, span, *, threshold: float, span_threshold: float, gap: int,
                         cut_run: int, min_shot: int) -> list[dict]:
    """TransNetV2's two heads to transitions: either head over its threshold, gaps closed, runs placed."""
    above = [s > threshold or p > span_threshold for s, p in zip(single, span)]
    return drop_short(runs(close_gaps(above, gap), cut_run), min_shot)


def disagreement(cpu, mps, max_diff: float, **knobs) -> str:
    """Why an MPS run is not CPU's answer, or "" when every frame agrees within max_diff and the transitions match."""
    stats = agreement(cpu, mps, **knobs)
    if len(cpu[0]) != len(mps[0]):
        return f"mps scored {len(mps[0])} frames and cpu {len(cpu[0])}"
    if stats["max_prob_diff"] > max_diff:
        return (f"mps probabilities differ from cpu by up to {stats['max_prob_diff']:.4g} "
                f"(bound {max_diff}) at frame {stats['worst_frame']}")
    if not stats["same_transitions"]:
        return f"mps finds {stats['mps_transitions']} transitions where cpu finds {stats['cpu_transitions']}"
    return ""


def _knobs(**over) -> dict:
    got = {"threshold": SINGLE_THRESHOLD, "span_threshold": SPAN_THRESHOLD, "gap": GAP_CLOSE_FRAMES,
           "cut_run": CUT_RUN_FRAMES, "min_shot": MIN_SHOT_FRAMES}
    got.update({k: v for k, v in over.items() if v is not None})
    return got


def agreement(cpu, mps, **knobs) -> dict:
    diffs = [abs(a - b) for head in (0, 1) for a, b in zip(cpu[head], mps[head])]
    worst = max(range(len(diffs)), key=diffs.__getitem__) if diffs else 0
    k = _knobs(**knobs)
    a, b = transnet_transitions(*cpu, **k), transnet_transitions(*mps, **k)
    return {"max_prob_diff": round(max(diffs, default=0.0), 6), "worst_frame": worst % max(1, len(cpu[0])),
            "cpu_transitions": len(a), "mps_transitions": len(b), "same_transitions": a == b}


def frames_of(clip: str) -> bytes:
    """The clip decoded to TransNetV2's input, rgb24 at 48x27."""
    return subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-i", clip,
                           "-vf", f"scale={_W}:{_H}", "-pix_fmt", "rgb24", "-f", "rawvideo", "-"],
                          check=True, capture_output=True).stdout


def probabilities(clip: str, device: str) -> tuple[list[float], list[float]]:
    """Per-frame (single-frame head, whole-transition head) probabilities on `device`."""
    if device == "mps":
        # MPS lacks TransNetV2's conv3d and avg_pool3d; the package's own fallback must be set before torch loads.
        os.environ["PYTORCH_ENABLE_MPS_FALLBACK"] = "1"
    import numpy as np
    import torch
    from transnetv2_pytorch import TransNetV2

    if device == "mps" and not torch.backends.mps.is_available():
        raise RuntimeError("mps is not available on this machine")
    raw = np.frombuffer(frames_of(clip), np.uint8).reshape(-1, _H, _W, 3).copy()
    model = TransNetV2(device=device)
    model.eval()
    with torch.no_grad():
        single, span = model.predict_frames(torch.from_numpy(raw).to(device), quiet=True)
    return single.cpu().numpy().reshape(-1).tolist(), span.cpu().numpy().reshape(-1).tolist()


def _transnetv2(a) -> dict:
    knobs = {"threshold": a.threshold, "span_threshold": a.span_threshold, "gap": a.gap,
             "cut_run": a.cut_run, "min_shot": a.min_shot}
    started = time.perf_counter()
    try:
        got = probabilities(a.clip, a.device)
    except RuntimeError as exc:
        if a.device == "mps":
            return {"refused": f"mps run failed: {exc}", "device": "mps"}
        raise
    out = {"device": a.device, "frames": len(got[0])}
    if a.device == "mps":
        cpu = probabilities(a.clip, REFERENCE_DEVICE)
        why = disagreement(cpu, got, a.max_diff, **knobs)
        out["agreement"] = {**agreement(cpu, got, **knobs), "bound": a.max_diff}
        if why:
            return {**out, "refused": why}
    out["transitions"] = transnet_transitions(*got, **_knobs(**knobs))
    out["seconds"] = round(time.perf_counter() - started, 3)
    return out


def _scenedetect(a) -> dict:
    import scenedetect
    started = time.perf_counter()
    if a.detector == "adaptive":
        det = scenedetect.AdaptiveDetector(adaptive_threshold=a.threshold, min_scene_len=a.min_shot)
    else:
        det = scenedetect.ContentDetector(threshold=a.threshold, min_scene_len=a.min_shot)
    scenes = scenedetect.detect(a.clip, det)
    starts = [start.frame_num for start, _ in scenes[1:]]
    return {"device": "cpu", "frames": scenes[-1][1].frame_num if scenes else 0,
            "transitions": [{"at": at, "kind": "cut", "first": at, "last": at} for at in starts],
            "seconds": round(time.perf_counter() - started, 3)}


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="harness.shot_detect", description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="engine", required=True)
    t = sub.add_parser("transnetv2")
    t.add_argument("--device", choices=TRANSNET_DEVICES, default="cpu")
    t.add_argument("--threshold", type=float, default=None)
    t.add_argument("--span-threshold", type=float, default=None)
    t.add_argument("--gap", type=int, default=None)
    t.add_argument("--cut-run", type=int, default=None)
    t.add_argument("--max-diff", type=float, default=None)
    s = sub.add_parser("scenedetect")
    s.add_argument("--detector", choices=DETECTORS, default="adaptive")
    s.add_argument("--threshold", type=float, default=None)
    for p in (t, s):
        p.add_argument("--clip", required=True)
        p.add_argument("--out", required=True)
        p.add_argument("--min-shot", type=int, default=None)
    return ap


def main(argv=None) -> int:
    a = parser().parse_args(argv)
    a.min_shot = MIN_SHOT_FRAMES if a.min_shot is None else a.min_shot
    if a.engine == "transnetv2":
        a.max_diff = MPS_MAX_PROB_DIFF if a.max_diff is None else a.max_diff
        got = _transnetv2(a)
    else:
        if a.threshold is None:
            a.threshold = ADAPTIVE_THRESHOLD if a.detector == "adaptive" else CONTENT_THRESHOLD
        got = _scenedetect(a)
    Path(a.out).write_text(json.dumps(got, indent=1) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
