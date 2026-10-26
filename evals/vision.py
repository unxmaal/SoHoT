"""The vision lane's cases: frames of local film copies aligned to CineScale's per-second shot-scale labels. #1207.

Labels: CineScale, Savardi et al., Mendeley Data, DOI 10.17632/th46h4vdwd.1, CC BY 4.0.
Frames, titles and paths stay under $LOCALHARNESS_HOME; only the synthetic stand-in ships.
Imports only the standard library at module level: the hf-task venv runs probe_predictions.
"""
from __future__ import annotations

import bisect
import csv
import hashlib
import json
import math
import random
import re
import shutil
import statistics
import subprocess
import time
from dataclasses import dataclass
from operator import itemgetter
from pathlib import Path

from harness.checks import shot_scale as ss

CREDIT = "CineScale (Savardi et al.), Mendeley Data, DOI 10.17632/th46h4vdwd.1, CC BY 4.0"
MANIFEST_VERSION = 1
SHIPPED = Path(__file__).resolve().parent / "cases" / "vision"

#: Copy speeds tried: film, PAL, NTSC and NTSC to PAL, each way, as exact ratios (RULE #1061).
SPEEDS = (1.0, 24 / 25, 25 / 24, 1000 / 1001, 1001 / 1000, 24000 / 25025, 25025 / 24000)
#: Seconds either way an edition may start early or late.
ALIGN_MAX_OFFSET_S = 600
#: Label changes a whole-film fit needs inside the copy; each half needs half of it.
ALIGN_MIN_MARKS = 50
#: Standard deviations a fit must beat shuffled change times by; each half needs this over sqrt 2.
ALIGN_MIN_Z = 8.0
#: Seconds the two halves' offsets may differ by.
HALF_OFFSET_TOLERANCE_S = 2
#: Random change-time draws the alignment null is built from.
NULL_DRAWS = 200
#: Frames drawn from each film.
FRAMES_PER_FILM = 500
#: Height in pixels a frame is extracted at, at the copy's display aspect.
FRAME_HEIGHT = 448
#: Bytes hashed from each end of a source copy for its manifest digest.
SOURCE_DIGEST_BYTES = 1 << 20
#: L2 strength of the reference probe, as scikit-learn's C (kubrick #2's linear row).
PROBE_C = 0.1
#: Probes trained on shuffled labels, the probe's own control.
PROBE_SHUFFLES = 5
#: L-BFGS iterations of the probe's fit in the hf-task venv.
FIT_MAX_ITER = 500
#: New tokens a labeller's reply may take, the same for every engine; hf-task's own default for an image reply.
REPLY_MAX_TOKENS = 512
#: Context llama-server is started with: one frame's image tokens, the prompt and a reply.
LLAMACPP_CTX = 4096
#: Seconds a private llama-server has to answer its health check after it starts.
LLAMACPP_START_S = 600
#: Seconds one frame's reply may take from a private llama-server.
REQUEST_TIMEOUT_S = 600
#: Bootstrap draws behind compare's interval on a kappa difference.
COMPARE_DRAWS = 2000
#: Coverage of compare's interval.
COMPARE_LEVEL = 0.95
#: The labellers a vision candidate may name, and where each may put the model. #1282.
LABELLERS = ("hf-vlm", "mlx-vlm", "llamacpp-vlm")
DEVICES = ("gpu", "cpu")

FILM_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")


class NotAligned(ValueError):
    pass


class Mismatched(ValueError):
    pass


def cases_root() -> Path:
    from harness import paths
    return paths.home() / "cases" / "vision"


def runs_root() -> Path:
    from harness import paths
    return paths.home() / "runs" / "vision"


# --- labels and alignment ------------------------------------------------------

def read_labels(path) -> list[int]:
    """CineScale code per annotated second; -1 where it says not available."""
    out = []
    with Path(path).open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            code = int(row["shotscale"])
            out.append(code if 0 <= code < len(ss.CINESCALE) and ss.CINESCALE[code] != "NA" else -1)
    return out


def _marks(labels) -> list[int]:
    return [t for t in range(1, len(labels))
            if labels[t] != labels[t - 1] and labels[t] >= 0 and labels[t - 1] >= 0]


