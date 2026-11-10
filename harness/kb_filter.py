"""`soh kb-filter`: a local model keeps the KB search hits that fit the caller's need. #1334."""
from __future__ import annotations

import json
import math
import random
import re
from collections import Counter
from pathlib import Path
from typing import NamedTuple

from harness import context_class as cc
from harness import context_report as cr
from harness.intervals import wilson
from harness.lexical_rank import tokens as words
from harness.paired import sign_test

SEARCH = cc.KB_PREFIX + "search"
_AT = re.compile(r"^\[(KNOWLEDGE/[A-Z_]+|NEGATIVE|ERROR|RULE) #(\d+)\]", re.M)
_FOOT = re.compile(r"\n\n(?=\(summary view|---\n|REMINDER|RULES CHECK)")
_ID = re.compile(r"#(\d+)\b")
#: Recall the decide threshold is tuned to on the weeks before the held-out one.
TARGET = 0.96
#: Recall and its Wilson lower bound the held-out week must reach before wiring (#1334).
GATE_RECALL, GATE_LOWER = 0.95, 0.92
ARMS = ("decide", "extract", "lexical", "combo", "position", "type")
#: Arms that call a local model; one ships only when it beats the lexical arm at equal tokens (#1690).
LOCAL = ("decide", "combo")


class Knobs(NamedTuple):
    """The filter's settings, set per run by `soh kb-filter` and written to its report."""
    min_hits: int
    floor: int
    hit_chars: int
    need_chars: int
    chunk: int
    reply: int


def unwrap(text: str) -> tuple[str, bool]:
    """The search's own text, and whether it came wrapped as {"result": ...}."""
    if text.lstrip().startswith("{"):
        try:
            got = json.loads(text)
        except ValueError:
            return text, False
        if isinstance(got, dict) and isinstance(got.get("result"), str):
            return got["result"], True
    return text, False


def parse(text: str) -> tuple[str, list[dict], str]:
    """(header, hits, footer) of a search result; every hit is {kind, id, text}."""
    starts = list(_AT.finditer(text))
    if not starts:
        return text, [], ""
    foot = _FOOT.search(text, starts[-1].end())
    end = foot.start() if foot else len(text)
    hits = []
    for i, m in enumerate(starts):
        stop = starts[i + 1].start() if i + 1 < len(starts) else end
        hits.append({"kind": m.group(1), "id": m.group(2), "text": text[m.start():stop].rstrip("\n")})
    return text[:starts[0].start()], hits, text[end:]


def tokens(text: str) -> int:
    return len(text) // 4


def asked(hits: list[dict], *texts: str) -> set[int]:
    """1-based positions of the hits whose id the caller wrote in its query or need."""
    ids = {n for t in texts for n in _ID.findall(t or "")}
    return {p for p, h in enumerate(hits, 1) if h["id"] in ids}


def render(header: str, hits: list[dict], kept: list[int], footer: str) -> str:
    """The result as Claude sees it after the filter: kept hits in order, the rest named by id."""
    kept_set = set(kept)
    body = "\n\n".join(h["text"] for p, h in enumerate(hits, 1) if p in kept_set)
    dropped = [f"[{h['kind']} #{h['id']}]" for p, h in enumerate(hits, 1) if p not in kept_set]
    note = (f"\n\n(kb-filter kept {len(kept_set)} of {len(hits)} hits for this need; also matched: "
            + ", ".join(dropped) + "; get_entry fetches any)") if dropped else ""
    return header + body + note + footer


def guard(hits: list[dict], chosen, query: str, need: str, k: Knobs, order: list[int] | None = None) -> list[int]:
    """The positions to keep: every hit on any doubt, else the choice plus asked ids, at least k.floor."""
    n = len(hits)
    every = list(range(1, n + 1))
    if n < k.min_hits or chosen is None:
        return every
    try:
        picked = {int(p) for p in chosen}
    except (TypeError, ValueError):
        return every
    if not picked or not picked <= set(every):
        return every
    picked |= asked(hits, query, need)
    for p in order or every:
        if len(picked) >= k.floor:
            break
        picked.add(p)
    return sorted(picked)


