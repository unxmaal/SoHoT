"""One case through transformers, in the hf-task venv: ocr (#562), retrieval (#563), pii (#564).

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


def read_image(model: str, image: str, prompt: str, revision: str | None = None,
               max_new_tokens: int = 512, device: str | None = None, attn: str = "",
               runtime: dict | None = None) -> str:
    """The model's transcription of `image`: a chat VLM is prompted, an encoder-decoder is not.

    Not a pipeline: transformers 5 has no image-to-text task, and its image-text-to-text
    pipeline refuses a repo with no processor class (trocr). Measured 2026-10-07.
    """
    import torch
    from PIL import Image
    from transformers import AutoModelForImageTextToText, AutoProcessor, AutoTokenizer

    from harness.torch_device import HALF
    dev = _device(torch, device)
    dtype = torch.float16 if dev in HALF else torch.float32
    picture = Image.open(image).convert("RGB")
    # Eager attention repeats grouped KV heads, which MPS's sdpa matmul cannot type. #604.
    net = AutoModelForImageTextToText.from_pretrained(
        model, revision=revision, dtype=dtype,
        **({"attn_implementation": attn} if attn else {})).to(dev)
    if runtime is not None:
        runtime.update(device=dev, attn=str(getattr(net.config, "_attn_implementation", "")
                                            or attn or "default"))
    proc = AutoProcessor.from_pretrained(model, revision=revision)
    if getattr(proc, "chat_template", None):
        messages = [{"role": "user", "content": [{"type": "image", "image": picture},
                                                 {"type": "text", "text": prompt}]}]
        inputs = proc.apply_chat_template(messages, add_generation_prompt=True, tokenize=True,
                                          return_dict=True, return_tensors="pt")
        inputs = inputs.to(dev, dtype=dtype)
        out = net.generate(**inputs, max_new_tokens=max_new_tokens, do_sample=False)
        new = out[:, inputs["input_ids"].shape[1]:]
        return proc.batch_decode(new, skip_special_tokens=True)[0].strip()
    pixels = getattr(proc, "image_processor", proc)(images=picture, return_tensors="pt")
    out = net.generate(pixel_values=pixels.pixel_values.to(dev, dtype=dtype),
                       max_new_tokens=max_new_tokens, do_sample=False)
    decoder = getattr(proc, "tokenizer", None) or _tokenizer(model, revision, AutoTokenizer)
    return decoder.batch_decode(out, skip_special_tokens=True)[0].strip()


def _tokenizer(model: str, revision, auto):
    """AutoTokenizer, else the class the repo's tokenizer_config names.

    transformers 5.17 falls back to a generic backend for a vision-encoder-decoder
    repo (trocr) and cannot build its sentencepiece tokenizer; the named class can.
    """
    try:
        return auto.from_pretrained(model, revision=revision)
    except ValueError:
        import json

        import transformers
        from huggingface_hub import hf_hub_download
        path = hf_hub_download(model, "tokenizer_config.json", revision=revision)
        with open(path, encoding="utf-8") as f:
            named = json.load(f).get("tokenizer_class") or ""
        cls = getattr(transformers, named, None)
        if cls is None:
            raise
        return cls.from_pretrained(model, revision=revision)


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


def main(argv=None, read=None, score=None, tag=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="task", required=True)
    o = sub.add_parser("ocr")
    o.add_argument("--model", required=True)
    o.add_argument("--image", required=True)
    o.add_argument("--prompt", default="")
    o.add_argument("--out", required=True)
    o.add_argument("--revision")
    o.add_argument("--max-new-tokens", type=int, default=512)
    o.add_argument("--device")
    o.add_argument("--attn", default="")
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
    argv = list(sys.argv[1:] if argv is None else argv)
    a = p.parse_args(argv)
    if a.task == "ocr" and read is None and not (a.one_attempt or a.device or a.attn):
        rc = fall_back(_attempt(argv))
        return rc if rc >= 0 else 128 - rc
    try:
        if a.task == "ocr":
            runtime: dict = {}
            reader = read or functools.partial(read_image, revision=a.revision,
                                               max_new_tokens=a.max_new_tokens, device=a.device,
                                               attn=a.attn, runtime=runtime)
            ocr(a.model, a.image, a.prompt, a.out, read=reader)
            if runtime:
                Path(runtime_path(a.out)).write_text(json.dumps(runtime), encoding="utf-8")
        elif a.task == "rank":
            scorer = score or functools.partial(score_texts, revision=a.revision,
                                                device=a.device)
            rank(a.mode, a.model, a.query, a.corpus, a.out, score=scorer)
        else:
            tagger = tag or functools.partial(tag_text, revision=a.revision, device=a.device)
            pii(a.model, a.text, a.out, tag=tagger)
    except ImportError as exc:
        print(exc, file=sys.stderr)
        what = next((ln.strip() for ln in str(exc).splitlines() if ln.strip()), repr(exc))
        print(f"hf-task venv lacks a package: {what}", file=sys.stderr)
        return MISSING_PACKAGE
    except ValueError as exc:
        if "trust_remote_code" not in str(exc):
            raise
        print(f"needs its own runner: {a.model} ships its own modelling code "
              f"(trust_remote_code), which hf-task never executes", file=sys.stderr)
        return NEEDS_OWN_RUNNER
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
