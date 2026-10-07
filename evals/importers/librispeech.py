"""stt: a committed LibriSpeech test-clean manifest pinned by sha256; audio fetched into a cache. #603.

    uv run python -m evals.importers.librispeech [--cache DIR]   # rebuild the manifest
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

from evals.importers import CASES, Imported, provenance

LANE = "stt"
SOURCE = "hf:openslr/librispeech_asr"
DATASET = "LibriSpeech test-clean (Panayotov et al. 2015)"
URL = "https://huggingface.co/datasets/openslr/librispeech_asr"
LICENSE = "CC BY 4.0"
REVISION = "71cacbfb7e2354c4226d01e70d77d5fca3d04ba1"
HF_ID = "openslr/librispeech_asr"
CONFIG, SPLIT = "clean", "test"
ROWS_API = "https://datasets-server.huggingface.co/rows"
#: The source has no per-item date; this bounds it (RULE #460).
DATE_NOTE = "before 2015-04: LibriVox recordings, LibriSpeech release"
#: Measured stt candidates whose cards name LibriSpeech as training data (its train splits).
TRAINED_ON = ["nvidia/parakeet-tdt-0.6b-v2", "nvidia/parakeet-ctc-0.6b"]
TRANSFORM = "human transcript as the reference; pass only when every word is right"
MANIFEST = Path(__file__).with_name("librispeech.jsonl")
MIN_WORDS, MAX_WORDS = 3, 20
MAX_WER = 0.0
N = 480
PAGE = 100


def select(rows, n: int = N) -> list[dict]:
    """Utterances in sha256(id) order, MIN_WORDS to MAX_WORDS long."""
    keep = [{"uid": r["id"], "row": idx, "text": r["text"].strip()} for idx, r in rows
            if MIN_WORDS <= len(r["text"].split()) <= MAX_WORDS]
    keep.sort(key=lambda e: hashlib.sha256(e["uid"].encode("utf-8")).hexdigest())
    return keep[:n]


def manifest() -> list[dict]:
    return [json.loads(line) for line in MANIFEST.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def download(entries, cache: Path, get) -> list[Path]:
    """Each clip into the cache, verified against its pinned sha256; `get(row)` returns bytes."""
    cache = Path(cache)
    cache.mkdir(parents=True, exist_ok=True)
    out = []
    for e in entries:
        path = cache / f"{e['uid']}.flac"
        if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == e["sha256"]:
            out.append(path)
            continue
        blob = get(e["row"])
        digest = hashlib.sha256(blob).hexdigest()
        if digest != e["sha256"]:
            raise ValueError(f"{e['uid']}: sha256 {digest}, pinned {e['sha256']}")
        path.write_bytes(blob)
        out.append(path)
    return out


def readable(text: str) -> str:
    low = text.strip().lower()
    return low[:1].upper() + low[1:]


def rows(entries, cache: Path) -> list[dict]:
    cache = Path(cache).resolve()
    return [{**e, "audio": str(cache / f"{e['uid']}.flac")} for e in entries]


def supersede(entries, root: Path = CASES) -> None:
    """Remove an evals.corpora case of the same clip, so one utterance is never two cases."""
    for e in entries:
        dup = Path(root) / LANE / f"{e['uid']}.yaml"
        if dup.is_file():
            dup.unlink()


def default_cache() -> Path:
    import os
    from harness import env
    return Path(os.environ.get("LIBRISPEECH_CACHE") or env.beside() / "corpora" / "librispeech-rows")


def fetch() -> list[dict]:
    """The manifest's clips, downloaded into the cache and verified; rows carry their audio path."""
    cache = default_cache()
    entries = manifest()
    download(entries, cache, audio_getter())
    supersede(entries)
    return rows(entries, cache)


def convert(row: dict) -> Imported:
    att = provenance(sys.modules[__name__], f"{SPLIT}.{CONFIG} row {row['row']} ({row['uid']})",
                     TRANSFORM)
    case = {"id": row["uid"], "modality": "stt", "prompt": readable(row["text"]),
            "audio_file": row["audio"], "assert": {"max_wer": MAX_WER},
            "attribution": {**att, "date_note": DATE_NOTE, "sha256": row["sha256"],
                            "trained_on": list(TRAINED_ON)}}
    return Imported(case)


def _neighbour_prompt(case) -> str:
    import yaml
    files = sorted(Path(case.source).parent.glob("*.yaml"))
    nxt = files[(files.index(Path(case.source)) + 1) % len(files)]
    return yaml.safe_load(nxt.read_text(encoding="utf-8"))["prompt"]


RESPONDERS = {
    "reference": lambda c: c.prompt,
    "the": lambda c: "the",
    "shuffled": _neighbour_prompt,
}


def passes(case, answer: str) -> bool:
    from evals.core import score
    return score(case, answer).passed


def _get(params: dict) -> dict:
    import httpx
    for attempt in range(8):
        r = httpx.get(ROWS_API, params=params, timeout=120)
        if r.status_code != 429 and r.status_code < 500:
            r.raise_for_status()
            return r.json()
        time.sleep(float(r.headers.get("retry-after") or 2 ** attempt))
    r.raise_for_status()
    return r.json()


def _page(offset: int, length: int) -> list:
    got = _get({"dataset": HF_ID, "config": CONFIG, "split": SPLIT,
                "offset": offset, "length": length})
    return got.get("rows") or []


def _src(row: dict) -> str:
    src = row["audio"][0]["src"]
    if f"/{REVISION}/" not in src:
        raise ValueError(f"{HF_ID} is no longer served at revision {REVISION}")
    return src


def audio_getter():
    """get(row) -> bytes, reading the rows API a page at a time: single-row reads hit rate limits."""
    import httpx
    srcs: dict[int, str] = {}

    def get(row: int) -> bytes:
        if row not in srcs:
            start = row - row % PAGE
            for r in _page(start, PAGE):
                srcs[r["row_idx"]] = _src(r["row"])
        if row not in srcs:
            raise ValueError(f"{HF_ID} has no row {row}")
        return httpx.get(srcs.pop(row), timeout=120).raise_for_status().content
    return get


def build_manifest(cache: Path, n: int = N) -> list[dict]:
    import httpx
    got, offset = [], 0
    while True:
        page = _page(offset, PAGE)
        if not page:
            break
        got += [(r["row_idx"], r["row"]) for r in page]
        offset += len(page)
    entries = select(got, n)
    srcs = {idx: _src(r) for idx, r in got}
    for e in entries:
        held = Path(cache) / f"{e['uid']}.flac"
        blob = held.read_bytes() if held.is_file() else (
            httpx.get(srcs[e["row"]], timeout=120).raise_for_status().content)
        e["sha256"], e["bytes"] = hashlib.sha256(blob).hexdigest(), len(blob)
        Path(cache).mkdir(parents=True, exist_ok=True)
        held.write_bytes(blob)
    MANIFEST.write_text("".join(json.dumps(e, sort_keys=True) + "\n" for e in entries),
                        encoding="utf-8")
    return entries


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m evals.importers.librispeech")
    ap.add_argument("--cache", type=Path, default=None)
    a = ap.parse_args(argv)
    got = build_manifest(a.cache or default_cache())
    print(f"{len(got)} clips in {MANIFEST.name}; import with `soh cases import librispeech`",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