def _context(item: dict, positions: list[int], k: Knobs) -> str:
    rows = "\n".join(f"result {p}: {item['hits'][p - 1]['text'][:k.hit_chars]}" for p in positions)
    return (f"The agent's current work, in its own words:\n{item['need'][-k.need_chars:]}\n\n"
            f"It searched its knowledge base for: {item['query']}\n\nThe search returned:\n{rows}")


QUESTION = ("A coding agent searched its knowledge base. For each result, answer true if the agent "
            "would use or cite it for the work described, false if it is unrelated to that work.")


def decide_scores(item: dict, ask, k: Knobs) -> list[float]:
    """P(keep) per hit from the decide lane, k.chunk hits per call; `ask` is delegate.decide."""
    out: list[float] = []
    n = len(item["hits"])
    for lo in range(1, n + 1, k.chunk):
        positions = list(range(lo, min(n, lo + k.chunk - 1) + 1))
        schema = {f"result_{p}": {"type": "boolean",
                                  "description": f"result {p} ({item['hits'][p - 1]['kind']} "
                                                 f"#{item['hits'][p - 1]['id']}) helps the agent's work"}
                  for p in positions}
        got = ask(QUESTION, schema, context=_context(item, positions, k))
        for p in positions:
            probs = got["probabilities"].get(f"result_{p}") or {}
            out.append(float(probs.get("true", 1.0 if str(got["answers"].get(f"result_{p}")) == "true" else 0.0)))
    return out


EXTRACT = ("{context}\n\nWhich results would the agent use or cite for that work? Reply with only a JSON "
           "list of their result numbers, like [2, 7]; reply [] if none would help.")


def extract_choice(item: dict, complete, k: Knobs) -> list[int] | None:
    """The result numbers the extract lane names, None when its reply holds no list; `complete` is delegate.complete."""
    every = list(range(1, len(item["hits"]) + 1))
    got = complete("extract", EXTRACT.format(context=_context(item, every, k)), max_tokens=k.reply,
                   thinking=False)
    m = re.search(r"\[[\d,\s]*\]", got.get("text") or "")
    if not m:
        return None
    return json.loads(m.group(0))


def by_position(item: dict, budget: int) -> list[int]:
    """The shortest prefix of hits whose tokens reach `budget`: the position arm at equal kept tokens."""
    kept, spent = [], 0
    for p, h in enumerate(item["hits"], 1):
        if spent >= budget and kept:
            break
        kept.append(p)
        spent += tokens(h["text"])
    return kept


def by_type(item: dict, k: int = 2) -> list[int]:
    """The first k hits of each kind (KNOWLEDGE, NEGATIVE, ERROR, RULE)."""
    seen: dict[str, int] = {}
    kept = []
    for p, h in enumerate(item["hits"], 1):
        kind = h["kind"].split("/")[0]
        seen[kind] = seen.get(kind, 0) + 1
        if seen[kind] <= k:
            kept.append(p)
    return kept


def threshold(items: list[dict], scores: dict, k: Knobs, target: float = TARGET) -> float:
    """The highest score cut whose recall over `items` reaches `target`, guard included (recall falls as the cut rises)."""
    cuts = sorted({s for it in items for s in scores.get(it["key"]) or []}, reverse=True)

    def reaches(cut: float) -> bool:
        return recall(items, {it["key"]: decide_keep(it, scores.get(it["key"]), cut, k) for it in items})[0] >= target
    lo, hi = 0, len(cuts)
    while lo < hi:
        mid = (lo + hi) // 2
        if reaches(cuts[mid]):
            hi = mid
        else:
            lo = mid + 1
    return cuts[lo] if lo < len(cuts) else 0.0


def vocabulary(items: list[dict]) -> dict:
    """Document frequency of every word over the hits of `items`: the lexical arm's idf."""
    df: Counter = Counter()
    n = 0
    for it in items:
        for h in it["hits"]:
            n += 1
            df.update(set(words(h["text"])))
    return {"n": n, "df": dict(df)}


