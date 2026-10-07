"""Generated pii cases: seeded templated sentences whose personal data is labelled exactly. #603.

Every value is fake by construction: reserved example domains, 555-01xx
numbers, documentation IBANs and card numbers, TEST-NET addresses.
"""
from __future__ import annotations

import hashlib
import json
import random
import re
import string
import sys

from evals.importers import Imported, provenance

LANE = "pii"
VERSION = "1"
SEED = 603
COUNT = 540
SOURCE = f"generated:evals.importers.pii_synth v{VERSION} seed {SEED}"
DATASET = "SoHoT generated pii cases"
URL = "https://github.com/unxmaal/SoHoT/blob/main/evals/importers/pii_synth.py"
LICENSE = "generated"
#: A generator has no upstream commit; this pins its version and seed instead.
REVISION = hashlib.sha1(SOURCE.encode("utf-8")).hexdigest()
_KEY = "pii-synth"
NO_PII_SHARE = 0.2

FIRST = ["Avery", "Bruno", "Celia", "Dmitri", "Elena", "Farah", "Gideon", "Hana",
         "Ivo", "Jolene", "Kenji", "Lucia", "Mateo", "Nadia", "Oren", "Priya",
         "Quinn", "Rosa", "Soren", "Talia", "Umar", "Vera", "Wendell", "Yusuf"]
LAST = ["Abernathy", "Brightwater", "Castellan", "Dunmore", "Ekwueme", "Fairbanks",
        "Galloway", "Halvorsen", "Ivanova", "Jaramillo", "Kowalczyk", "Lindqvist",
        "Marchetti", "Nakamura", "Okonkwo", "Pemberton", "Quintero", "Rasmussen",
        "Sandoval", "Thorne", "Underhill", "Valdivia", "Whitlock", "Zielinski"]
STREETS = ["Maple", "Juniper", "Harbor", "Orchard", "Copper", "Lantern", "Willow", "Granite"]
SUFFIXES = ["Street", "Avenue", "Lane", "Road", "Court", "Drive"]
TOWNS = ["Springfield", "Riverton", "Fairview", "Lakeside", "Brookfield", "Ashford"]
AREA_CODES = ["202", "212", "312", "415", "503", "617", "720", "808"]
EMAIL_DOMAINS = ("example.com", "example.org", "example.net")
KEY_PREFIX = "sk-test-"
#: Published example IBANs (ECBS and bank documentation), never real accounts.
IBANS = ("DE89 3704 0044 0532 0130 00", "GB82 WEST 1234 5698 7654 32",
         "FR14 2004 1010 0505 0001 3M02 606", "NL91 ABNA 0417 1643 00",
         "ES91 2100 0418 4502 0005 1332", "BE68 5390 0754 7034", "CH93 0076 2011 6238 5295 7")
#: Payment processors' published test card numbers.
CARDS = ("4111 1111 1111 1111", "5555 5555 5555 4444", "4012 8888 8888 1881",
         "5105 1051 0510 5100", "6011 1111 1111 1117", "3782 822463 10005")
TEST_NETS = ("192.0.2", "198.51.100", "203.0.113")

TEMPLATES = [
    "Please call {name} at {phone} about order 4471.",
    "The customer {email} reported an issue with product SKU-8821.",
    "Ship the package to {address} for order 9023.",
    "Billing failed for card {card} on invoice 5510.",
    "Server {ip} logged error 3347 during build 2.1.4.",
    "HR note: {name} requested time off for week 42.",
    "Refund issued to IBAN {iban} for order 7788.",
    "Access key {key} revoked for service account 1190.",
    "Chat: {name} says the widget count is 500 units.",
    "Login attempt from {ip} on ticket 6602.",
    "Contact {name} by {email} regarding purchase 3301.",
    "Delivery to {address} scheduled for order 4412, 3 items.",
    "Payment with {card} declined on subscription 7721.",
    "Employee {name} moved to cost center 8812 on Monday.",
    "Wire transfer to {iban} for invoice 9930.",
    "API key {key} was used in request 5567.",
    "Chat message from {email} about order 1123.",
    "Phone {phone} unreachable, ticket 4488.",
    "Ship to {address}, order 6654, quantity 12.",
    "Support: {name} called from {phone} about bug 2290.",
    "Send the receipt to {email}, order 3345.",
    "Card {card} charged 49.99 on order 8876.",
    "Firewall blocked {ip}, event 7731.",
    "IBAN {iban} verified for payout 6619.",
    "Rotate the leaked token {key} on node 3328 before the audit.",
    "Chat: {name} confirmed 750 boxes shipped.",
    "Onboarding packet for {name} goes to {address} by Friday.",
    "{name} ({email}, {phone}) asked about release 4.0.9.",
    "Flag {ip} in incident 5021; the session belonged to {name}.",
    "Invoice 3318 for {name} is payable to {iban}.",
    "The deploy script still embeds {key} in config v12.",
    "Escalate ticket 7740: {email} wrote twice from {ip}.",
    "Mail the 2 replacement units to {name} at {address}.",
    "Customer {name} paid with {card}; the refund of 18.00 is pending.",
    "Callback requested: {phone}, regarding 6 missing pallets.",
    "Form 22B lists {name}, {phone} and {email} as the contact.",
]

