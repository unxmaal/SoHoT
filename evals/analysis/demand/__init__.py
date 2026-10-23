"""Demand census: Claude Code subtasks by task shape, local fit and latency tolerance, from a blind-labelled sample. #1151."""
from __future__ import annotations

import hashlib
import json
import random
import re
import time
from collections import Counter, defaultdict
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from evals import redact, session_cut
from evals.fairness import kappa as _cohen
from evals.importers import transcripts as tr

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DAYS = 14
SEED = 1151
SAMPLE = 120
#: A gap between records longer than this is idle time, not work.
IDLE_GAP_S = 600
#: Output-token edges of the size strata: small below the first, large at or above the second.
SIZE_EDGES = (2000, 20000)
#: Projects kept by name in the strata; the rest pool as "other".
TOP_PROJECTS = 4
FLOOR = 1
#: Final-count messages the output model needs before it estimates the partial ones.
MIN_FINAL = 20
#: Seconds past a cost-state record's covered span a message may start and still be counted against it.
COST_SLACK_S = 5
BOOTSTRAP = 2000
REQUEST_CAP = 1500
RESULT_CAP = 600
STEP_CAP = 100
STEPS = 15

SHAPES = {
    "extract_classify": "pull fields, facts or a label out of given text or data; the answer is short and checkable",
    "summarise_digest": "condense logs, a thread, a diff, issues or a document into a shorter account",
    "triage_decide": "pick among a few options, rank, judge or approve; the output is a decision with a reason",
    "draft_prose": "write prose for people: an issue, PR body, README section, message, report",
    "small_code_edit": "change code or config in one file, or a few lines across two, with the target known",
    "multi_file_code": "implement or fix across several files: a feature, a migration, a refactor, with tests",
    "investigation_debug": "find out why or where: read code and logs, run commands, measure; the output is a finding",
    "orchestration_chat": "steer other agents, merge, coordinate, or talk with the person; little work of its own",
    "media": "make or edit an image, video, audio, SVG or other non-text artifact",
}
FITS = {
    "fits_now": "a local model on the Studio could do this today through an existing lane, at a quality the person "
                "would keep",
    "fits_with_harness_work": "a local model could do it if the harness gained something specific (tools, a lane, "
                              "a bigger context, a checker, retrieval); name it in the reason",
    "does_not_fit": "needs frontier-model judgment, long multi-step tool use over a large repo, or knowledge a local "
                    "model lacks",
}
LATENCIES = {
    "interactive": "the person sits waiting for this reply before typing again: it must come back in under 30 seconds",
    "soon": "the person wants it in this sitting, their next step uses it: minutes are fine, under 10",
    "queued": "the person would be as well served hours later: an overnight batch, a measurement, a PR or report "
              "reviewed in a later sitting",
}
#: Who waits is the person: a parent agent waiting on a subagent waits only as long as the person waits on the parent.
LATENCY_RULE = ("Judge latency by the person, not by an agent. minutes_to_next_request says how long the person took "
                "to type again after this subtask ended (null when they never did in the window). Between soon and "
                "queued: if the person acted on the result in the same sitting, soon; if it only matters in a later "
                "sitting, queued.")
#: What a labeller is told the local side can do, so "fits" means the same to both.
LOCAL = ("The Studio is a Mac Studio (Apple Silicon, 96 GB). Its adopted text models: Ornith-1.5-35B (a 35B MoE "
         "coder, 4-bit) for the code and agent lanes, about 145 tok/s on one request and 4 parallel slots of 262k "
         "context; 4B to 30B models for decide, extract, web and svg; local image, music and speech models. The "
         "harness serves one-shot lanes (code, web, svg, extract, decide) and a limited agent lane with tool calls. "
         "Ornith passes about 86% of self-contained function problems but 2 to 5 of 39 real multi-file fixes from "
         "this project's history, where Opus passes 12 of 41.")
LABEL_KEYS = ("shape", "fit", "latency")
CLOSED = {"shape": SHAPES, "fit": FITS, "latency": LATENCIES}
CANDIDATES = ("media", "orchestration", "multi_file", "small_edit", "investigate", "chat")
_MEDIA = re.compile(r"(?i)image|video|svg|music|tts|speech|audio")
_SPAWN = ("Agent", "Task")
MEDIA_FILES = (".svg", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".wav", ".mp3", ".flac", ".mp4", ".mov")
_REPO = re.compile(r"/github/([^/\s'\"]+)/([^/\s'\"]+)")
_WORKTREE = re.compile(r"-\d+[a-z]?(?:-[\w.]+)?$")
_PATH_KEYS = ("file_path", "path", "notebook_path")


