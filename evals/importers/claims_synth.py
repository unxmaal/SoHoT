"""Generated claims cases: seeded retro-computing chat with the claims in it known by construction. #2182.

Every fact is a draw from a table, written into the chat in one of several phrasings; the reviewed
claim is the table's sentence, so the reference reply is those sentences. Each reviewed case also
carries one rejected claim (made up or wrong) that a planted reply emits, and the expect-empty
cases hold only questions, opinions, jokes and greetings.
"""
from __future__ import annotations

import hashlib
import json
import random
import sys

from evals.importers import Imported, provenance

LANE = "claims"
VERSION = "1"
SEED = 2182
COUNT = 1440
SOURCE = f"generated:evals.importers.claims_synth v{VERSION} seed {SEED}"
DATASET = "SoHoT generated claims cases"
URL = "https://github.com/unxmaal/SoHoT/blob/main/evals/importers/claims_synth.py"
LICENSE = "generated"
#: A generator has no upstream commit; this pins its version and seed instead.
REVISION = hashlib.sha1(SOURCE.encode("utf-8")).hexdigest()
_KEY = "claims-synth"
EMPTY_SHARE = 0.45

SYSTEM = (
    "Lines are '[ref] user-id: text'. Extract standalone factual claims about technology, hardware, software, "
    "SGI and IRIX, retrocomputing, first-hand experience, or where to find things. Rewrite each in your own "
    "words as one short sentence, never copy a message. It must make sense alone: resolve pronouns ('it' "
    "becomes the thing meant). No questions, opinions, jokes, banter or greetings. First-hand experience is "
    "stated as the speaker's own ('they run ...'). Reply {\"c\":[[user-id, claim, [refs]], ...]}: the exact "
    "user id of the line the claim rests on, the claim without any user id in it, the ref numbers of its "
    "lines. Say only what the lines say. With zero claims, reply {\"c\":[]}.")
SCHEMA = {
    "additionalProperties": False,
    "properties": {"c": {"items": {"maxItems": 3, "minItems": 3, "prefixItems": [
        {"pattern": "^user-[0-9a-f]{4,}$", "type": "string"},
        {"maxLength": 220, "type": "string"},
        {"items": {"type": "integer"}, "minItems": 1, "type": "array"}], "type": "array"},
        "type": "array"}},
    "required": ["c"], "type": "object"}

MACHINES = ["Indy", "Indigo2", "O2", "Octane", "Octane2", "Onyx2", "Fuel", "Tezro",
            "Challenge S", "Origin 200", "Indigo", "Crimson", "Personal IRIS", "Onyx"]

