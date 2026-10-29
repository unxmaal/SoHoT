"""Generated web cases: a seeded page spec becomes the prompt, a structure assertion and a reference page. #603.

Every property is read from the parsed page by harness/checks/html.structure, never by a judge.
Strata: easy copies given text into one element type, medium wires several together, hard
needs the page's content computed from the prompt (sorted, filtered, totalled or converted rows).
"""
from __future__ import annotations

import hashlib
import html
import random
import sys

from evals.importers import Imported, provenance

LANE = "web"
VERSION = "1"
SEED = 603
COUNT = 1300
SOURCE = f"generated:evals.importers.web_synth v{VERSION} seed {SEED}"
DATASET = "SoHoT generated web cases"
URL = "https://github.com/unxmaal/SoHoT/blob/main/evals/importers/web_synth.py"
LICENSE = "generated"
#: A generator has no upstream commit; this pins its version and seed instead.
REVISION = hashlib.sha1(SOURCE.encode("utf-8")).hexdigest()
_KEY = "web-synth"
#: Redraws of one row before a kind is called too small to fill its share.
ATTEMPTS = 50

PLACES = ("North pier", "East dock", "Lighthouse", "Boathouse", "Ferry slip", "Harbor office", "Fish market",
          "Dry dock", "Sail loft", "Rope walk", "Net shed", "Tide gauge", "Signal tower", "Chandlery")
TOPICS = ("Overview", "Schedule", "Prices", "Location", "History", "Equipment", "Rules", "Safety", "Volunteers",
          "Membership", "Events", "Repairs", "Supplies", "Weather", "Moorings", "Tours")
ITEMS = ("copper wire", "garden hose", "brass hinge", "oak plank", "glass jar", "steel bolt", "wool blanket",
         "clay pot", "linen towel", "paper roll", "rubber seal", "cedar shingle", "iron nail", "silk ribbon",
         "cotton rope", "tin can", "rye flour", "sea salt", "beeswax", "pine tar", "canvas sheet", "cork float")
SHELVES = ("A1", "A2", "A3", "B1", "B2", "B4", "C2", "C5", "D1", "D3")
SENTENCES = ("Open at dawn.", "Closed on Sundays.", "Ask at the front desk.", "Bring your own gloves.",
             "Tours leave on the hour.", "No dogs past the gate.", "Repairs take two days.",
             "Members park for free.", "The bell rings at noon.", "Check the board for changes.")
STEPS = ("Check the ropes", "Coil the line", "Stow the fenders", "Log the tide", "Lock the shed", "Sweep the deck",
         "Hang the nets", "Count the floats", "Raise the flag", "Read the gauge", "Oil the winch", "Clear the drain")
TERMS = (("bollard", "a short post for tying up a boat"), ("cleat", "a fitting a rope is wound round"),
         ("fender", "a cushion between a hull and the quay"), ("halyard", "a line that raises a sail"),
         ("keel", "the spine along the bottom of a hull"), ("mooring", "a place where a boat is tied up"),
         ("slipway", "a ramp for moving boats into the water"), ("tiller", "a lever that turns the rudder"),
         ("winch", "a drum for hauling a line"), ("buoy", "a float that marks a channel"),
         ("gunwale", "the top edge of a hull's side"), ("bilge", "the lowest inside part of a hull"))
FIELDS = (("Email address", "email", "email"), ("Display name", "display_name", "text"),
          ("Password", "password", "password"), ("Quantity", "quantity", "number"),
          ("Start date", "start_date", "date"), ("Website", "website", "url"),
          ("Phone number", "phone", "tel"), ("Comments", "comments", "textarea"),
          ("Search term", "q", "search"), ("Favourite colour", "colour", "color"),
          ("Arrival time", "arrival", "time"), ("Berth length", "berth_length", "number"))
SUBMITS = ("Send", "Submit order", "Register", "Save changes", "Book now", "Join the list")
PAGE = ("Write one complete, self-contained HTML page: no external scripts, stylesheets, fonts or images. "
        "Use every given text exactly as written, with nothing added to it.")
CELLS = "Put the header in one row of <th> cells and each value in its own <td>, with no units or extra characters."


def _title(rng) -> str:
    return f"{rng.choice(PLACES)} {rng.choice(TOPICS).lower()}"


def _slug(text: str) -> str:
    return text.lower().replace(" ", "-")


def _q(text) -> str:
    return f'"{text}"'


def _rows(rng, n: int, low: int = 10, high: int = 999):
    items = rng.sample(ITEMS, n)
    counts = rng.sample(range(low, high), n)
    return [[i, str(c)] for i, c in zip(items, counts)]


def _table_prompt(caption, head, rows) -> str:
    listed = "; ".join(", ".join(r) for r in rows)
    return (f"a table with the caption {_q(caption)}, the header cells {', '.join(map(_q, head))}, "
            f"and these rows given as {' / '.join(head)}: {listed}.")