def lexical_scores(item: dict, vocab: dict, k: Knobs) -> list[float]:
    """Per hit, the idf of the words it shares with the query and need, over the search's best: no model."""
    n, df = vocab["n"], vocab["df"]
    asked_words = set(words(item["query"] + " " + item["need"][-k.need_chars:]))
    raw = [sum(math.log(1 + (n - df.get(w, 0) + 0.5) / (df.get(w, 0) + 0.5))
               for w in asked_words & set(words(h["text"][:k.hit_chars]))) for h in item["hits"]]
    top = max(raw, default=0.0) or 1.0
    return [s / top for s in raw]


def mean_scores(a: dict, b: dict) -> dict:
    """key -> per-hit mean of two arms' scores, for the searches both scored in full."""
    return {key: [(x + y) / 2 for x, y in zip(a[key], b[key])] for key in a
            if a[key] and b.get(key) and len(a[key]) == len(b[key])}


def budget_keep(item: dict, probs: list[float] | None, budget: int, k: Knobs) -> list[int]:
    """The best-scored hits until their tokens reach `budget`: an arm at another arm's kept tokens."""
    if probs is None or len(probs) != len(item["hits"]):
        return guard(item["hits"], None, item["query"], item["need"], k)
    order = sorted(range(1, len(probs) + 1), key=lambda p: -probs[p - 1])
    kept, spent = [], 0
    for p in order:
        if spent >= budget and kept:
            break
        kept.append(p)
        spent += tokens(item["hits"][p - 1]["text"])
    return guard(item["hits"], kept, item["query"], item["need"], k, order)


def decide_keep(item: dict, probs: list[float] | None, cut: float, k: Knobs) -> list[int]:
    if probs is None or len(probs) != len(item["hits"]):
        return guard(item["hits"], None, item["query"], item["need"], k)
    order = sorted(range(1, len(probs) + 1), key=lambda p: -probs[p - 1])
    return guard(item["hits"], [p for p in order if probs[p - 1] >= cut] or order[:k.floor],
                 item["query"], item["need"], k, order)


def recall(items: list[dict], kept: dict) -> tuple[float, int, int]:
    """(recall, referenced hits kept, referenced hits) over items."""
    k = n = 0
    for it in items:
        mine = set(kept[it["key"]])
        n += len(it["gold"])
        k += sum(1 for p in it["gold"] if p in mine)
    return (k / n if n else 1.0), k, n


def kept_tokens(item: dict, positions: list[int]) -> int:
    return tokens(render(item["header"], item["hits"], positions, item["footer"]))


def summary(items: list[dict], kept: dict) -> dict:
    r, k, n = recall(items, kept)
    shown = sum(it["tokens"] for it in items)
    left = sum(kept_tokens(it, kept[it["key"]]) for it in items)
    return {"recall": round(r, 4), "kept_referenced": k, "referenced": n, "lower": wilson(k, n)[0],
            "hits": sum(len(it["hits"]) for it in items), "kept_hits": sum(len(kept[it["key"]]) for it in items),
            "tokens_shown": shown, "tokens_kept": left, "kept_share": round(left / shown, 4) if shown else 1.0}


def paired(items: list[dict], mine: dict, theirs: dict) -> dict:
    """Referenced hits one arm keeps and the other drops, and the sign test on them."""
    won = lost = 0
    for it in items:
        a, b = set(mine[it["key"]]), set(theirs[it["key"]])
        won += sum(1 for p in it["gold"] if p in a and p not in b)
        lost += sum(1 for p in it["gold"] if p in b and p not in a)
    return {"won": won, "lost": lost, "p": round(sign_test(won, won + lost), 4)}


def plant(items: list[dict], n: int = 20, seed: int = 1334) -> list[dict]:
    """Synthesized searches, each with one hit whose title is the need word for word, at position 6 or later."""
    rng = random.Random(seed)
    pool = [it for it in items if len(it["hits"]) >= 6 and it["need"].strip()]
    out = []
    for it in rng.sample(pool, min(n, len(pool))):
        title = " ".join(it["need"].split())[-160:]
        hit = {"kind": "RULE", "id": "990001", "text": f"[RULE #990001] {title} (planted)\n  {title}"}
        at = rng.randint(6, len(it["hits"]) + 1)
        hits = it["hits"][:at - 1] + [hit] + it["hits"][at - 1:]
        out.append({**it, "key": it["key"] + ":planted", "hits": hits, "gold": [at]})
    return out


