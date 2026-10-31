"""Shadow replay of the census's local-fit units on the adopted local models, graded blind. #1161."""
from __future__ import annotations

import concurrent.futures
import hashlib
import json
import math
import random
import re
import subprocess
import tempfile
import threading
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from evals import redact, session_cut
from evals.analysis import demand as d
from evals.importers import transcripts as tr
from harness import intervals

SEED = 1161
CONTROLS = 10
REPEATS = 2
FITTING = ("fits_now", "fits_with_harness_work")
#: Shapes a text lane cannot answer; a control is never drawn from them.
NOT_TEXT = ("media",)
GRADES = ("usable_as_is", "usable_with_edits", "not_usable")
#: Shape -> the lane group it maps to; no prose lane exists, so prose goes to the code lane's general model.
GROUP = {"extract_classify": "extract", "summarise_digest": "extract", "triage_decide": "decide",
         "small_code_edit": "code", "multi_file_code": "code", "investigation_debug": "code",
         "draft_prose": "prose", "orchestration_chat": "prose"}
LANE = {"extract": "extract", "decide": "decide", "code": "code", "prose": "code"}
CONTEXT_BYTES = session_cut.BUDGET_BYTES
REFERENCE_BYTES = 12000
RESULT_CAP = 4000
JUDGE_MODEL = "claude-opus-5-5"
JUDGE_TIMEOUT_S = 600.0
JUDGE_JOBS = 4
#: Share of planted wrong answers the judge must grade not_usable before its grades count.
REJECT_MIN = 0.9
#: Share of units two replays must grade the same.
AGREE_MIN = 0.95
#: The does-not-fit control's as-is rate at or below which it reads as near zero.
CONTROL_MAX = 0.1
PLANTS = ("swap", "corrupt", "wrong")
#: The candidate that is each lane's adopted model at call time.
ADOPTED = "adopted"
#: A known-good candidate: the session's own record, which the judge must not reject.
SELF = "self"

SYSTEM = ("You stand in for the assistant of a Claude Code session. You have no tools: you cannot run commands or "
          "read, search or edit files, nothing in your reply is executed, and the quoted session is all you get. "
          "Answer its latest request in one reply with what the assistant should deliver: the answer, decision, "
          "summary or text asked for; for a code change, the change as one unified diff with a/ and b/ paths from "
          "the repository root.")
HEAD = ("Each line below that starts with > quotes a Claude Code session up to its latest request. Its tool calls "
        "ran then and none can run now.\n\n")
TAIL = "\n\n(End of the quoted session.) Reply to its latest request."
JUDGE_SYSTEM = (
    "You grade one candidate reply to a subtask from a Claude Code session. You see the session up to the "
    "subtask's request, a record of what the session's assistant actually did for it (its tool calls, edits and "
    "final text), and the candidate, which had no tools and answered in one reply. You are not told who wrote "
    "the candidate. Judge whether the person could use it in place of what was done:\n"
    "usable_as_is: reaches the same outcome as the record or an equally good one; the person would keep it, at "
    "most fixing a typo.\n"
    "usable_with_edits: the right answer or approach, with gaps or slips the person would fix in a minute or "
    "two.\n"
    "not_usable: wrong, off-task, contradicts the record's outcome, invents facts, or misses what was asked.\n"
    "A candidate that asks to run a tool, or says it cannot, without answering is not_usable. Reply with one "
    'JSON object and nothing else: {"grade": "<one of the three>", "reason": "<one line>"}')
WRONG_SYSTEM = ("You write test items that calibrate a grader of assistant replies. Every item must be wrong in a "
                "way that matters, while reading as a plausible, confident, on-task reply.")
WRONG_ASK = ("Below are a session's latest request and a record of what its assistant actually did. Write a reply "
             "to that request that looks plausible and on-task but is wrong in a way that matters: reach the "
             "opposite conclusion, pick a different option, state different facts or numbers, or make a code "
             "change that does something else. Match the record's length and style. Reply with only that wrong "
             "reply.\n\n")