#: attribute -> (values, claim, phrasings naming the machine, phrasings with a bare "it", first-hand phrasings)
ATTRS = {
    "cpu": (["R4400", "R5000", "R10000", "R12000", "R14000", "R8000", "R4600"],
            "The {m} can take an {v} CPU.",
            ["the {m} will happily run an {v} processor", "you can drop an {v} into the {m}",
             "{m} boards accept the {v} chip"],
            ["it takes an {v} cpu no problem", "it runs the {v} fine"],
            ["my {m} has an {v} in it", "i put an {v} in my {m} last year"]),
    "ram": (["128 MB", "256 MB", "512 MB", "1 GB", "2 GB", "4 GB", "8 GB"],
            "The {m} supports up to {v} of RAM.",
            ["the {m} tops out at {v} of memory", "max memory on the {m} is {v}",
             "{m} owners can fit {v} of RAM at most"],
            ["it maxes out at {v} of ram", "it will not go past {v} of memory"],
            ["my {m} has {v} of ram installed", "i filled my {m} with {v} of memory"]),
    "os": (["5.3", "6.2", "6.3", "6.5.22", "6.5.30"],
           "The {m} runs IRIX {v}.",
           ["the {m} is happiest on irix {v}", "irix {v} is what runs on the {m} here",
            "for the {m} you want irix {v}"],
           ["it boots irix {v} without trouble", "it is stable on irix {v}"],
           ["i run irix {v} on my {m}", "my {m} sits on irix {v}"]),
    "gfx": (["XZ", "Newport", "Extreme", "VPro V12", "SI", "SE", "Impact MXI", "Elan"],
            "The {m} can be fitted with {v} graphics.",
            ["the {m} was sold with {v} graphics", "{v} graphics exist for the {m}",
             "you can order the {m} with {v} graphics"],
            ["it comes with {v} graphics", "it can take {v} graphics"],
            ["my {m} came with {v} graphics", "the {m} on my desk has {v} graphics"]),
    "disk": (["9 GB", "18 GB", "36 GB", "73 GB"],
             "The {m} accepts a {v} SCSI drive.",
             ["the {m} boots from a {v} scsi disk", "a {v} scsi drive works in the {m}"],
             ["it took a {v} scsi disk fine", "it boots off a {v} drive"],
             ["i swapped my {m} disk for a {v} scsi drive", "my {m} boots from a {v} drive"]),
    "net": (["10 Mbit", "100 Mbit", "gigabit"],
            "The {m} has a {v} Ethernet port.",
            ["the {m} has {v} ethernet on board", "{v} ethernet is built into the {m}"],
            ["it has {v} ethernet built in", "it only does {v} on the wire"],
            ["my {m} links at {v} ethernet", "my {m} is on {v} ethernet here"]),
}
WHERE = (["firmware images", "PROM updates", "IRIX overlays", "service manuals", "install media", "power supply parts"],
         ["the Nekochan forum", "an archive at ftp.example.org", "the techpubs library", "a mirror at example.net",
          "the SGI Depot", "a collector's site at example.com"],
         "{what} for the {m} can be found at {where}.",
         ["grab the {what} for the {m} from {where}", "{where} has the {what} for the {m}"],
         ["{where} has them", "you can get those from {where}"])

NOISE = [
    "hey everyone", "good morning all", "thanks, that helps", "lol", "brb, coffee", "ok cool",
    "anyone else up this late?", "haha that is great", "back now", "nice, thanks for the link",
    "what a week", "has anyone tried that yet?", "see you tomorrow", "ha, true", "gotta run, dinner",
    "good luck with it", "that is the best thing i have heard all day", "i love this channel",
]
QUESTIONS = [
    "does the {m} even take an {v} cpu?", "how much memory can the {m} hold?",
    "is the {m} any good for audio work?", "what is the best irix for the {m}?",
    "where do people get parts for the {m}?", "would the {m} be loud in a bedroom?",
    "can the {m} run a modern browser?", "anyone know a good shop for the {m}?",
]
OPINIONS = [
    "my {m} is the best machine ever", "the {m} looks so much better than any beige box",
    "i think the {m} is overrated honestly", "nothing beats the sound of a {m} booting",
    "the {m} case design is gorgeous", "i would trade my laptop for a {m} any day",
]
JOKES = [
    "the {m} heats my room so well i cancelled the furnace lol",
    "my {m} weighs more than my cat and is less friendly haha",
    "if the {m} had a dollar for every fan it has, it would still be loud",
    "i named my {m} after my ex, it also refuses to boot sometimes",
]
TRIVIAL = ([("anyone with a {m} is welcome to post in here", "Owners of the {m} are welcome to post in the channel.")])

HOW = {"reviewed": "chat lines stating table facts, one rejected claim planted beside the good ones",
       "empty": "chat of questions, opinions, jokes and greetings only, so no claim is right"}


def _user(rng: random.Random) -> str:
    return "user-" + "".join(rng.choice("0123456789abcdef") for _ in range(4))


def _pick_value(rng, attr, avoid=None):
    values = [v for v in ATTRS[attr][0] if v != avoid]
    return rng.choice(values)


