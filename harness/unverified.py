"""Claims in a turn's final message that no tool result in the turn supports: the Stop hook behind `soh unverified` (#1380)."""
from __future__ import annotations

import json
import math
import os
import re
import time
from pathlib import Path

#: Candidate claims one turn sends to the decide model; the rest go unchecked.
CLAIMS_PER_TURN = 12
#: Seconds the whole check may take before the stop is allowed unchecked.
TURN_TIMEOUT_S = 10.0
#: Bytes read from the transcript's tail; a turn that starts before them is allowed unchecked.
TRANSCRIPT_BYTES = 4 * 1024 * 1024
#: Characters of the turn's tool output put before the model with one claim.
EVIDENCE_CHARS = 2400
#: Probability of "shown" below which a factual claim is flagged; a claim no tool output shares a term with always is.
SHOWN_P = 0.9
#: Characters in one evidence window the retrieval ranks.
WINDOW_CHARS = 400
#: Sessions whose last blocked turn the state file remembers.
SESSIONS_KEPT = 200

LOG = "unverified.jsonl"
STATE = "unverified-state.json"
ALLOW, BLOCK = "allow", "block"

STATE_WORDS = re.compile(
    r"\b(pass(es|ed|ing)?|fail(s|ed|ing|ure)?|green|red|merged|open|closed|running|runs|ran|queued|done|"
    r"finished|complete[ds]?|succeeded|deployed|installed|exists?|missing|empty|broken|works|working|"
    r"timed out|refused|blocked|loaded|resident|idle|holds?|returned|shows?|reports?|up|down|serves?|"
    r"starts?|started|stopped|crashed)\b", re.I)
HEDGES = re.compile(
    r"\b(unverified|not verified|unchecked|not checked|hypothes[ie]s|i think|i expect|i believe|i assume|"
    r"probably|likely|might|may|perhaps|guess)\b", re.I)
CITED = re.compile(r"https?://|\b(RULE|FINDING|DECISION|NEGATIVE|ERROR|KNOWLEDGE|PREFERENCE)\s+#\d+|"
                   r"\b[\w./-]+\.(py|sh|md|json|yaml|toml|txt|log):\d+\b")
FENCE = re.compile(r"```.*?(```|$)", re.S)
SPLIT = re.compile(r"(?<=[.!?;])\s+(?=[A-Z0-9\"'(`])")
TOKEN = re.compile(r"[a-z0-9][a-z0-9._:/_-]*[a-z0-9]|[0-9]")
STOP = frozenset("the and for are was were has have had this that with from into not but all any its it's "
                 "our you your his her they them then than there here which what when where who how one two "
                 "also only just been being now out off per via each every some more most".split())

SCHEMA = {
    "kind": {"type": "enum", "choices": ["fact", "other"],
             "description": "fact: the sentence states a fact about the world as observed (a state, a count, a "
                            "time, a pass or fail result); other: a plan, an intention, an opinion, a question or "
                            "an instruction"},
    "support": {"type": "enum", "choices": ["shown", "not_shown"],
                "description": "shown: the tool output in the context states what the sentence says, with the "
                               "same numbers and states; not_shown: the output is silent about it, differs from "
                               "it, or the context is empty"},
}
QUESTION = ("An assistant ended its turn with the sentence below. The context is the tool output from that same "
            "turn that shares the most words with it. Judge the sentence against that output only, never against "
            "what you know.\n\nSentence: {claim}")


def _records(path: Path, limit: int) -> tuple[list[dict], bool]:
    """The parsed records of the transcript's last `limit` bytes, and whether that is the whole file."""
    size = path.stat().st_size
    start = max(0, size - int(limit))
    with open(path, "rb") as f:
        f.seek(start)
        data = f.read()
    lines = data.split(b"\n")
    if start:
        lines = lines[1:]
    out = []
    for raw in lines:
        if not raw.strip():
            continue
        try:
            got = json.loads(raw)
        except ValueError:
            continue
        if isinstance(got, dict):
            out.append(got)
    return out, start == 0


def _content(r: dict):
    return (r.get("message") or {}).get("content")


def _is_result(r: dict) -> bool:
    c = _content(r)
    return "toolUseResult" in r or (isinstance(c, list) and bool(c) and all(
        isinstance(b, dict) and b.get("type") == "tool_result" for b in c))


def starts_turn(r: dict) -> bool:
    """A typed prompt, task notification or peer message; never a tool result, compact summary or bare meta record."""
    if r.get("type") != "user" or r.get("isSidechain") or r.get("isCompactSummary") or _is_result(r):
        return False
    return bool(r.get("origin")) or not r.get("isMeta")


def current_turn(records: list[dict], whole: bool) -> tuple[str, list[dict]] | None:
    """(the turn's first record's uuid, the records after it); None when the turn starts before what was read."""
    for i in range(len(records) - 1, -1, -1):
        if starts_turn(records[i]):
            return str(records[i].get("uuid") or i), records[i + 1:]
    return ("", records) if whole else None