#: Word pairs a corrupt plant swaps, both ways.
FLIPS = (("yes", "no"), ("true", "false"), ("pass", "fail"), ("passes", "fails"), ("passed", "failed"),
         ("can", "cannot"), ("should", "should not"), ("does", "does not"), ("is", "is not"), ("add", "remove"),
         ("added", "removed"), ("before", "after"), ("enable", "disable"), ("increase", "decrease"),
         ("correct", "wrong"), ("merged", "closed"), ("open", "closed"), ("first", "last"), ("left", "right"))
REPORT_TOOLS = d.REPORT_TOOLS
_NUMBER = re.compile(r"(?<![\w.])\d+(?:\.\d+)?(?![\w.])")
_GRADE = re.compile(r"\{.*\}", re.S)
_CAT_N = re.compile(r"^\s*\d+\t", re.M)


@dataclass
class Located:
    key: str
    kind: str
    session: str
    stream: str
    start: float
    recs: list


def select(rows: list[dict], controls: int = CONTROLS, seed: int = SEED) -> list[dict]:
    """The fitting units and a seeded draw of `controls` text-shaped does-not-fit units, each marked `control`."""
    fit = [dict(r, control=False) for r in rows if r["final"]["fit"] in FITTING]
    pool = sorted((r for r in rows if r["final"]["fit"] not in FITTING and r["final"]["shape"] not in NOT_TEXT),
                  key=lambda r: r["key"])
    drawn = random.Random(seed).sample(pool, min(controls, len(pool)))
    return sorted(fit + [dict(r, control=True) for r in drawn], key=lambda r: r["id"])


def _main_starts(recs: list) -> list[float]:
    """Start times of the main-loop units in a session, as the census's scan splits them."""
    out, began = [], False
    for rec in recs:
        if rec.get("isSidechain"):
            continue
        at = tr._ts(rec.get("timestamp"))
        if tr.human_text(rec) is not None and at:
            out.append(at)
            began = True
        elif not began and at and rec.get("type") in ("user", "assistant"):
            out.append(at)
            began = True
    return out


def locate(root: Path, keys, now: float) -> dict:
    """key -> Located for each census unit key found under `root`, reading records up to `now` as the scan did."""
    want, got = set(keys), {}
    for _project, main, subs in tr.sessions(Path(root)):
        if not want - set(got):
            break
        recs = [r for r in tr.records(main) if tr._ts(r.get("timestamp")) <= now]
        if d._headless(recs):
            continue
        session = main.stem
        for at in _main_starts(recs):
            if (k := d.unit_key(session, "main", at)) in want:
                got[k] = Located(k, "main", session, "main", at, [r for r in recs if not r.get("isSidechain")])
        for s in subs:
            rs = [r for r in tr.records(s) if tr._ts(r.get("timestamp")) <= now]
            if (began := d._began(rs)) and (k := d.unit_key(session, s.stem, began)) in want:
                got[k] = Located(k, "subagent", session, s.stem, began, rs)
    return got


def reported(e: session_cut.Event) -> session_cut.Event:
    """A subagent's final-report call as the assistant text it is; any other event as it is."""
    if e.kind == "call" and e.name in REPORT_TOOLS and str((e.input or {}).get("message") or "").strip():
        return session_cut.Event(e.at, "text", body=session_cut._clean(str(e.input["message"])))
    return e


def split(loc: Located) -> tuple[list, list]:
    """(context, did): the stream's events up to and including the unit's opening turn, then the unit's own."""
    user_text = tr.human_text if loc.kind == "main" else tr._sub_text
    evs = [reported(e) for e in session_cut.events(loc.recs, user_text, tr._ts)]
    opening = next((i for i, e in enumerate(evs) if e.kind == "user" and abs(e.at - loc.start) < 1e-3), None)
    if opening is None:
        cut = next((i for i, e in enumerate(evs) if e.at >= loc.start), len(evs))
        context, rest = evs[:cut], evs[cut:]
    else:
        context, rest = evs[:opening + 1], evs[opening + 1:]
    end = next((i for i, e in enumerate(rest) if e.kind == "user"), len(rest)) if loc.kind == "main" else len(rest)
    return context, rest[:end]


def rel_path(path: str) -> str:
    """A file's path from its repository root when it sits under github/<owner>/<repo>, else its name."""
    m = d._REPO.search(path or "")
    return path[m.end():].lstrip("/") if m else Path(path or "").name


