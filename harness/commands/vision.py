"""`soh vision import|run|probe|compare|candidate|report`: the shot-scale exam over this machine's film frames (#1207, #1282)."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from harness.commands.common import err

PROBE_MODEL = "facebook/dinov2-small"
MLX_VLM_DEFAULT_BIN = str(Path(__file__).resolve().parents[2] / "scripts" / "mlx-vlm.sh")
CANDIDATES = ("hf-vlm:<repo>[@rev][,device=gpu|cpu], mlx-vlm:<repo>[@rev][,device=...], "
              "llamacpp-vlm:<repo>[@rev][:<quant>][,device=...], or size (the stand-in's labeller)")


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
    r.add_argument("--candidate", required=True, help=CANDIDATES)
    r.add_argument("--cases", default=None, help="a vision cases folder (default: the home's cases/vision)")
    r.add_argument("--out", default=None, help="run folder (default: the home's runs/vision/<stamp>-<candidate>)")
    r.add_argument("--film", default="", help="only this film's frames, by its opaque id (a CPU run's subset)")
    b = act.add_parser("probe", help="the reference row: DINOv2 features and a leave-one-film-out linear probe")
    b.add_argument("--model", default=PROBE_MODEL)
    b.add_argument("--cases", default=None)
    b.add_argument("--out", default=None)
    b.add_argument("--shuffles", type=int, default=None, help="probes trained on shuffled labels (its control)")
    c = act.add_parser("compare", help="two runs over the same frames: kappa difference with a film-blocked "
                       "bootstrap interval, and the share answered alike (#1282)")
    c.add_argument("a", help="a run folder")
    c.add_argument("b", help="another run folder over the same frames")
    c.add_argument("--json", action="store_true")
    n = act.add_parser("candidate", help="the labeller spelling for a repo, read from its card in the store (#1282)")
    n.add_argument("repo")
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


def _collected(frames, out: Path, who: str, run) -> list[str]:
    """run(frames file, answers file) labels what is not yet answered; every frame must then have a reply."""
    from harness import cuts
    answers = out / "vlm-answers.jsonl"
    run(_frames_file(frames, out / "frames.jsonl"), answers)
    have = _answers(answers)
    missing = [f.id for f in frames if f.id not in have]
    if missing:
        raise RuntimeError(f"{who} answered {len(frames) - len(missing)} of {len(frames)} frames; "
                           f"rerun with --out {out} to resume")
    cut = sum(1 for d in map(json.loads, answers.read_text(encoding="utf-8").splitlines()) if d.get("cut"))
    if cut:
        cuts.cut("vision_reply_max_tokens", f"{who}: replies cut at the reply budget", kept=len(frames) - cut,
                 dropped=cut)
    return [have[f.id] for f in frames]


def _exit(who: str, rc: int) -> None:
    if rc:
        raise RuntimeError(f"{who} exited {rc}")


def hf_vlm(model: str, out: Path, device: str = ""):
    """A labeller that sends every frame through the hf-task venv in one process, resuming what it already has."""
    from evals import vision
    from harness.checks import shot_scale as ss
    repo, _, rev = model.partition("@")

    def run(frames_file, answers):
        argv = [_hf_task(), "vision-label", "--model", repo, "--frames", str(frames_file), "--prompt", ss.PROMPT,
                "--out", str(answers), "--max-new-tokens", str(vision.REPLY_MAX_TOKENS)]
        argv += (["--revision", rev] if rev else []) + (["--device", "cpu"] if device == "cpu" else [])
        _exit("hf-task vision-label", subprocess.run(argv, check=False).returncode)
    return lambda frames: _collected(frames, out, "hf-task vision-label", run)


def mlx_vlm(model: str, out: Path, device: str = "gpu"):
    """A labeller that sends every frame through mlx-vlm in its own venv, one process, resuming. #1282."""
    from evals import vision
    from harness.checks import shot_scale as ss
    repo, _, rev = model.partition("@")

    def run(frames_file, answers):
        argv = [os.environ.get("MLX_VLM_BIN", MLX_VLM_DEFAULT_BIN), "--model", repo, "--frames", str(frames_file),
                "--prompt", ss.PROMPT, "--out", str(answers), "--device", device or "gpu",
                "--max-tokens", str(vision.REPLY_MAX_TOKENS)] + (["--revision", rev] if rev else [])
        _exit("mlx-vlm", subprocess.run(argv, check=False).returncode)
    return lambda frames: _collected(frames, out, "mlx-vlm", run)


def llamacpp_vlm(model: str, out: Path, quant: str = "", device: str = "gpu"):
    """A labeller that serves a GGUF and its mmproj from a private llama-server for the run. #1282."""
    import functools

    from harness import hf_task, llama_vlm
    from harness.checks import shot_scale as ss
    repo, _, rev = model.partition("@")

    def run(frames_file, answers):
        out.mkdir(parents=True, exist_ok=True)
        with (out / "llama-server.log").open("ab") as log:
            hf_task.vision_label(repo, frames_file, ss.PROMPT, answers, label=functools.partial(
                llama_vlm.label_images, quant=quant, revision=rev or None, device=device or "gpu", log=log))
    return lambda frames: _collected(frames, out, "llamacpp-vlm", run)