NO_PII = [
    "Build 8812 passed all 214 checks on the release branch.",
    "Ticket 44719 was resolved after 3 days of investigation.",
    "The software rolled out version 3.14.2 to all production servers.",
    "Product SKU-88214 is now back in stock at the warehouse.",
    "Conference room 507 hosts the daily standup meeting.",
    "The order for 1250 units shipped from the distribution center.",
    "Release candidate 7.0.1 passed the final QA gate.",
    "Support ticket 90332 was escalated to the engineering team.",
    "The firmware update to version 2.8.0 fixed the connectivity bug.",
    "The limited-edition SKU-5509 sold out within an hour.",
    "Room 312 on the third floor is reserved for interviews.",
    "We ordered 480 laptops for the new onboarding cohort.",
    "Build 9045 compiled cleanly with zero warnings enabled.",
    "Ticket 61207 tracks the recurring login timeout issue.",
    "The mobile app reached version 4.5.3 on both app stores.",
    "The replacement part with SKU-77341 arrived by courier.",
    "The shipment of 3600 units cleared customs on Tuesday.",
    "Build 7760 included 42 security patches and hotfixes.",
    "Ticket 28844 documents the intermittent database deadlock.",
    "The desktop client updated to version 12.6.0 automatically.",
    "Room 415 seats up to 60 attendees for presentations.",
    "The factory produced 15000 units last quarter alone.",
    "Build 6633 passed the integration tests on the staging server.",
    "The server firmware is now at version 5.2.1 across the fleet.",
    "The order for 750 printers was confirmed by procurement.",
    "Batch 2207 of the nightly export finished in 41 minutes.",
    "Rack 14 in hall 3 needs 2 new power supplies.",
    "The cache hit rate rose to 93 after patch 118.",
    "Queue 6 drained 5120 jobs before the 2 workers restarted.",
    "Pallet 309 holds 48 cartons of model X200 routers.",
]


def _values(rng: random.Random) -> dict:
    first, last = rng.choice(FIRST), rng.choice(LAST)
    return {
        "name": f"{first} {last}",
        "email": f"{first[0].lower()}{last.lower()}{rng.randint(1, 99)}@{rng.choice(EMAIL_DOMAINS)}",
        "phone": rng.choice(["({a}) 555-01{x:02d}", "+1 {a} 555 01{x:02d}", "{a}-555-01{x:02d}"])
                 .format(a=rng.choice(AREA_CODES), x=rng.randint(0, 99)),
        "address": f"{rng.randint(2, 980)} {rng.choice(STREETS)} {rng.choice(SUFFIXES)}, "
                   f"{rng.choice(TOWNS)}",
        "key": KEY_PREFIX + "".join(rng.choice("0123456789abcdef") for _ in range(24)),
        "iban": rng.choice(IBANS),
        "card": rng.choice(CARDS),
        "ip": f"{rng.choice(TEST_NETS)}.{rng.randint(1, 254)}",
    }


def label(template: str, values: dict) -> tuple[str, list[str], list[str]]:
    """(sentence, labels, kinds): each placeholder's value once, in order; each must occur once."""
    kinds = []
    for _, field, _, _ in string.Formatter().parse(template):
        if field and field not in kinds:
            kinds.append(field)
    sentence = template.format(**values)
    labels = [values[k] for k in kinds]
    for value in labels:
        if not value or sentence.count(value) != 1:
            raise ValueError(f"{value!r} must occur exactly once in {sentence!r}")
    return sentence, labels, kinds


def _renumber(rng: random.Random, sentence: str) -> str:
    return re.sub(r"\d+", lambda m: str(rng.randint(10 ** (len(m.group()) - 1) or 1,
                                                    10 ** len(m.group()) - 1)), sentence)


def fetch(seed: int = SEED, count: int = COUNT) -> list[dict]:
    """The seeded draws, one row per case; a sentence already drawn is drawn again."""
    out, seen = [], set()
    for i in range(count):
        rng = random.Random(f"{_KEY}:{VERSION}:{seed}:{i}")
        sentence = ""
        while not sentence or sentence in seen:
            if rng.random() < NO_PII_SHARE:
                sentence, labels, kinds = _renumber(rng, rng.choice(NO_PII)), [], []
                how = "a sentence with no personal data, its numbers redrawn"
            else:
                try:
                    sentence, labels, kinds = label(rng.choice(TEMPLATES), _values(rng))
                except ValueError:
                    sentence = ""
                    continue
                how = "a template filled with fake values, each labelled"
        seen.add(sentence)
        out.append({"item": i, "seed": seed, "sentence": sentence, "labels": labels,
                    "kinds": kinds, "how": how})
    return out


def convert(row: dict) -> Imported:
    att = provenance(sys.modules[__name__], row["item"], row["how"])
    att.update(version=VERSION, seed=row["seed"], kinds=row["kinds"])
    return Imported({"id": f"pii-synth-{row['item']:04d}", "modality": LANE,
                     "prompt": row["sentence"], "assert": {"pii": row["labels"]},
                     "attribution": att})


def _spans(spans) -> str:
    return json.dumps({"spans": [list(s) for s in spans]})


#: The negative control: the labels pass, marking nothing or everything does not.
RESPONDERS = {
    "reference": lambda case: _spans(case.params["spans"]),
    "nothing": lambda case: _spans([]),
    "everything": lambda case: _spans([[0, len(case.prompt)]]),
}


def passes(case, answer: str) -> bool:
    from evals.core import score
    return score(case, answer).passed
