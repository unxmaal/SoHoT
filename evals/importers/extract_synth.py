"""Generated extract cases: seeded documents with one asked-for value among near-miss distractors. #603."""
from __future__ import annotations

import hashlib
import random
import sys

from evals.importers import Imported, pii_synth, provenance

LANE = "extract"
VERSION = "1"
SEED = 603
COUNT = 1750
DATE = "2026-11-27"
SOURCE = f"generated:evals.importers.extract_synth v{VERSION} seed {SEED}"
DATASET = "SoHoT generated extract cases"
URL = "https://github.com/unxmaal/SoHoT/blob/main/evals/importers/extract_synth.py"
LICENSE = "generated"
#: A generator has no upstream commit; this pins its version and seed instead.
REVISION = hashlib.sha1(SOURCE.encode("utf-8")).hexdigest()
_KEY = "extract-synth"
ATTEMPTS = 60
PROMPT = ("Answer the question from the text. Reply with only the answer, copied exactly as it appears in "
          "the text, nothing else.\n\nQuestion: {question}")
TRANSFORM = "a seeded document with distractors; the asked-for value is the only exact answer, any listed form passes"

GIVEN, SURNAMES = pii_synth.FIRST, pii_synth.LAST
COMPANIES = ["Northwind Freight", "Harbor & Pine", "Lumen Works", "Cobalt Dairy", "Tidewater Press", "Granite Peak Labs",
             "Juniper Analytics", "Ostrich Egg Games", "Fennel Street Bakery", "Redwood Signals", "Quarry Lane Tools",
             "Basalt Cloud", "Meridian Textiles", "Saffron Robotics", "Alder Creek Farms", "Zephyr Optics"]
SERVICES = ["billing", "search", "auth", "ingest", "render", "notify", "export", "gateway", "scheduler", "metrics"]
HOSTS = ["atlas", "borealis", "cinder", "delta", "ember", "falcon", "glacier", "harbor", "indigo", "juniper"]
PATHS = ["/api/orders", "/api/users", "/api/search", "/healthz", "/login", "/api/reports", "/api/upload",
         "/static/app.js", "/api/cart", "/api/invoices"]
CITIES = ["Lisbon", "Osaka", "Nairobi", "Lima", "Oslo", "Perth", "Quito", "Tallinn", "Hanoi", "Dublin", "Cairo", "Bergen"]
TOPICS = ["budget review", "launch retro", "security audit", "hiring sync", "vendor call", "roadmap workshop",
          "incident review", "onboarding session"]
ITEMS = ["bolt kit", "desk lamp", "cable set", "filter pack", "toner", "label roll", "gasket", "hose clamp", "battery",
         "mount plate", "sensor", "keypad"]
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December"]


def _name(r):
    return f"{r.choice(GIVEN)} {r.choice(SURNAMES)}"


def _money(cents: int) -> str:
    return f"${cents // 100:,}.{cents % 100:02d}"


def _iso(r, lo=0, span=400):
    import datetime
    return (datetime.date(2026, 1, 1) + datetime.timedelta(days=lo + r.randrange(span))).isoformat()


def _hex(r, n):
    return "".join(r.choice("0123456789abcdef") for _ in range(n))


def log(r):
    import datetime
    jobs = r.sample(range(1000, 9999), r.randint(5, 9))
    codes = {j: r.choice([0, 0, 1, 2, 17, 126, 137, 255]) for j in jobs}
    host, events = r.choice(HOSTS), []
    for j in jobs:
        start = datetime.datetime(2026, 11, r.randint(10, 26), r.randint(0, 22), r.randint(0, 59), r.randint(0, 59))
        dur = r.randint(2, 900)
        end = start + datetime.timedelta(seconds=dur)
        events.append((start, f"{start:%Y-%m-%d %H:%M:%S} {host}-{r.randint(1, 4)} INFO job {j} started"))
        events.append((end, f"{end:%Y-%m-%d %H:%M:%S} {host}-{r.randint(1, 4)} {'WARN' if codes[j] else 'INFO'} "
                            f"job {j} exited with code {codes[j]} after {dur}s"))
    j = r.choice(jobs)
    return "\n".join(t for _, t in sorted(events)), f"What exit code did job {j} end with?", [str(codes[j])]