def parse_candidate(candidate: str) -> tuple[str, str, str, str, dict]:
    """(labeller, repo, revision, quant, options) of a vision candidate; ValueError for one no labeller takes."""
    from evals import vision
    head, _, optstr = candidate.partition(",")
    kind, _, model = head.partition(":")
    quant = ""
    if kind == "llamacpp-vlm":
        model, _, quant = model.partition(":")
    elif ":" in model:
        raise ValueError(f"{candidate!r}: only llamacpp-vlm takes a :<quant>")
    repo, _, rev = model.partition("@")
    if kind not in vision.LABELLERS or not repo:
        raise ValueError(f"unknown vision candidate {candidate!r}: {CANDIDATES}")
    options = {}
    for chunk in filter(None, (c.strip() for c in optstr.split(","))):
        key, sep, value = chunk.partition("=")
        if not sep or key != "device" or value not in vision.DEVICES:
            raise ValueError(f"{candidate!r}: options are device={'|'.join(vision.DEVICES)}")
        options[key] = value
    return kind, repo, rev, quant, options


def labeller_knobs(candidate: str) -> dict:
    """The limits a candidate's labeller runs under, recorded in its score.json. #1282."""
    from evals import vision
    if candidate == "size":
        return {}
    got = {"vision_reply_max_tokens": vision.REPLY_MAX_TOKENS}
    if candidate.startswith("llamacpp-vlm:"):
        got.update(vision_llamacpp_ctx=vision.LLAMACPP_CTX, vision_llamacpp_start_s=vision.LLAMACPP_START_S,
                   vision_request_timeout_s=vision.REQUEST_TIMEOUT_S)
    return got


def labeller_for(candidate: str, out: Path):
    from evals import vision
    if candidate == "size":
        return vision.size_labeller
    kind, repo, rev, quant, options = parse_candidate(candidate)
    model = f"{repo}@{rev}" if rev else repo
    device = options.get("device", "")
    if kind == "hf-vlm":
        return hf_vlm(model, out, device)
    if kind == "mlx-vlm":
        return mlx_vlm(model, out, device or "gpu")
    return llamacpp_vlm(model, out, quant, device or "gpu")


def compare(a, b, cases=None) -> dict:
    """Two runs' answers on the frames both answered, paired: kappa difference, interval, agreement. #1282."""
    from evals import vision
    from harness.checks import shot_scale as ss

    def rows(d):
        return {r["id"]: r for r in map(json.loads, (Path(d) / "answers.jsonl").read_text(encoding="utf-8")
                                        .splitlines()) if r.get("id")}
    ra, rb = rows(a), rows(b)
    ids = sorted(set(ra) & set(rb))
    if not ids:
        raise ValueError(f"{a} and {b} share no frame; compare two runs over the same cases")
    known = {}
    if any("truth" not in ra[i] for i in ids):
        known = {f.id: f for f in vision.load(Path(cases) if cases else vision.cases_root())}
    truth = [ra[i].get("truth") or known[i].truth for i in ids]
    films = [ra[i].get("film") or known[i].film for i in ids]
    got = ss.paired_kappa(truth, [ra[i]["answer"] for i in ids], [rb[i]["answer"] for i in ids], films,
                          draws=vision.COMPARE_DRAWS, level=vision.COMPARE_LEVEL)
    got["knobs"] = {"vision_compare_draws": vision.COMPARE_DRAWS, "vision_compare_level": vision.COMPARE_LEVEL}
    return got


def candidate_command(repo: str) -> int:
    from evals import vision
    from harness import memory_store as ms
    store = ms.connect()
    try:
        card = ms.card_of(store, repo)
    finally:
        store.close()
    if card is None:
        return err(f"{repo} is not in the store; `soh discover --inspect` reads its card first")
    print(vision.candidate_for(repo, card))
    return 0


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


def run_command(cases=None, candidate: str = "", out=None, label=None, film: str = "") -> int:
    from evals import vision
    root = Path(cases) if cases else vision.cases_root()
    frames = vision.load(root)
    if not frames:
        return _none_here(root)
    if film:
        frames = [f for f in frames if f.film == film]
        if not frames:
            raise ValueError(f"no frame of film {film!r} under {root}")
    out = Path(out) if out else vision.run_dir(candidate)
    got = vision.run_exam(frames, label or labeller_for(candidate, out), out, candidate,
                          knobs=labeller_knobs(candidate))
    _summary(got)
    return 0


def compare_command(a, b, as_json: bool = False) -> int:
    got = compare(a, b)
    if as_json:
        print(json.dumps(got, indent=1))
        return 0
    print(f"vision compare: kappa {got['kappa_a']:.3f} vs {got['kappa_b']:.3f}, difference {got['diff']:+.3f} "
          f"[{got['low']:+.3f}, {got['high']:+.3f}] at {got['level']:.0%}; answered alike {got['agree']:.3f}; "
          f"{got['n']} frames, {got['films']} films")
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
            return run_command(a.cases, a.candidate, a.out, film=a.film)
        except (ValueError, RuntimeError) as exc:
            return err(str(exc))
    if a.action == "probe":
        return probe_command(a.model, a.cases, a.out, a.shuffles)
    if a.action == "compare":
        try:
            return compare_command(a.a, a.b, a.json)
        except (ValueError, OSError) as exc:
            return err(str(exc))
    if a.action == "candidate":
        return candidate_command(a.repo)
    return report_command(a.json)