@dataclass
class Unit:
    key: str
    kind: str
    session: str
    stream: str
    start: float
    end: float = 0.0
    active_s: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    tokens_out_recorded: int = 0
    messages: list = field(default_factory=list)
    calls: int = 0
    tools: Counter = field(default_factory=Counter)
    read: set = field(default_factory=set)
    edited: set = field(default_factory=set)
    repos: Counter = field(default_factory=Counter)
    request: str = ""
    result: str = ""
    steps: list = field(default_factory=list)
    project: str = "none"
    repo: str = ""
    next_request_s: float | None = None
    candidate: str = "chat"
    size: str = "S"

    @property
    def stratum(self) -> str:
        return f"{self.project}/{self.candidate}/{self.size}"


def unit_key(session: str, stream: str, start: float) -> str:
    return hashlib.sha256(f"{session}\0{stream}\0{start:.3f}".encode()).hexdigest()[:16]


def repo_of(path: str) -> str | None:
    """owner/repo of a path under github/<owner>/<repo>, a worktree folded into its repo."""
    m = _REPO.search(path or "")
    return f"{m.group(1)}/{_WORKTREE.sub('', m.group(2))}" if m else None


@dataclass
class Msg:
    """One API message: input tokens, the output tokens its records carry, whether one carries the final count (a
    stop_reason), the characters of its visible text and tool input, the characters of its thinking signatures."""
    tokens_in: int = 0
    out: int = 0
    final: bool = False
    visible: int = 0
    signature: int = 0
    at: float = 0.0


