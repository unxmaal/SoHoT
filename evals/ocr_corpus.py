"""Render the ocr lane's cases: text drawn into PNGs whose reference is known. #562.

    uv run python -m evals.ocr_corpus [--out evals/cases/ocr]

Pillow's bundled Aileron font, fixed sizes, seeded noise: the same script writes
the same images, and the images are committed so a test never renders one.
"""
from __future__ import annotations

import argparse
import random
from pathlib import Path

import yaml

DEFAULT_OUT = Path(__file__).resolve().parent / "cases" / "ocr"
PROMPT = "Transcribe all of the text in this image exactly, line by line."
MAX_CER = 0.1

#: id -> (reference text, font size, style)
CASES = {
    "sign-open": ("OPEN 24 HOURS", 48, "plain"),
    "invoice-line": ("Invoice #4471 due 2026-11-30", 32, "plain"),
    "phone-ext": ("Call +1 (555) 013-2297 ext. 42", 32, "plain"),
    "two-lines": ("The quick brown fox\njumps over the lazy dog.", 32, "plain"),
    "serial-small": ("serial no. KX-88213-B", 18, "plain"),
    "platform-noise": ("Platform 9 departs 14:05", 32, "noise"),
    "label-tilted": ("Keep refrigerated after opening", 30, "tilt"),
    "code-line": ("def total(items): return sum(items)", 28, "plain"),
}


def render(text: str, size: int, style: str, seed: int = 7):
    from PIL import Image, ImageDraw, ImageFont
    font = ImageFont.load_default(size=size)
    probe = ImageDraw.Draw(Image.new("L", (1, 1)))
    left, top, right, bottom = probe.multiline_textbbox((0, 0), text, font=font, spacing=8)
    pad = size
    im = Image.new("L", (right - left + 2 * pad, bottom - top + 2 * pad), 255)
    if style == "noise":
        rng = random.Random(seed)
        px = im.load()
        for y in range(im.height):
            for x in range(im.width):
                px[x, y] = 200 + int(40 * x / im.width) + rng.randint(-12, 12)
    ImageDraw.Draw(im).multiline_text((pad - left, pad - top), text, fill=20,
                                      font=font, spacing=8)
    if style == "tilt":
        im = im.rotate(2.0, resample=Image.BICUBIC, expand=True, fillcolor=255)
    return im.convert("RGB")


def write(out: Path = DEFAULT_OUT) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    (out / "images").mkdir(exist_ok=True)
    written = []
    for case_id, (text, size, style) in CASES.items():
        image = out / "images" / f"{case_id}.png"
        render(text, size, style).save(image, optimize=True)
        case = {"id": f"ocr-{case_id}", "modality": "ocr", "prompt": PROMPT,
                "input_file": f"images/{case_id}.png",
                "assert": {"text": text, "max_cer": MAX_CER}}
        path = out / f"{case_id}.yaml"
        path.write_text(yaml.safe_dump(case, sort_keys=False, allow_unicode=True),
                        encoding="utf-8")
        written += [image, path]
    return written


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    for path in write(p.parse_args(argv).out):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