def gate(held: dict, position: dict, planted: dict | None) -> list[str]:
    """Why the filter may not be wired yet; empty when every held-out bar holds."""
    why = []
    if held["recall"] < GATE_RECALL:
        why.append(f"recall {held['recall']:.3f} < {GATE_RECALL}")
    if held["lower"] < GATE_LOWER:
        why.append(f"Wilson lower {held['lower']:.3f} < {GATE_LOWER}")
    if not (position["won"] > position["lost"] and position["p"] < 0.05):
        why.append(f"does not beat the position arm ({position['won']} won, {position['lost']} lost, "
                   f"p {position['p']})")
    if planted is None:
        why.append("planted check not run")
    elif planted["kept_referenced"] < planted["referenced"]:
        why.append(f"planted {planted['kept_referenced']} of {planted['referenced']} kept")
    return why


def _need(recs: list[dict], upto: int) -> str:
    """The caller's last text block before record `upto`, else the stream's opening prompt."""
    for rec in reversed(recs[:upto]):
        if rec.get("type") == "assistant":
            texts = [b.get("text") for b in cc._blocks(rec) if b.get("type") == "text" and b.get("text")]
            if texts:
                return str(texts[-1])
    for rec in recs[:upto]:
        if rec.get("type") == "user":
            msg = rec.get("message") if isinstance(rec.get("message"), dict) else {}
            if isinstance(msg.get("content"), str):
                return msg["content"]
            texts = [b.get("text") for b in cc._blocks(rec) if b.get("type") == "text"]
            if texts:
                return str(texts[0])
    return ""


_NAMED = re.compile(r"\b(KNOWLEDGE|FINDING|DECISION|INSIGHT|NEGATIVE|ERROR|RULE)\b[^#\n]{0,16}#(\d+)\b", re.I)
_TYPE = {"knowledge": "knowledge", "finding": "knowledge", "decision": "knowledge", "insight": "knowledge"}


def named(recs: list[dict]) -> dict:
    """Last record index at which Claude wrote each (type, id) with its kind beside it, e.g. 'RULE #12'."""
    out: dict = {}
    for i, rec in enumerate(recs):
        if rec.get("type") != "assistant":
            continue
        for b in cc._blocks(rec):
            said = b.get("text") if b.get("type") == "text" else (
                json.dumps(b.get("input"), ensure_ascii=False) if b.get("type") == "tool_use" else "")
            for kind, n in _NAMED.findall(str(said or "")):
                out[(_TYPE.get(kind.lower(), kind.lower()), n)] = i
    return out


def labelled(root: Path, *, since: float, until: float = float("inf"), big: int = cc.BIG,
             strict: bool = False) -> list[dict]:
    """Searches of at least `big` tokens with a hit referenced later; `strict` drops bare '#n' (ids collide with issues)."""
    out: list[dict] = []
    seen: set = set()
    for recs, _usage in cr.streams(root, since):
        _edits, nums, entries = cc._look_ahead(recs)
        if strict:
            nums = {}
            for k, v in named(recs).items():
                entries[k] = max(v, entries.get(k, -1))
        calls: dict = {}
        for i, rec in enumerate(recs):
            at = cr._epoch(rec.get("timestamp")) or 0.0
            for b in cc._blocks(rec):
                if b.get("type") == "tool_use" and b.get("name") == SEARCH:
                    calls[b.get("id")] = (b.get("input") or {}, i)
                if b.get("type") != "tool_result" or b.get("tool_use_id") not in calls:
                    continue
                uid = b.get("tool_use_id")
                if uid in seen or not since <= at < until:
                    continue
                seen.add(uid)
                text, _ = unwrap(cr.result_text(b.get("content")))
                if tokens(text) < big:
                    continue
                header, hits, footer = parse(text)
                gold = [p for p, h in enumerate(hits, 1)
                        if nums.get(h["id"], -1) > i
                        or entries.get((h["kind"].split("/")[0].lower(), h["id"]), -1) > i]
                if not gold:
                    continue
                inp, used_at = calls[uid]
                out.append({"key": str(uid), "at": at, "query": str(inp.get("query") or ""),
                            "need": _need(recs, used_at), "header": header, "hits": hits,
                            "footer": footer, "tokens": tokens(text), "gold": gold})
    return sorted(out, key=lambda it: it["at"])