def _usage(recs, skip=frozenset()) -> dict:
    """message id -> Msg over every record of that message; `skip` ids are counted in another stream."""
    got: dict = {}
    for rec in recs:
        msg = rec.get("message")
        if rec.get("type") != "assistant" or not isinstance(msg, dict) or not isinstance(msg.get("usage"), dict):
            continue
        mid = msg.get("id") or rec.get("uuid")
        if mid in skip:
            continue
        u, m = msg["usage"], got.setdefault(mid, Msg(at=tr._ts(rec.get("timestamp"))))
        m.tokens_in = max(m.tokens_in, sum(int(u.get(k) or 0) for k in
                                           ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")))
        m.out = max(m.out, int(u.get("output_tokens") or 0))
        m.final = m.final or bool(msg.get("stop_reason"))
        for b in msg.get("content") or []:
            if isinstance(b, dict):
                m.visible += len(b.get("text") or "") if b.get("type") == "text" else \
                    len(json.dumps(b.get("input"), ensure_ascii=False)) if b.get("type") == "tool_use" else 0
                m.signature += len(b.get("signature") or "") if b.get("type") == "thinking" else 0
    return got


def _solve(rows: list[Msg]) -> tuple[float, float, float]:
    """Least-squares (per visible char, per signature char, intercept) for output tokens over `rows`."""
    xs = [(m.visible, m.signature, 1.0) for m in rows]
    a = [[sum(x[i] * x[j] for x in xs) for j in range(3)] + [sum(x[i] * m.out for x, m in zip(xs, rows))]
         for i in range(3)]
    for i in range(3):
        piv = max(range(i, 3), key=lambda r: abs(a[r][i]))
        a[i], a[piv] = a[piv], a[i]
        if not a[i][i]:
            return (0.0, 0.0, 0.0)
        a[i] = [v / a[i][i] for v in a[i]]
        for r in range(3):
            if r != i:
                a[r] = [v - a[r][i] * w for v, w in zip(a[r], a[i])]
    return (a[0][3], a[1][3], a[2][3])


def output_model(messages: list[Msg], seed: int = SEED) -> dict:
    """Fit output tokens on the messages whose records carry the final count, check it on a held-out half, and
    return the coefficients fitted on all of them. Claude Code often writes a message's records before its final
    usage arrives, so a message with no stop_reason carries a partial count."""
    final = [m for m in messages if m.final]
    out = {"final": len(final), "partial": len(messages) - len(final), "coef": (0.0, 0.0, 0.0)}
    if len(final) < MIN_FINAL:
        return out
    shuffled = random.Random(seed).sample(final, len(final))
    train, test = shuffled[: len(final) // 2], shuffled[len(final) // 2:]
    c = _solve(train)
    pred = [c[0] * m.visible + c[1] * m.signature + c[2] for m in test]
    mean = sum(m.out for m in test) / len(test)
    ss = sum((p - m.out) ** 2 for p, m in zip(pred, test))
    st = sum((m.out - mean) ** 2 for m in test) or 1.0
    out.update(coef=tuple(round(v, 4) for v in _solve(final)), held_out_r2=round(1 - ss / st, 3),
               held_out_ratio=round(sum(pred) / (sum(m.out for m in test) or 1), 3))
    return out


def estimated(m: Msg, coef) -> int:
    """A message's output tokens: its own count when final, else the larger of that and the fitted estimate."""
    return m.out if m.final else max(m.out, round(coef[0] * m.visible + coef[1] * m.signature + coef[2]))


def _tool(name: str) -> str:
    """mcp__server__tool as mcp:server.tool; a built-in tool as itself."""
    parts = name.split("__")
    return f"mcp:{parts[1]}.{'__'.join(parts[2:])}" if name.startswith("mcp__") and len(parts) >= 3 else name


def _step(name: str, args: dict) -> str:
    if name == "Bash":
        arg = str(args.get("command") or "")
    elif any(k in args for k in _PATH_KEYS):
        arg = Path(str(next(args[k] for k in _PATH_KEYS if k in args))).name
    else:
        arg = str(args.get("description") or args.get("pattern") or args.get("query") or args.get("url") or "")
    return f"{name}: {' '.join(arg.split())}"[:STEP_CAP]


def _add(unit: Unit, rec: dict, usage: dict, counted: set) -> None:
    """Fold one record into `unit`: its time, tokens (once per message), tool calls and the paths they name."""
    at = tr._ts(rec.get("timestamp"))
    if at:
        if unit.end and at - unit.end > 0:
            unit.active_s += min(at - unit.end, IDLE_GAP_S)
        unit.end = max(unit.end, at)
    if rec.get("cwd") and (r := repo_of(str(rec["cwd"]))):
        unit.repos[r] += 1
    msg = rec.get("message")
    if rec.get("type") != "assistant" or not isinstance(msg, dict):
        return
    mid = msg.get("id") or rec.get("uuid")
    if mid not in usage:
        return
    if mid not in counted:
        counted.add(mid)
        unit.messages.append(usage[mid])
        unit.tokens_in += usage[mid].tokens_in
        unit.tokens_out_recorded += usage[mid].out
    for b in msg.get("content") or []:
        if not isinstance(b, dict):
            continue
        if b.get("type") == "text" and session_cut._clean(b.get("text")):
            unit.result = session_cut._clean(b.get("text"))
        elif b.get("type") == "tool_use":
            name, args = str(b.get("name") or ""), dict(b.get("input") or {})
            unit.calls += 1
            unit.tools[_tool(name)] += 1
            if len(unit.steps) < STEPS:
                unit.steps.append(_step(name, args))
            for k in _PATH_KEYS:
                if isinstance(args.get(k), str):
                    if r := repo_of(args[k]):
                        unit.repos[r] += 3
                    (unit.edited if name in session_cut.EDITS else unit.read if name in session_cut.READS
                     else set()).add(args[k])
            if name == "Bash" and (r := repo_of(str(args.get("command") or ""))):
                unit.repos[r] += 1


def _began(recs) -> float:
    """When a subagent began: its first user turn (the spawn prompt), not a copied parent message before it."""
    times = [tr._ts(r.get("timestamp")) for r in recs if r.get("type") == "user"] or \
        [tr._ts(r.get("timestamp")) for r in recs]
    return next((t for t in times if t), 0.0)


def _headless(recs) -> bool:
    return any(str(r.get("entrypoint") or "").startswith("sdk-") for r in recs[:50])


def scan(root: Path | None = None, now: float | None = None, days: int = DAYS) -> tuple[list[Unit], dict]:
    """(units, facts): every main-loop stretch between typed requests and every subagent run that starts in the window,
    and facts {skipped, output_model, cost_check}; a record after `now` is ignored so a fixed `now` re-reads the same
    population."""
    root = Path(root or tr.default_root())
    now = time.time() if now is None else now
    since = now - days * 86400
    units, skipped, states = [], Counter(), []
    for _project, main, subs in tr.sessions(root):
        if main.stat().st_mtime < since:
            skipped["stale_file"] += 1
            continue
        recs = [r for r in tr.records(main) if tr._ts(r.get("timestamp")) <= now]
        if _headless(recs):
            skipped["headless_session"] += 1
            continue
        session = main.stem
        sub_recs = {s: [r for r in tr.records(s) if tr._ts(r.get("timestamp")) <= now] for s in subs}
        sub_recs = dict(sorted(sub_recs.items(), key=lambda kv: (_began(kv[1]), kv[0].stem)))
        usage, counted, cur = _usage([r for r in recs if not r.get("isSidechain")]), set(), None
        # A forked subagent's file repeats the message that spawned it: a message counts in the first stream.
        claimed, sub_usage = set(usage), {}
        for s, rs in sub_recs.items():
            sub_usage[s] = _usage(rs, claimed)
            claimed |= set(sub_usage[s])
        mine = []
        if cost := [r for r in recs if r.get("type") == "cost-state"]:
            states.append((session, cost[-1], [m for u in [usage, *sub_usage.values()] for m in u.values()]))
        for rec in recs:
            if rec.get("isSidechain"):
                continue
            text = tr.human_text(rec)
            at = tr._ts(rec.get("timestamp"))
            if text is not None and at:
                cur = Unit(unit_key(session, "main", at), "main", session, "main", at, end=at,
                           request=session_cut._clean(text))
                mine.append(cur)
            elif cur is None and at and rec.get("type") in ("user", "assistant"):
                cur = Unit(unit_key(session, "main", at), "main", session, "main", at, end=at)
                mine.append(cur)
            if cur is not None:
                _add(cur, rec, usage, counted)
        for s, rs in sub_recs.items():
            if not (began := _began(rs)):
                continue
            u = Unit(unit_key(session, s.stem, began), "subagent", session, s.stem, began, end=began)
            u.request = next((session_cut._clean(t) for r in rs if (t := tr._sub_text(r))), "")
            sc: set = set()
            for rec in rs:
                _add(u, rec, sub_usage[s], sc)
            mine.append(u)
        typed = sorted(u.start for u in mine if u.kind == "main" and u.request)
        for u in mine:
            u.next_request_s = next((t - u.end for t in typed if t >= u.end), None)
            if u.start < since:
                skipped["before_window"] += 1
            elif u.tokens_out_recorded or u.calls:
                units.append(u)
            else:
                skipped["no_model_turn"] += 1
    model = output_model([m for u in units for m in u.messages])
    for u in units:
        u.tokens_out = sum(estimated(m, model["coef"]) for m in u.messages)
    _classify(units)
    facts = {"skipped": dict(sorted(skipped.items())), "output_model": model,
             "cost_check": [cost_check(s, st, ms, model["coef"]) for s, st, ms in states]}
    return sorted(units, key=lambda u: (u.start, u.key)), facts


def cost_check(session: str, state: dict, messages: list[Msg], coef) -> dict:
    """A session's own output-token total (its last cost-state record) beside the recorded and estimated sums of the
    messages in the span that record covers."""
    t0 = float(state.get("startTime") or 0) / 1000
    t1 = t0 + float(state.get("totalDuration") or 0) / 1000
    inside = [m for m in messages if t0 <= m.at <= t1 + COST_SLACK_S]
    return {"session": hashlib.sha256(session.encode()).hexdigest()[:12],
            "cost_state": sum(int(u.get("outputTokens") or 0) for u in (state.get("modelUsage") or {}).values()),
            "recorded": sum(m.out for m in inside), "estimated": sum(estimated(m, coef) for m in inside),
            "messages": len(inside)}


def candidate(u: Unit) -> str:
    """A shape guessed from tool use alone, for stratifying the draw; the labels, not this, are the result."""
    if any(t.startswith("mcp:") and _MEDIA.search(t.split(".", 1)[-1]) for t in u.tools) or \
            any(Path(f).suffix.lower() in MEDIA_FILES for f in u.edited):
        return "media"
    if sum(u.tools[t] for t in _SPAWN):
        return "orchestration"
    if len(u.edited) >= 2:
        return "multi_file"
    if u.edited:
        return "small_edit"
    return "investigate" if u.calls else "chat"


def size_of(tokens_out: int) -> str:
    return "S" if tokens_out < SIZE_EDGES[0] else "M" if tokens_out < SIZE_EDGES[1] else "L"


def _classify(units: list[Unit]) -> None:
    volume = Counter()
    for u in units:
        u.repo = u.repos.most_common(1)[0][0] if u.repos else ""
        volume[u.repo] += u.tokens_out_recorded
    keep = set(sorted((r for r in volume if r), key=lambda r: (-volume[r], r))[:TOP_PROJECTS])
    for u in units:
        u.project = u.repo.split("/", 1)[1] if u.repo in keep else "other"
        u.candidate, u.size = candidate(u), size_of(u.tokens_out_recorded)


def allocate(strata: dict, total: int = SAMPLE, floor: int = FLOOR) -> dict:
    """Draws per stratum: `floor` each (or all), the rest in proportion to the stratum's output tokens by largest
    remainder, never more than the stratum holds. `strata` is name -> (units, output tokens)."""
    got = {s: min(floor, n) for s, (n, _) in strata.items()}
    while (spare := total - sum(got.values())) > 0:
        room = {s: strata[s][0] - got[s] for s in strata if got[s] < strata[s][0]}
        if not room:
            break
        mass = {s: strata[s][1] or 1 for s in room}
        share = {s: spare * mass[s] / sum(mass.values()) for s in room}
        add = {s: min(int(share[s]), room[s]) for s in room}
        for s in sorted(room, key=lambda s: (-(share[s] - int(share[s])), s)):
            if sum(add.values()) < spare and add[s] < room[s]:
                add[s] += 1
        for s, k in add.items():
            got[s] += k
    return got


def draw(units: list[Unit], n: int = SAMPLE, seed: int = SEED, floor: int = FLOOR) -> tuple[list[Unit], dict]:
    """(sample, strata) where strata is name -> {N, n, tokens_out, tokens_in, active_s}; a seeded draw within each."""
    by = defaultdict(list)
    for u in units:
        by[u.stratum].append(u)
    sizes = {s: (len(v), sum(u.tokens_out_recorded for u in v)) for s, v in sorted(by.items())}
    take = allocate(sizes, n, floor)
    rng = random.Random(seed)
    picked, strata = [], {}
    for s in sorted(by):
        group = sorted(by[s], key=lambda u: u.key)
        chosen = rng.sample(group, take[s])
        picked += chosen
        strata[s] = {"N": len(group), "n": take[s], "fraction": round(take[s] / len(group), 4),
                     "tokens_out": sum(u.tokens_out for u in group), "tokens_in": sum(u.tokens_in for u in group),
                     "tokens_out_recorded": sum(u.tokens_out_recorded for u in group),
                     "active_s": round(sum(u.active_s for u in group), 1)}
    order = random.Random(seed + 1).sample(picked, len(picked))
    return order, strata


def _cap(text: str, n: int) -> str:
    return text if len(text) <= n else text[:n] + f" [... {len(text) - n} more chars]"


def packet(u: Unit, pid: str, known: redact.Known) -> dict:
    """What a blind labeller sees of one unit: sizes, tool counts and redacted, capped text."""
    def red(text: str, cap: int) -> str:
        return redact.redact(_cap(text, cap), known).text
    return {"id": pid, "kind": u.kind, "project": u.project, "tokens_in": u.tokens_in, "tokens_out": u.tokens_out,
            "active_minutes": round(u.active_s / 60, 1),
            "minutes_to_next_request": None if u.next_request_s is None else round(u.next_request_s / 60, 1),
            "tool_calls": u.calls, "tools": dict(u.tools.most_common()),
            "files_read": len(u.read), "files_edited": len(u.edited),
            "edited_types": sorted({Path(f).suffix or Path(f).name for f in u.edited}),
            "request": red(u.request, REQUEST_CAP), "steps": [red(s, STEP_CAP) for s in u.steps],
            "result": red(u.result, RESULT_CAP)}


def _outside_tree(out: Path) -> None:
    """Packets hold redacted transcript text: refuse a directory git would track."""
    out = Path(out).resolve()
    if out.is_relative_to(ROOT) and subprocess.run(["git", "-C", str(ROOT), "check-ignore", "-q", str(out)]).returncode:
        raise ValueError(f"{out} is in the tracked tree; put packets under an ignored tmp/")


def census(out: Path, root: Path | None = None, now: float | None = None, days: int = DAYS, n: int = SAMPLE,
           seed: int = SEED, known: redact.Known | None = None) -> dict:
    """Scan, draw, and write frame.json and the labellers' packets (A in draw order, B reversed) under `out`."""
    _outside_tree(out)
    now = time.time() if now is None else now
    units, facts = scan(root, now, days)
    sample, strata = draw(units, n, seed)
    known = redact.known_here() if known is None else known
    out.mkdir(parents=True, exist_ok=True)
    rows = [packet(u, f"P{i + 1:03d}", known) for i, u in enumerate(sample)]
    leaks = [r["id"] for r in rows if redact.detect(json.dumps(r, ensure_ascii=False), known)]
    if leaks:
        raise ValueError(f"redaction left findings in packets {leaks}")
    for name, seq in (("packets-a.jsonl", rows), ("packets-b.jsonl", rows[::-1])):
        (out / name).write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in seq), encoding="utf-8")
    frame = {"now": now, "days": days, "seed": seed, "n": len(sample), "population": len(units), **facts,
             "repos": dict(sorted({u.project: u.repo for u in units if u.project != "other"}.items())),
             "totals": {"tokens_out": sum(u.tokens_out for u in units), "tokens_in": sum(u.tokens_in for u in units),
                        "tokens_out_recorded": sum(u.tokens_out_recorded for u in units),
                        "active_s": round(sum(u.active_s for u in units), 1),
                        "kinds": dict(Counter(u.kind for u in units))},
             "strata": strata,
             "sample": [{"id": f"P{i + 1:03d}", "key": u.key, "kind": u.kind, "stratum": u.stratum,
                         "tokens_in": u.tokens_in, "tokens_out": u.tokens_out,
                         "tokens_out_recorded": u.tokens_out_recorded, "active_s": round(u.active_s, 1),
                         "tool_calls": u.calls, "files_edited": len(u.edited)} for i, u in enumerate(sample)]}
    (out / "frame.json").write_text(json.dumps(frame, indent=1) + "\n", encoding="utf-8")
    return frame


def load_labels(path: Path, partial: bool = False) -> dict:
    """id -> label row; a value off a closed set, a missing key (unless `partial`) or a repeated id is refused."""
    got = {}
    for i, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        for k in LABEL_KEYS:
            if (k in row or not partial) and row.get(k) not in CLOSED[k]:
                raise ValueError(f"{path}:{i}: {k} {row.get(k)!r} is not one of {', '.join(CLOSED[k])}")
        if row.get("id") in got:
            raise ValueError(f"{path}:{i}: {row.get('id')} labelled twice")
        got[row["id"]] = row
    return got


def load_rounds(paths) -> dict:
    """One labeller's labels over rounds: the first file whole, each later one (a relabel of some keys under refined
    definitions) overriding the keys it carries."""
    got = load_labels(Path(paths[0]))
    for p in paths[1:]:
        for pid, row in load_labels(Path(p), partial=True).items():
            if pid not in got:
                raise ValueError(f"{p}: {pid} is not in {paths[0]}")
            got[pid] = {**got[pid], **{k: v for k, v in row.items() if k != "id"}}
    return got


def kappa_ci(a: list, b: list, seed: int = SEED, reps: int = BOOTSTRAP) -> tuple[float | None, float, float]:
    """(Cohen's kappa, 95% bootstrap lo, hi) over paired labels."""
    k = _cohen(a, b)
    rng, n, got = random.Random(seed), len(a), []
    for _ in range(reps):
        idx = [rng.randrange(n) for _ in range(n)]
        v = _cohen([a[i] for i in idx], [b[i] for i in idx])
        got.append(1.0 if v is None else v)
    got.sort()
    return (None if k is None else round(k, 3)), round(got[int(0.025 * reps)], 3), round(got[int(0.975 * reps) - 1], 3)


def final_labels(a: dict, b: dict, settled: dict | None = None) -> dict:
    """id -> {shape, fit, latency, settled}: agreed values, a settled value where they differ, else A's."""
    out = {}
    for pid in sorted(set(a) & set(b)):
        row, s = {}, (settled or {}).get(pid, {})
        for k in LABEL_KEYS:
            row[k] = a[pid][k] if a[pid][k] == b[pid][k] else s.get(k, a[pid][k])
        row["settled"] = any(a[pid][k] != b[pid][k] for k in LABEL_KEYS) and bool(s)
        out[pid] = row
    return out


def _value(r: dict, measure: str) -> float:
    return 1 if measure == "count" else r[measure]


def _total(v: dict, measure: str) -> float:
    return v["N"] if measure == "count" else v[measure]


def estimate(sample: list[dict], strata: dict, labels: dict, cell, measure: str) -> float:
    """Population share of `measure` in units whose labels satisfy `cell`: within each stratum the sampled ratio,
    weighted by the stratum's known total (separate ratio estimator); `measure` "count" weights each unit 1."""
    num, den = defaultdict(float), defaultdict(float)
    for r in sample:
        x = _value(r, measure)
        den[r["stratum"]] += x
        if cell(labels[r["id"]]):
            num[r["stratum"]] += x
    total = sum(_total(strata[s], measure) for s in den)
    return sum(_total(strata[s], measure) * num[s] / den[s] for s in den if den[s]) / total if total else 0.0


def boot_ci(sample: list[dict], strata: dict, labels: dict, cell, measure: str, seed: int = SEED,
            reps: int = BOOTSTRAP // 4) -> list[float]:
    """95% stratified bootstrap interval of `estimate`: each stratum's sampled units resampled with replacement, the
    strata sampled once pooled into one group so their variance is not taken as zero."""
    rng, by, got = random.Random(seed), defaultdict(list), []
    sizes = Counter(r["stratum"] for r in sample)
    for r in sample:
        by[r["stratum"] if sizes[r["stratum"]] > 1 else ""].append(r)
    for _ in range(reps):
        boot = [rows[rng.randrange(len(rows))] for rows in by.values() for _ in rows]
        got.append(estimate(boot, strata, labels, cell, measure))
    got.sort()
    return [round(got[int(0.025 * reps)], 4), round(got[int(0.975 * reps) - 1], 4)]


MEASURES = ("count", "tokens_out", "tokens_in", "active_s")


def report(frame: dict, a: dict, b: dict, settled: dict | None = None) -> dict:
    """Kappa per label, disagreements, and the weighted shape x fit x latency table with token and wall shares."""
    ids = sorted(set(a) & set(b) & {r["id"] for r in frame["sample"]})
    if not ids:
        raise ValueError("no sampled unit carries both labellers' labels")
    missing = sorted({r["id"] for r in frame["sample"]} - set(ids))
    kap = {k: dict(zip(("kappa", "lo", "hi"), kappa_ci([a[i][k] for i in ids], [b[i][k] for i in ids])),
                   agree=sum(a[i][k] == b[i][k] for i in ids), n=len(ids)) for k in LABEL_KEYS}
    labels = final_labels({i: a[i] for i in ids}, b, settled)
    sample = [r for r in frame["sample"] if r["id"] in labels]
    cells = []
    for key in sorted({(v["shape"], v["fit"], v["latency"]) for v in labels.values()}):
        cell = (lambda L, key=key: (L["shape"], L["fit"], L["latency"]) == key)
        cells.append({"shape": key[0], "fit": key[1], "latency": key[2],
                      "sampled": sum(1 for r in sample if cell(labels[r["id"]])),
                      **{m: round(estimate(sample, frame["strata"], labels, cell, m), 4) for m in MEASURES}})
    cells.sort(key=lambda c: (-c["tokens_out"], c["shape"], c["fit"], c["latency"]))
    margins = {}
    for k, values in CLOSED.items():
        margins[k] = []
        for v in values:
            cell = (lambda L, k=k, v=v: L[k] == v)
            row = {"value": v, "sampled": sum(1 for r in sample if cell(labels[r["id"]]))}
            for m in MEASURES:
                row[m] = round(estimate(sample, frame["strata"], labels, cell, m), 4)
                row[m + "_ci"] = boot_ci(sample, frame["strata"], labels, cell, m)
            margins[k].append(row)
    disagree = [{"id": i, **{k: [a[i][k], b[i][k]] for k in LABEL_KEYS if a[i][k] != b[i][k]}}
                for i in ids if any(a[i][k] != b[i][k] for k in LABEL_KEYS)]
    covered = {r["stratum"] for r in sample}
    return {"n": len(ids), "missing": missing, "kappa": kap, "cells": cells, "margins": margins,
            "disagreements": disagree, "unsettled": sum(1 for d in disagree if not (settled or {}).get(d["id"])),
            "strata_covered": [len(covered), len(frame["strata"])]}


def _pct(x: float) -> str:
    return f"{100 * x:5.1f}%"


def _model_lines(frame: dict) -> list[str]:
    m, t = frame.get("output_model") or {}, frame["totals"]
    if not m:
        return []
    out = [f"output tokens: {m['partial']} of {m['partial'] + m['final']} messages carry a partial count (no "
           f"stop_reason); recorded {t.get('tokens_out_recorded', 0):,}, estimated {t['tokens_out']:,}, from "
           f"{m['coef'][0]} per visible char + {m['coef'][1]} per signature char {m['coef'][2]:+} fitted on the "
           f"{m['final']} final ones (held-out R2 {m.get('held_out_r2')}, sum ratio {m.get('held_out_ratio')}); "
           f"strata and allocation use the recorded count, shares the estimate"]
    out += [f"  cost-state {c['session']}: own total {c['cost_state']:,}, recorded {c['recorded']:,}, estimated "
            f"{c['estimated']:,} over {c['messages']} messages" for c in frame.get("cost_check", [])]
    return out


def text(frame: dict, got: dict) -> str:
    """The report as plain text: population, strata fractions, kappa, margins with intervals, and the cell table."""
    t = frame["totals"]
    out = [f"population {frame['population']} subtasks over {frame['days']} days to "
           f"{time.strftime('%Y-%m-%d %H:%M', time.gmtime(frame['now']))} UTC ({t['kinds']}); "
           f"output tokens {t['tokens_out']:,}, input tokens {t['tokens_in']:,}, active hours {t['active_s'] / 3600:.1f}",
           f"skipped {frame['skipped']}",
           *_model_lines(frame),
           f"sample {frame['n']} (seed {frame['seed']}), {len(frame['strata'])} strata project/candidate/size, "
           f"floor {FLOOR}, rest in proportion to output tokens; labelled {got['n']}, missing {len(got['missing'])}",
           "", "stratum N n fraction output_tokens"]
    out += [f"  {s} {v['N']} {v['n']} {v['fraction']:.3f} {v['tokens_out']:,}" for s, v in frame["strata"].items()]
    out += ["", "Cohen's kappa, two blind labellers (95% bootstrap interval)"]
    out += [f"  {k}: {v['kappa']} [{v['lo']}, {v['hi']}], agree {v['agree']}/{v['n']}" for k, v in got["kappa"].items()]
    out.append(f"  disagreements {len(got['disagreements'])}, unsettled {got['unsettled']}" + (" (A's label used)" if got['unsettled'] else ""))
    if got.get("rounds", 1) > 1:
        out.append(f"  labels from {got['rounds']} rounds: a later round relabels some keys under refined definitions")
    for k, rows in got["margins"].items():
        out += ["", f"{k}: sampled, share of units, output tokens, wall time (95% stratified bootstrap)"]
        for r in rows:
            out.append(f"  {r['value']:<24} {r['sampled']:>3}  units {_pct(r['count'])}  out {_pct(r['tokens_out'])} "
                       f"[{_pct(r['tokens_out_ci'][0]).strip()}, {_pct(r['tokens_out_ci'][1]).strip()}]  "
                       f"wall {_pct(r['active_s'])} [{_pct(r['active_s_ci'][0]).strip()}, "
                       f"{_pct(r['active_s_ci'][1]).strip()}]")
    out += ["", "shape x fit x latency: sampled, share of units, output tokens, input tokens, wall time"]
    out += [f"  {c['shape']:<20} {c['fit']:<23} {c['latency']:<11} {c['sampled']:>3} {_pct(c['count'])} "
            f"{_pct(c['tokens_out'])} {_pct(c['tokens_in'])} {_pct(c['active_s'])}" for c in got["cells"]]
    return "\n".join(out) + "\n"


def _said(text_: str, known: redact.Known) -> str:
    return redact.redact(" ".join(str(text_ or "").split())[:160], known).text


def manifest(frame: dict, a: dict, b: dict, settled: dict | None, known: redact.Known) -> list[dict]:
    """One row per labelled unit: its key, stratum and weight, sizes, both labels, the final label, and A's
    redacted reason and gist. No transcript text."""
    labels = final_labels(a, b, settled)
    rows = []
    for r in frame["sample"]:
        if r["id"] not in labels:
            continue
        v = frame["strata"][r["stratum"]]
        rows.append({**{k: r[k] for k in ("id", "key", "kind", "stratum", "tokens_in", "tokens_out",
                                          "tokens_out_recorded", "active_s",
                                          "tool_calls", "files_edited")},
                     "weight": round(v["N"] / v["n"], 4),
                     "a": {k: a[r["id"]][k] for k in LABEL_KEYS}, "b": {k: b[r["id"]][k] for k in LABEL_KEYS},
                     "final": {k: labels[r["id"]][k] for k in LABEL_KEYS}, "settled": labels[r["id"]]["settled"],
                     "fit_reason": _said(a[r["id"]].get("fit_reason"), known), "gist": _said(a[r["id"]].get("gist"), known)})
    return rows


def public_repo(repo: str) -> bool:
    """Whether GitHub says owner/name is public; anything else, an error included, is not."""
    try:
        got = subprocess.run(["gh", "repo", "view", repo, "--json", "isPrivate", "-q", ".isPrivate"],
                             capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return got.returncode == 0 and got.stdout.strip() == "false"


def masked(frame: dict, rows: list[dict], public=public_repo) -> tuple[dict, list[dict]]:
    """`frame` and manifest `rows` with each project whose repo is not public renamed private-N and its rows' gist and
    reason left out."""
    names, k = {}, 0
    for name, repo in frame.get("repos", {}).items():
        if not public(repo):
            k += 1
            names[name] = f"private-{k}"

    def stratum(s: str) -> str:
        head, _, rest = s.partition("/")
        return f"{names.get(head, head)}/{rest}"
    out = {**frame, "repos": {names.get(n, n): (r if n not in names else "") for n, r in frame.get("repos", {}).items()},
           "strata": {stratum(s): v for s, v in frame["strata"].items()},
           "sample": [dict(r, stratum=stratum(r["stratum"])) for r in frame["sample"]]}
    hidden = (lambda r: r["stratum"].partition("/")[0] in names)
    return out, [dict(r, stratum=stratum(r["stratum"]), **({"fit_reason": "", "gist": ""} if hidden(r) else {}))
                 for r in rows]


def write(dest: Path, frame: dict, got: dict, rows: list[dict], known: redact.Known, public=public_repo) -> list[Path]:
    """manifest.jsonl, strata.json and census.txt under `dest`, private projects masked; refused when any of them
    holds a redact finding."""
    frame, rows = masked(frame, rows, public)
    files = {"manifest.jsonl": "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
             "strata.json": json.dumps({k: frame.get(k) for k in ("now", "days", "seed", "n", "population", "skipped",
                                                                     "output_model", "cost_check", "repos", "totals",
                                                                     "strata")}, indent=1) + "\n",
             "census.txt": text(frame, got)}
    bad = {name: found for name, body in files.items() if (found := redact.detect(body, known))}
    if named := sorted({w for r in rows for w in redact.name_like(f"{r['fit_reason']} {r['gist']}")}):
        bad["manifest.jsonl names"] = named
    if bad:
        raise ValueError(f"refusing to write: redact.detect finds {bad}")
    dest.mkdir(parents=True, exist_ok=True)
    for name, body in files.items():
        (dest / name).write_text(body, encoding="utf-8")
    return [dest / n for n in files]