def _read_body(body: str) -> str:
    """A Read tool's output with the cat -n line prefixes taken off."""
    return _CAT_N.sub("", body).rstrip("\n") + "\n"


def edits(context: list, did: list) -> dict:
    """rel path -> {base, post}: each file the unit edited whose whole text an earlier Read showed, before and after
    the unit's own edits; a file whose edit does not apply to that text is left out."""
    bases, out = {}, {}
    calls = {}
    for e in context:
        if e.kind == "call" and e.name == "Read":
            calls[e.ref] = e
        elif e.kind == "result" and e.ref in calls:
            args = calls[e.ref].input or {}
            if not args.get("offset") and not args.get("limit") and "more bytes]" not in e.body:
                bases[str(args.get("file_path") or "")] = _read_body(e.body)
    post, broken = dict(bases), set()
    for e in did:
        if e.kind != "call" or e.name not in ("Edit", "Write", "MultiEdit"):
            continue
        a = e.input or {}
        path = str(a.get("file_path") or "")
        if e.name == "Write":
            post[path] = str(a.get("content") or "")
            continue
        if path not in post:
            broken.add(path)
            continue
        for one in (a.get("edits") or []) if e.name == "MultiEdit" else [a]:
            old, new = str(one.get("old_string") or ""), str(one.get("new_string") or "")
            if not old or old not in post[path]:
                broken.add(path)
                break
            post[path] = post[path].replace(old, new) if one.get("replace_all") else post[path].replace(old, new, 1)
    for path, text in post.items():
        if path in broken or text == bases.get(path):
            continue
        out[rel_path(path)] = {"base": bases.get(path, ""), "post": text}
    return out


def _last_text(did: list) -> str:
    return next((e.body for e in reversed(did) if e.kind == "text"), "")


def quote(text: str) -> str:
    return "\n".join(f"> {line}" if line else ">" for line in text.splitlines())


def _red(text: str, known: redact.Known) -> str:
    return redact.redact(text, known).text


def build(loc: Located, row: dict, known: redact.Known, capped: Counter | None = None) -> dict:
    """One unit's replay packet: the redacted prompt and its hashes, the redacted record of what was done, and the
    files its edits changed."""
    context, did = split(loc)
    last = _last_text(did)
    if capped is not None:
        capped["result"] += len(last.encode("utf-8")) > RESULT_CAP
    raw = HEAD + quote(session_cut.render(context, CONTEXT_BYTES)) + TAIL
    prompt = _red(raw, known)
    files = {}
    for rel, pair in edits(context, did).items():
        both = _red(pair["base"] + "\0" + pair["post"], known).split("\0")
        files[rel] = {"base": both[0], "post": both[-1]}
    group = GROUP.get(row["final"]["shape"], "")
    return {"id": row["id"], "key": row["key"], "kind": row["kind"], "control": row["control"],
            "weight": row.get("weight", 1.0), **{k: row["final"][k] for k in d.LABEL_KEYS},
            "group": group, "lane": LANE.get(group, ""),
            "prompt_sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
            "redacted_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            "prompt": prompt, "reference": _red(session_cut.render(did, REFERENCE_BYTES), known),
            "result": _red(session_cut._cap(last, RESULT_CAP), known), "files": files}


