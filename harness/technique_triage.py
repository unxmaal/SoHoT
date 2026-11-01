"""Technique proposals triaged into methods: a measurable technique becomes a template crossed with each lane's incumbent. #993, #1476."""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field

from harness import methods

PROMPT, DECODING, MULTI_CALL, CONTEXT = methods.KINDS
#: Kinds a template measures here; each is crossed with the incumbent once its canary passes. #1476.
MEASURABLE = methods.KINDS
ENGINE, TRAINING, NOT_A_METHOD, REFUSED = "engine", "training", "not-a-method", "refused"
#: Why a technique is not measured here, by outcome.
UNMEASURABLE = {ENGINE: "an engine or serving change, handed to the engine path (#1475)",
                TRAINING: "needs training or new weights, which this harness does not do",
                NOT_A_METHOD: "changes nothing a local model is sent or how it samples",
                REFUSED: "the draft or its canary failed"}
#: What #993 wrote for every technique that was not a prompt one; such a row is triaged again.
LEGACY_OTHER = "other"
#: Drafts one triage run makes at most; a technique a registered method's source names costs none.
PER_RUN = 80
DRAFT_TOKENS = 1500
#: The lanes a technique routed to no one lane is drafted for.
DEFAULT_LANES = ("code", "extract", "web")
#: The lane whose adopted model drafts and answers the canary.
DRAFT_LANE = "extract"
#: Nights the backlog should drain in at the knob's size; the triage report says how far off it is.
DRAIN_NIGHTS = 7
#: (task, material, answer) a drafted template must carry to its answer before it is crossed: the #993 canary.
CANARY = (("What is 17 multiplied by 3? Reply with the number only.", "", "51"),
          ("What is the vault code in the note? Reply with the code only.",
           "Note from the night shift: the vault code is 4417. The lights are on a timer.", "4417"))

DRAFT_SYSTEM = "You read one proposed technique and reply with one JSON object and nothing else."
DRAFT_PROMPT = """A technique was proposed for a local language model. Classify how it works:
- "prompt": it changes only what is sent (a pre-prompt, a rewrite of the task, a plan step)
- "decoding": it changes how replies are sampled (temperature, top_p, min_p, top_k, penalties)
- "multi-call": it makes several calls and combines them (self-consistency, verify then revise, plan then act)
- "context": it changes where or how the given material is placed (after the task, task repeated after it, numbered lines)
- "engine": it needs a change to the serving software (a kernel, a cache, speculative or draft-model decoding, quantization)
- "training": it needs training, fine-tuning or new weights
- "other": none of these (a benchmark, a dataset, a survey, an architecture study)

Registered methods: {known}

Reply with one JSON object:
{{"mechanism": one of the seven words above,
 "why": "one sentence",
 "same_as": "" or the registered method it is,
 "name": "two to four words naming it",
 "note": "one line on what the steps do",
 "lanes": the subset of {lanes} it would help,
 "steps": [{{"as": "a name a later step reads", "prompt": "...", "samples": 1, "sampling": {{}}, "context": "before"}}, {{"prompt": "the last call, whose reply is the answer"}}]}}

Each step is one model call. Write {{task}} where the task goes; a later step reads an earlier step's reply as {{<its as>}}.
"samples" (1 to {samples}) draws that many replies of a step, and a later step reads them numbered; the last step answers once.
"sampling" sets any of {sampling} for that step.
"context" puts the material: {shapes}.
Leave steps empty when the mechanism is engine, training or other.

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
    """The text lanes a technique is drafted for: its routed text lane, none for another lane, else the defaults."""
    from harness import lanes, rank
    got = rank.technique_route(row)
    if got in methods.TEXT_LANES:
        return (got,)
    return () if got in lanes.ALL else DEFAULT_LANES


def _triaged(conn) -> set:
    return {r[0] for r in conn.execute(
        "SELECT p.name FROM technique_triage t JOIN proposals p ON p.id = t.proposal_id WHERE t.outcome <> ?",
        (LEGACY_OTHER,))}


def pending(conn) -> list[dict]:
    """Unsettled techniques not yet triaged (or triaged before #1476 as other) a template could serve."""
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
                                 samples=methods.MAX_SAMPLES, sampling=", ".join(methods.SAMPLING_RANGES),
                                 shapes=", ".join(methods.CONTEXT_SHAPES),
                                 title=row.get("title") or row["name"], url=row.get("url") or "",
                                 description=row.get("description") or "")
    got = delegate.complete(DRAFT_LANE, prompt, system=DRAFT_SYSTEM, max_tokens=DRAFT_TOKENS)
    return {**parse_draft(got.get("text") or ""), "drafted_by": got.get("spec") or ""}


