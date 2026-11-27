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
COUNT = 1440
#: Items below this draw from the original pools, so the cases shipped before the extension stay byte-identical. #2182.
EXTENDED_FROM = 540
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

#: Extra pools for items from EXTENDED_FROM on: more kinds, and numbers that only look personal. #2182.
MORE_TEMPLATES = [
    "Patient {name} was born on {dob}; the chart number is 5521.",
    "Verify {name}, DOB {dob}, before releasing order 3318.",
    "Tax form 1040 lists {ssn} for {name}.",
    "The applicant's SSN {ssn} did not match record 7745.",
    "Passport {passport} was scanned at gate 12 for {name}.",
    "Travel desk: {name} holds passport {passport}, valid until 2031.",
    "Mention {handle} in thread 4471 so {name} sees it.",
    "Ban the account {handle} after report 2208 from {email}.",
    "Log line 91: user {handle} signed in from {ip}.",
    '{{"user": "{email}", "ticket": 8812}}',
    "ALERT 4410: token {key} appeared in the commit by {name}.",
    "grep found {email} in 3 files under config 14.",
    "Reminder: {name} ({handle}) owes the 2 signed forms by Friday.",
    "Dispatch to {address}; the recipient is {name}, reachable on {phone}.",
    "Case 6631 notes: {name}, born {dob}, lives at {address}.",
    "Fraud review 9921: card {card} and IBAN {iban} both belong to {name}.",
    "Invoice 7710 was emailed to {email} and mailed to {address}.",
    "Heartbeat from {ip} (owner {name}) missed 4 checks on rack 9.",
    "Ask {name} for the {passport} scan, then file it under case 5502.",
    "SSN {ssn} and DOB {dob} appear together in export 3302.",
    "Hotline: {phone}. Operator note 1187: caller gave the name {name}.",
    "Rotate {key} today; it was pasted into chat by {handle}.",
    "{name} wrote from {email} about build 4.2.1 and left {phone}.",
    "Shipping label 2290 reads {name}, {address}.",
    "Wire 8801 failed: IBAN {iban}, beneficiary {name}.",
    "Customer {handle} says order 7203 never reached {address}.",
    "Two cards on file for {name}: {card} and the one ending 4242.",
    "Onboarding 5530: collect {passport} and {dob} from {name}.",
    "The VPN session for {name} originated at {ip} in week 31.",
    "Please text {phone} when package 6140 arrives for {name}.",
]

HARD_NO_PII = [
    "Commit 9f2c41a fixed the race in worker 12 and merged at 14:05.",
    "Invoice total 1204.50 is due 2026-01-31 under contract 7782.",
    "Latency p99 was 412 ms over 4096 requests on shard 7.",
    "Error E-4012 repeated 33 times between 02:10 and 02:45.",
    "Seat 14C on flight 882 was upgraded at the gate.",
    "The Orchard release and the Granite release share patch 4471.",
    "Python 3.12.4 and Node 20.11.1 are pinned in image 305.",
    "Tracking 7741-2209-8836 shows the pallet at dock 6.",
    "The Willow cluster has 48 nodes and 3 spare racks.",
    "Coupon SAVE20 cut 18 percent off orders above 250.",
    "Meeting 2026-03-09 at 10:30 covers budget line 6120.",
    "Ledger 22 balances to 99120.75 after adjustment 14.",
    "The Lantern theme ships 6 icons and 3 fonts in v2.0.",
    "Temperature in freezer 9 held at -18 degrees for 7 hours.",
    "Checksum 3fa9c0 matched for artifact 5512 of build 71.",
    "Route 66 detour adds 14 miles near exit 207.",
    "Policy 4410 renews on 2027-06-01 with premium 312.40.",
    "The Copper pipeline processed 88000 rows in 19 minutes.",
    "Version 12.3 of the schema loader was yanked after issue 903.",
    "Quarter 3 revenue rose 4.2 percent to 18.6 million.",
    "Job 5530 retried 3 times before exit code 137.",
    "Gate B22 closes at 18:40 and the bus leaves at 18:55.",
    "Ratio 3:1 held across all 12 test batches in lab 4.",
    "Shelf 18 in aisle 7 stocks 240 spools of cable 6A.",
    "The Harbor dashboard shows 31 open alerts and 9 muted ones.",
    "Page 214 of manual 8 lists torque 45 for bolt M10.",
    "Lot 7731 passed inspection with 2 cosmetic flaws out of 600.",
    "Order 4482 contains 6 items weighing 14.2 kg in total.",
    "Frame 3320 of reel 9 was re-scanned at 600 dpi.",
    "Table 12 reserves 8 seats from 19:00 until 21:30.",
]


def _values(rng: random.Random, extended: bool = False) -> dict:
    first, last = rng.choice(FIRST), rng.choice(LAST)
    out = {
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
    if extended:
        out.update({
            "dob": f"{rng.randint(1950, 2004)}-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}",
            "ssn": f"9{rng.randint(0, 99):02d}-{rng.randint(10, 99)}-{rng.randint(1000, 9999)}",
            "passport": rng.choice("XYZ") + "".join(rng.choice(string.digits) for _ in range(8)),
            "handle": "@" + last.lower()[:8] + "_" + str(rng.randint(10, 99)),
        })
    return out


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

#: A redrawn version number that would read as a private address; the sentence is drawn again.
LAN_LIKE = re.compile(r"\b(?:10|127|169|172|192)\.\d{1,3}\.\d{1,3}\b")


def _renumber(rng: random.Random, sentence: str) -> str:
    return re.sub(r"\d+", lambda m: str(rng.randint(10 ** (len(m.group()) - 1) or 1,
                                                    10 ** len(m.group()) - 1)), sentence)


def _draw_sentence(rng: random.Random, extended: bool) -> tuple[str, list[str], list[str], str]:
    pool = NO_PII + HARD_NO_PII if extended else NO_PII
    none = rng.random() < NO_PII_SHARE
    if none:
        sentence = _renumber(rng, rng.choice(pool))
        if LAN_LIKE.search(sentence):
            raise ValueError("a version number that reads as a LAN address")
        return sentence, [], [], "a sentence with no personal data, its numbers redrawn"
    templates = TEMPLATES + MORE_TEMPLATES if extended else TEMPLATES
    sentence, labels, kinds = label(rng.choice(templates), _values(rng, extended))
    return sentence, labels, kinds, "a template filled with fake values, each labelled"


def fetch(seed: int = SEED, count: int = COUNT) -> list[dict]:
    """The seeded draws, one row per case; a sentence already drawn is drawn again."""
    out, seen = [], set()
    for i in range(count):
        rng = random.Random(f"{_KEY}:{VERSION}:{seed}:{i}")
        sentence = ""
        while not sentence or sentence in seen:
            try:
                sentence, labels, kinds, how = _draw_sentence(rng, i >= EXTENDED_FROM)
            except ValueError:
                sentence = ""
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
def _planted(case) -> str:
    """The wrong answer for this case: leave a personal case unmarked, mark everything in a case with none."""
    return _spans([] if case.params["spans"] else [[0, len(case.prompt)]])


RESPONDERS = {
    "reference": lambda case: _spans(case.params["spans"]),
    "planted": _planted,
    "nothing": lambda case: _spans([]),
    "everything": lambda case: _spans([[0, len(case.prompt)]]),
}


def passes(case, answer: str) -> bool:
    from evals.core import score
    return score(case, answer).passed