def _texts(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _texts(v)
    elif isinstance(value, list):
        for v in value:
            yield from _texts(v)


def findings(p: dict, known: redact.Known) -> dict:
    """redact.detect over each text a packet holds, its digests left out: JSON escapes and hex digests misread."""
    got = Counter()
    for t in _texts({k: v for k, v in p.items() if not k.endswith("_sha256")}):
        got.update(redact.detect(t, known))
    return dict(got)


def _jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_jsonl(path: Path, rows) -> None:
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


class Appender:
    """Rows appended to a JSONL file one at a time under a lock, so a stopped run resumes where it stopped."""

    def __init__(self, path: Path):
        self.path, self.lock = path, threading.Lock()

    def __call__(self, row: dict) -> None:
        with self.lock, self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def prepare(out: Path, manifest: Path, root: Path, now: float, controls: int = CONTROLS, seed: int = SEED,
            known: redact.Known | None = None) -> dict:
    """Select the units, rebuild each prompt read-only from its transcript, and write packets.jsonl under `out`."""
    d._outside_tree(out)
    known = redact.known_here() if known is None else known
    rows = select(_jsonl(Path(manifest)), controls, seed)
    found = locate(root, [r["key"] for r in rows], now)
    packets, missing, capped = [], [], Counter()
    for r in rows:
        if r["key"] not in found:
            missing.append(r["id"])
            continue
        packets.append(build(found[r["key"]], r, known, capped))
    if capped["result"]:
        from harness import cuts
        cuts.cut("replay_result_cap", "replay packet results cut short", dropped=capped["result"])
    leaks = [p["id"] for p in packets if findings(p, known)]
    if leaks:
        raise ValueError(f"redaction left findings in packets {leaks}")
    out.mkdir(parents=True, exist_ok=True)
    _write_jsonl(out / "packets.jsonl", packets)
    meta = {"now": now, "seed": seed, "controls": controls, "selected": len(rows), "missing": missing}
    (out / "prepared.json").write_text(json.dumps(meta, indent=1) + "\n", encoding="utf-8")
    return meta


def ask_local(lane: str, prompt: str, model: str | None = None, system: str = SYSTEM) -> dict:
    """`model`, or the lane's adopted model, at temperature 0, its reply budget cut to what the served context
    leaves."""
    from harness import completion, context, delegate, methods
    spec, _ = delegate.route(lane, model)
    base = methods.base_of(spec) or spec
    ctx = context.served_ctx(base)
    most = delegate.cap(ctx, prompt, system, count=delegate.counter(base) if ctx else None)
    budget = min(completion.BUDGET.get(lane, completion.MAX_TOKENS), most)
    if budget < 1:
        raise delegate.Refused(f"the prompt fills the {ctx}-token context {base} is served at")
    return delegate.complete(lane, prompt, system=system, max_tokens=budget, temperature=0.0, model=model)


def slug(candidate: str) -> str:
    return re.sub(r"[^\w.-]+", "_", candidate)


def run_local(out: Path, packets: list[dict], repeat: int, ask=None, candidate: str = ADOPTED) -> list[dict]:
    """Replay every packet not yet in replies-<candidate>-<repeat>.jsonl on its lane, served by `candidate` or the
    lane's adopted model; a refusal or failure is its row's error."""
    from harness import completion, delegate
    ask = ask or ask_local
    model = None if candidate == ADOPTED else candidate
    path = out / f"replies-{slug(candidate)}-{repeat}.jsonl"
    done = {r["id"] for r in _jsonl(path)}
    add = Appender(path)
    for p in packets:
        if p["id"] in done:
            continue
        if not p["lane"]:
            add({"id": p["id"], "repeat": repeat, "lane": "", "error": f"no text lane serves shape {p['shape']}"})
            continue
        try:
            got = ask(p["lane"], p["prompt"], model)
            row = {"text": got.get("text") or "", "model": got.get("model"), "spec": got.get("spec"),
                   "seconds": got.get("seconds"), "ttft_s": got.get("ttft_s"),
                   "prompt_tokens": got.get("prompt_tokens"), "completion_tokens": got.get("completion_tokens")}
        except (delegate.Refused, completion.CompletionError) as exc:
            row = {"error": str(exc)[:400], "failure_class": getattr(exc, "failure_class", "refused")}
        add({"id": p["id"], "repeat": repeat, "candidate": candidate, "lane": p["lane"], "temperature": 0.0, **row})
    return _jsonl(path)


def claude(prompt: str, system: str, model: str = JUDGE_MODEL, execute=None, timeout: float | None = None) -> str:
    """One headless `claude -p` answer with no tools, MCP or settings, the prompt on stdin."""
    from evals.runners import claude_code
    execute = execute or claude_code.stream_run
    argv = ["claude", "-p", "--model", model, "--output-format", "json", "--no-session-persistence",
            "--strict-mcp-config", "--setting-sources", "", "--system-prompt", system, "--tools", ""]
    from harness import cuts
    with tempfile.TemporaryDirectory(prefix="lh-replay-judge-") as cwd, \
            cuts.timeout("replay_judge_timeout", "claude -p judge or plant call", value=timeout or JUDGE_TIMEOUT_S):
        proc = execute(argv, cwd=cwd, input=prompt, timeout=timeout or JUDGE_TIMEOUT_S, capture_output=True,
                       text=True, encoding="utf-8")
    body = claude_code.result_of(proc.stdout)
    if body.get("is_error") or proc.returncode:
        raise RuntimeError(f"claude -p: {str(body.get('result'))[:300]}")
    return str(body.get("result") or "")


def judge_prompt(p: dict, candidate: str) -> str:
    return (f"## The session up to the subtask's request\n{p['prompt']}\n\n"
            f"## What the session's assistant actually did\n{p['reference']}\n\n"
            f"## The candidate reply\n{candidate}")


def parse_grade(text: str) -> tuple[str, str]:
    """(grade, reason) from a judge's reply; ValueError when it names no grade."""
    m = _GRADE.search(text or "")
    try:
        body = json.loads(m.group(0)) if m else {}
    except ValueError:
        body = {}
    grade = str(body.get("grade") or "").strip()
    if grade not in GRADES:
        raise ValueError(f"no grade in judge reply: {(text or '')[:120]!r}")
    return grade, " ".join(str(body.get("reason") or "").split())[:300]


def judge(p: dict, candidate: str, ask=None) -> dict:
    """The blind judge's grade of one candidate; asked twice when the first reply names no grade."""
    ask, why = ask or claude, ""
    for _ in range(2):
        try:
            grade, reason = parse_grade(ask(judge_prompt(p, candidate), JUDGE_SYSTEM))
            return {"grade": grade, "reason": reason, "grader": "judge"}
        except (ValueError, RuntimeError, OSError, subprocess.TimeoutExpired) as exc:
            why = str(exc)[:300]
    return {"grade": None, "reason": why, "grader": "judge"}


def corrupt(text: str) -> str | None:
    """`text` with every number moved and every flip word swapped; None when nothing changed."""
    table = {**{a: b for a, b in FLIPS}, **{b: a for a, b in FLIPS}}
    words = re.compile(r"\b(" + "|".join(sorted(map(re.escape, table), key=len, reverse=True)) + r")\b", re.I)

    def flip(m):
        got = table[m.group(1).lower()]
        return got.capitalize() if m.group(1)[:1].isupper() else got

    def move(m):
        v = m.group(0)
        return str(int(v) * 2 + 1) if v.isdigit() else f"{float(v) * 2 + 1:g}"
    out = words.sub(flip, _NUMBER.sub(move, text or ""))
    return out if out != text else None


def plant(kind: str, p: dict, others: list[dict], ask=None) -> str | None:
    """A planted candidate for packet `p`: a wrong answer of `kind`, or SELF (the session's own record)."""
    if kind == SELF:
        return p["reference"]
    if kind == "swap":
        pool = [o for o in others if o["id"] != p["id"] and o["result"].strip() and o["shape"] != p["shape"]] or \
            [o for o in others if o["id"] != p["id"] and o["result"].strip()]
        return random.Random(f"{SEED}:{p['id']}").choice(pool)["result"] if pool else None
    if kind == "corrupt":
        return corrupt(p["result"])
    if kind == "wrong":
        ask = ask or claude
        latest = p["prompt"][-RESULT_CAP:]
        return ask(f"{WRONG_ASK}## The session's latest turns\n{latest}\n\n## What was actually done\n"
                   f"{p['reference']}", WRONG_SYSTEM).strip() or None
    raise ValueError(f"unknown plant {kind!r}")


def _pool(jobs: int, fn, items) -> None:
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, jobs)) as ex:
        for f in [ex.submit(fn, i) for i in items]:
            f.result()