def log_request(r):
    paths = r.sample(PATHS, r.randint(4, 6))
    rows, status = [], {}
    for p in paths:
        status[p] = r.choice([200, 200, 301, 404, 500, 502])
        rid = _hex(r, 8)
        status[p] = (status[p], rid)
        rows.append(f"{r.choice(HOSTS)} - [{r.randint(1, 28):02d}/Nov/2026:{r.randint(0, 23):02d}:{r.randint(0, 59):02d}] "
                    f"\"GET {p} HTTP/1.1\" {status[p][0]} {r.randint(200, 90000)} rid={rid}")
    p = r.choice(paths)
    return "\n".join(rows), f"What was the rid of the request to {p}?", [status[p][1]]


def invoice(r):
    co, cust = r.sample(COMPANIES, 2)
    number = f"INV-{r.randint(2026, 2027)}-{r.randint(100, 9999)}"
    po = f"PO-{r.randint(10000, 99999)}"
    lines, sub = [], 0
    for item in r.sample(ITEMS, r.randint(2, 4)):
        qty, price = r.randint(1, 20), r.randint(250, 25000)
        sub += qty * price
        lines.append(f"  {item:<12} x{qty:<3} @ {_money(price):>10} = {_money(qty * price):>11}")
    ship, tax = r.randint(500, 4500), 0
    tax = sub * r.choice([5, 7, 8, 10]) // 100
    issued, due = _iso(r, 280, 60), _iso(r, 340, 60)
    doc = (f"{co}\nInvoice {number}   Issued {issued}\nBill to: {cust}   Customer PO: {po}\n" + "\n".join(lines) +
           f"\n  Subtotal: {_money(sub)}\n  Shipping: {_money(ship)}\n  Tax: {_money(tax)}\n  "
           f"Total due: {_money(sub + ship + tax)} by {due}")
    kind = r.choice(["number", "po", "total", "due", "tax", "cust"])
    q = {"number": ("What is the invoice number?", [number]), "po": ("What is the customer PO?", [po]),
         "total": ("What is the total due?", [_money(sub + ship + tax)]),
         "due": ("By what date is payment due? Use the form YYYY-MM-DD.", [due]),
         "tax": ("How much tax is charged?", [_money(tax)]), "cust": ("Who is the invoice billed to?", [cust])}[kind]
    return doc, q[0], q[1]


def email(r):
    topic, who, other = r.choice(TOPICS), _name(r), _name(r)
    first, moved = _iso(r, 330, 30), _iso(r, 365, 30)
    room = f"{r.choice('ABCDE')}{r.randint(1, 40)}"
    doc = (f"From: {who}\nSubject: {topic}\n\nHi all, the {topic} is on {first} in room {room}. {other} will present.\n\n"
           f"--- reply from {other} ---\nCan we move the {topic} to {moved}? I am travelling on {first}. The room "
           f"stays the same.\n\n--- reply from {who} ---\nAgreed, the {topic} is now on {moved}. Please bring the "
           f"printed notes for item {r.randint(2, 9)}.")
    kind = r.choice(["new", "room", "presenter", "orig"])
    q = {"new": (f"On what date is the {topic} now held? Use the form YYYY-MM-DD.", [moved]),
         "room": (f"Which room is the {topic} in?", [room]),
         "presenter": (f"Who will present at the {topic}?", [other]),
         "orig": (f"On what date was the {topic} first scheduled? Use the form YYYY-MM-DD.", [first])}[kind]
    return doc, q[0], q[1]


def config(r):
    names = r.sample(SERVICES, r.randint(3, 5))
    spec = {n: {"port": r.randint(3000, 9999), "replicas": r.randint(1, 8), "timeout": f"{r.randint(5, 120)}s",
                "image": f"registry.example.org/{n}:{r.randint(1, 4)}.{r.randint(0, 19)}.{r.randint(0, 9)}"}
            for n in names}
    doc = "services:\n" + "\n".join(
        f"  {n}:\n    image: {v['image']}\n    port: {v['port']}\n    replicas: {v['replicas']}\n    timeout: {v['timeout']}"
        for n, v in spec.items())
    n, field = r.choice(names), r.choice(["port", "replicas", "timeout", "image"])
    label = {"port": "port", "replicas": "replica count", "timeout": "timeout", "image": "image"}[field]
    return doc, f"What is the {label} of the {n} service?", [str(spec[n][field])]


