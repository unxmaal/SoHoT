"""Technique proposals triaged into methods: a prompt technique becomes a template crossed with each lane's incumbent. #993."""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field

from harness import methods

PROMPT, OTHER, REFUSED = "prompt", "other", "refused"
#: Model calls one triage run makes at most; a technique a registered method's source names costs none.
PER_RUN = 12
DRAFT_TOKENS = 1500
#: The lanes a technique routed to no one text lane is drafted for.
DEFAULT_LANES = ("code", "extract", "web")

DRAFT_SYSTEM = "You read one proposed technique and reply with one JSON object and nothing else."
DRAFT_PROMPT = """A technique was proposed for a local language model. Decide whether it is a PROMPT technique: one that works only by changing what is sent to the model (a pre-prompt, a rewrite of the task, a plan, critique or revise step), with no training, no new weights and no change to the serving software.

Registered methods: {known}

Reply with one JSON object:
{{"mechanism": "prompt" or "other",
 "why": "one sentence",
 "same_as": "" or the registered method it is,
 "name": "two to four words naming it",
 "note": "one line on what the steps do",
 "lanes": the subset of {lanes} it would help,
 "steps": [{{"as": "a name a later step reads", "prompt": "..."}}, {{"prompt": "the last call, whose reply is the answer"}}]}}

Each step is one model call. Write {{task}} where the task goes; a later step reads an earlier step's reply as {{<its as>}}. Leave steps empty when the mechanism is other.

TECHNIQUE
title: {title}
link: {url}
{description}
"""


@dataclass
class Triaged:
    name: str
    outcome: str
    method: str = ""
    why: str = ""
    #: (lane, spec, what): what is queued, declined or the crossing's state when it was already known.
    crossings: list = field(default_factory=list)


class Run(list):
    """One triage run's Triaged rows; `stopped` says why it ended early, "" when it did not."""
    stopped = ""


def key_of(text: str) -> str:
    """One technique's identity across sources: arxiv:<id> for a paper, else host and path."""
    t = (text or "").strip()
    m = re.search(r"(?:^arxiv:|arxiv\.org/(?:abs|pdf)/|huggingface\.co/papers/)(\d{4}\.\d{4,5})", t, re.I)
    if m:
        return f"arxiv:{m.group(1)}"
    t = re.sub(r"^post:", "", t)
    t = re.sub(r"^[a-z][a-z0-9+.-]*://", "", t, flags=re.I).split("#")[0].split("?")[0]
    return re.sub(r"^www\.", "", t, flags=re.I).rstrip("/").lower()


def known_method(row: dict) -> str:
    """The registered method whose source is this technique, or ""."""
    keys = {key_of(row.get("name") or ""), key_of(row.get("url") or "")} - {""}
    for m in methods.REGISTRY.values():
        src = m.extra.get("source") or ""
        if src and key_of(src) in keys and not m.extra.get("control"):
            return m.name
    return ""


def lanes_for(row: dict) -> tuple:
    """The text lanes a technique is drafted for: its routed lane, the defaults for a general one, else none."""
    from harness import lanes, rank
    got = rank.technique_route(row)
    if got in methods.TEXT_LANES:
        return (got,)
    return DEFAULT_LANES if got == lanes.GENERAL else ()


def _triaged(conn) -> set:
    return {r[0] for r in conn.execute(
        "SELECT p.name FROM technique_triage t JOIN proposals p ON p.id = t.proposal_id")}


def pending(conn) -> list[dict]:
    """Unsettled techniques never triaged that a template could serve, in ms.techniques order."""
    from harness import memory_store as ms
    done = _triaged(conn)
    return [r for r in ms.techniques(conn)
            if r["name"] not in done and (known_method(r) or lanes_for(r))]


def parse_draft(text: str) -> dict:
    """The JSON object in a model's reply; ValueError when there is none."""
    s = text or ""
    start, end = s.find("{"), s.rfind("}")
    try:
        got = json.loads(s[start:end + 1]) if 0 <= start < end else None
    except json.JSONDecodeError:
        got = None
    if not isinstance(got, dict):
        raise ValueError("the reply holds no JSON object")
    return got


def draft(row: dict, known=()) -> dict:
    """The extract lane's model reads the technique and drafts a template; raises delegate.Refused or CompletionError."""
    from harness import delegate
    prompt = DRAFT_PROMPT.format(known=", ".join(known) or "none", lanes=json.dumps(list(DEFAULT_LANES)),
                                 title=row.get("title") or row["name"], url=row.get("url") or "",
                                 description=row.get("description") or "")
    got = delegate.complete("extract", prompt, system=DRAFT_SYSTEM, max_tokens=DRAFT_TOKENS)
    return {**parse_draft(got.get("text") or ""), "drafted_by": got.get("spec") or ""}


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", str(name or "").lower()).strip("-")[:40].strip("-")
    return s if s and s[0].isalpha() else f"x-{s}" if s else "technique"


