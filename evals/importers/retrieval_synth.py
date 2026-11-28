"""Generated retrieval cases: seeded notes about invented systems, each question's gold note known by construction. #2182."""
from __future__ import annotations

import hashlib
import json
import random
import re
import sys
from pathlib import Path

from evals.importers import Imported, extract_synth, pii_synth, provenance

LANE = "retrieval"
VERSION = "1"
SEED = 603
COUNT = 840
DATE = "2026-11-27"
SOURCE = f"generated:evals.importers.retrieval_synth v{VERSION} seed {SEED}"
DATASET = "SoHoT generated retrieval cases"
URL = "https://github.com/unxmaal/SoHoT/blob/main/evals/importers/retrieval_synth.py"
LICENSE = "generated"
#: A generator has no upstream commit; this pins its version and seed instead.
REVISION = hashlib.sha1(SOURCE.encode("utf-8")).hexdigest()
_KEY = "retrieval-synth"
K = 1
TRANSFORM = ("a seeded corpus of notes, one per (system, facet); the question asks for one pair, so the gold note is "
             "the one written for it")
#: Questions one corpus carries, in this turn of kinds.
KINDS = ("exact", "synonym", "contrast", "exact", "contrast", "exact", "synonym", "contrast")
ATTEMPTS = 40
ENTITIES = 6
FACETS_EACH = 5

BIRDS = ["Heron", "Plover", "Kestrel", "Wren", "Osprey", "Ibis", "Curlew", "Tern", "Egret", "Shrike", "Pipit", "Lark",
         "Merlin", "Bittern", "Dunlin", "Avocet", "Swift", "Teal", "Godwit", "Siskin"]
TEAMS = ["Ledger", "Compass", "Anvil", "Prism", "Trellis", "Keystone", "Ember", "Lattice", "Harbor", "Sprocket",
         "Tessera", "Quill"]
CITIES = extract_synth.CITIES
LANGS = ["Rust", "Go", "Kotlin", "Elixir", "Haskell", "Zig", "Swift", "Erlang", "Scala", "OCaml"]
MONTHS = extract_synth.MONTHS
FILLER = ["The page was last reviewed in the spring.", "Details change slowly, so check the history first.",
          "An older draft of this note was archived.", "A diagram is attached to the wiki entry.",
          "The entry was reformatted last quarter.", "Nothing about this has been disputed so far."]


def _person(r) -> str:
    return f"{r.choice(pii_synth.FIRST)} {r.choice(pii_synth.LAST)}"


def _date(r) -> str:
    return f"{r.choice(MONTHS)} {r.randint(1, 28)}, {r.randint(2027, 2029)}"