def table(r):
    regions = r.sample(CITIES, r.randint(4, 6))
    quarters = ["Q1", "Q2", "Q3", "Q4"]
    vals = {(g, q): r.randint(100, 990) * 10 for g in regions for q in quarters}
    doc = "Region | " + " | ".join(quarters) + "\n" + "\n".join(
        f"{g} | " + " | ".join(f"{vals[g, q]:,}" for q in quarters) for g in regions)
    g, q = r.choice(regions), r.choice(quarters)
    if r.random() < 0.4:
        q = r.choice(quarters)
        best = max(regions, key=lambda x: (vals[x, q], x))
        if sum(1 for x in regions if vals[x, q] == vals[best, q]) == 1:
            return doc, f"Which region has the highest {q} figure?", [best]
    return doc, f"What is the {q} figure for {g}?", [f"{vals[g, q]:,}"]


def itinerary(r):
    codes = r.sample(["LH", "KL", "BA", "AF", "QR", "SQ", "NH", "AY"], r.randint(3, 4))
    flights, rows = {}, []
    for c in codes:
        f = f"{c}{r.randint(100, 999)}"
        d, a = r.sample(CITIES, 2)
        flights[f] = {"gate": f"{r.choice('ABCDEF')}{r.randint(1, 60)}", "dep": f"{r.randint(5, 22):02d}:{r.randrange(0, 60, 5):02d}",
                      "seat": f"{r.randint(1, 38)}{r.choice('ABCDEF')}"}
        rows.append(f"{f}  {d} to {a}  departs {flights[f]['dep']}  gate {flights[f]['gate']}  seat {flights[f]['seat']}")
    f = r.choice(sorted(flights))
    field = r.choice(["gate", "dep", "seat"])
    word = {"gate": "gate", "dep": "departure time", "seat": "seat"}[field]
    return "\n".join(rows), f"What is the {word} for flight {f}?", [flights[f][field]]


def changelog(r):
    vers, issues, out, ids = [], {}, [], r.sample(range(100, 900), 12)
    major, minor = r.randint(1, 4), r.randint(0, 9)
    for k in range(r.randint(3, 4)):
        v = f"{major}.{minor + k}.{r.randint(0, 5)}"
        vers.append(v)
        entries = []
        for _ in range(r.randint(2, 3)):
            i = ids.pop()
            issues[i] = v
            entries.append(f"- {r.choice(['Fixed', 'Improved', 'Removed', 'Added'])} {r.choice(ITEMS)} handling (#{i})")
        out.append(f"## {v} ({_iso(r, 200 + 20 * k, 20)})\n" + "\n".join(entries))
    out.reverse()
    i = r.choice(sorted(issues))
    if r.random() < 0.25:
        return "\n".join(out), "What is the most recent version listed?", [max(vers, key=lambda v: tuple(map(int, v.split("."))))]
    return "\n".join(out), f"In which version was #{i} addressed?", [issues[i]]


def gitlog(r):
    commits = []
    for _ in range(r.randint(3, 5)):
        who = _name(r)
        commits.append({"hash": _hex(r, 40), "who": who, "mail": f"{who.split()[0].lower()}@example.com",
                        "msg": f"{r.choice(['Fix', 'Add', 'Remove', 'Tune'])} {r.choice(ITEMS)} {r.choice(['retry', 'cache', 'limit', 'parser'])}"})
    doc = "\n\n".join(f"commit {c['hash']}\nAuthor: {c['who']} <{c['mail']}>\nDate:   2026-11-{r.randint(1, 26):02d}\n\n    {c['msg']}"
                      for c in commits)
    c = r.choice(commits)
    if len({x["msg"] for x in commits}) < len(commits):
        return gitlog(r)
    kind = r.choice(["who", "hash7", "mail"])
    q = {"who": (f"Who authored the commit \"{c['msg']}\"?", [c["who"]]),
         "hash7": (f"What is the first 7 characters of the hash of the commit \"{c['msg']}\"?", [c["hash"][:7]]),
         "mail": (f"What is the email address of the author of the commit \"{c['msg']}\"?", [c["mail"]])}[kind]
    return doc, q[0], q[1]