def final_text(turn: list[dict]) -> str:
    """The assistant text after the turn's last tool call or result."""
    parts: list[str] = []
    for r in reversed(turn):
        c = _content(r)
        if r.get("type") == "user" and _is_result(r):
            break
        if r.get("type") != "assistant" or not isinstance(c, list):
            continue
        if any(isinstance(b, dict) and b.get("type") == "tool_use" for b in c):
            break
        parts[:0] = [b.get("text") or "" for b in c if isinstance(b, dict) and b.get("type") == "text"]
    return "\n".join(p for p in parts if p.strip())


def evidence(turn: list[dict]) -> list[str]:
    """Each tool call's name and input, and each tool result's text, in the turn's order."""
    from harness.context_report import result_text
    out = []
    for r in turn:
        c = _content(r)
        if not isinstance(c, list):
            continue
        for b in c:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "tool_use":
                out.append(f"{b.get('name', '')} {json.dumps(b.get('input') or {}, ensure_ascii=False)}")
            elif b.get("type") == "tool_result":
                out.append(result_text(b.get("content")))
    return [e for e in out if e.strip()]


def sentences(text: str) -> list[str]:
    """The message's sentences and list items, code blocks and markdown marks left out."""
    out = []
    for line in FENCE.sub("\n", text or "").splitlines():
        line = re.sub(r"^\s*(?:[-*+>]|\d+[.)]|#+)\s+", "", line).replace("**", "").replace("__", "").strip()
        if not line or line.startswith("|"):
            continue
        out.extend(s.strip() for s in SPLIT.split(line) if s.strip())
    return out


def candidate(s: str) -> bool:
    """A sentence that may state a checkable fact and neither cites its receipt nor marks itself unverified."""
    if len(s) < 12 or s.rstrip().endswith("?") or HEDGES.search(s) or CITED.search(s):
        return False
    return bool(re.search(r"\d", s) or STATE_WORDS.search(s))


def candidates(text: str) -> list[str]:
    seen, out = set(), []
    for s in sentences(text):
        if candidate(s) and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def terms(text: str) -> set[str]:
    got = set()
    for t in TOKEN.findall(text.lower()):
        t = t.strip(".:/-")
        if t and t not in STOP and (len(t) > 2 or t.isdigit()):
            got.add(t)
    return got


def windows(items: list[str]) -> list[str]:
    out = []
    for item in items:
        buf = ""
        for line in item.splitlines() or [item]:
            while len(line) > WINDOW_CHARS:
                if buf:
                    out.append(buf)
                    buf = ""
                out.append(line[:WINDOW_CHARS])
                line = line[WINDOW_CHARS:]
            if buf and len(buf) + len(line) + 1 > WINDOW_CHARS:
                out.append(buf)
                buf = ""
            buf = f"{buf}\n{line}" if buf else line
        if buf.strip():
            out.append(buf)
    return out


def retrieve(claim: str, chunks: list[str], limit: int | None = None) -> tuple[str, int]:
    """(the windows sharing the claim's rarest terms, up to `limit` chars in turn order, relevant windows left out)."""
    limit = EVIDENCE_CHARS if limit is None else limit
    want = terms(claim)
    sets = [terms(c) for c in chunks]
    df = {t: sum(t in s for s in sets) for t in want}
    n = len(chunks)

    def score(s):
        return sum((math.log((n + 1) / (df[t] + 0.5)) + 1) * (2 if any(ch.isdigit() for ch in t) else 1)
                   for t in want & s)
    ranked = sorted((i for i in range(n) if want & sets[i]), key=lambda i: -score(sets[i]))
    kept, used, dropped = [], 0, 0
    for i in ranked:
        if used + len(chunks[i]) > limit:
            dropped += 1
            continue
        kept.append(i)
        used += len(chunks[i]) + 5
    return "\n---\n".join(chunks[i] for i in sorted(kept)), dropped


def shown(got: dict) -> float:
    """The model's probability that the tool output shows the claim; its answer as 0 or 1 when it gave none."""
    p = ((got.get("probabilities") or {}).get("support") or {}).get("shown")
    return float(p) if p is not None else float(got.get("answers", {}).get("support") == "shown")


def local_decide(question: str, schema: dict, context: str, timeout: float) -> dict:
    from harness import delegate
    return delegate.decide(question, schema, context=context, timeout=timeout)


