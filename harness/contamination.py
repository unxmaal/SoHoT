"""Contamination signals: declared training data, a prefix-completion probe, scores without overlap. #470."""
from __future__ import annotations

import re
import time
from pathlib import Path

PREFIX_WORDS = 32
TARGET_WORDS = 16
#: Share of the hidden continuation's leading words reproduced verbatim that counts as a hit.
HIT = 0.5
MAX_TOKENS = 1024
#: The limit a probe records when the reply ended at MAX_TOKENS or came back empty. #700.
LIMIT = "contamination_max_tokens"
_THINK = re.compile(r"<think>.*?(</think>|$)", re.S)
INSTRUCTION = ("Continue the following text exactly as it appears in its original source. "
               "Output only the continuation, with no commentary.\n\n")


class Cut(RuntimeError):
    """The probe's reply ended at our token budget or held no answer; a limit, never a miss. #700."""

    def __init__(self, why: str, max_tokens: int):
        self.limit = f"{LIMIT}>{max_tokens}"
        super().__init__(f"limit {self.limit}: {why}")


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", (text or "").lower())


def declared(source: str, datasets) -> bool:
    """Whether a dataset a card declares is this source or a mirror of it, by repo name tokens."""
    src = (source or "").strip().lower()
    mine = set(_words(src.split("/")[-1]))
    for d in datasets or ():
        d = str(d).strip().lower()
        if d == src or (mine and mine <= set(_words(d.split("/")[-1]))):
            return True
    return False


def split_prefix(text: str):
    """(the shown prefix, the hidden continuation) on word boundaries; None if too short."""
    words = (text or "").split()
    if len(words) < PREFIX_WORDS + TARGET_WORDS:
        from harness import cuts
        cuts.cut("contamination_probe_words", "source item too short to probe", kept=0, dropped=1)
        return None
    return (" ".join(words[:PREFIX_WORDS]),
            " ".join(words[PREFIX_WORDS:PREFIX_WORDS + TARGET_WORDS]))


def overlap(continuation: str, target: str) -> float:
    """Leading words of the target the continuation reproduces verbatim, as a share."""
    got, want = _words(continuation), _words(target)
    if not want:
        return 0.0
    n = 0
    for a, b in zip(got, want):
        if a != b:
            break
        n += 1
    return round(n / len(want), 4)


def family(case_id: str) -> str:
    return str(case_id).split("-", 1)[0]


def probe(conn, model: str, cases, ask, at: float | None = None, lane: str = "decide") -> list[dict]:
    """Ask `model` to continue each case's source text from a prefix and record what it reproduced."""
    from harness import memory_store as ms
    at = time.time() if at is None else float(at)
    out = []
    for case in cases:
        row = {"model": model, "lane": lane, "case_id": case.id, "family": family(case.id),
               "overlap": None, "detail": "", "hit_limit": ""}
        parts = split_prefix(getattr(case, "context", "") or "")
        if parts is None:
            row.update(outcome="skipped", detail="source text too short to probe")
        else:
            prefix, target = parts
            try:
                got = ask(model, INSTRUCTION + prefix)
                row["overlap"] = overlap(got, target)
                row["outcome"] = "hit" if row["overlap"] >= HIT else "miss"
                row["detail"] = (got or "")[:200]
            except Cut as exc:
                row.update(outcome="error", detail=str(exc), hit_limit=exc.limit)
            except Exception as exc:  # noqa: BLE001
                row.update(outcome="error", detail=str(exc))
        ms.record_probe(conn, at=at, **row)
        out.append(row)
    return out


def gateway_ask(base: str, post=None, max_tokens: int = MAX_TOKENS):
    """A greedy non-thinking chat call through the gateway with this machine's key; returns the answer or raises Cut."""
    from harness import gateway_key
    if post is None:
        import httpx
        post = httpx.post

    def ask(model: str, prompt: str) -> str:
        r = post(f"{base.rstrip('/')}/v1/chat/completions",
                 json={"model": model, "temperature": 0, "max_tokens": max_tokens,
                       "chat_template_kwargs": {"enable_thinking": False},
                       "messages": [{"role": "user", "content": prompt}]},
                 headers={"Content-Type": "application/json", **gateway_key.headers()},
                 timeout=600)
        r.raise_for_status()
        choice = (r.json().get("choices") or [{}])[0]
        text = _THINK.sub("", (choice.get("message") or {}).get("content") or "").strip()
        if not text:
            raise Cut("no answer in content", max_tokens)
        # Only the leading TARGET_WORDS are scored, so a capped reply that reaches them carries the whole signal.
        if choice.get("finish_reason") == "length" and len(_words(text)) < TARGET_WORDS:
            raise Cut("ended at the token budget", max_tokens)
        return text
    return ask


def with_and_without(conn, lane: str, cases_root: Path) -> list[dict]:
    """Each candidate's newest pass rate on the lane, with and without cases its card trained on."""
    from evals import benchmark_import as bi
    from harness import memory_store as ms
    sources = bi.case_sources(Path(cases_root) / lane)
    out = []
    for t in ms.training(conn):
        if not t["alias"]:
            continue
        run = conn.execute(
            "SELECT MAX(r.run_id) AS run FROM results r JOIN runs u ON u.id = r.run_id "
            "WHERE u.lane = ? AND r.candidate = ?", (lane, t["alias"])).fetchone()
        if not run or run["run"] is None:
            continue
        rows = [(str(r["case_id"]).split("#", 1)[0], bool(r["passed"])) for r in conn.execute(
            "SELECT case_id, passed FROM results WHERE run_id = ? AND candidate = ?",
            (run["run"], t["alias"]))]
        hot = sorted({c for c, _ in rows if declared(sources.get(c, ""), t["datasets"])})
        clean = [p for c, p in rows if c not in hot]
        out.append({"candidate": t["alias"], "model": t["candidate"], "run_id": run["run"],
                    "all": round(sum(p for _, p in rows) / len(rows), 4), "n_all": len(rows),
                    "clean": round(sum(clean) / len(clean), 4) if clean else None,
                    "n_clean": len(clean), "overlapping": hot})
    return out