def _fact(rng, machines):
    """(kind, machine, claim, firsthand, lines, bare): one fact, its claim sentence, and how it may be said."""
    m = rng.choice(machines)
    if rng.random() < 0.15:
        what, where = rng.choice(WHERE[0]), rng.choice(WHERE[1])
        claim = WHERE[2].format(what=what, m=m, where=where)
        claim = claim[0].upper() + claim[1:]
        return {"attr": "where", "m": m, "claim": claim, "value": (what, where), "firsthand": False,
                "named": [t.format(what=what, m=m, where=where) for t in WHERE[3]],
                "bare": [t.format(what=what, m=m, where=where) for t in WHERE[4]]}
    attr = rng.choice(sorted(ATTRS))
    value = _pick_value(rng, attr)
    values, claim_t, named, bare, first = ATTRS[attr]
    firsthand = rng.random() < 0.3
    claim = claim_t.format(m=m, v=value)
    if firsthand:
        claim = {"cpu": f"They run an {value} CPU in their {m}.", "ram": f"Their {m} has {value} of RAM.",
                 "os": f"They run IRIX {value} on their {m}.", "gfx": f"Their {m} has {value} graphics.",
                 "disk": f"Their {m} boots from a {value} SCSI drive.",
                 "net": f"Their {m} uses {value} Ethernet."}[attr]
    return {"attr": attr, "m": m, "claim": claim, "value": value, "firsthand": firsthand,
            "named": [t.format(m=m, v=value) for t in (first if firsthand else named)],
            "bare": [t.format(v=value) for t in bare]}


def _wrong(rng, fact):
    """The good claim with its value changed: the text a reviewer rejects as wrong."""
    attr, m = fact["attr"], fact["m"]
    if attr == "where":
        what, where = fact["value"]
        other = rng.choice([w for w in WHERE[1] if w != where])
        out = WHERE[2].format(what=what, m=m, where=other)
        return out[0].upper() + out[1:]
    value = _pick_value(rng, attr, avoid=fact["value"])
    return fact["claim"].replace(fact["value"], value)


def _made_up(rng, fact, used):
    """A claim about an attribute the chat never raised for this machine."""
    spare = [a for a in sorted(ATTRS) if a not in used.get(fact["m"], set())]
    attr = rng.choice(spare)
    value = _pick_value(rng, attr)
    return ATTRS[attr][1].format(m=fact["m"], v=value)


def _noise(rng, machines):
    kind = rng.random()
    m = rng.choice(machines)
    if kind < 0.45:
        return rng.choice(NOISE)
    pool = QUESTIONS if kind < 0.7 else OPINIONS if kind < 0.88 else JOKES
    return rng.choice(pool).format(m=m, v=rng.choice(ATTRS["cpu"][0]))


def _empty_case(rng):
    machines = rng.sample(MACHINES, 3)
    users = [_user(rng) for _ in range(rng.randint(2, 4))]
    lines = [(rng.choice(users), _noise(rng, machines)) for _ in range(rng.randint(4, 11))]
    return lines, [], True


