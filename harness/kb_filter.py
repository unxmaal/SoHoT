"""`soh kb-filter`: a local model keeps the KB search hits that fit the caller's need. #1334."""
from __future__ import annotations

import json
import random
import re
from pathlib import Path
from typing import NamedTuple

from harness import context_class as cc
from harness import context_report as cr
from harness.intervals import wilson
from harness.paired import sign_test

SEARCH = cc.KB_PREFIX + "search"
_AT = re.compile(r"^\[(KNOWLEDGE/[A-Z_]+|NEGATIVE|ERROR|RULE) #(\d+)\]", re.M)
_FOOT = re.compile(r"\n\n(?=\(summary view|---\n|REMINDER|RULES CHECK)")
_ID = re.compile(r"#(\d+)\b")
#: Recall the decide threshold is tuned to on the weeks before the held-out one.
TARGET = 0.96
#: Recall and its Wilson lower bound the held-out week must reach before wiring (#1334).
GATE_RECALL, GATE_LOWER = 0.95, 0.92
ARMS = ("decide", "extract", "position", "type")


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
    """The highest P(keep) cut whose recall over `items` reaches `target`, guard included."""
    cuts = sorted({s for it in items for s in scores.get(it["key"], [])}, reverse=True)
    for cut in cuts:
        if recall(items, {it["key"]: decide_keep(it, scores.get(it["key"]), cut, k) for it in items})[0] >= target:
            return cut
    return 0.0


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


def report(tune: list[dict], held: list[dict], decide: dict, extract: dict, k: Knobs,
           planted: list[dict] | None = None) -> dict:
    """Every arm on the held-out searches at the decide arm's kept tokens, and the gate."""
    have = [it for it in tune if it["key"] in decide]
    cut = threshold(have, decide, k) if have else 0.5
    arms = {"decide": {it["key"]: decide_keep(it, decide.get(it["key"]), cut, k) for it in held}}
    arms["position"] = {it["key"]: guard(it["hits"], by_position(it, sum(tokens(it["hits"][p - 1]["text"])
                                                                         for p in arms["decide"][it["key"]])),
                                         it["query"], it["need"], k) for it in held}
    arms["type"] = {it["key"]: guard(it["hits"], by_type(it), it["query"], it["need"], k) for it in held}
    if extract:
        arms["extract"] = {it["key"]: guard(it["hits"], extract.get(it["key"]), it["query"], it["need"], k)
                           for it in held if it["key"] in extract}
    out = {"tuning": len(have), "held_out": len(held), "threshold": cut, "knobs": k._asdict(),
           "arms": {a: summary([it for it in held if it["key"] in k], k) for a, k in arms.items()},
           "vs_position": paired(held, arms["decide"], arms["position"])}
    plant_row = None
    if planted:
        plant_row = summary(planted, {it["key"]: decide_keep(it, decide.get(it["key"]), cut, k) for it in planted})
        out["planted"] = plant_row
    out["gate"] = gate(out["arms"]["decide"], out["vs_position"], plant_row)
    return out