def align(labels, change, max_offset: int | None = None, min_marks: int | None = None) -> dict:
    """The speed and offset mapping annotated second t to our second t*speed + offset that puts label changes on cuts."""
    max_offset = ALIGN_MAX_OFFSET_S if max_offset is None else max_offset
    min_marks = ALIGN_MIN_MARKS if min_marks is None else min_marks
    marks = _marks(labels)
    n = len(change)
    best = {"score": -math.inf, "speed": None, "offset": None, "marks": 0}
    for s in SPEEDS:
        base = sorted(int(math.floor(m * s + 0.5)) for m in marks)
        if not base:
            continue
        pad = max_offset + max(base[-1], n) + 1
        padded = [0.0] * max_offset + list(change) + [0.0] * pad
        pick = itemgetter(*base) if len(base) > 1 else (lambda seq, b=base[0]: (seq[b],))
        for o in range(-max_offset, max_offset + 1):
            inside = bisect.bisect_left(base, n - o) - bisect.bisect_right(base, -o)
            if inside < min_marks:
                continue
            sc = sum(pick(padded[o + max_offset:])) / inside
            if sc > best["score"]:
                best = {"score": sc, "speed": s, "offset": o, "marks": inside}
    if not best["marks"]:
        return {**best, "score": None, "z": -math.inf,
                "reason": f"fewer than {min_marks} label changes land inside the copy"}
    rng = random.Random(0)
    null = [statistics.fmean(change[rng.randint(1, n - 1)] for _ in range(best["marks"])) for _ in range(NULL_DRAWS)]
    sd = statistics.pstdev(null)
    best["z"] = (best["score"] - statistics.fmean(null)) / sd if sd else math.inf
    return best


def check_alignment(labels, change, min_z: float | None = None) -> dict:
    """Align the whole film and each half of the part the copy holds; a real copy agrees with itself."""
    min_z = ALIGN_MIN_Z if min_z is None else min_z
    whole = align(labels, change)
    if not whole["marks"]:
        return {**whole, "halves": [], "accepted": False}
    inside = [t for t, c in enumerate(labels)
              if c >= 0 and 0 <= t * whole["speed"] + whole["offset"] < len(change)]
    mid = (inside[0] + inside[-1]) // 2
    halves = []
    for keep in (lambda t: t < mid, lambda t: t >= mid):
        part = [c if keep(t) else -1 for t, c in enumerate(labels)]
        halves.append(align(part, change, min_marks=max(ALIGN_MIN_MARKS // 2, 10)))
    agree = all(h["marks"] and h["speed"] == whole["speed"]
                and abs(h["offset"] - whole["offset"]) <= HALF_OFFSET_TOLERANCE_S
                and h["z"] >= min_z / math.sqrt(2) for h in halves)
    return {**whole, "halves": [(h["speed"], h["offset"], round(h["z"], 1)) for h in halves],
            "accepted": bool(agree and whole["z"] >= min_z)}


def eligible(labels, speed: float, offset: int, n_ours: int) -> list[int]:
    """Annotated seconds on the ladder whose label holds a second either side and that land inside the copy."""
    ladder = {ss.CINESCALE.index(x) for x in ss.LADDER}
    return [t for t in range(1, len(labels) - 1)
            if labels[t] in ladder and labels[t - 1] == labels[t] == labels[t + 1]
            and t * speed + offset >= 1 and (t + 1) * speed + offset <= n_ours - 1]


def _seed(text: str) -> int:
    return int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:16], 16)


def sample(seconds, n: int, seed: str) -> list[int]:
    """n seconds drawn uniformly, seeded by the film id, so the class mix is the film's own."""
    return sorted(random.Random(_seed(seed)).sample(list(seconds), min(n, len(seconds))))


# --- the copy: read only -----------------------------------------------------------

def picture_change(source) -> list[float]:
    """Mean absolute grey difference between consecutive 1 fps samples of the copy; d[0] = 0."""
    w, h = 32, 18
    got = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(source), "-vf",
                          f"fps=1,scale={w}:{h},format=gray", "-f", "rawvideo", "-"],
                         capture_output=True, check=True).stdout
    size = w * h
    frames = [got[i:i + size] for i in range(0, len(got) - size + 1, size)]
    out = [0.0]
    for a, b in zip(frames, frames[1:]):
        out.append(sum(abs(x - y) for x, y in zip(a, b)) / size)
    return out[: len(frames)]


