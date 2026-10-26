"""One case through transformers, in the hf-task venv: ocr (#562), retrieval (#563), pii (#564), vision (#1207).

Run by scripts/hf-task.sh; imports nothing from this package but torch_device and reasons.
A repo that ships its own modelling code is refused, never executed.
"""
from __future__ import annotations

import argparse
import functools
import json
import subprocess
import sys
from pathlib import Path

from harness import reasons

#: Exit status for "this needs a runner hf-task will not be": its own code.
NEEDS_OWN_RUNNER = 3
#: Exit status for "the hf-task venv lacks a package": the harness, never the model. #601.
MISSING_PACKAGE = 4
#: Beside an ocr artifact: the device and attention that answered. #604.
RUNTIME_SUFFIX = ".runtime.json"
#: (device, attention) tried in turn while the MPS backend aborts; None is the default device. #604.
FALLBACKS = ((None, ""), (None, "eager"), ("cpu", ""))
#: What transformers' sentencepiece extractor imports before it falls back to tiktoken. #1025.
SENTENCEPIECE_MODULES = ("sentencepiece", "google.protobuf")
#: Words in a slow-to-fast tokenizer conversion failure.
CONVERTERS = ("sentencepiece", "tiktoken")
#: New tokens an ocr reply may take; a reply that fills it records hf_max_new_tokens on its row. #700.
MAX_NEW_TOKENS = 512
#: The dtypes an ocr case may be forced to load at. #1018.
DTYPES = ("bfloat16", "float16", "float32")


def runtime_path(out) -> str:
    return f"{out}{RUNTIME_SUFFIX}"


def fall_back(attempt) -> int:
    """Run attempt(device, attn) per FALLBACKS until one ends without an MPS backend abort."""
    rc = 0
    for device, attn in FALLBACKS:
        rc, err = attempt(device, attn)
        if rc == 0 or not reasons.mps_abort(err):
            return rc
        print(f"hf-task: the MPS backend aborted (device {device or 'default'}, "
              f"attention {attn or 'default'}); trying the next fallback", file=sys.stderr)
    return rc


def _device(torch, device: str | None) -> str:
    from harness.torch_device import accelerator
    return device or accelerator(torch) or "cpu"


def limit_hit(generated: int, max_new_tokens: int) -> str:
    """The `limit:` body when a reply took every new token it was allowed, else "". #700."""
    return f"hf_max_new_tokens>{max_new_tokens}" if generated >= max_new_tokens else ""


def model_dtype(model: str, device: str, revision: str | None = None, forced: str = "") -> str:
    """The dtype an ocr model loads at: `forced`, else what its snapshot declares, else fp16 on an accelerator. #1018."""
    from harness.torch_device import FP16, declared_dtype, load_dtype, snapshot
    return load_dtype(forced or declared_dtype(snapshot(model, revision=revision)), device, FP16)


def read_image(model: str, image: str, prompt: str, revision: str | None = None,
               max_new_tokens: int | None = None, device: str | None = None, attn: str = "",
               runtime: dict | None = None, dtype: str = "") -> str:
    """The model's transcription of `image`: a chat VLM is prompted, an encoder-decoder is not.

    Not a pipeline: transformers 5 has no image-to-text task, and its image-text-to-text
    pipeline refuses a repo with no processor class (trocr). Measured 2026-10-07.
    """
    ask = load_reader(model, revision, max_new_tokens, device, attn, runtime, dtype)
    return ask(image, prompt)