def calibrate(out: Path, packets: list[dict], ask=None, jobs: int = JUDGE_JOBS,
              known: redact.Known | None = None) -> list[dict]:
    """Plant wrong answers (and the session's own record) for every packet and grade each blind; resumable."""
    known = redact.known_here() if known is None else known
    path = out / "calibration.jsonl"
    done = {(r["id"], r["plant"]) for r in _jsonl(path)}
    add = Appender(path)
    todo = [(p, k) for p in packets for k in (*PLANTS, SELF) if (p["id"], k) not in done]

    def one(item):
        p, kind = item
        try:
            text = plant(kind, p, packets, ask)
        except (RuntimeError, OSError, subprocess.TimeoutExpired, ValueError) as exc:
            add({"id": p["id"], "plant": kind, "grade": None, "reason": f"plant: {str(exc)[:200]}"})
            return
        if text is None:
            add({"id": p["id"], "plant": kind, "grade": None, "reason": "nothing to plant", "skipped": True})
            return
        text = _red(text, known)
        add({"id": p["id"], "plant": kind, "candidate_sha256": hashlib.sha256(text.encode()).hexdigest(),
             **judge(p, text, ask)})
    _pool(jobs, one, todo)
    if n := sum(k == "wrong" and len(p["prompt"]) > RESULT_CAP for p, k in todo):
        from harness import cuts
        cuts.cut("replay_result_cap", "session tails a wrong-answer plant was shown", dropped=n)
    return _jsonl(path)