def _free_name(name: str, taken: set) -> str:
    base = f"{methods.DRAFTED_PREFIX}{_slug(name)}"
    got, n = base, 1
    while got in taken:
        n += 1
        got = f"{base}-{n}"
    return got


def _registered() -> list:
    return list(methods.REGISTRY.values())


def _stored_drafts(conn) -> dict:
    return methods.stored_templates(conn.execute(
        "SELECT method, template FROM technique_triage WHERE template <> ''").fetchall())


def _lanes(method, row: dict, d: dict) -> tuple:
    route = lanes_for(row)
    asked = tuple(x for x in (d.get("lanes") or ()) if isinstance(x, str)) if isinstance(d.get("lanes"), list) else ()
    return tuple(x for x in method.lanes if (not route or x in route) and (not asked or x in asked))


def _resolve(conn, row: dict, d: dict, taken: set):
    """(outcome, method or None, why, template row or None) for one draft."""
    mech, why = d.get("mechanism"), str(d.get("why") or "")
    if mech == OTHER:
        return OTHER, None, why or "not a prompt transform", None
    if mech != PROMPT:
        return REFUSED, None, f"the draft's mechanism is {mech!r}, not prompt or other", None
    same = str(d.get("same_as") or "")
    if same and dict.__contains__(methods.REGISTRY, same):
        return PROMPT, methods.REGISTRY[same], why or f"the registered method {same}", None
    route = lanes_for(row)
    asked = [x for x in d.get("lanes") or () if isinstance(x, str)] if isinstance(d.get("lanes"), list) else []
    want = [x for x in (asked or route) if x in methods.TEXT_LANES and (not route or x in route)]
    if not want:
        return REFUSED, None, f"the draft names no text lane this technique routes to ({asked or 'none'})", None
    t = {"name": _free_name(d.get("name") or row["name"], taken), "note": str(d.get("note") or why)[:200],
         "source": row.get("url") or row["name"], "lanes": want, "steps": d.get("steps") or []}
    try:
        m = methods.from_template(t, f"the draft for {row['name']}")
    except (ValueError, TypeError, AttributeError) as exc:
        return REFUSED, None, str(exc), None
    for r in [*_registered(), *_stored_drafts(conn).values()]:
        if r.extra.get("digest") == m.extra["digest"]:
            return PROMPT, r, why or f"the same steps as {r.name}", None
    return PROMPT, m, why, t


def stored_loss(conn, method: str, lane: str) -> str:
    """Why the newest stored measure run of `method` in `lane`, on any base, was significantly worse than
    the one candidate it was paired with there; "" if it was not or there is no such run."""
    from harness import adopt, canary
    hit = conn.execute(
        "SELECT x.run_id, x.candidate FROM results x JOIN runs u ON u.id = x.run_id "
        "WHERE u.lane = ? AND u.tier = 'measure' AND (x.candidate LIKE ? OR x.candidate GLOB ?) "
        "ORDER BY x.run_id DESC LIMIT 1", (lane, f"{method}/%", f"{method}-[0-9]*/*")).fetchone()
    if not hit:
        return ""
    run, key = int(hit[0]), hit[1]
    others = [r[0] for r in conn.execute("SELECT DISTINCT candidate FROM results WHERE run_id = ? AND candidate <> ?",
                                         (run, key))]
    if len(others) != 1:
        return ""
    rows = canary._stored_rows(conn, run, others[0], lane) + canary._stored_rows(conn, run, key, lane)
    why = adopt._worse(rows, others[0], key, lane)
    return f"stored run {run}: {key} against {others[0]} was {why}" if why else ""


def _incumbents(conn):
    from harness import adopt, winners
    typed = winners.typed()
    return lambda lane: adopt.default_for(lane, typed.get(lane, ""), conn=conn)


def cross(conn, method, want, technique: str, incumbent_of) -> list:
    """Queue `method` over each lane's incumbent, or decline it on a stored loss; a known crossing is left alone."""
    from harness import lanes, reasons
    from harness import memory_store as ms
    out = []
    for lane in want:
        if lanes.parked(lane)[0]:
            continue
        base = incumbent_of(lane)
        if not base or methods.is_method(base):
            continue
        spec = method.compose(base)
        known = conn.execute("SELECT state FROM proposals WHERE name = ?", (spec,)).fetchone()
        if known:
            out.append((lane, spec, known[0] or "known"))
            continue
        ms.record(conn, ms.Seen(name=spec, source=methods.CROSSING_SOURCE, kind=methods.CROSSING_KIND,
                                lane=lane, resolved=spec, why=f"{method.name} from {technique} over the "
                                f"incumbent {base}", description=method.note))
        loss = stored_loss(conn, method.name, lane)
        if loss:
            ms.decide(conn, spec, "declined", tier=ms.INSPECT, reason=reasons.CANDIDATE,
                      detail=f"{lane}: {loss}; not measured again on this lane")
            out.append((lane, spec, "declined"))
        else:
            ms.decide(conn, spec, "queued", tier=ms.INSPECT, reason=reasons.CANDIDATE,
                      detail=f"a method triaged from the technique {technique}, over the {lane} lane's incumbent")
            out.append((lane, spec, "queued"))
    return out