def load_reader(model: str, revision: str | None = None, max_new_tokens: int | None = None,
                device: str | None = None, attn: str = "", runtime: dict | None = None, dtype: str = ""):
    """Load an image-text model once; returns ask(image, prompt) -> its reply. #1207."""
    import torch
    from PIL import Image
    from transformers import AutoModelForImageTextToText, AutoProcessor, AutoTokenizer

    dev = _device(torch, device)
    max_new_tokens = MAX_NEW_TOKENS if max_new_tokens is None else max_new_tokens
    runtime = {} if runtime is None else runtime
    name = model_dtype(model, dev, revision, dtype)
    dtype = getattr(torch, name)
    # Eager attention repeats grouped KV heads, which MPS's sdpa matmul cannot type. #604.
    net = AutoModelForImageTextToText.from_pretrained(
        model, revision=revision, dtype=dtype,
        **({"attn_implementation": attn} if attn else {})).to(dev)
    runtime.update(device=dev, attn=str(getattr(net.config, "_attn_implementation", "")
                                        or attn or "default"), dtype=name)
    proc = AutoProcessor.from_pretrained(model, revision=revision)
    if getattr(proc, "chat_template", None):
        def chat(image: str, prompt: str) -> str:
            picture = Image.open(image).convert("RGB")
            messages = [{"role": "user", "content": [{"type": "image", "image": picture},
                                                     {"type": "text", "text": prompt}]}]
            inputs = proc.apply_chat_template(messages, add_generation_prompt=True, tokenize=True,
                                              return_dict=True, return_tensors="pt")
            inputs = inputs.to(dev, dtype=dtype)
            out = net.generate(**inputs, max_new_tokens=max_new_tokens, do_sample=False)
            new = out[:, inputs["input_ids"].shape[1]:]
            runtime["limit"] = limit_hit(new.shape[1], max_new_tokens)
            return proc.batch_decode(new, skip_special_tokens=True)[0].strip()
        return chat
    # Built before generating, so a tokenizer the venv cannot build fails in seconds. #1025.
    decoder = getattr(proc, "tokenizer", None) or _tokenizer(model, revision, AutoTokenizer)

    def read(image: str, prompt: str) -> str:
        picture = Image.open(image).convert("RGB")
        pixels = getattr(proc, "image_processor", proc)(images=picture, return_tensors="pt")
        out = net.generate(pixel_values=pixels.pixel_values.to(dev, dtype=dtype),
                           max_new_tokens=max_new_tokens, do_sample=False)
        # The decoder's start token is not a new one.
        runtime["limit"] = limit_hit(out.shape[1] - 1, max_new_tokens)
        return decoder.batch_decode(out, skip_special_tokens=True)[0].strip()
    return read


def _tokenizer(model: str, revision, auto):
    """AutoTokenizer, else the class the repo's tokenizer_config names.

    transformers 5.17 falls back to a generic backend for a vision-encoder-decoder
    repo (trocr) and cannot build its sentencepiece tokenizer; the named class can.
    """
    try:
        return auto.from_pretrained(model, revision=revision)
    except ValueError as exc:
        try:
            return _named_tokenizer(model, revision, exc)
        except ValueError as again:
            gap = _converter_gap(again)
            if not gap:
                raise
            raise ModuleNotFoundError(f"No module named '{gap}'", name=gap) from again


def _named_tokenizer(model: str, revision, exc: ValueError):
    import transformers
    from transformers.utils import cached_file
    path = cached_file(model, "tokenizer_config.json", revision=revision)
    with open(path, encoding="utf-8") as f:
        named = json.load(f).get("tokenizer_class") or ""
    cls = getattr(transformers, named, None)
    if cls is None:
        raise exc
    return cls.from_pretrained(model, revision=revision)


def _converter_gap(exc: BaseException) -> str:
    """The module a failed slow-tokenizer conversion lacked: sentencepiece's pair before tiktoken, its fallback. #1025."""
    if not any(w in str(e).lower() for e in _chain(exc) for w in CONVERTERS):
        return ""
    import importlib
    for name in SENTENCEPIECE_MODULES:
        try:
            importlib.import_module(name)
        except ImportError:
            return name
    return import_gap(exc)


def _chain(exc: BaseException | None):
    seen = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        yield exc
        exc = exc.__cause__ or exc.__context__


def import_gap(exc: BaseException) -> str:
    """The module an ImportError under this exception names, or "". #1025."""
    return next((e.name for e in _chain(exc) if isinstance(e, ImportError) and e.name), "")