def extract_frames(source, seconds, out_dir, height: int | None = None) -> list[Path]:
    """One PNG per time in seconds, at the copy's display aspect; the copy is only read."""
    height = FRAME_HEIGHT if height is None else height
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = []
    for i, s in enumerate(seconds):
        p = out_dir / f"{i:05d}.png"
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-ss", f"{s:.3f}", "-i", str(source),
                        "-frames:v", "1", "-vf", f"scale=-2:{height}:flags=area,setsar=1", str(p)],
                       check=True)
        out.append(p)
    return out


def _sha(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _ends(path) -> str:
    """sha256 of the copy's size and its first and last SOURCE_DIGEST_BYTES: cheap, and changes with the edition."""
    size = Path(path).stat().st_size
    h = hashlib.sha256(str(size).encode())
    with Path(path).open("rb") as f:
        h.update(f.read(SOURCE_DIGEST_BYTES))
        f.seek(max(0, size - SOURCE_DIGEST_BYTES))
        h.update(f.read(SOURCE_DIGEST_BYTES))
    return h.hexdigest()


def private_names_of(labels_csv, source) -> list[str]:
    """What an import must never publish: each file's title, with and without a trailing year, and the folder."""
    out = []
    for p in (Path(labels_csv), Path(source)):
        stem = p.stem
        out += [stem, re.sub(r"[\s._(\[-]*(19|20)\d\d[)\]]?\s*$", "", stem).strip()]
    out.append(str(Path(source).resolve().parent))
    return [n for n in dict.fromkeys(out) if n]


def _norm(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text.lower()).split())


def _check_film_id(film: str) -> None:
    from harness import privacy
    if not FILM_ID.match(film or ""):
        raise ValueError(f"film id {film!r} must be 1-32 of a-z, 0-9 and -, starting with a letter or digit")
    mine = f" {_norm(film)} "
    for name in privacy.home_names():
        n = _norm(name)
        if len(n) >= privacy.MIN_HOME_NAME and f" {n} " in mine:
            raise ValueError(f"film id {film!r} holds a registered private name; choose an opaque id")


def _others(root: Path, film: str):
    for d in sorted(p for p in root.iterdir() if p.is_dir() and p.name != film and not p.name.startswith(".")):
        lab, ch = d / "labels.json", d / "change.json"
        if lab.is_file() and ch.is_file():
            yield d.name, json.loads(lab.read_text(encoding="utf-8")), json.loads(ch.read_text(encoding="utf-8"))


