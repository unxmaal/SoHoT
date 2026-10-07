"""SQuAD 2.0 dev at a pinned commit, shared by squad2_check, squad2_extract and squad2_retrieval. #603."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

SOURCE = "github:rajpurkar/SQuAD-explorer"
DATASET = "SQuAD 2.0, dev (Rajpurkar et al. 2018)"
LICENSE = "CC BY-SA 4.0"
REVISION = "240e165ab706d95bd4323653bb92421f446208cf"
URL = f"https://raw.githubusercontent.com/rajpurkar/SQuAD-explorer/{REVISION}/dataset/dev-v2.0.json"
SHA256 = "80a5225e94905956a6446d296ca1093975c4d3b3260f1d6c8f68bc2ab77182d8"
#: The source has no per-item date; this bounds it (RULE #460).
DATE_NOTE = "before 2018-06: SQuAD 2.0 release, paragraphs from 2016 Wikipedia"
#: Measured candidates whose cards name this dataset as training data (none found 2026-10-07).
TRAINED_ON: list[str] = []


@dataclass(frozen=True)
class Question:
    qid: str
    question: str
    answers: tuple
    answerable: bool


@dataclass(frozen=True)
class Paragraph:
    article: str
    index: int
    context: str
    qas: tuple

    @property
    def pid(self) -> str:
        return f"{self.article}#{self.index}"


def order(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def shuffled(items, key):
    return sorted(items, key=lambda x: order(key(x)))


def verified(blob: bytes) -> dict:
    digest = hashlib.sha256(blob).hexdigest()
    if digest != SHA256:
        raise ValueError(f"SQuAD 2.0 dev changed: sha256 {digest}, pinned {SHA256}")
    return json.loads(blob.decode("utf-8"))


def load(cache: Path | None = None) -> dict:
    """The dev set from the cache if it holds the pinned bytes, else downloaded into it."""
    from harness import env
    cache = Path(cache) if cache else env.beside() / "corpora" / "squad2"
    path = cache / "dev-v2.0.json"
    if path.is_file():
        try:
            return verified(path.read_bytes())
        except ValueError:
            path.unlink()
    import httpx
    blob = httpx.get(URL, timeout=120, follow_redirects=True).raise_for_status().content
    data = verified(blob)
    cache.mkdir(parents=True, exist_ok=True)
    path.write_bytes(blob)
    return data


def paragraphs(data: dict) -> list[Paragraph]:
    out = []
    for article in data["data"]:
        for i, para in enumerate(article["paragraphs"]):
            qas = []
            for qa in para["qas"]:
                texts = []
                for a in qa.get("answers") or ():
                    t = a["text"].strip()
                    if t and t not in texts:
                        texts.append(t)
                qas.append(Question(qa["id"], qa["question"].strip(), tuple(texts),
                                    bool(texts) and not qa.get("is_impossible")))
            out.append(Paragraph(article["title"], i, para["context"], tuple(qas)))
    return out


def attribution(mod, item: str, transform: str) -> dict:
    from evals.importers import provenance
    return {**provenance(mod, item, transform), "date_note": DATE_NOTE,
            "trained_on": list(TRAINED_ON)}


def neighbour(case) -> dict:
    """The next case file in its directory as raw YAML, the last wrapping to the first: a shuffled responder's key."""
    import yaml
    files = sorted(Path(case.source).parent.glob("*.yaml"))
    nxt = files[(files.index(Path(case.source)) + 1) % len(files)]
    return yaml.load(nxt.read_text(encoding="utf-8"),
                     Loader=getattr(yaml, "CSafeLoader", yaml.SafeLoader))