def ocr(model: str, image: str, prompt: str, out, read=read_image) -> None:
    Path(out).write_text(read(model, image, prompt), encoding="utf-8")


def _attempt(argv: list[str]):
    """One ocr attempt as its own process, since an MPS abort kills the interpreter."""
    def run(device, attn):
        cmd = [sys.executable, "-m", "harness.hf_task", *argv, "--one-attempt"]
        cmd += ["--device", device] if device else []
        cmd += ["--attn", attn] if attn else []
        got = subprocess.run(cmd, capture_output=True, text=True)
        sys.stdout.write(got.stdout or "")
        sys.stderr.write(got.stderr or "")
        return got.returncode, got.stderr or ""
    return run


def score_texts(mode: str, model: str, query: str, texts: list[str],
                revision: str | None = None, device: str | None = None) -> list[float]:
    """A relevance score per text: a cross-encoder reads each pair, a bi-encoder compares
    normalised embeddings. The model's own query/document prompts are used when it names them."""
    import torch
    from sentence_transformers import CrossEncoder, SentenceTransformer
    dev = _device(torch, device)
    if mode == "cross":
        net = CrossEncoder(model, revision=revision, device=dev)
        return [float(s) for s in net.predict([(query, t) for t in texts])]
    net = SentenceTransformer(model, revision=revision, device=dev)
    prompts = getattr(net, "prompts", None) or {}
    q = net.encode([query], normalize_embeddings=True,
                   **({"prompt_name": "query"} if "query" in prompts else {}))
    side = next((n for n in ("document", "passage") if n in prompts), None)
    d = net.encode(texts, normalize_embeddings=True,
                   **({"prompt_name": side} if side else {}))
    return [float(x) for x in d @ q[0]]


def rank(mode: str, model: str, query: str, corpus, out, score=score_texts) -> None:
    """Write {"ranking": [ids best first]}; ties keep corpus order."""
    import json
    docs = [json.loads(line) for line in Path(corpus).read_text(encoding="utf-8").splitlines()
            if line.strip()]
    scores = score(mode, model, query, [d["text"] for d in docs])
    order = sorted(range(len(docs)), key=lambda i: (-scores[i], i))
    Path(out).write_text(json.dumps({"ranking": [docs[i]["id"] for i in order]}),
                         encoding="utf-8")


def tag_text(model: str, text: str, revision: str | None = None,
             device: str | None = None) -> list[dict]:
    """Entity groups from a token-classification model; every non-O group is a span."""
    import torch
    from transformers import pipeline
    pipe = pipeline("token-classification", model=model, revision=revision,
                    device=_device(torch, device), aggregation_strategy="simple")
    return list(pipe(text))


def pii(model: str, text: str, out, tag=tag_text) -> None:
    """Write {"spans": [[start, end, label]]}."""
    import json
    spans = [[int(g["start"]), int(g["end"]), str(g.get("entity_group") or g.get("entity") or "")]
             for g in tag(model, text)]
    Path(out).write_text(json.dumps({"spans": spans}), encoding="utf-8")


def _jsonl(path) -> list[dict]:
    p = Path(path)
    if not p.is_file():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def label_images(model: str, images: list[str], prompt: str, **load):
    """One reply per image from one loaded model, yielded as each is read. #1207."""
    ask = load_reader(model, **load)
    for image in images:
        yield ask(image, prompt)


def vision_label(model: str, frames, prompt: str, out, label=label_images) -> None:
    """Append {id, reply} per frame to out, skipping frames out already answers, so an abort resumes."""
    done = {d["id"] for d in _jsonl(out)}
    todo = [f for f in _jsonl(frames) if f["id"] not in done]
    with Path(out).open("a", encoding="utf-8") as f:
        for frame, reply in zip(todo, label(model, [t["image"] for t in todo], prompt)):
            # A labeller may say a reply filled its token budget: (reply, cut). #1282.
            reply, cut = reply if isinstance(reply, tuple) else (reply, False)
            f.write(json.dumps({"id": frame["id"], "reply": reply, **({"cut": True} if cut else {})}) + "\n")
            f.flush()


