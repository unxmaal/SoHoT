"""`soh vision import|run|probe|report`: the shot-scale exam over frames of this machine's own film copies (#1207)."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from harness.commands.common import err

PROBE_MODEL = "facebook/dinov2-small"


def add_parser(sub) -> None:
    p = sub.add_parser("vision", help="the vision lane: import a film copy against its CineScale labels, run a "
                       "candidate or the DINOv2 probe over the frames, report the scores (#1207)")
    act = p.add_subparsers(dest="action", required=True)
    i = act.add_parser("import", help="align one local copy to its CineScale CSV and freeze its frames under the home")
    i.add_argument("--labels", required=True, help="the film's CineScale annotation CSV")
    i.add_argument("--source", required=True, help="this machine's copy of the film; only read")
    i.add_argument("--film", required=True, help="an opaque id for the film (a-z, 0-9, -); never its title")
    i.add_argument("--frames", type=int, default=None, help="frames to draw (default evals.vision.FRAMES_PER_FILM)")
    i.add_argument("--height", type=int, default=None, help="frame height in pixels (default evals.vision.FRAME_HEIGHT)")
    r = act.add_parser("run", help="one candidate over every imported frame, with the shuffled-label control")
    r.add_argument("--candidate", required=True, help="hf-vlm:<repo>[@revision], or size (the stand-in's labeller)")
    r.add_argument("--cases", default=None, help="a vision cases folder (default: the home's cases/vision)")
    r.add_argument("--out", default=None, help="run folder (default: the home's runs/vision/<stamp>-<candidate>)")
    b = act.add_parser("probe", help="the reference row: DINOv2 features and a leave-one-film-out linear probe")
    b.add_argument("--model", default=PROBE_MODEL)
    b.add_argument("--cases", default=None)
    b.add_argument("--out", default=None)
    b.add_argument("--shuffles", type=int, default=None, help="probes trained on shuffled labels (its control)")
    rep = act.add_parser("report", help="the newest run per candidate, as the export carries it")
    rep.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_vision)


def _hf_task() -> str:
    from harness import engines
    return os.environ.get("HF_TASK_BIN", engines.HF_TASK_DEFAULT_BIN)


def _frames_file(frames, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps({"id": f.id, "image": str(f.path), "film": f.film, "truth": f.truth}) + "\n"
                            for f in frames), encoding="utf-8")
    return path


def _answers(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    return {d["id"]: d.get("reply", "") for d in map(json.loads, path.read_text(encoding="utf-8").splitlines())
            if d.get("id")}


def hf_vlm(model: str, out: Path):
    """A labeller that sends every frame through the hf-task venv in one process, resuming what it already has."""
    from harness.checks import shot_scale as ss
    repo, _, rev = model.partition("@")

    def label(frames):
        answers = out / "vlm-answers.jsonl"
        argv = [_hf_task(), "vision-label", "--model", repo, "--frames", str(_frames_file(frames, out / "frames.jsonl")),
                "--prompt", ss.PROMPT, "--out", str(answers)] + (["--revision", rev] if rev else [])
        got = subprocess.run(argv, check=False)
        if got.returncode:
            raise RuntimeError(f"hf-task vision-label exited {got.returncode}")
        have = _answers(answers)
        return [have.get(f.id, "") for f in frames]
    return label


def labeller_for(candidate: str, out: Path):
    from evals import vision
    kind, _, model = candidate.partition(":")
    if candidate == "size":
        return vision.size_labeller
    if kind == "hf-vlm" and model:
        return hf_vlm(model, out)
    raise ValueError(f"unknown vision candidate {candidate!r}: hf-vlm:<repo>[@revision] or size")


def _none_here(root) -> int:
    print(f"vision: not run: no imported vision cases under {root}; add one with `soh vision import`")
    return 0


def _summary(got: dict) -> None:
    head = f"vision {got['candidate']}: {got['status']}"
    if got["status"] == "ok":
        head += (f", kappa {got['kappa']:.3f}, within one {got['within_one']:.3f}, accuracy {got['accuracy']:.3f} "
                 f"(majority {got['majority']:.3f}), valid {got['valid_rate']:.3f}")
    else:
        head += f" ({got['reason']})"
    print(f"{head}; control {got['control']['mean']:+.3f} over {got['control']['draws']} draws; "
          f"{got['n']} frames, {got['films_n']} films, {len(got['not_run'])} not run")
    print(f"  {got['dir']}")


def run_command(cases=None, candidate: str = "", out=None, label=None) -> int:
    from evals import vision
    root = Path(cases) if cases else vision.cases_root()
    frames = vision.load(root)
    if not frames:
        return _none_here(root)
    out = Path(out) if out else vision.run_dir(candidate)
    got = vision.run_exam(frames, label or labeller_for(candidate, out), out, candidate)
    _summary(got)
    return 0


def probe_command(model: str = PROBE_MODEL, cases=None, out=None, shuffles=None) -> int:
    from evals import vision
    root = Path(cases) if cases else vision.cases_root()
    frames = [f for f in vision.load(root) if not f.missing]
    if not frames:
        return _none_here(root)
    candidate = f"probe:{model}"
    out = Path(out) if out else vision.run_dir(candidate)
    preds = out / "probe.json"
    argv = [_hf_task(), "vision-probe", "--model", model, "--frames", str(_frames_file(frames, out / "frames.jsonl")),
            "--out", str(preds), "--features", str(vision.features_cache(model, frames)),
            "--c", str(vision.PROBE_C), "--shuffles", str(vision.PROBE_SHUFFLES if shuffles is None else shuffles)]
    got = subprocess.run(argv, check=False)
    if got.returncode:
        return err(f"hf-task vision-probe exited {got.returncode}")
    _summary(vision.score_probe(vision.load(root), json.loads(preds.read_text(encoding="utf-8")), out, candidate))
    return 0


def report_command(as_json: bool = False) -> int:
    from evals import vision
    rows = vision.export_rows()
    if as_json:
        print(json.dumps(rows, indent=1))
        return 0
    if not rows:
        print("vision: no runs yet")
        return 0
    for r in rows:
        kappa = f"{r['kappa']:.3f}" if "kappa" in r else "-"
        print(f"{r['candidate']:<48} {r['status']:<9} kappa {kappa:>6}  within1 {r.get('within_one', 0):.3f}  "
              f"control {r['control']:+.3f}  {r['frames']} frames / {r['films']} films"
              + ("  (reference)" if r["reference"] else ""))
    print(f"labels: {vision.CREDIT}")
    return 0


def cmd_vision(a) -> int:
    from evals import vision
    if a.action == "import":
        try:
            m = vision.import_film(a.labels, a.source, a.film, frames=a.frames, height=a.height)
        except (vision.NotAligned, vision.Mismatched, ValueError) as exc:
            return err(str(exc))
        al = m["alignment"]
        print(f"vision import {m['film']}: {len(m['frames'])} frames, speed {al['speed']:.6f}, offset {al['offset']} s, "
              f"z {al['z']}, halves {al['halves']}")
        return 0
    if a.action == "run":
        try:
            return run_command(a.cases, a.candidate, a.out)
        except (ValueError, RuntimeError) as exc:
            return err(str(exc))
    if a.action == "probe":
        return probe_command(a.model, a.cases, a.out, a.shuffles)
    return report_command(a.json)