def _headings(rng, title):
    n = rng.randint(3, 6)
    subs = rng.sample(TOPICS, n)
    prompt = (f"The page needs an <h1> reading {_q(title)} followed by these <h2> headings in order: "
              f"{', '.join(map(_q, subs))}. Use no other h1, h2 or h3 headings.")
    return "easy", prompt, {"headings": [[1, title]] + [[2, s] for s in subs]}, None


def _table_plain(rng, title):
    n, wide = rng.randint(3, 8), rng.random() < 0.5
    rows = _rows(rng, n)
    head = ["Item", "Count"]
    if wide:
        head.append("Shelf")
        rows = [r + [rng.choice(SHELVES)] for r in rows]
    caption = f"{rng.choice(PLACES)} stock"
    prompt = f"The page holds {_table_prompt(caption, head, rows)} Keep the rows in this order. {CELLS}"
    return "easy", prompt, {"tables": [{"caption": caption, "head": head, "rows": rows}]}, None


def _dl(rng, title):
    pairs = [list(p) for p in rng.sample(TERMS, rng.randint(3, 6))]
    listed = "; ".join(f"{_q(t)}: {_q(d)}" for t, d in pairs)
    prompt = (f"The page holds one definition list (<dl>) of these terms (<dt>) and their definitions (<dd>), "
              f"in this order: {listed}.")
    return "easy", prompt, {"dl": pairs}, None


def _articles(rng, title):
    n = rng.randint(3, 7)
    cards = [[p, rng.choice(SENTENCES)] for p in rng.sample(PLACES, n)]
    listed = "; ".join(f"{_q(h)} with {_q(s)}" for h, s in cards)
    prompt = (f"The page holds exactly {n} <article> elements, in this order, each with one <h2> heading and "
              f"one <p> paragraph: {listed}. Use <article> for nothing else.")
    return "medium", prompt, {"articles": cards}, None


def _form_of(rng, n: int):
    fields = [{"label": lab, "name": name, "type": kind, "required": rng.random() < 0.5}
              for lab, name, kind in rng.sample(FIELDS, n)]
    said = []
    for f in fields:
        what = "a <textarea>" if f["type"] == "textarea" else f"an <input> of type {_q(f['type'])}"
        said.append(f"{what} named {_q(f['name'])} labelled {_q(f['label'])} with a <label> element, "
                    f"{'required' if f['required'] else 'not required'}")
    submit = rng.choice(SUBMITS)
    return {"fields": fields, "submit": submit}, (f"a form with {'; '.join(said)}; and a submit button reading "
                                                 f"{_q(submit)}.")


def _form(rng, title):
    spec, said = _form_of(rng, rng.randint(3, 6))
    return "medium", f"The page holds {said} Mark only the controls asked as required.", {"form": spec}, None


def _sections(rng, n: int):
    heads = rng.sample(TOPICS, n)
    nav = [[h, f"#{_slug(h)}"] for h in heads]
    said = ", ".join(f"{_q(h)} to #{_slug(h)}" for h in heads)
    return nav, {_slug(h): h for h in heads}, (
        f"a <nav> holding exactly these links in this order: {said}; and, for each link, a <section> whose id "
        f"is the link's target without the # and which starts with an <h2> reading the link text.")


def _nav(rng, title):
    nav, sections, said = _sections(rng, rng.randint(3, 6))
    return "medium", f"The page holds {said}", {"nav": nav, "sections": sections}, None


def _outline(rng, title):
    ordered = rng.random() < 0.5
    tops = rng.sample(STEPS, rng.randint(3, 5))
    pool = [s for s in STEPS if s not in tops]
    items, said = [], []
    for t in tops:
        k = min(rng.randint(0, 3), len(pool))
        subs = [pool.pop(rng.randrange(len(pool))).lower() for _ in range(k)]
        items.append([t, subs] if subs else t)
        said.append(f"{_q(t)} (sub-items: {', '.join(map(_q, subs))})" if subs else _q(t))
    tag = "an ordered list (<ol>)" if ordered else "an unordered list (<ul>)"
    prompt = (f"The page holds {tag} with these items in order: {'; '.join(said)}. Where sub-items are given, "
              f"put them in a nested <ul> inside that item, in the order given.")
    return "medium", prompt, {"lists": [{"ordered": ordered, "items": items}]}, None


def _sorted(rng, title):
    rows = _rows(rng, rng.randint(4, 9))
    while rows == sorted(rows, key=lambda r: -int(r[1])):
        rng.shuffle(rows)
    caption = f"{rng.choice(PLACES)} orders"
    head = ["Item", "Count"]
    prompt = (f"The page holds {_table_prompt(caption, head, rows)} List the rows sorted by Count, largest "
              f"first. {CELLS}")
    ordered = sorted(rows, key=lambda r: -int(r[1]))
    return "hard", prompt, {"tables": [{"caption": caption, "head": head, "rows": ordered}]}, rows