def embed_images(model: str, images: list[str], revision: str | None = None, device: str | None = None,
                 batch: int = 32) -> list[list[float]]:
    """CLS token plus mean patch token per image, the frozen features kubrick's linear row used. #1207."""
    import torch
    from PIL import Image
    from transformers import AutoImageProcessor, AutoModel
    dev = _device(torch, device)
    proc = AutoImageProcessor.from_pretrained(model, revision=revision)
    net = AutoModel.from_pretrained(model, revision=revision).to(dev).eval()
    out: list[list[float]] = []
    with torch.no_grad():
        for i in range(0, len(images), batch):
            pics = [Image.open(x).convert("RGB") for x in images[i:i + batch]]
            h = net(**proc(images=pics, return_tensors="pt").to(dev)).last_hidden_state
            out += torch.cat([h[:, 0], h[:, 1:].mean(1)], dim=1).float().cpu().tolist()
    return out


def fit_logistic(X, y, c: float, max_iter: int | None = None):
    """Standardised multinomial logistic regression, L2 as scikit-learn's C; returns predict(X) -> labels. #1207."""
    import torch

    from evals.vision import FIT_MAX_ITER
    max_iter = FIT_MAX_ITER if max_iter is None else max_iter
    labels = sorted(set(y))
    x = torch.tensor(X, dtype=torch.float64)
    mu, sd = x.mean(0), x.std(0).clamp_min(1e-8)
    z = (x - mu) / sd
    t = torch.tensor([labels.index(v) for v in y])
    w = torch.zeros(z.shape[1], len(labels), dtype=torch.float64, requires_grad=True)
    b = torch.zeros(len(labels), dtype=torch.float64, requires_grad=True)
    opt = torch.optim.LBFGS([w, b], max_iter=max_iter, line_search_fn="strong_wolfe")

    def closure():
        opt.zero_grad()
        loss = torch.nn.functional.cross_entropy(z @ w + b, t) + (w ** 2).sum() / (2 * c * len(y))
        loss.backward()
        return loss
    opt.step(closure)

    def predict(xs):
        zx = (torch.tensor(xs, dtype=torch.float64) - mu) / sd
        return [labels[i] for i in (zx @ w + b).argmax(1).tolist()]
    return predict


def vision_probe(model: str, frames, out, features, c: float, shuffles: int, seed: int,
                 embed=embed_images, fit=fit_logistic) -> None:
    """Features (cached), then evals.vision's leave-one-film-out probe and its shuffled-label control."""
    from evals import vision
    rows = _jsonl(frames)
    cache = Path(features)
    have = json.loads(cache.read_text(encoding="utf-8")) if cache.is_file() else {}
    todo = [r for r in rows if r["id"] not in have]
    if todo:
        have.update(zip((r["id"] for r in todo), embed(model, [r["image"] for r in todo])))
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(have), encoding="utf-8")
    picked = [vision.Frame(r["id"], r["film"], Path(r["image"]), r["truth"]) for r in rows]
    preds = vision.probe_predictions(picked, have, shuffles=shuffles, seed=seed, fit=fit, c=c)
    Path(out).write_text(json.dumps(preds), encoding="utf-8")


def _lacks(exc: ImportError) -> int:
    print(exc, file=sys.stderr)
    what = next((ln.strip() for ln in str(exc).splitlines() if ln.strip()), repr(exc))
    print(f"hf-task venv lacks a package: {what}", file=sys.stderr)
    return MISSING_PACKAGE