def import_film(labels_csv, source, film: str, frames: int | None = None, height: int | None = None,
                change=picture_change, extract=extract_frames, root=None) -> dict:
    """Align one copy, refuse a mismatched pair, draw and extract its frames, and freeze them in a manifest."""
    from harness import cuts, privacy
    frames = FRAMES_PER_FILM if frames is None else frames
    height = FRAME_HEIGHT if height is None else height
    privacy.register(private_names_of(labels_csv, source))
    _check_film_id(film)
    root = Path(root) if root is not None else cases_root()
    root.mkdir(parents=True, exist_ok=True)
    labels = read_labels(labels_csv)
    ch = list(change(source))
    a = check_alignment(labels, ch)
    if a["offset"] is not None and abs(a["offset"]) >= ALIGN_MAX_OFFSET_S:
        cuts.cut("vision_align_max_offset", f"vision import {film}: best offset at the edge of the search")
    if not a["accepted"]:
        knob = ("vision_align_min_marks" if not a["marks"] else "vision_align_min_z" if a["z"] < ALIGN_MIN_Z
                else "vision_half_offset_tolerance")
        cuts.cut(knob, f"vision import {film}: alignment refused")
        raise NotAligned(f"{film}: the labels do not fit this copy (z {a['z']:.1f}, halves {a['halves']}, "
                         f"needs z {ALIGN_MIN_Z}); {a.get('reason', 'a different edition or a re-cut copy')}")
    for other, their_labels, their_change in _others(root, film):
        if check_alignment(labels, their_change)["accepted"] or check_alignment(their_labels, ch)["accepted"]:
            raise Mismatched(f"{film}: its labels and film {other}'s picture fit each other, so one of the two "
                             f"alignments cannot be trusted (NEGATIVE #34)")
    ok = eligible(labels, a["speed"], a["offset"], len(ch))
    if len(ok) > frames:
        cuts.cut("vision_frames_per_film", f"vision import {film}", value=frames, kept=frames, dropped=len(ok) - frames)
    picks = sample(ok, frames, seed=film)
    times = [(t + 0.5) * a["speed"] + a["offset"] for t in picks]
    stage = root / f".{film}.importing"
    shutil.rmtree(stage, ignore_errors=True)
    (stage / "raw").mkdir(parents=True)
    try:
        made = extract(source, times, stage / "raw", height)
        rows = []
        for t, at, p in zip(picks, times, made):
            fid = f"{film}-{t:05d}"
            dest = stage / f"{fid}.png"
            Path(p).replace(dest)
            rows.append({"id": fid, "file": dest.name, "second": t, "at": round(at, 3),
                         "truth": ss.CINESCALE[labels[t]], "sha256": _sha(dest)})
        shutil.rmtree(stage / "raw", ignore_errors=True)
        manifest = {"version": MANIFEST_VERSION, "film": film, "labels": CREDIT,
                    "labels_sha256": _sha(labels_csv),
                    "source": {"size": Path(source).stat().st_size, "sha256_ends": _ends(source)},
                    "alignment": {"speed": a["speed"], "offset": a["offset"], "z": round(a["z"], 2),
                                  "marks": a["marks"], "halves": [list(h) for h in a["halves"]]},
                    "height": height, "knobs": import_knobs(frames, height), "frames": rows, "digest": _digest(rows)}
        (stage / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")
        (stage / "labels.json").write_text(json.dumps(labels), encoding="utf-8")
        (stage / "change.json").write_text(json.dumps([round(x, 2) for x in ch]), encoding="utf-8")
        final = root / film
        shutil.rmtree(final, ignore_errors=True)
        stage.replace(final)
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    return manifest


def import_knobs(frames: int, height: int) -> dict:
    return {"vision_align_max_offset": ALIGN_MAX_OFFSET_S, "vision_align_min_marks": ALIGN_MIN_MARKS,
            "vision_align_min_z": ALIGN_MIN_Z, "vision_half_offset_tolerance": HALF_OFFSET_TOLERANCE_S,
            "vision_null_draws": NULL_DRAWS, "vision_frames_per_film": frames, "vision_frame_height": height,
            "vision_source_digest_bytes": SOURCE_DIGEST_BYTES}


def _digest(rows) -> str:
    return hashlib.sha256(json.dumps([[r["id"], r["truth"], r["sha256"]] for r in rows]).encode()).hexdigest()


# --- loading -----------------------------------------------------------------------

@dataclass(frozen=True)
class Frame:
    id: str
    film: str
    path: Path
    truth: str
    missing: bool = False
    sha256: str = ""


def load(root=None) -> list[Frame]:
    """Every frame under root's film manifests; a frame file that is gone is missing, one that changed is refused."""
    root = Path(root) if root is not None else cases_root()
    out = []
    if not root.is_dir():
        return out
    for m in sorted(root.glob("*/manifest.json")):
        doc = json.loads(m.read_text(encoding="utf-8"))
        if doc.get("version") != MANIFEST_VERSION:
            raise ValueError(f"{m}: manifest version {doc.get('version')} is not {MANIFEST_VERSION}")
        if _digest(doc["frames"]) != doc["digest"]:
            raise ValueError(f"{m}: the frame list does not match its digest")
        for r in doc["frames"]:
            p = m.parent / r["file"]
            if not p.is_file():
                out.append(Frame(r["id"], doc["film"], p, r["truth"], missing=True, sha256=r["sha256"]))
                continue
            if _sha(p) != r["sha256"]:
                raise ValueError(f"{p.name}: frame bytes do not match the manifest digest")
            out.append(Frame(r["id"], doc["film"], p, r["truth"], sha256=r["sha256"]))
    return out


# --- the committed stand-in ----------------------------------------------------------

#: Share of the frame the stand-in's subject covers at each scale; size_label reads it back.
STAND_IN_SHARE = {"ECU": 0.85, "CU": 0.6, "MCU": 0.4, "MS": 0.25, "MLS": 0.14, "LS": 0.07, "ELS": 0.025}
STAND_IN_SIZE = (96, 54)


def _stand_in(label: str, rng: random.Random):
    from PIL import Image, ImageDraw
    w, h = STAND_IN_SIZE
    share = STAND_IN_SHARE[label] * rng.uniform(0.92, 1.08)
    bh = min(h, max(2, round(math.sqrt(share * w * h / 0.75))))
    bw = min(w, max(2, round(share * w * h / bh)))
    x, y = rng.randint(0, w - bw), rng.randint(0, h - bh)
    im = Image.new("L", (w, h), 200 + rng.randint(-20, 20))
    ImageDraw.Draw(im).rectangle([x, y, x + bw - 1, y + bh - 1], fill=30 + rng.randint(0, 20))
    return im.convert("RGB")


def synthesize(out=None, per_label: int = 3) -> Path:
    """The stand-in: two films of drawn frames whose subject size is the label. Deterministic."""
    out = Path(out) if out is not None else SHIPPED
    for film in ("synthetic-a", "synthetic-b"):
        d = out / film
        d.mkdir(parents=True, exist_ok=True)
        rng = random.Random(_seed(film))
        rows = []
        for i, label in enumerate(label for label in ss.LADDER for _ in range(per_label)):
            fid = f"{film}-{i:05d}"
            p = d / f"{fid}.png"
            _stand_in(label, rng).save(p)
            rows.append({"id": fid, "file": p.name, "second": i, "at": i + 0.5, "truth": label, "sha256": _sha(p)})
        manifest = {"version": MANIFEST_VERSION, "film": film, "labels": "synthetic: drawn subject size",
                    "labels_sha256": "", "source": {}, "alignment": {}, "height": STAND_IN_SIZE[1],
                    "frames": rows, "digest": _digest(rows)}
        (d / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")
    return out


def size_label(path) -> str:
    """The stand-in's known-answer labeller: the scale whose subject share is nearest on a log scale."""
    from PIL import Image
    g = Image.open(path).convert("L")
    dark = sum(1 for v in g.tobytes() if v < 128) / (g.width * g.height)
    return min(ss.LADDER, key=lambda k: abs(math.log(max(dark, 1e-4)) - math.log(STAND_IN_SHARE[k])))


def size_labeller(frames) -> list[str]:
    return [size_label(f.path) for f in frames]


# --- runs ---------------------------------------------------------------------------

def _slug(candidate: str) -> str:
    return re.sub(r"[^A-Za-z0-9.]+", "-", candidate).strip("-")[:80] or "candidate"


def run_dir(candidate: str) -> Path:
    return runs_root() / f"{time.strftime('%Y%m%d-%H%M%S')}-{_slug(candidate)}"


def features_cache(model: str, frames) -> Path:
    """Where the probe's features for this model and these frames are kept, so a refit needs no GPU."""
    from harness import paths
    key = hashlib.sha256(json.dumps([model, sorted(f"{f.id}:{f.sha256}" for f in frames)]).encode()).hexdigest()[:16]
    return paths.home() / "cache" / "vision" / f"{key}.json"


def candidate_for(name: str, card=None) -> str:
    """The labeller spelling for a repo: an MLX conversion to mlx-vlm, a GGUF to llama-server, else transformers. #1282."""
    from harness import runner_gaps
    card = card or {}
    tags = {t.lower() for t in runner_gaps.tags_of(card)}
    library = str(card.get("library") or card.get("library_name") or "").strip().lower()
    mtype = runner_gaps.model_type(card)
    if library == "mlx" or "mlx" in tags:
        return f"mlx-vlm:{name}"
    if library == "gguf" or "gguf" in tags:
        return f"llamacpp-vlm:{name}"
    if mtype and not runner_gaps.native_in_transformers(mtype) and runner_gaps.mlx_vlm_builds(mtype):
        return f"mlx-vlm:{name}"
    return f"hf-vlm:{name}"


def _finish(frames, answers: dict, candidate: str, out, extra_control=None, reference=False, knobs=None) -> dict:
    runnable = [f for f in frames if not f.missing]
    rows = [{"film": f.film, "id": f.id, "truth": f.truth, "answer": ss.parse(answers.get(f.id, ""))}
            for f in runnable]
    got = ss.judge(rows, extra_control=extra_control)
    got.update(candidate=candidate, reference=reference, not_run=[f.id for f in frames if f.missing],
               films_n=len({f.film for f in runnable}), generated_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    got["knobs"] = {"vision_control_draws": ss.CONTROL_DRAWS, "vision_control_max_kappa": ss.CONTROL_MAX_KAPPA,
                    **(knobs or {})}
    if extra_control is not None:
        got["probe_control"] = list(extra_control)
        got["knobs"].update(vision_probe_c=PROBE_C, vision_probe_shuffles=len(extra_control),
                            vision_fit_max_iter=FIT_MAX_ITER)
    out = Path(out) if out is not None else run_dir(candidate)
    out.mkdir(parents=True, exist_ok=True)
    with (out / "answers.jsonl").open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps({"id": r["id"], "film": r["film"], "truth": r["truth"],
                                "reply": answers.get(r["id"], ""), "answer": r["answer"]}) + "\n")
    (out / "score.json").write_text(json.dumps(got, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    got["dir"] = str(out)
    return got


def run_exam(frames, label, out, candidate: str, knobs=None) -> dict:
    """label(frames) -> one reply per frame; scored, controlled and written to a run directory."""
    runnable = [f for f in frames if not f.missing]
    replies = list(label(runnable)) if runnable else []
    if len(replies) != len(runnable):
        raise ValueError(f"{candidate}: {len(replies)} replies for {len(runnable)} frames")
    return _finish(frames, {f.id: r for f, r in zip(runnable, replies)}, candidate, out, knobs=knobs)


def probe_predictions(frames, feats: dict, shuffles: int | None = None, seed: int = 1207, fit=None,
                      c: float | None = None) -> dict:
    """Leave-one-film-out: fit(X, y, c) on every other film, predict this one; again on labels shuffled within each film."""
    if fit is None:
        raise ValueError("probe_predictions needs a fit(X, y, c) -> predict")
    shuffles = PROBE_SHUFFLES if shuffles is None else shuffles
    c = PROBE_C if c is None else c
    have = [f for f in frames if not f.missing and f.id in feats]
    films = sorted({f.film for f in have})
    answers: dict[str, str] = {}
    control: list[dict[str, str]] = [{} for _ in range(shuffles)]
    rng = random.Random(seed)
    for test in films:
        train = [f for f in have if f.film != test]
        held = [f for f in have if f.film == test]
        if not train:
            continue
        X = [feats[f.id] for f in train]
        Xt = [feats[f.id] for f in held]
        predict = fit(X, [f.truth for f in train], c)
        answers.update(zip((f.id for f in held), predict(Xt)))
        for d in range(shuffles):
            y = []
            for film in films:
                if film != test:
                    y += ss.shuffled([f.truth for f in train if f.film == film], rng)
            order = [f for film in films if film != test for f in train if f.film == film]
            predict = fit([feats[f.id] for f in order], y, c)
            control[d].update(zip((f.id for f in held), predict(Xt)))
    return {"answers": answers, "control": control}


def score_probe(frames, preds: dict, out, candidate: str) -> dict:
    """The reference row: the probe's answers, gated by the scorer's control and by its shuffled-label training."""
    runnable = [f for f in frames if not f.missing]
    truth = [f.truth for f in runnable]
    extra = []
    for draw in preds.get("control") or []:
        k = ss.kappa(truth, [draw.get(f.id, ss.INVALID) for f in runnable])
        extra.append(0.0 if k is None else k)
    return _finish(frames, preds["answers"], candidate, out, extra_control=extra, reference=True)


EXPORTED = ("kappa", "within_one", "accuracy", "majority", "valid_rate")


def export_rows(root=None) -> list[dict]:
    """The newest run per candidate, as scores only: no case id, film id, path or frame."""
    root = Path(root) if root is not None else runs_root()
    newest: dict[str, dict] = {}
    for p in sorted(root.glob("*/score.json")) if root.is_dir() else []:
        doc = json.loads(p.read_text(encoding="utf-8"))
        cand = doc.get("candidate", "")
        if cand and doc.get("generated_at", "") >= newest.get(cand, {}).get("generated_at", ""):
            newest[cand] = doc
    out = []
    for cand, doc in sorted(newest.items()):
        row = {"candidate": cand, "status": doc.get("status", ""), "reference": bool(doc.get("reference")),
               "frames": doc.get("n", 0), "films": doc.get("films_n", 0), "not_run": len(doc.get("not_run") or []),
               "control": round((doc.get("control") or {}).get("mean", 0.0), 4),
               "generated_at": doc.get("generated_at", ""), "labels": CREDIT}
        for k in EXPORTED:
            if doc.get(k) is not None:
                row[k] = round(doc[k], 4)
        out.append(row)
    return out