def _response_text(resp):
    """(text, put) for a search's tool_response, where put(new) rebuilds the same shape; None for a shape unknown."""
    if isinstance(resp, str):
        return resp, lambda new: new
    if isinstance(resp, dict) and isinstance(resp.get("result"), str):
        return resp["result"], lambda new: {**resp, "result": new}
    blocks = resp.get("content") if isinstance(resp, dict) else resp
    if isinstance(blocks, list):
        at = [i for i, b in enumerate(blocks) if isinstance(b, dict) and b.get("type") == "text"]
        if len(at) == 1:
            def put(new, i=at[0]):
                out = [*blocks[:i], {**blocks[i], "text": new}, *blocks[i + 1:]]
                return {**resp, "content": out} if isinstance(resp, dict) else out
            return str(blocks[at[0]].get("text") or ""), put
    return None


def hook(event: dict, chosen: dict, vocab: dict, decide=None) -> dict | None:
    """The PostToolUse output that shows a KB search's kept hits and names the rest; None leaves the result whole."""
    from harness import unverified as uv
    arm = chosen.get("ship", {}).get("arm")
    if event.get("tool_name") != SEARCH or arm not in ("lexical", *LOCAL):
        return None
    got = _response_text(event.get("tool_response"))
    if got is None:
        return None
    raw, put = got
    text, wrapped = unwrap(raw)
    header, hits, footer = parse(text)
    k = Knobs(**chosen["knobs"])
    if len(hits) < k.min_hits:
        return None
    path = Path(str(event.get("transcript_path") or ""))
    recs = uv._records(path, uv.TRANSCRIPT_BYTES)[0] if path.is_file() else []
    item = {"query": str((event.get("tool_input") or {}).get("query") or ""), "need": _need(recs, len(recs)),
            "hits": hits}
    probs, cut = lexical_scores(item, vocab, k), chosen["thresholds"]["lexical"]
    local = None
    if arm in LOCAL and decide is not None:
        try:
            local = decide_scores(item, decide, k)
        except Exception:  # noqa: BLE001 - the lane being down leaves the lexical arm
            local = None
    if local is not None:
        probs, cut = (local if arm == "decide" else [(a + b) / 2 for a, b in zip(local, probs)],
                      chosen["thresholds"][arm])
    kept = decide_keep(item, probs, cut, k)
    if len(kept) == len(hits):
        return None
    new = render(header, hits, kept, footer)
    out = put(json.dumps({"result": new}) if wrapped else new)
    return {"hookSpecificOutput": {"hookEventName": "PostToolUse", "updatedMCPToolOutput": out,
                                   "updatedToolOutput": out}}


def settings(command: str) -> dict:
    """The settings.json block that runs the filter on every KB search; printed, never written."""
    return {"hooks": {"PostToolUse": [{"matcher": SEARCH, "hooks": [{"type": "command", "command": command}]}]}}


def split(items: list[dict], days: float) -> tuple[list[dict], list[dict]]:
    """(tuning, held out): the held-out set is the newest `days` of searches."""
    if not items:
        return [], []
    cut = items[-1]["at"] - days * 86400
    return [it for it in items if it["at"] < cut], [it for it in items if it["at"] >= cut]


def load(path: Path) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def scored(path: Path) -> dict:
    """key -> stored answer from a scores file (one JSON line per search, the last line for a key winning)."""
    if not Path(path).exists():
        return {}
    return {r["key"]: r["answer"] for r in load(path)}


def score(items: list[dict], arm: str, path: Path, call, k: Knobs, log=lambda *_: None) -> dict:
    """Run `arm`'s model over items not yet in `path`, appending each answer; a failed call stores None."""
    done = scored(path)
    with Path(path).open("a", encoding="utf-8") as fh:
        for n, it in enumerate(items, 1):
            if it["key"] in done:
                continue
            try:
                answer = decide_scores(it, call, k) if arm == "decide" else extract_choice(it, call, k)
            except Exception as exc:  # noqa: BLE001
                log(f"{it['key']}: {type(exc).__name__}: {str(exc)[:160]}")
                answer = None
            done[it["key"]] = answer
            fh.write(json.dumps({"key": it["key"], "answer": answer}) + "\n")
            fh.flush()
            if n % 25 == 0:
                log(f"{arm}: {n} of {len(items)}")
    return done