def canary(method) -> str:
    """Why `method` fails the known-answer canary on the drafting lane's model, "" when it carries every answer.
    Raises delegate.Refused or a CompletionError other than a cut reply, which ends the run."""
    from harness import completion, delegate, reasons
    for task, material, answer in CANARY:
        try:
            got = delegate.complete(DRAFT_LANE, task, max_tokens=DRAFT_TOKENS, method=method, context=material,
                                    max_tokens_knob="triage_draft_tokens")
        except completion.CompletionError as exc:
            if exc.failure_class != reasons.TOKEN_BUDGET_EXHAUSTED:
                raise
            return f"its canary ran past {DRAFT_TOKENS} tokens on {task!r}"
        miss = missed(got.get("text") or "", answer)
        if miss:
            return f"failed its known-answer canary: {task!r} {miss}"
    return ""


def missed(text: str, answer: str) -> str:
    """Why `text` does not carry `answer` as a whole word, "" when it does."""
    if re.search(rf"(?<![\w.]){re.escape(answer)}(?![\w])", text or ""):
        return ""
    return f"answered {(text or '').strip()[:80]!r}, not {answer}"


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
    if mech == LEGACY_OTHER:
        return NOT_A_METHOD, None, why or UNMEASURABLE[NOT_A_METHOD], None
    if mech in (ENGINE, TRAINING):
        return mech, None, why or UNMEASURABLE[mech], None
    if mech not in MEASURABLE:
        return REFUSED, None, f"the draft's mechanism is {mech!r}, not one of the seven", None
    same = str(d.get("same_as") or "")
    if same and dict.__contains__(methods.REGISTRY, same):
        return mech, methods.REGISTRY[same], why or f"the registered method {same}", None
    route = lanes_for(row)
    asked = [x for x in d.get("lanes") or () if isinstance(x, str)] if isinstance(d.get("lanes"), list) else []
    want = [x for x in (asked or route) if x in methods.TEXT_LANES and (not route or x in route)]
    if not want:
        return REFUSED, None, f"the draft names no text lane this technique routes to ({asked or 'none'})", None
    t = {"name": _free_name(d.get("name") or row["name"], taken), "note": str(d.get("note") or why)[:200],
         "source": row.get("url") or row["name"], "lanes": want, "kind": mech, "steps": d.get("steps") or []}
    try:
        m = methods.from_template(t, f"the draft for {row['name']}")
    except (ValueError, TypeError, AttributeError) as exc:
        return REFUSED, None, str(exc), None
    for r in [*_registered(), *_stored_drafts(conn).values()]:
        if r.extra.get("digest") == m.extra["digest"]:
            return mech, r, why or f"the same steps as {r.name}", None
    return mech, m, why, t


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


def _final(conn, row: dict, why: str) -> None:
    """A technique that needs training is declined at inspect with the reason: final, nothing reopens it."""
    from harness import reasons
    from harness import memory_store as ms
    ms.decide(conn, row["name"], "declined", tier=ms.INSPECT, reason=reasons.CANDIDATE,
              detail=f"{UNMEASURABLE[TRAINING]}: {why}"[:500])


