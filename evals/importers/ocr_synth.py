"""Generated ocr cases: seeded text rendered into small PNGs whose reference is exact. #603.

Only Pillow's bundled font renders the same on macOS, Linux and Windows, so the
variety is in size, weight, slant, width, contrast, noise, blur and rotation.
"""
from __future__ import annotations

import functools
import hashlib
import io
import random
import sys

from evals.importers import Imported, provenance

LANE = "ocr"
VERSION = "1"
SEED = 603
COUNT = 440
SOURCE = f"generated:evals.importers.ocr_synth v{VERSION} seed {SEED}"
DATASET = "SoHoT generated ocr cases"
URL = "https://github.com/unxmaal/SoHoT/blob/main/evals/importers/ocr_synth.py"
LICENSE = "generated"
#: A generator has no upstream commit; this pins its version and seed instead.
REVISION = hashlib.sha1(SOURCE.encode("utf-8")).hexdigest()
_KEY = "ocr-synth"
PROMPT = "Transcribe all of the text in this image exactly, line by line."
MAX_CER = 0.1

WORDS = ["Nova", "Orbit", "Cedar", "Pixel", "Harbor", "Summit", "Atlas", "Delta",
         "Maple", "Quartz", "Willow", "Falcon", "Zephyr", "Comet", "Juniper", "Vertex"]

TEMPLATES = {
    "invoice": ["Invoice #{n} due 2026-11-{dd}", "Ref: #{n} - Pay by {dd}/11/26",
                "Total due: ${n}.99", "PO #{n} confirmed", "Balance: {n} units @ $4.50",
                "Invoice #{n} | VAT incl.", "Amount: {n}.00 USD", "Tax {d}% on ${n}",
                "#{n} | Terms: 30 days", "Invoice #{n} paid ${d}.50"],
    "sign": ["OPEN {d} DAYS A WEEK", "CLOSED SUNDAY {d}PM", "NO PARKING {d}AM-{d}PM", "SALE {d}0% OFF",
             "PUSH TO OPEN {L}{d}", "EXIT {d} THIS WAY", "PLATFORM {d}", "QUIET ZONE {d}",
             "GATE {L}{dd}", "{W} STREET", "NO ENTRY - BAY {dd}", "{W} AVENUE {n}"],
    "code": ["for i in range({n}): print(i)", "x = {d} + {e}  # add them",
             "if n > {n}: return True", "arr = [1, 2, {d}, {n}]", "def f(x): return x * {d}",
             "result = items[{d}] + {n}", "while (count < {n}) count++;",
             "return items[{d}] * {n}", "for k in range({d}, {n}): pass",
             "SELECT id FROM {w} LIMIT {n};"],
    "label": ["Keep below {d}C after opening", "Best before: 2026-11-{dd}",
              "Net weight {n} g", "Do not freeze #{d}", "Contains {n} servings",
              "Store cool & dry #{n}", "Batch #{n} - Lot {d}", "Expiry: {dd}/{d}/2027",
              "Shake well, use within {d} days", "{W} Farms - {n} ml"],
    "numbers": ["Lot {n} / Qty {d}0 / Net {d}.5 kg", "Ref {n} - {d} of {e} items",
                "Page {d} / {n} pages", "Row {n}, Col {d} of {e}", "Order #{n} - {d} units",
                "Tier {d}, Rank {n}", "Code {n}-{d}{e}-{d}", "SN: {L}{L}-{n}-{L}",
                "{n}.{dd} kg x {d}", "Item {n} | {d} in stock"],
    "mixed": ["{W}Book Pro M{d} - 16GB RAM", "{W}Phone {d} {n}MHz 5G", "{W}Cam 4K {d}MP",
              "{W}Watch {d} - GPS", "{W}Tablet {d} inch {n}GB", "{W}Monitor 27in {n}Hz",
              "{W}Speaker {d}0W Bluetooth", "{W}Router {d} band {n}Mbps",
              "{W}Charger {d}5W USB-C", "eBay order {L}{n}x"],
}
STYLES = ("plain", "bold", "slant", "narrow", "wide", "inverse", "faint",
          "noise", "blur", "tilt")
SIZES = (14, 16, 20, 24, 28, 32, 36)
#: Degradations that leave the clean OS reader room to miss, so a holdout is not saturated.
DEGRADE = ("none", "lowres", "smear", "ghost", "speckle", "skew")
#: Strength of each degradation, tuned so the OS reader passes well short of every case.
STRENGTH = {"lowres": 0.27, "smear": 2.4, "ghost": 0.07, "speckle": 0.08, "skew": 20}


def _fill(rng: random.Random, template: str) -> str:
    return template.format(
        n=rng.randint(10, 9999), d=rng.randint(1, 9), e=rng.randint(1, 9),
        dd=f"{rng.randint(1, 28):02d}", L=rng.choice("ABCDEFGHJKMNPRSTUVWXYZ"),
        W=rng.choice(WORDS), w=rng.choice(WORDS).lower())