def _spent(item: dict, kept: list[int]) -> int:
    return sum(tokens(item["hits"][p - 1]["text"]) for p in kept)


def ship(out: dict) -> dict:
    """The arm a hook runs: a local arm only when its gate holds, it beats lexical at equal tokens and keeps no more."""
    lex = out["arms"]["lexical"]
    why = []
    for a in sorted(LOCAL, key=lambda a: out["arms"][a]["tokens_kept"]):
        vs = out["vs_lexical"][a]
        if out["gates"][a]:
            why.append(f"{a}: gate fails")
        elif not (vs["won"] > vs["lost"] and vs["p"] < 0.05):
            why.append(f"{a}: does not beat lexical at equal tokens ({vs['won']} won, {vs['lost']} lost, p {vs['p']})")
        elif out["arms"][a]["tokens_kept"] > lex["tokens_kept"]:
            why.append(f"{a}: keeps {out['arms'][a]['tokens_kept']} tokens to lexical's {lex['tokens_kept']}")
        else:
            return {"arm": a, "cut": out["thresholds"][a], "why": why}
    if out["gates"]["lexical"]:
        return {"arm": "none", "cut": None, "why": why + ["lexical: " + "; ".join(out["gates"]["lexical"])]}
    return {"arm": "lexical", "cut": out["thresholds"]["lexical"], "why": why}


def report(tune: list[dict], held: list[dict], decide: dict, extract: dict, k: Knobs,
           planted: list[dict] | None = None, vocab: dict | None = None) -> dict:
    """Every arm on the held-out searches, each local arm against lexical at its own kept tokens, the gates, and the arm to ship."""
    vocab = vocab if vocab is not None else vocabulary(tune)
    lexical = {it["key"]: lexical_scores(it, vocab, k) for it in tune + held + (planted or [])}
    scores = {"decide": decide, "lexical": lexical, "combo": mean_scores(decide, lexical)}
    have = [it for it in tune if it["key"] in decide]
    cuts = {"decide": threshold(have, decide, k) if have else 0.5,
            "lexical": threshold(tune, lexical, k) if tune else 0.5,
            "combo": threshold(have, scores["combo"], k) if have else 0.5}
    arms = {a: {it["key"]: decide_keep(it, s.get(it["key"]), cuts[a], k) for it in held} for a, s in scores.items()}
    at_tokens = {a: {it["key"]: guard(it["hits"], by_position(it, _spent(it, arms[a][it["key"]])),
                                      it["query"], it["need"], k) for it in held} for a in scores}
    arms["position"] = at_tokens["decide"]
    arms["type"] = {it["key"]: guard(it["hits"], by_type(it), it["query"], it["need"], k) for it in held}
    if extract:
        arms["extract"] = {it["key"]: guard(it["hits"], extract.get(it["key"]), it["query"], it["need"], k)
                           for it in held if it["key"] in extract}
    out = {"tuning": len(have), "held_out": len(held), "threshold": cuts["decide"], "thresholds": cuts,
           "knobs": k._asdict(),
           "arms": {a: summary([it for it in held if it["key"] in kept], kept) for a, kept in arms.items()},
           "vs_position": paired(held, arms["decide"], arms["position"])}
    vs_pos = {a: paired(held, arms[a], at_tokens[a]) for a in scores}
    out["vs_lexical"] = {a: paired(held, arms[a], {it["key"]: budget_keep(it, lexical[it["key"]],
                                                                          _spent(it, arms[a][it["key"]]), k)
                                                   for it in held}) for a in LOCAL}
    rows = {a: None for a in scores}
    if planted:
        rows = {a: summary(planted, {it["key"]: decide_keep(it, s.get(it["key"]), cuts[a], k) for it in planted})
                for a, s in scores.items()}
        out["planted"] = rows["decide"]
        out["planted_by_arm"] = rows
    out["gates"] = {a: gate(out["arms"][a], vs_pos[a], rows[a]) for a in scores}
    out["gate"] = out["gates"]["decide"]
    out["ship"] = ship(out)
    return out