def check(text: str, turn: list[dict], decide=None, *, budget_s: float | None = None,
          clock=time.monotonic) -> dict:
    """Judge each candidate claim in `text` against the turn's tool output; fails open on any error or the deadline."""
    from harness import cuts
    decide = decide or local_decide
    budget_s = TURN_TIMEOUT_S if budget_s is None else budget_s
    started = clock()
    found = candidates(text)
    out = {"decision": ALLOW, "why": "", "candidates": len(found), "checked": 0, "flagged": []}
    claims = cuts.take(found, CLAIMS_PER_TURN, "unverified_claims", "claims one Stop hook checks")
    chunks = windows(evidence(turn))
    evidence_cut = doubted = 0
    for claim in claims:
        left = budget_s - (clock() - started)
        if left <= 0:
            cuts.cut("unverified_turn_timeout_s", "Stop hook claim check", kept=out["checked"],
                     dropped=len(claims) - out["checked"])
            return {**out, "why": "timeout"}
        context, dropped = retrieve(claim, chunks)
        evidence_cut += dropped
        try:
            got = decide(QUESTION.format(claim=claim), SCHEMA, context, left)
        except Exception as exc:  # noqa: BLE001 - every failure allows the stop; only the class is logged
            late = cuts.timed_out(exc) or getattr(exc, "failure_class", "") == "timeout"
            if late:
                cuts.cut("unverified_turn_timeout_s", "Stop hook decide call", kept=out["checked"],
                         dropped=len(claims) - out["checked"])
            return {**out, "why": f"{'timeout' if late else 'error'}: {type(exc).__name__}"}
        out["checked"] += 1
        answers = (got or {}).get("answers") or {}
        if answers.get("kind") == "fact" and (not context or shown(got) < SHOWN_P):
            out["flagged"].append(claim)
            doubted += bool(context) and answers.get("support") == "shown"
    if evidence_cut:
        cuts.cut("unverified_evidence_chars", "tool output windows put before the decide model", dropped=evidence_cut)
    if doubted:
        cuts.cut("unverified_shown_p", "claims the model answered shown, flagged below the probability",
                 dropped=doubted)
    if clock() - started > budget_s:
        return {**out, "why": "timeout"}
    if out["flagged"]:
        return {**out, "decision": BLOCK, "why": "unsupported"}
    return {**out, "why": "supported" if claims else "no claims"}


def reason(flagged: list[str]) -> str:
    lines = [f"{i}. {c}" for i, c in enumerate(flagged, 1)]
    return ("No tool result in this turn shows these claims from your final message:\n" + "\n".join(lines) +
            "\nFor each one: cite its receipt (command output, file:line, KB id), check it now, or mark it "
            "unverified with how to check it. This check runs once per turn.")


def _state_path() -> Path:
    from harness import paths
    return paths.home() / STATE


def _blocked(session: str, turn: str) -> bool:
    try:
        return json.loads(_state_path().read_text(encoding="utf-8")).get(session) == turn
    except (OSError, ValueError, AttributeError):
        return False


def _remember(session: str, turn: str) -> bool:
    """Record the blocked turn; False when it cannot be written, and then the hook must not block."""
    path = _state_path()
    try:
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
            state = state if isinstance(state, dict) else {}
        except (OSError, ValueError):
            state = {}
        state.pop(session, None)
        state[session] = turn
        state = dict(list(state.items())[-SESSIONS_KEPT:])
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{STATE}.{os.getpid()}")
        tmp.write_text(json.dumps(state), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        return False
    return True


def log(row: dict) -> bool:
    """One row per stop: counts, outcome, reason, seconds and flagged claims; never other transcript text."""
    from harness import paths
    keep = ("at", "session", "turn", "decision", "why", "candidates", "checked", "flagged", "seconds")
    try:
        path = paths.logs() / LOG
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps({k: row.get(k) for k in keep}) + "\n")
    except OSError:
        return False
    return True


def turn_of(transcript: Path) -> tuple[str, list[dict]] | None:
    from harness import cuts
    records, whole = _records(transcript, TRANSCRIPT_BYTES)
    got = current_turn(records, whole)
    if got is None:
        cuts.cut("unverified_transcript_bytes", "Stop hook turn read")
    return got


def hook(event: dict, decide=None, clock=time.monotonic) -> dict:
    """The Stop hook's verdict on one stop event; logged, and allow on any failure."""
    started = clock()
    session = str(event.get("session_id") or "")
    row = {"at": time.time(), "session": session, "turn": "", "decision": ALLOW, "why": "",
           "candidates": 0, "checked": 0, "flagged": []}
    try:
        if event.get("stop_hook_active"):
            row["why"] = "stop_hook_active"
        else:
            got = turn_of(Path(str(event.get("transcript_path") or "")))
            if got is None:
                row["why"] = "turn longer than unverified_transcript_bytes"
            else:
                row["turn"], turn = got
                if _blocked(session, row["turn"]):
                    row["why"] = "already blocked this turn"
                else:
                    text = str(event.get("last_assistant_message") or "") or final_text(turn)
                    row.update(check(text, turn, decide, budget_s=TURN_TIMEOUT_S - (clock() - started),
                                     clock=clock))
                    if row["decision"] == BLOCK and not _remember(session, row["turn"]):
                        row.update(decision=ALLOW, why="state not writable")
    except Exception as exc:  # noqa: BLE001 - a hook that raises would strand the turn
        row.update(decision=ALLOW, why=f"error: {type(exc).__name__}")
    row["seconds"] = round(clock() - started, 3)
    log(row)
    return row


def settings(command: str) -> dict:
    """The settings.json block that turns the hook on for one project; printed, never written."""
    return {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": command,
                                            "timeout": int(TURN_TIMEOUT_S * 3)}]}]}}