def _apply(files: dict, diff: str) -> dict | None:
    """rel path -> text after `diff` is applied to the base texts of `files` with git apply; None when it fails."""
    from evals import repo
    if not diff.strip():
        return None
    with tempfile.TemporaryDirectory(prefix="lh-replay-check-") as tmp:
        root = Path(tmp)
        subprocess.run(["git", "init", "-q"], cwd=root, check=False, capture_output=True)
        for rel, pair in files.items():
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_text(pair["base"], encoding="utf-8")
        headed = repo.with_git_headers(diff, lambda rel: (root / rel).exists())
        got = subprocess.run(["git", "apply", "--recount", "--whitespace=nowarn", "-"], cwd=root,
                             input=headed.encode("utf-8"), capture_output=True, check=False)
        if got.returncode:
            return None
        return {rel: (root / rel).read_text(encoding="utf-8") if (root / rel).exists() else "" for rel in files}


def _same(a: str, b: str) -> bool:
    return [x.rstrip() for x in a.strip().splitlines()] == [x.rstrip() for x in b.strip().splitlines()]


def check(p: dict, reply: str) -> dict | None:
    """A command's grade where the unit's outcome is checkable: a reply whose diff git-applies to the files the unit
    edited and leaves each as the unit did is usable as is; None leaves the grade to the judge."""
    from evals import repo
    if not p.get("files"):
        return None
    after = _apply(p["files"], repo.extract_diff(reply))
    if after is None:
        return None
    if all(_same(after[rel], pair["post"]) for rel, pair in p["files"].items()):
        return {"grade": "usable_as_is", "reason": "the diff applies and leaves every edited file as the session did",
                "grader": "check"}
    return None


def grade(out: Path, packets: list[dict], repeat: int, ask=None, jobs: int = JUDGE_JOBS,
          candidate: str = ADOPTED) -> list[dict]:
    """Grade every reply of `candidate`'s `repeat` not yet graded: a failed reply not usable, then a check where one
    applies, else the blind judge."""
    by = {p["id"]: p for p in packets}
    path = out / f"grades-{slug(candidate)}-{repeat}.jsonl"
    done = {r["id"] for r in _jsonl(path)}
    add = Appender(path)
    replies = [r for r in _jsonl(out / f"replies-{slug(candidate)}-{repeat}.jsonl")
               if r["id"] in by and r["id"] not in done]

    def one(r):
        p = by[r["id"]]
        if r.get("error") or not str(r.get("text") or "").strip():
            got = {"grade": "not_usable", "reason": r.get("error") or "empty reply", "grader": "error"}
        else:
            got = check(p, r["text"]) or judge(p, r["text"], ask)
        add({"id": r["id"], "repeat": repeat, "candidate": candidate, **got})
    _pool(jobs, one, replies)
    return _jsonl(path)


def _pctl(values, q: float):
    """Nearest-rank percentile; None for no values."""
    vals = sorted(v for v in values if v is not None)
    return vals[max(0, math.ceil(q * len(vals)) - 1)] if vals else None


def _rate(k: int, n: int) -> dict:
    lo, hi = intervals.wilson(k, n)
    return {"k": k, "n": n, "rate": round(k / n, 4) if n else None, "ci": [lo, hi]}