def fetch(seed: int = SEED, count: int = COUNT) -> list[dict]:
    """The seeded draws, one row per case; a text already drawn is drawn again."""
    out, seen = [], set()
    kinds = sorted(TEMPLATES)
    for i in range(count):
        rng = random.Random(f"{_KEY}:{VERSION}:{seed}:{i}")
        kind = kinds[i % len(kinds)]
        text = ""
        while not text or text in seen:
            text = _fill(rng, rng.choice(TEMPLATES[kind]))
            if rng.random() < 0.2:
                text += "\n" + _fill(rng, rng.choice(TEMPLATES[rng.choice(kinds)]))
        seen.add(text)
        style, size, degrade = rng.choice(STYLES), rng.choice(SIZES), rng.choice(DEGRADE)
        out.append({"item": i, "seed": seed, "text": text, "kind": kind, "style": style,
                    "size": size, "degrade": degrade})
    return out


def case_of(row: dict) -> dict:
    """The case file for a row, without rendering its image."""
    case_id = f"ocr-synth-{row['item']:04d}"
    att = provenance(sys.modules[__name__], row["item"],
                     f"rendered with Pillow's bundled font, {row['style']}, "
                     f"{row['size']}px, degraded {row['degrade']}")
    att.update(version=VERSION, seed=row["seed"], kind=row["kind"], style=row["style"],
               size=row["size"], degrade=row["degrade"])
    return {"id": case_id, "modality": LANE, "prompt": PROMPT,
            "input_file": f"images/{case_id}.png",
            "assert": {"text": row["text"], "max_cer": MAX_CER}, "attribution": att}


def convert(row: dict) -> Imported:
    case = case_of(row)
    png = io.BytesIO()
    render(row["text"], row["size"], row["style"], row["seed"] * 100003 + row["item"],
           row["degrade"]).save(png, format="PNG", optimize=True)
    return Imported(case, files=((case["input_file"], png.getvalue()),))


@functools.lru_cache(maxsize=4)
def _texts(directory) -> tuple:
    from evals.core import load_cases
    return tuple(c.assertions["text"] for c in load_cases(directory))


def _neighbour(case) -> str:
    texts = _texts(case.source.parent)
    return texts[(texts.index(case.assertions["text"]) + 1) % len(texts)]


#: The negative control: the reference passes, another case's text does not.
RESPONDERS = {
    "reference": lambda case: case.assertions["text"],
    "other-case": _neighbour,
    "empty": lambda case: "",
}


def passes(case, answer: str) -> bool:
    from evals.core import score
    return score(case, answer).passed


def render(text: str, size: int, style: str, seed: int, degrade: str = "none"):
    from PIL import Image, ImageDraw, ImageFilter, ImageFont
    font = ImageFont.load_default(size=size)
    stroke = 1 if style == "bold" else 0
    probe = ImageDraw.Draw(Image.new("L", (1, 1)))
    left, top, right, bottom = probe.multiline_textbbox((0, 0), text, font=font, spacing=8,
                                                       stroke_width=stroke)
    pad = size // 2 + 4
    ink, paper = (235, 25) if style == "inverse" else (20, 250)
    if style == "faint":
        ink, paper = 110, 200
    im = Image.new("L", (right - left + 2 * pad, bottom - top + 2 * pad), paper)
    if style == "noise":
        rng = random.Random(seed)
        im.putdata([200 + int(40 * (k % im.width) / im.width) + 6 * rng.randint(-2, 2)
                    for k in range(im.width * im.height)])
    ImageDraw.Draw(im).multiline_text((pad - left, pad - top), text, fill=ink, font=font,
                                      spacing=8, stroke_width=stroke, stroke_fill=ink)
    if style == "slant":
        shear = 0.2
        im = im.transform((im.width + int(shear * im.height), im.height), Image.AFFINE,
                          (1, shear, -shear * im.height, 0, 1, 0),
                          resample=Image.BICUBIC, fillcolor=paper)
    elif style in ("narrow", "wide"):
        im = im.resize((int(im.width * (0.8 if style == "narrow" else 1.25)), im.height),
                       Image.LANCZOS)
    elif style == "blur":
        im = im.filter(ImageFilter.GaussianBlur(0.8))
    elif style == "tilt":
        im = im.rotate(random.Random(seed).choice((-3, -2, 2, 3)), resample=Image.BICUBIC,
                       expand=True, fillcolor=paper)
    return _degrade(im, degrade, seed, paper)


def _degrade(im, how: str, seed: int, paper: int):
    from PIL import Image, ImageFilter
    if how == "none":
        return im
    if how not in STRENGTH:
        raise ValueError(f"unknown degradation {how!r}; known: {', '.join(DEGRADE)}")
    k = STRENGTH[how]
    if how == "lowres":
        small = im.resize((max(1, int(im.width * k)), max(1, int(im.height * k))), Image.BOX)
        return small.resize(im.size, Image.NEAREST)
    if how == "smear":
        return im.filter(ImageFilter.GaussianBlur(k))
    if how == "ghost":
        return im.point(lambda v: int(paper + (v - paper) * k))
    if how == "speckle":
        rng = random.Random(seed ^ 0x5EED)
        px = im.load()
        for y in range(im.height):
            for x in range(im.width):
                if rng.random() < k:
                    px[x, y] = rng.choice((0, 255))
        return im
    if how == "skew":
        return im.rotate(random.Random(seed).choice((-k, k)), resample=Image.BICUBIC,
                         expand=True, fillcolor=paper)
    return im