#: facet -> (word the notes repeat, value drawer, how the value reads, note variants, exact asks, synonym asks)
FACETS = {
    "owner": ("owner", lambda r: r.choice(TEAMS), "the {v} team",
              ["The owner of {E} is the {v} team, and every change to {E} goes through their review.",
               "{E} has one owner, the {v} team, which approves each release and keeps the runbook current.",
               "Questions about {E} start with its owner, the {v} team; they triage anything filed against it."],
              ["Who is the owner of {E}?", "Which team is the owner of {E}?"],
              ["Which group is accountable for {E}?", "Who is in charge of {E}?"]),
    "port": ("port", lambda r: str(r.randint(2000, 9999)), "{v}",
             ["{E} listens on port {v}; anyone who cannot reach that port should check the firewall rules.",
              "The service {E} takes traffic on port {v}, and the port is fixed across every environment.",
              "For {E} the port is {v}. Changing the port needs a change ticket."],
             ["Which port does {E} listen on?", "What is the port number of {E}?"],
             ["On what socket number does {E} receive requests?", "What number do you dial to talk to {E}?"]),
    "retire": ("retirement date", _date, "{v}",
               ["The retirement date for {E} is {v}; after that day it stops serving.",
                "{E} reaches its retirement date on {v}, so every consumer has to migrate before then.",
                "Plan around the retirement date of {E}: {v} is when it goes dark."],
               ["What is the retirement date of {E}?", "When is the retirement date for {E}?"],
               ["At what point will {E} be switched off?", "Until when can {E} still be used?"]),
    "budget": ("budget", lambda r: f"{r.randint(12, 980) * 5}", "${v}k",
               ["The yearly budget for {E} is ${v}k, covering licences and hosting.",
                "{E} was granted a budget of ${v}k this year; an unspent budget does not roll over.",
                "Finance fixed the budget of {E} at ${v}k, reviewed every quarter."],
               ["What is the budget of {E}?", "How big is the budget for {E} this year?"],
               ["How many dollars may {E} spend?", "What funding was approved for {E}?"]),
    "site": ("datacenter", lambda r: r.choice(CITIES), "the {v} datacenter",
             ["{E} runs in the {v} datacenter, next to its database.",
              "The primary datacenter of {E} is {v}; failover is handled by operations.",
              "All instances of {E} live in the datacenter at {v}."],
             ["Which datacenter hosts {E}?", "In which datacenter does {E} run?"],
             ["In which city are the machines of {E} located?", "Where is {E} physically kept?"]),
    "limit": ("rate limit", lambda r: str(r.randint(2, 90) * 50), "{v} requests per minute",
              ["The rate limit of {E} is {v} requests per minute; callers over it get a 429.",
               "{E} enforces a rate limit of {v} requests per minute per caller.",
               "Expect throttling at the rate limit for {E}, which is {v} requests per minute."],
              ["What is the rate limit of {E}?", "How high is the rate limit for {E}?"],
              ["What throughput ceiling applies to {E}?", "How much load can {E} absorb before it pushes back?"]),
    "pager": ("pager rotation", _person, "{v}",
              ["The pager rotation for {E} is run by {v}; alerts page them first.",
               "{v} is on the pager rotation of {E} this month, with a deputy as backup.",
               "Pages from {E} land on the pager rotation of {v} before anyone else."],
              ["Who is on the pager rotation of {E}?", "Whose pager rotation covers {E}?"],
              ["Who gets woken up at night when {E} breaks?", "Which engineer handles incidents for {E}?"]),
    "lang": ("language", lambda r: r.choice(LANGS), "{v}",
             ["{E} is implemented in {v}; the language was chosen for its tooling.",
              "The language of {E} is {v}, which new contributors must know.",
              "Source for {E} is written in {v}; no other language is allowed in its repository."],
             ["Which language is {E} written in?", "What is the language of {E}?"],
             ["What do developers type to build {E}?", "With what technology stack is {E} coded?"]),
}
CONTRAST = ("Unlike {P}, whose {w} is handled elsewhere, the {w} of {E} is {vt}. "
            "Nobody should assume the {w} of {E} applies to {P}, the {w} differs.")
_WORD = re.compile(r"[a-z0-9]+")
STOP = frozenset("a an the of to in on at is are was be it its for by and or with as that this from what which who "
                 "how do does when where whose before after than then not no".split())


def words(text: str) -> set[str]:
    """Content words of a text, lower-cased with a trailing s dropped, for the kind checks."""
    return {w[:-1] if len(w) > 3 and w.endswith("s") else w for w in _WORD.findall(text.lower()) if w not in STOP}


def _corpus(r) -> tuple[list[dict], dict]:
    """(notes in corpus order, facts): facts[(system, facet)] -> note id; each note carries its system and facet."""
    names = [f"{b}-{r.randint(2, 9)}" for b in r.sample(BIRDS, ENTITIES)]
    facets = list(FACETS)
    have = {e: r.sample(facets, FACETS_EACH) for e in names}
    value = {(e, f): FACETS[f][1](r) for e in names for f in have[e]}
    peers: dict[tuple, str] = {}
    notes = []
    for e in names:
        for f in have[e]:
            w, _, show, variants, *_ = FACETS[f]
            others = [p for p in names if p != e and f in have[p]]
            vt = show.format(v=value[(e, f)])
            contrast = bool(others) and r.random() < 0.4
            if contrast:
                p = r.choice(others)
                peers[(p, f)] = e
                text = CONTRAST.format(P=p, w=w, E=e, vt=vt)
            else:
                text = r.choice(variants).format(E=e, v=value[(e, f)])
            if r.random() < 0.4:
                text += " " + r.choice(FILLER)
            notes.append({"system": e, "facet": f, "text": text, "contrast": contrast})
    r.shuffle(notes)
    for i, n in enumerate(notes):
        n["id"] = f"n{i:02d}"
    return notes, peers