def main(argv=None, read=None, score=None, tag=None, label=None, embed=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="task", required=True)
    o = sub.add_parser("ocr")
    o.add_argument("--model", required=True)
    o.add_argument("--image", required=True)
    o.add_argument("--prompt", default="")
    o.add_argument("--out", required=True)
    o.add_argument("--revision")
    o.add_argument("--max-new-tokens", type=int, default=None)
    o.add_argument("--device")
    o.add_argument("--attn", default="")
    o.add_argument("--dtype", default="", choices=("", *DTYPES))
    o.add_argument("--one-attempt", action="store_true")
    r = sub.add_parser("rank")
    r.add_argument("--mode", choices=("cross", "bi"), required=True)
    r.add_argument("--model", required=True)
    r.add_argument("--query", required=True)
    r.add_argument("--corpus", required=True)
    r.add_argument("--out", required=True)
    r.add_argument("--revision")
    r.add_argument("--device")
    t = sub.add_parser("pii")
    t.add_argument("--model", required=True)
    t.add_argument("--text", required=True)
    t.add_argument("--out", required=True)
    t.add_argument("--revision")
    t.add_argument("--device")
    v = sub.add_parser("vision-label")
    v.add_argument("--model", required=True)
    v.add_argument("--frames", required=True)
    v.add_argument("--prompt", required=True)
    v.add_argument("--out", required=True)
    v.add_argument("--revision")
    v.add_argument("--max-new-tokens", type=int, default=None)
    v.add_argument("--device")
    v.add_argument("--attn", default="")
    v.add_argument("--dtype", default="", choices=("", *DTYPES))
    v.add_argument("--one-attempt", action="store_true")
    q = sub.add_parser("vision-probe")
    q.add_argument("--model", required=True)
    q.add_argument("--frames", required=True)
    q.add_argument("--out", required=True)
    q.add_argument("--features", required=True)
    q.add_argument("--c", type=float, required=True)
    q.add_argument("--shuffles", type=int, required=True)
    q.add_argument("--seed", type=int, default=1207)
    q.add_argument("--revision")
    q.add_argument("--device")
    argv = list(sys.argv[1:] if argv is None else argv)
    a = p.parse_args(argv)
    if a.task in ("ocr", "vision-label") and read is None and label is None and not (
            a.one_attempt or a.device or a.attn):
        rc = fall_back(_attempt(argv))
        return rc if rc >= 0 else 128 - rc
    try:
        if a.task == "ocr":
            runtime: dict = {}
            reader = read or functools.partial(read_image, revision=a.revision,
                                               max_new_tokens=a.max_new_tokens, device=a.device,
                                               attn=a.attn, runtime=runtime, dtype=a.dtype)
            ocr(a.model, a.image, a.prompt, a.out, read=reader)
            if runtime:
                Path(runtime_path(a.out)).write_text(json.dumps(runtime), encoding="utf-8")
        elif a.task == "vision-label":
            labeller = label or functools.partial(label_images, revision=a.revision, max_new_tokens=a.max_new_tokens,
                                                  device=a.device, attn=a.attn, dtype=a.dtype)
            vision_label(a.model, a.frames, a.prompt, a.out, label=labeller)
        elif a.task == "vision-probe":
            embedder = embed or functools.partial(embed_images, revision=a.revision, device=a.device)
            vision_probe(a.model, a.frames, a.out, a.features, a.c, a.shuffles, a.seed, embed=embedder)
        elif a.task == "rank":
            scorer = score or functools.partial(score_texts, revision=a.revision,
                                                device=a.device)
            rank(a.mode, a.model, a.query, a.corpus, a.out, score=scorer)
        else:
            tagger = tag or functools.partial(tag_text, revision=a.revision, device=a.device)
            pii(a.model, a.text, a.out, tag=tagger)
    except ImportError as exc:
        return _lacks(exc)
    except ValueError as exc:
        gap = import_gap(exc)
        if gap and "trust_remote_code" not in str(exc):
            print(exc, file=sys.stderr)
            return _lacks(ModuleNotFoundError(f"No module named '{gap}'", name=gap))
        if "trust_remote_code" not in str(exc):
            raise
        print(f"needs its own runner: {a.model} ships its own modelling code "
              f"(trust_remote_code), which hf-task never executes", file=sys.stderr)
        return NEEDS_OWN_RUNNER
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