def calibration_summary(rows: list[dict]) -> dict:
    """Planted wrong answers the judge graded not_usable, by plant and pooled, and the session's own record
    accepted; skipped and ungraded plants are counted apart."""
    graded = [r for r in rows if r.get("grade")]
    out = {}
    for kind in (*PLANTS, SELF):
        mine = [r for r in graded if r["plant"] == kind]
        hit = sum(r["grade"] == "not_usable" for r in mine) if kind != SELF else \
            sum(r["grade"] != "not_usable" for r in mine)
        out[kind] = _rate(hit, len(mine))
    wrong = [r for r in graded if r["plant"] in PLANTS]
    out["planted"] = _rate(sum(r["grade"] == "not_usable" for r in wrong), len(wrong))
    out["skipped"] = sum(1 for r in rows if r.get("skipped"))
    out["ungraded"] = sum(1 for r in rows if not r.get("grade") and not r.get("skipped"))
    out["passes"] = bool(wrong) and out["planted"]["rate"] >= REJECT_MIN
    return out


def _cell(rows: list[dict]) -> dict:
    n = len(rows)
    as_is = sum(r["grade"] == "usable_as_is" for r in rows)
    usable = sum(r["grade"] in ("usable_as_is", "usable_with_edits") for r in rows)
    secs = [r.get("seconds") for r in rows]
    return {"n": n, "as_is": _rate(as_is, n), "usable": _rate(usable, n), "p50_s": _pctl(secs, 0.5),
            "p90_s": _pctl(secs, 0.9), "gpu_s": round(sum(s for s in secs if s), 1),
            "graders": dict(sorted(Counter(str(r.get("grader")) for r in rows).items()))}


def report(packets: list[dict], replies: dict, grades: dict, calibration: list[dict], meta: dict | None = None,
           candidate: str = ADOPTED) -> dict:
    """One candidate's per shape x lane usable rates with Wilson intervals, latency, GPU seconds and correct answers per GPU-hour
    for the fitting units; the control's rate; agreement between repeats; the judge's calibration."""
    by = {p["id"]: p for p in packets}
    joined = {}
    for rep, rows in grades.items():
        secs = {r["id"]: r for r in replies.get(rep, [])}
        joined[rep] = [{**by[g["id"]], **{k: secs.get(g["id"], {}).get(k) for k in ("seconds", "model", "spec")},
                        **g} for g in rows if g["id"] in by and g.get("grade")]
    first = joined.get(min(joined), []) if joined else []
    fit = [r for r in first if not r["control"]]
    cells = defaultdict(list)
    for r in fit:
        cells[(r["shape"], r["lane"])].append(r)
    weighted = sum(r["weight"] for r in fit)
    out = {"meta": meta or {}, "candidate": candidate, "units": len(packets), "fit_units": sum(not p["control"] for p in packets),
           "control_units": sum(p["control"] for p in packets),
           "cells": {f"{s} x {lane}": _cell(rows) for (s, lane), rows in sorted(cells.items())},
           "fit": _cell(fit), "control": _cell([r for r in first if r["control"]]),
           "weighted_as_is": round(sum(r["weight"] for r in fit if r["grade"] == "usable_as_is") / weighted, 4)
           if weighted else None,
           "models": dict(Counter(r.get("model") or r.get("spec") or "" for r in first)),
           "calibration": calibration_summary(calibration)}
    accepted = {r["id"] for r in calibration if r.get("plant") == SELF and r.get("grade") in GRADES[:2]}
    out["reachable"] = _cell([r for r in fit if r["id"] in accepted]) if accepted else None
    hours = out["fit"]["gpu_s"] / 3600
    out["per_gpu_hour"] = {"as_is": round(out["fit"]["as_is"]["k"] / hours, 1) if hours else None,
                           "usable": round(out["fit"]["usable"]["k"] / hours, 1) if hours else None,
                           "gpu_hours": round(hours, 3)}
    reps = sorted(joined)
    if len(reps) >= 2:
        a, b = ({r["id"]: r["grade"] for r in joined[k]} for k in reps[:2])
        both = sorted(set(a) & set(b))
        out["agreement"] = {**_rate(sum(a[i] == b[i] for i in both), len(both)), "repeats": reps[:2]}
        out["agreement"]["passes"] = bool(both) and out["agreement"]["rate"] >= AGREE_MIN
    c = out["control"]
    out["control_near_zero"] = c["n"] > 0 and c["as_is"]["rate"] <= CONTROL_MAX
    return out