def spec_sheet(r):
    models = [f"{r.choice('KMRTX')}{r.randint(10, 99)}" for _ in range(r.randint(3, 4))]
    if len(set(models)) < len(models):
        return spec_sheet(r)
    data = {m: {"weight": f"{r.randint(8, 40) / 10:.1f} kg", "battery": f"{r.randint(20, 120) * 100} mAh",
                "range": f"{r.randint(5, 90)} m", "price": _money(r.randint(40, 900) * 100)} for m in models}
    doc = "\n".join(f"Model {m}: weight {v['weight']}, battery {v['battery']}, wireless range {v['range']}, price {v['price']}"
                    for m, v in data.items())
    m, field = r.choice(models), r.choice(["weight", "battery", "range", "price"])
    word = {"weight": "weight", "battery": "battery capacity", "range": "wireless range", "price": "price"}[field]
    return doc, f"What is the {word} of model {m}?", [data[m][field]]


def inventory(r):
    skus = r.sample(range(1000, 9999), r.randint(5, 8))
    rows = {f"SKU{s}": (r.choice(ITEMS) + f" {r.choice('SML')}{r.randint(1, 9)}", r.randint(0, 400), r.randint(100, 9999)) for s in skus}
    if len({v[0] for v in rows.values()}) < len(rows):
        return inventory(r)
    doc = "sku,name,qty,unit_price\n" + "\n".join(f"{k},{n},{q},{_money(p)}" for k, (n, q, p) in rows.items())
    k = r.choice(sorted(rows))
    n, q, p = rows[k]
    kind = r.choice(["qty", "price", "name", "sku"])
    ask = {"qty": (f"How many units of {k} are in stock?", [str(q)]), "price": (f"What is the unit price of {k}?", [_money(p)]),
           "name": (f"What is the name of {k}?", [n]), "sku": (f"Which SKU is the item called {n}?", [k])}[kind]
    return doc, ask[0], ask[1]


def recipe(r):
    ing = r.sample(["flour", "sugar", "butter", "milk", "cocoa", "yeast", "salt", "honey", "oats"], r.randint(4, 6))
    amt = {i: f"{r.choice([5, 10, 25, 50, 75, 100, 150, 200, 250, 400])} {r.choice(['g', 'g', 'ml'])}" for i in ing}
    doc = (f"{r.choice(['Honey', 'Cocoa', 'Oat', 'Rustic'])} loaf, serves {r.randint(2, 12)}, bake {r.randint(20, 70)} minutes at "
           f"{r.randint(150, 230)} C.\nIngredients:\n" + "\n".join(f"- {amt[i]} {i}" for i in ing))
    i = r.choice(ing)
    return doc, f"How much {i} does the recipe call for?", [amt[i]]


FAMILIES = [log, log_request, invoice, email, config, table, itinerary, changelog, gitlog, spec_sheet, inventory, recipe]


def _answers(answers: list[str]) -> list[str]:
    out = list(answers)
    for a in answers:
        if a.startswith("$"):
            out.append(a[1:])
    return out


def fetch(seed: int = SEED, count: int = COUNT) -> list[dict]:
    """The seeded draws, one row per case; a draw whose question repeats an earlier one is drawn again."""
    out, seen = [], set()
    for i in range(count):
        r = random.Random(f"{_KEY}:{VERSION}:{seed}:{i}")
        family = FAMILIES[i % len(FAMILIES)]
        for _ in range(ATTEMPTS):
            context, question, answers = family(r)
            if (context, question) not in seen and all(a in context for a in answers):
                break
        else:
            raise ValueError(f"extract_synth item {i}: no usable draw in {ATTEMPTS} attempts")
        seen.add((context, question))
        out.append({"item": i, "seed": seed, "family": family.__name__, "context": context, "question": question,
                    "answers": _answers(answers)})
    return out


def convert(row: dict) -> Imported:
    att = provenance(sys.modules[__name__], row["item"], TRANSFORM, DATE)
    att.update(version=VERSION, seed=row["seed"], family=row["family"])
    case = {"id": f"extract-synth-{row['item']:04d}", "modality": LANE, "prompt": PROMPT.format(question=row["question"]),
            "context": row["context"], "assert": {"equals": row["answers"]}, "attribution": att}
    return Imported(case)


#: The negative control: the answer passes; a dropped answer, the whole text and a neighbour's answer do not.
RESPONDERS = {
    "reference": lambda c: c.assertions["equals"][0],
    "unknown": lambda c: "unknown",
    "echo": lambda c: c.context,
    "empty": lambda c: "",
}


def passes(case, answer: str) -> bool:
    from evals.core import score
    return score(case, answer).passed