def _queries(r, notes: list[dict], peers: dict) -> list[dict]:
    """One question per slot of KINDS, each over a different note."""
    by = {(n["system"], n["facet"]): n for n in notes}
    used: set = set()
    keys: list = [None] * len(KINDS)
    for want in ("contrast", None):
        for i, kind in enumerate(KINDS):
            if (kind == "contrast") != (want == "contrast"):
                continue
            plain = [k for k in sorted(by) if not by[k]["contrast"] and k not in used]
            pool = [k for k in plain if k in peers] if kind == "contrast" else plain
            keys[i] = r.choice(pool)
            used.add(keys[i])
    out = []
    for kind, (e, f) in zip(KINDS, keys):
        ask = FACETS[f][5 if kind == "synonym" else 4]
        out.append({"kind": kind, "system": e, "facet": f, "question": r.choice(ask).format(E=e),
                    "relevant": by[(e, f)]["id"]})
    return out


def corpus_of(seed: int, index: int) -> tuple[list[dict], list[dict]]:
    r = random.Random(f"{_KEY}:{VERSION}:{seed}:{index}")
    for _ in range(ATTEMPTS):
        notes, peers = _corpus(r)
        plain = {(n["system"], n["facet"]) for n in notes if not n["contrast"]}
        if sum(1 for k in peers if k in plain) >= KINDS.count("contrast"):
            return notes, _queries(r, notes, peers)
    raise ValueError(f"retrieval_synth corpus {index}: too few contrast notes in {ATTEMPTS} draws")


def fetch(seed: int = SEED, count: int = COUNT) -> list[dict]:
    """The seeded draws, one row per question; KINDS questions share one corpus."""
    out, size = [], len(KINDS)
    for c in range((count + size - 1) // size):
        notes, queries = corpus_of(seed, c)
        for j, q in enumerate(queries):
            item = c * size + j
            if item >= count:
                break
            out.append({"item": item, "seed": seed, "corpus": c, "notes": notes, **q})
    return out


def corpus_file(row: dict) -> str:
    return f"corpus-{row['corpus']:03d}.jsonl"


def convert(row: dict) -> Imported:
    att = provenance(sys.modules[__name__], row["item"], TRANSFORM, DATE)
    att.update(version=VERSION, seed=row["seed"], kind=row["kind"], facet=row["facet"])
    case = {"id": f"retrieval-synth-{row['item']:04d}", "modality": "retrieval", "prompt": row["question"],
            "input_file": corpus_file(row), "assert": {"relevant": [row["relevant"]], "k": K}, "attribution": att}
    body = "".join(json.dumps({"id": n["id"], "text": n["text"]}, ensure_ascii=False) + "\n" for n in row["notes"])
    return Imported(case, files=((corpus_file(row), body.encode("utf-8")),))


def _ids(case) -> list[str]:
    return [json.loads(line)["id"] for line in Path(case.input_file).read_text(encoding="utf-8").splitlines() if line]


def _ranking(ids) -> str:
    return json.dumps({"ranking": list(ids)})


def _wrong(case) -> str:
    gold = set(case.assertions["relevant"])
    return _ranking([i for i in _ids(case) if i not in gold] + [i for i in _ids(case) if i in gold])


#: The negative control: the reference passes; the gold note ranked last, the corpus order and a shuffle do not.
RESPONDERS = {
    "reference": lambda c: _ranking(list(c.assertions["relevant"]) + _ids(c)),
    "wrong": _wrong,
    "corpus_order": lambda c: _ranking(_ids(c)),
    "shuffled": lambda c: _ranking(random.Random(c.id).sample(_ids(c), len(_ids(c)))),
}


def passes(case, answer: str) -> bool:
    from evals.core import score
    return score(case, answer).passed