def _r(x: dict) -> str:
    if not x["n"]:
        return "0/0"
    return f"{x['k']}/{x['n']} {100 * x['rate']:.0f}% [{100 * x['ci'][0]:.0f}, {100 * x['ci'][1]:.0f}]"


def _s(v) -> str:
    return "-" if v is None else f"{v:.1f}s"


def text(got: dict, head: bool = True) -> str:
    """One candidate's replay report as plain text, led by the judge's calibration when `head`."""
    m, cal = got["meta"], got["calibration"]
    out = [] if not head else [f"shadow replay (#1161): {got['units']} units, {got['fit_units']} fitting and {got['control_units']} "
           f"does-not-fit controls; missing from the transcripts {len(m.get('missing', []))}",
           f"judge calibration ({JUDGE_MODEL}, blind): planted wrong answers rejected {_r(cal['planted'])} "
           f"(needs {100 * REJECT_MIN:.0f}%: {'PASS' if cal['passes'] else 'FAIL'})",
           "  " + ", ".join(f"{k} {_r(cal[k])}" for k in PLANTS)
           + f"; the session's own record accepted {_r(cal[SELF])}; skipped {cal['skipped']}, ungraded "
             f"{cal['ungraded']}"]
    out += ["", f"candidate {got['candidate']}"]
    if got["fit"]["n"]:
        out += ["fitting units, first replay: shape x lane, n, usable as is, usable with edits too "
                    "(95% Wilson), latency p50 p90, GPU seconds"]
        for name, c in got["cells"].items():
            out.append(f"  {name:<32} {c['n']:>3}  as is {_r(c['as_is'])}  usable {_r(c['usable'])}  "
                       f"{_s(c['p50_s'])} {_s(c['p90_s'])}  {c['gpu_s']}s")
        f, c, h = got["fit"], got["control"], got["per_gpu_hour"]
        out += [f"  all fitting {f['n']}: as is {_r(f['as_is'])}, usable {_r(f['usable'])}; census-weighted as is "
                f"{got['weighted_as_is']}; graded by {f['graders']}",
                *([f"  the {got['reachable']['n']} whose own record the judge accepts: as is "
                   f"{_r(got['reachable']['as_is'])}, usable {_r(got['reachable']['usable'])}"]
                  if got.get("reachable") else []),
                f"  correct answers per GPU-hour: as is {h['as_is']}, usable {h['usable']} over {h['gpu_hours']} h",
                f"control (does not fit): {c['n']} units, as is {_r(c['as_is'])}, usable {_r(c['usable'])} "
                f"(near zero at as is <= {100 * CONTROL_MAX:.0f}%: {'PASS' if got['control_near_zero'] else 'FAIL'})",
                f"models: {got['models']}"]
    if "agreement" in got:
        a = got["agreement"]
        out.append(f"replays {a['repeats'][0]} and {a['repeats'][1]} grade alike on {_r(a)} "
                   f"(needs {100 * AGREE_MIN:.0f}%: {'PASS' if a['passes'] else 'FAIL'})")
    return "\n".join(out) + "\n"


def text_all(reports: list[dict]) -> str:
    """Every candidate's report, the calibration said once."""
    return "".join(text(r, head=not i) for i, r in enumerate(reports))


STEPS = ("prepare", "calibrate", "local", "grade", "report")


def load(out: Path) -> tuple[list[dict], dict]:
    path = out / "packets.jsonl"
    if not path.exists():
        raise ValueError(f"no packets at {path}; run the prepare step first")
    meta = json.loads((out / "prepared.json").read_text(encoding="utf-8")) if (out / "prepared.json").exists() else {}
    return _jsonl(path), meta


def results(out: Path, repeats: int, candidate: str = ADOPTED) -> tuple[dict, dict]:
    reps, s = range(1, repeats + 1), slug(candidate)
    return ({r: _jsonl(out / f"replies-{s}-{r}.jsonl") for r in reps},
            {r: g for r in reps if (g := _jsonl(out / f"grades-{s}-{r}.jsonl"))})