def _record(conn, row: dict, got: Triaged, template, drafted_by: str, now: float) -> None:
    pid = conn.execute("SELECT id FROM proposals WHERE name = ?", (row["name"],)).fetchone()[0]
    conn.execute("DELETE FROM technique_triage WHERE proposal_id = ? AND outcome = ?", (pid, LEGACY_OTHER))
    conn.execute("INSERT INTO technique_triage (proposal_id, outcome, method, why, template, drafted_by, "
                 "triaged_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                 (pid, got.outcome, got.method, got.why[:500], json.dumps(template) if template else "",
                  drafted_by, now))
    conn.commit()
    if template:
        methods.forget_drafted()


def _known_kind(method) -> str:
    return method.extra.get("kind") or PROMPT


def triage(conn, draft=None, limit: int | None = None, incumbent_of=None, want: str = "",
           now: float | None = None, canary=None) -> Run:
    """Triage pending techniques, at most `limit` drafts; a refused or failed call ends the run.
    A new template is crossed only once `canary(method)` returns ""; a training one is made final."""
    from harness import completion, delegate, reasons
    draft = draft or globals()["draft"]
    canary = canary or globals()["canary"]
    limit = PER_RUN if limit is None else int(limit)
    incumbent_of = incumbent_of or _incumbents(conn)
    now = time.time() if now is None else float(now)
    taken = {*dict.keys(methods.REGISTRY), *_stored_drafts(conn)}
    names = sorted(m.name for m in _registered() if not m.extra.get("control"))
    out, calls = Run(), 0
    for row in pending(conn):
        known, d, drafted_by = known_method(row), {}, ""
        if known:
            method = methods.REGISTRY[known]
            outcome, why, template = _known_kind(method), "its link is this method's source", None
        else:
            if calls >= limit:
                from harness import cuts
                out.stopped = f"the limit of {limit} draft(s) this run"
                cuts.cut("triage_per_run", f"{limit} draft(s) this run; {row['name']} and later wait",
                         value=limit, conn=conn)
                break
            calls += 1
            try:
                d = draft(row, names)
                drafted_by = str(d.get("drafted_by") or "")
                outcome, method, why, template = _resolve(conn, row, d, taken)
                miss = canary(method) if template else ""
            except completion.CompletionError as exc:
                if exc.failure_class != reasons.TOKEN_BUDGET_EXHAUSTED:
                    out.stopped = f"the {DRAFT_LANE} lane's model did not answer: {str(exc)[:160]}"
                    break
                from harness import cuts
                cuts.cut("triage_draft_tokens", f"the draft for {row['name']} ran past its reply budget", conn=conn)
                outcome, method, why, template = REFUSED, None, f"the draft ran past {DRAFT_TOKENS} tokens", None
            except delegate.Refused as exc:
                out.stopped = f"the {DRAFT_LANE} lane's model did not answer: {str(exc)[:160]}"
                break
            except ValueError as exc:
                outcome, method, why, template = REFUSED, None, str(exc), None
            else:
                if miss:
                    outcome, method, why, template = REFUSED, None, f"{template['name']} {miss}", None
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
        if outcome == TRAINING:
            _final(conn, row, why)
        _record(conn, row, got, template, drafted_by, now)
        out.append(got)
    return out


def handed_to_engines(conn) -> list[str]:
    """Techniques triage found to be engine or serving changes, for the engine path (#1475) to take."""
    return [r[0] for r in conn.execute(
        "SELECT p.name FROM technique_triage t JOIN proposals p ON p.id = t.proposal_id WHERE t.outcome = ? "
        "ORDER BY t.id", (ENGINE,))]


OUTCOMES = (*MEASURABLE, *UNMEASURABLE)


def counts(conn, since: float | None = None) -> dict:
    """Triage rows by outcome, every one or those triaged since `since`."""
    got = {k: 0 for k in OUTCOMES}
    q, args = "SELECT outcome, COUNT(*) FROM technique_triage", ()
    if since is not None:
        q, args = q + " WHERE triaged_at >= ?", (since,)
    for outcome, n in conn.execute(q + " GROUP BY outcome", args):
        got[outcome] = n
    return got