def _total(rng, title):
    rows = _rows(rng, rng.randint(3, 8), 1, 400)
    caption = f"{rng.choice(PLACES)} tally"
    head = ["Item", "Count"]
    prompt = (f"The page holds {_table_prompt(caption, head, rows)} Keep the rows in this order and end the "
              f"table with one more row whose first cell is \"Total\" and whose second cell is the sum of the "
              f"counts. {CELLS}")
    total = rows + [["Total", str(sum(int(r[1]) for r in rows))]]
    return "hard", prompt, {"tables": [{"caption": caption, "head": head, "rows": total}]}, rows


def _filter(rng, title):
    rows = _rows(rng, rng.randint(5, 9))
    counts = sorted(int(r[1]) for r in rows)
    floor = counts[rng.randint(2, len(counts) - 2)]
    caption = f"{rng.choice(PLACES)} reorders"
    head = ["Item", "Count"]
    prompt = (f"From these rows, the page holds only those whose Count is at least {floor}, in the order "
              f"given, as {_table_prompt(caption, head, rows)} {CELLS}")
    kept = [r for r in rows if int(r[1]) >= floor]
    return "hard", prompt, {"tables": [{"caption": caption, "head": head, "rows": kept}]}, rows


def _convert(rng, title):
    n = rng.randint(3, 7)
    stations = rng.sample(PLACES, n)
    temps = rng.sample(range(-30, 45), n)
    rows = [[s, str(t)] for s, t in zip(stations, temps)]
    caption = "Water temperature"
    prompt = (f"The page holds {_table_prompt(caption, ['Station', 'Celsius'], rows)} Keep the rows in this "
              f"order and add a third column with the header \"Fahrenheit\" holding each Celsius value converted "
              f"(F = C x 9/5 + 32), written with exactly one decimal place, such as 50.0, and a plain hyphen for "
              f"a negative number. {CELLS}")
    done = [r + [f"{int(r[1]) * 9 / 5 + 32:.1f}"] for r in rows]
    return "hard", prompt, {"tables": [{"caption": caption, "head": ["Station", "Celsius", "Fahrenheit"],
                                        "rows": done}]}, rows


def _mix(rng, title):
    nav, sections, said = _sections(rng, rng.randint(3, 4))
    rows = _rows(rng, rng.randint(3, 5), 1, 400)
    caption = f"{rng.choice(PLACES)} tally"
    form, asked = _form_of(rng, 2)
    prompt = (f"The page holds {said} It also holds {_table_prompt(caption, ['Item', 'Count'], rows)} Keep those "
              f"rows in order and end the table with a row whose first cell is \"Total\" and whose second cell is "
              f"the sum of the counts. {CELLS} Last, it holds {asked} Mark only the controls asked as required.")
    total = rows + [["Total", str(sum(int(r[1]) for r in rows))]]
    spec = {"nav": nav, "sections": sections,
            "tables": [{"caption": caption, "head": ["Item", "Count"], "rows": total}], "form": form}
    return "hard", prompt, spec, rows


KINDS = {"headings": _headings, "table": _table_plain, "dl": _dl, "articles": _articles, "form": _form,
         "nav": _nav, "outline": _outline, "sorted": _sorted, "total": _total, "filter": _filter,
         "convert": _convert, "mix": _mix}


def scene(row: dict):
    """The page of one row: (stratum, prompt, structure, the rows as the prompt gives them or None)."""
    rng = random.Random(f"{_KEY}:{VERSION}:{row['seed']}:{row['item']}:{row['attempt']}")
    title = _title(rng)
    stratum, body, spec, raw = KINDS[row["kind"]](rng, title)
    prompt = f"{PAGE} The page title (<title>) is {_q(title)}. {body}"
    return stratum, prompt, {"title": title, **spec, "self_contained": True}, raw


def fetch(seed: int = SEED, count: int = COUNT) -> list[dict]:
    """The seeded draws, kinds in equal turn; a prompt already drawn is drawn again."""
    out, seen, kinds = [], set(), sorted(KINDS)
    for i in range(count):
        row = {"item": i, "seed": seed, "kind": kinds[i % len(kinds)], "attempt": 0}
        while scene(row)[1] in seen:
            row["attempt"] += 1
            if row["attempt"] > ATTEMPTS:
                raise ValueError(f"{row['kind']} has too few distinct prompts for {count} cases")
        seen.add(scene(row)[1])
        out.append(row)
    return out


