"""Generated tts cases: seeded English sentences, the sentence itself the reference transcript. #603.

Numbers stay between 2 and 99: the scorer spells digits with num2words, which
says "one hundred and five" where a voice says "one hundred five" (#606).
"""
from __future__ import annotations

import hashlib
import random
import sys

from evals.importers import Imported, provenance

LANE = "tts"
VERSION = "1"
SEED = 603
COUNT = 420
SOURCE = f"generated:evals.importers.tts_synth v{VERSION} seed {SEED}"
DATASET = "SoHoT generated tts cases"
URL = "https://github.com/unxmaal/SoHoT/blob/main/evals/importers/tts_synth.py"
LICENSE = "generated"
#: A generator has no upstream commit; this pins its version and seed instead.
REVISION = hashlib.sha1(SOURCE.encode("utf-8")).hexdigest()
_KEY = "tts-synth"
MAX_WER = 0.2

NAMES = ["Anna", "David", "Maria", "James", "Sarah", "Peter", "Laura", "Daniel",
         "Emma", "Thomas", "Grace", "Henry", "Olivia", "Lucas", "Nina", "Oscar"]
CITIES = ["London", "Paris", "Tokyo", "Chicago", "Berlin", "Madrid", "Sydney",
          "Toronto", "Boston", "Denver", "Rome", "Dublin"]

TEMPLATES = [
    "{name} counted {n} boxes on Monday, then {m} more; was that enough?",
    "Hey {name}, did you really see {n} ducks, or was it just {m}?",
    "Wait, {name}: are the {n} apples ripe, or still {m} days away?",
    "So {name}, if {n} people came, why were there only {m} chairs?",
    "{name}, could you pass the {n} books, and leave the other {m} behind?",
    "Really, {name}? You finished {n} laps, then asked for {m} more?",
    "Listen closely, {name}: the {n} bells rang, then {m} more times.",
    "Did the {n} cats really chase {m} mice all evening, {name}?",
    "Alright, {name}; shall we count {n} stars, or wait for {m}?",
    "{name}, why are there {n} questions, but only {m} answers here?",
    "Guess what, {name}: I met {n} old friends, and {m} brand new ones.",
    "Hold on, {name}; the {n} tickets cost {m} dollars in total, right?",
    "Come now, {name}, can {n} runners beat {m} cyclists in a week?",
    "So {n} slices remain, {name}, and {m} were served already?",
    "{name}, please confirm: {n} windows open, plus {m} tabs; is that correct?",
    "You painted {n} fences, {name}, then did {m} more by dusk?",
    "If {n} birds flew north, {name}, where did the other {m} stay?",
    "Quick now, {name}: grab {n} umbrellas, since {m} are still dry.",
    "Dear {name}, did the {n} letters arrive, or were they {m} days late?",
    "Excuse me, {name}; are these {n} keys for the {m} front doors?",
    "You solved {n} puzzles, {name}, then {m} bonus riddles too.",
    "Wait a moment, {name}; the {n} guests left, yet {m} just arrived.",
    "Listen, {name}; the {n} trains were delayed, so we waited {m} extra minutes.",
    "{name}, could {n} artists finish {m} murals before the festival?",
    "We bought {n} balloons, {name}, then popped {m} by noon.",
    "Alright {name}, report back: {n} files saved, and {m} still pending?",
    "Did you call {n} clients, {name}, or just {m} today?",
    "Quick question, {name}: {n} eggs for {m} people, is that fair?",
    "The {n} songs played, {name}, then {m} encores followed.",
    "Excuse me once more, {name}; are {n} seats left, or are all {m} taken?",
    "Hold tight, {name}; the {n} steps are steep, but only {m} remain.",
    "The flight to {city} left at gate {n}, and {name} sat in row {m}.",
    "\"Is {city} far?\" asked {name}; \"about {n} miles,\" said the driver.",
    "{name} spent {n} nights in {city} (and {m} more on the coast).",
    "In {city}, {name} found {n} bakeries; sadly, only {m} were open.",
    "The museum in {city} has {n} rooms, {name}, but we saw {m} of them.",
    "\"Pack {n} sweaters,\" {name} said, \"because {city} gets cold.\"",
    "{name} took bus {n} across {city}, then walked {m} blocks; tired yet?",
    "Why did {name} ship {n} crates to {city}, and not the {m} we ordered?",
    "The choir from {city} sang {n} hymns; {name} knew {m} of them by heart.",
]


def fetch(seed: int = SEED, count: int = COUNT) -> list[dict]:
    """The seeded draws, one row per case; a sentence already drawn is drawn again."""
    out, seen = [], set()
    for i in range(count):
        rng = random.Random(f"{_KEY}:{VERSION}:{seed}:{i}")
        sentence = ""
        while not sentence or sentence in seen:
            n, m = rng.sample(range(2, 100), 2)
            sentence = rng.choice(TEMPLATES).format(name=rng.choice(NAMES), n=n, m=m,
                                                     city=rng.choice(CITIES))
        seen.add(sentence)
        out.append({"item": i, "seed": seed, "sentence": sentence})
    return out


def convert(row: dict) -> Imported:
    att = provenance(sys.modules[__name__], row["item"],
                     "a template filled with a name, a city and two numbers")
    att.update(version=VERSION, seed=row["seed"])
    return Imported({"id": f"tts-synth-{row['item']:04d}", "modality": LANE, "language": "en",
                     "prompt": row["sentence"], "assert": {"max_wer": MAX_WER},
                     "attribution": att})


#: The negative control, as what the ear heard: the sentence passes, silence or one fixed sentence does not.
RESPONDERS = {
    "reference": lambda case: case.prompt,
    "silence": lambda case: "",
    "fixed": lambda case: TEMPLATES[0].format(name=NAMES[0], n=2, m=3, city=CITIES[0]),
}


def passes(case, heard: str) -> bool:
    """What the tts checker decides when the ear heard `heard`."""
    from harness.checks import speech
    return speech.wer(case.prompt, heard, case.language) <= case.assertions["max_wer"]
