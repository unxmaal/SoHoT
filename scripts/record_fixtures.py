#!/usr/bin/env python3
"""Re-record the registry cards tests/fakes.py reads.

RECORDED, NOT INVENTED. A hand-written card encodes what somebody expected a
registry to say, and three defects in September 2026 existed precisely because
the real one said something else: `lora` sitting seventh in a tag list, a
text-to-SVG model declaring pipeline_tag text-generation, a 2-bit quant whose
tensor names no loader recognises. Nobody writes those on purpose.

    uv run python scripts/record_fixtures.py [model_id ...]

With no arguments it refreshes every card already in the directory, so a
fixture that has gone stale can be updated without anyone deciding what the
new content should be.
"""
from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from harness.inspect import MODEL_URL  # noqa: E402  the URL the tier reads

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "registry"
#: Only the fields the ladder reads. A whole card is 40 KB of README that no
#: test looks at and that changes on every push.
KEEP = ("id", "pipeline_tag", "tags", "library_name", "cardData",
        "siblings", "lastModified", "downloads", "config")
#: Of config, what inspect reads; tokenizer_config alone carries a chat template. #567.
CONFIG_KEEP = ("architectures", "model_type", "auto_map")


def trim(card: dict) -> dict:
    """`card` with its config cut to CONFIG_KEEP."""
    config = card.get("config")
    if not isinstance(config, dict):
        return card
    return {**card, "config": {k: config[k] for k in CONFIG_KEEP if k in config}}


def record(model_id: str) -> Path:
    req = urllib.request.Request(
        MODEL_URL.format(model_id=model_id),
        headers={"User-Agent": "localharness-fixtures"})
    with urllib.request.urlopen(req, timeout=30) as r:
        card = json.load(r)
    out = trim({k: card.get(k) for k in KEEP})
    if out.get("siblings"):
        out["siblings"] = [{"rfilename": s.get("rfilename"),
                            "size": s.get("size")}
                           for s in out["siblings"]]
    path = FIXTURES / (model_id.replace("/", "_") + ".json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=1), encoding="utf-8")
    return path


def main(argv: list[str]) -> int:
    wanted = argv or [p.stem.replace("_", "/", 1)
                      for p in sorted(FIXTURES.glob("*.json"))]
    if not wanted:
        print("nothing to record and nothing recorded yet", file=sys.stderr)
        return 1
    for model_id in wanted:
        try:
            print(f"  {record(model_id)}")
        except Exception as exc:  # noqa: BLE001
            # One dead repo must not stop the rest: a fixture whose model was
            # deleted is a finding, not a reason to refresh nothing.
            print(f"  {model_id}: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