def _record(conn, row: dict, got: Triaged, template, drafted_by: str, now: float) -> None:
    pid = conn.execute("SELECT id FROM proposals WHERE name = ?", (row["name"],)).fetchone()[0]
    conn.execute("INSERT INTO technique_triage (proposal_id, outcome, method, why, template, drafted_by, "
                 "triaged_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                 (pid, got.outcome, got.method, got.why[:500], json.dumps(template) if template else "",
                  drafted_by, now))
    conn.commit()
    if template:
        methods.forget_drafted()


def triage(conn, draft=None, limit: int = PER_RUN, incumbent_of=None, want: str = "",
           now: float | None = None) -> Run:
    """Triage pending techniques, at most `limit` model calls; a refused or failed call ends the run."""
    from harness import completion, delegate, reasons
    draft = draft or globals()["draft"]
    incumbent_of = incumbent_of or _incumbents(conn)
    now = time.time() if now is None else float(now)
    taken = {*dict.keys(methods.REGISTRY), *_stored_drafts(conn)}
    names = sorted(m.name for m in _registered() if not m.extra.get("control"))
    out, calls = Run(), 0
    for row in pending(conn):
        known, d, drafted_by = known_method(row), {}, ""
        if known:
            outcome, method, why, template = PROMPT, methods.REGISTRY[known], "its link is this method's source", None
        else:
            if calls >= limit:
                from harness import cuts
                out.stopped = f"the limit of {limit} model call(s) this run"
                cuts.cut("triage_per_run", f"{limit} draft(s) this run; {row['name']} and later wait", conn=conn)
                break
            calls += 1
            try:
                d = draft(row, names)
            except completion.CompletionError as exc:
                if exc.failure_class != reasons.TOKEN_BUDGET_EXHAUSTED:
                    out.stopped = f"the extract lane's model did not answer: {str(exc)[:160]}"
                    break
                from harness import cuts
                cuts.cut("triage_draft_tokens", f"the draft for {row['name']} ran past its reply budget", conn=conn)
                outcome, method, why, template = REFUSED, None, f"the draft ran past {DRAFT_TOKENS} tokens", None
            except delegate.Refused as exc:
                out.stopped = f"the extract lane's model did not answer: {str(exc)[:160]}"
                break
            except ValueError as exc:
                outcome, method, why, template = REFUSED, None, str(exc), None
            else:
                drafted_by = str(d.get("drafted_by") or "")
                outcome, method, why, template = _resolve(conn, row, d, taken)
        got = Triaged(row["name"], outcome, method.name if method else "", why)
        if method is not None and method.extra.get("control"):
            got.why = f"{method.name} is the negative control; it is crossed only beside its method"
        elif method is not None:
            lanes = _lanes(method, row, d)
            if want:
                lanes = tuple(x for x in lanes if x == want)
            got.crossings = cross(conn, method, lanes, row["name"], incumbent_of)
        if template:
            taken.add(template["name"])
        _record(conn, row, got, template, drafted_by, now)
        out.append(got)
    return out


def counts(conn) -> dict:
    """Every triage row by outcome, and the crossings triage queued, for the loop's report."""
    got = {k: 0 for k in (PROMPT, OTHER, REFUSED)}
    for outcome, n in conn.execute("SELECT outcome, COUNT(*) FROM technique_triage GROUP BY outcome"):
        got[outcome] = n
    return got


def lines(conn, got: list | None, per_run: int = PER_RUN) -> list[str]:
    """The loop's `technique triage` section: this run's outcomes and crossings, and what is still to triage."""
    waiting = len(pending(conn))
    out = ["\n=== technique triage ==="]
    if got is None:
        out.append(f"  {waiting} technique(s) to triage; --run drafts up to {per_run} with the extract lane's model")
        return out
    by = {k: sum(1 for g in got if g.outcome == k) for k in (PROMPT, OTHER, REFUSED)}
    out.append(f"  {len(got)} triaged this run: {by[PROMPT]} prompt, {by[OTHER]} other, "
               f"{by[REFUSED]} refused; {waiting} still to triage")
    if getattr(got, "stopped", ""):
        out.append(f"  stopped at {got.stopped}")
    total = counts(conn)
    out.append(f"  in all: {total[PROMPT]} prompt, {total[OTHER]} other, {total[REFUSED]} refused")
    for g in got:
        out.append(f"  {g.outcome:8} {g.name}{f'  -> {g.method}' if g.method else ''}"
                   f"{f'  ({g.why[:120]})' if g.why and not g.crossings else ''}")
        for lane, spec, what in g.crossings:
            out.append(f"    {what:8} {lane:8} {spec}")
    return out