def case_of(row: dict) -> dict:
    stratum, prompt, spec, _ = scene(row)
    att = provenance(sys.modules[__name__], row["item"],
                     "a seeded page spec described as a prompt, asserted on its parsed structure")
    att.update(version=VERSION, seed=row["seed"], kind=row["kind"], stratum=stratum)
    return {"id": f"web-synth-{row['item']:04d}", "modality": LANE, "prompt": prompt,
            "assert": {"structure": spec}, "attribution": att}


def convert(row: dict) -> Imported:
    return Imported(case_of(row))


def _e(text) -> str:
    return html.escape(str(text), quote=True)


def _list(items, ordered: bool) -> str:
    tag = "ol" if ordered else "ul"
    lis = "".join(f"<li>{_e(i[0])}{_list(i[1], False)}</li>" if isinstance(i, list) else f"<li>{_e(i)}</li>"
                  for i in items)
    return f"<{tag}>{lis}</{tag}>"


def _form_html(form: dict) -> str:
    out = []
    for n, f in enumerate(form["fields"]):
        req = " required" if f["required"] else ""
        out.append(f'<label for="f{n}">{_e(f["label"])}</label>')
        out.append(f'<textarea id="f{n}" name="{_e(f["name"])}"{req}></textarea>' if f["type"] == "textarea" else
                   f'<input id="f{n}" name="{_e(f["name"])}" type="{_e(f["type"])}"{req}>')
    return "<form>" + "".join(out) + f'<button type="submit">{_e(form["submit"])}</button></form>'


def page(spec: dict) -> str:
    """A page with exactly the properties `spec` asserts: the reference answer."""
    body = ([f"<h{lvl}>{_e(t)}</h{lvl}>" for lvl, t in spec["headings"]] if "headings" in spec
            else [f"<h1>{_e(spec['title'])}</h1>"])
    if "nav" in spec:
        body.append("<nav>" + " ".join(f'<a href="{_e(h)}">{_e(t)}</a>' for t, h in spec["nav"]) + "</nav>")
    for sid, head in (spec.get("sections") or {}).items():
        body.append(f'<section id="{_e(sid)}"><h2>{_e(head)}</h2></section>')
    for t in spec.get("tables", []):
        rows = "".join("<tr>" + "".join(f"<td>{_e(c)}</td>" for c in r) + "</tr>" for r in t["rows"])
        body.append(f"<table><caption>{_e(t['caption'])}</caption><thead><tr>"
                    + "".join(f"<th>{_e(h)}</th>" for h in t["head"]) + f"</tr></thead><tbody>{rows}</tbody></table>")
    for lst in spec.get("lists", []):
        body.append(_list(lst["items"], lst["ordered"]))
    if "dl" in spec:
        body.append("<dl>" + "".join(f"<dt>{_e(t)}</dt><dd>{_e(d)}</dd>" for t, d in spec["dl"]) + "</dl>")
    for h, p in spec.get("articles", []):
        body.append(f"<article><h2>{_e(h)}</h2><p>{_e(p)}</p></article>")
    if "form" in spec:
        body.append(_form_html(spec["form"]))
    return (f"<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\"><title>{_e(spec['title'])}</title>"
            f"</head>\n<body>\n" + "\n".join(body) + "\n</body></html>\n")


def reference(case) -> str:
    return page(case.assertions["structure"])


def _row(item: int, prompt: str = "") -> dict:
    """The draw that wrote case `item`, found by its prompt; the first draw without one."""
    row = {"item": item, "seed": SEED, "kind": sorted(KINDS)[item % len(KINDS)], "attempt": 0}
    while prompt and scene(row)[1] != prompt:
        row["attempt"] += 1
        if row["attempt"] > ATTEMPTS:
            raise ValueError(f"web-synth-{item:04d} is not a draw of this generator")
    return row


def untransformed(case) -> str:
    """The reference page with a hard kind's table rows left as the prompt gives them."""
    raw = scene(_row(int(case.id.rsplit("-", 1)[1]), case.prompt))[3]
    spec = dict(case.assertions["structure"])
    spec["tables"] = [{**spec["tables"][0], "rows": raw}] + spec["tables"][1:]
    return page(spec)


def _other(case) -> str:
    return page(scene(_row((int(case.id.rsplit("-", 1)[1]) + 1) % COUNT))[2])


#: The negative control: the reference passes; a bare page or the next case's page does not.
RESPONDERS = {
    "reference": reference,
    "blank": lambda case: "<!doctype html><html><head><title>Page</title></head><body><p>Hello.</p></body></html>",
    "other-case": _other,
}


def passes(case, page_text: str) -> bool:
    """What the web checker decides on `page_text`, parse and structure, without a browser."""
    from harness.checks import html as html_check
    return html_check.check(page_text).ok and not html_check.structure(
        page_text, case.assertions.get("structure") or {})