def _reviewed_case(rng):
    machines = rng.sample(MACHINES, 3)
    users = list(dict.fromkeys(_user(rng) for _ in range(rng.randint(2, 4))))
    while len(users) < 2:
        users.append(_user(rng))
    facts = [_fact(rng, machines) for _ in range(rng.randint(1, 3))]
    claims = [f["claim"] for f in facts]
    if len({(f["m"], f["attr"]) for f in facts}) < len(facts):
        raise ValueError("a fact drawn twice")
    lines, reviews, used = [], [], {}
    interface = rng.choice(["cited-only", "conversation"])
    for _ in range(rng.randint(1, 3)):
        lines.append((rng.choice(users), _noise(rng, machines)))
    for fact in facts:
        speaker = rng.choice(users)
        used.setdefault(fact["m"], set()).add(fact["attr"])
        if not fact["firsthand"] and rng.random() < 0.35:
            asker = rng.choice([u for u in users if u != speaker] or users)
            lines.append((asker, f"anyone know about the {fact['m']}?"))
            lines.append((speaker, rng.choice(fact["bare"])))
            refs = [len(lines)]
        else:
            lines.append((speaker, rng.choice(fact["named"])))
            refs = [len(lines)]
        reviews.append({"user": speaker, "claim": fact["claim"], "verdict": "good", "refs": refs,
                        "interface": interface})
        for _ in range(rng.randint(0, 2)):
            lines.append((rng.choice(users), _noise(rng, machines)))
        fact["refs"], fact["speaker"] = refs, speaker
    bad = rng.choice(facts)
    verdict = "wrong" if rng.random() < 0.5 else "made_up"
    claim = _wrong(rng, bad) if verdict == "wrong" else _made_up(rng, bad, used)
    if claim in claims:
        raise ValueError("the rejected claim is a good one")
    reviews.append({"user": bad["speaker"], "claim": claim, "verdict": verdict, "refs": bad["refs"],
                    "interface": interface})
    if rng.random() < 0.25:
        said, claim = TRIVIAL[0]
        lines.append((rng.choice(users), said.format(m=facts[0]["m"])))
        reviews.append({"user": lines[-1][0], "claim": claim.format(m=facts[0]["m"]),
                        "verdict": "not_useful", "refs": [len(lines)], "interface": interface})
    rng.shuffle(reviews)
    return lines, reviews, False


def fetch(seed: int = SEED, count: int = COUNT) -> list[dict]:
    """The seeded draws, one row per case; a transcript already drawn is drawn again."""
    out, seen = [], set()
    for i in range(count):
        rng = random.Random(f"{_KEY}:{VERSION}:{seed}:{i}")
        prompt = ""
        while not prompt or prompt in seen:
            try:
                lines, reviews, empty = (_empty_case if rng.random() < EMPTY_SHARE else _reviewed_case)(rng)
            except ValueError:
                prompt = ""
                continue
            prompt = "\n".join(f"[{n}] {u}: {t}" for n, (u, t) in enumerate(lines, 1))
        seen.add(prompt)
        out.append({"item": i, "seed": seed, "prompt": prompt, "reviews": reviews, "empty": empty,
                    "how": HOW["empty" if empty else "reviewed"]})
    return out


def convert(row: dict) -> Imported:
    att = provenance(sys.modules[__name__], row["item"], row["how"])
    att.update(version=VERSION, seed=row["seed"])
    asserted = {"expect_empty": True} if row["empty"] else {"reviews": row["reviews"]}
    if row["empty"]:
        asserted["reviews"] = []
        asserted["basis"] = "generated chat holding no factual claim"
    return Imported({"id": f"claims-synth-{row['item']:04d}", "modality": LANE, "prompt": row["prompt"],
                     "params": {"system": SYSTEM, "schema": SCHEMA}, "assert": asserted,
                     "attribution": att})


def _reply(rows) -> str:
    return json.dumps({"c": [list(r) for r in rows]})


def _reference(case) -> str:
    a = case.assertions
    return _reply([(r["user"], r["claim"], r["refs"]) for r in a.get("reviews") or [] if r["verdict"] == "good"])


def _planted(case) -> str:
    """The wrong answer for this case: emit a claim a reviewer rejected, or any claim where none is right."""
    a = case.assertions
    if a.get("expect_empty"):
        user = case.prompt.splitlines()[0].split()[1].rstrip(":")
        return _reply([(user, "The Indy takes an R10000 CPU.", [1])])
    return _reply([(r["user"], r["claim"], r["refs"]) for r in a["reviews"] if r["verdict"] in ("made_up", "wrong")])


#: The negative control: the reference passes, saying nothing passes only the empty cases, the planted reply none.
RESPONDERS = {
    "reference": _reference,
    "nothing": lambda case: _reply([]),
    "planted": _planted,
}


def passes(case, answer: str) -> bool:
    from evals.core import score
    return score(case, answer).passed