def crossings(conn) -> dict:
    """Every crossing of a triaged method by where it stands: measured (won, lost), declined unmeasured, waiting."""
    got = {"measured": 0, "won": 0, "lost": 0, "declined": 0, "waiting": 0}
    rows = conn.execute(
        "SELECT p.id, p.name, p.state FROM proposals p WHERE p.kind = ? AND EXISTS (SELECT 1 FROM technique_triage t "
        "WHERE t.method <> '' AND p.name LIKE t.method || ':%')", (methods.CROSSING_KIND,)).fetchall()
    for pid, name, state in rows:
        tiers = {r[0] for r in conn.execute("SELECT DISTINCT tier FROM verdicts WHERE proposal_id = ?", (pid,))}
        won = conn.execute("SELECT 1 FROM adoptions a JOIN candidates c ON c.id = a.candidate_id WHERE c.spec = ?",
                           (name,)).fetchone()
        if tiers & {"measure", "adopt"} or won:
            got["measured"] += 1
            if won:
                got["won"] += 1
            elif state == "declined":
                got["lost"] += 1
        elif state == "declined":
            got["declined"] += 1
        else:
            got["waiting"] += 1
    return got


def nights(waiting: int, per_run: int) -> int:
    """Nightly runs the backlog takes at `per_run` drafts a night; 0 for none waiting."""
    return 0 if waiting <= 0 else -(-waiting // max(1, per_run))


def _tally(by: dict, keys) -> str:
    return ", ".join(f"{by.get(k, 0)} {k}" for k in keys)


def lines(conn, got: list | None, per_run: int | None = None) -> list[str]:
    """The loop's `technique triage` section: this run's outcomes and crossings, and what is still to triage."""
    per_run = PER_RUN if per_run is None else per_run
    waiting = len(pending(conn))
    took = nights(waiting, per_run)
    drain = f"; about {took} night(s) at {per_run} a night" + (
        f", past the {DRAIN_NIGHTS} the knob is sized for" if took > DRAIN_NIGHTS else "") if waiting else ""
    out = ["\n=== technique triage ==="]
    if got is None:
        out.append(f"  {waiting} technique(s) to triage{drain}; --run drafts up to {per_run} with the "
                   f"{DRAFT_LANE} lane's model")
        return out
    by = {k: sum(1 for g in got if g.outcome == k) for k in OUTCOMES}
    out.append(f"  {len(got)} triaged this run: {_tally(by, OUTCOMES)}; {waiting} still to triage{drain}")
    if getattr(got, "stopped", ""):
        out.append(f"  stopped at {got.stopped}")
    out.append(f"  in all: {_tally(counts(conn), OUTCOMES)}")
    for g in got:
        out.append(f"  {g.outcome:12} {g.name}{f'  -> {g.method}' if g.method else ''}"
                   f"{f'  ({g.why[:120]})' if g.why and not g.crossings else ''}")
        for lane, spec, what in g.crossings:
            out.append(f"    {what:8} {lane:8} {spec}")
    return out


def morning(conn, since: float) -> dict:
    """The brief's technique facts: what was triaged since `since`, how crossings fared, and why the rest are not measured."""
    return {"triaged": counts(conn, since), "all": counts(conn), "crossings": crossings(conn),
            "waiting": len(pending(conn)), "per_run": PER_RUN}


def morning_lines(t: dict | None) -> list[str]:
    """The brief's `techniques` lines; none before the triage table exists."""
    if not t:
        return []
    night, c = t["triaged"], t["crossings"]
    return [f"techniques {sum(night.values())} triaged: {_tally(night, MEASURABLE)} measurable; "
            f"{t['waiting']} waiting ({nights(t['waiting'], t['per_run'])} night(s) at {t['per_run']})",
            f"           crossings: {c['measured']} measured ({c['won']} won, {c['lost']} lost), "
            f"{c['declined']} declined on a stored loss, {c['waiting']} waiting",
            "           unmeasurable in all: " + ", ".join(f"{t['all'][k]} {k} ({why})" for k, why in UNMEASURABLE.items())]
