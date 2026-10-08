"""Techniques from HuggingFace daily papers: one technique proposal per paper, laned by its prose. #576."""
from __future__ import annotations

import time

SOURCE = "hf-daily-papers"
KIND = "papers"
API = "https://huggingface.co/api/daily_papers"
PAGE = "https://huggingface.co/papers/{id}"
#: The most days one sweep catches up on, one request per day.
MAX_DAYS = 7
DESCRIPTION_CHARS = 600


def _get_json(url: str, params: dict | None = None):
    from harness import ratelimit
    return ratelimit.get_json(url, params)


def _day(t: float) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(t))


def due_dates(last_read: float | None, now: float, force: bool = False) -> list[str | None]:
    """The days to ask for: [None] (today's page) on a first read or a forced one, else each missed day."""
    if force or not last_read:
        return [None]
    days = []
    t = now
    while _day(t) > _day(last_read) and len(days) < MAX_DAYS:
        days.append(_day(t))
        t -= 86400
    return sorted(days)


def lane_of(title: str, summary: str) -> str:
    """The lane whose task the paper names; a serving or general LLM paper has none. #631."""
    from harness import lanes
    got = lanes.technique_route(title, summary)
    return got if got in lanes.ALL else ""


def proposal(entry: dict):
    """One daily-papers entry as a Seen, or None when it carries no paper id."""
    from harness import feeds
    from harness import memory_store as ms
    paper = entry.get("paper") or {}
    pid = str(paper.get("id") or "").strip()
    if not pid:
        return None
    title = " ".join(str(paper.get("title") or entry.get("title") or "").split())
    summary = " ".join(str(paper.get("summary") or entry.get("summary") or "").split())
    lane = lane_of(title, summary)
    return ms.Seen(name=f"arxiv:{pid}", source=SOURCE, url=PAGE.format(id=pid),
                   why=title[:160], relevance=feeds.relevance(f"{title} {summary}"),
                   lane=lane, lane_source="prose" if lane else "",
                   description=f"{title}. {summary}"[:DESCRIPTION_CHARS],
                   category=ms.TECHNIQUE)


def sweep(conn, get=None, now: float | None = None, force: bool = False) -> list:
    """Read the days not yet read, record each paper as a technique sighting, and the read itself."""
    from harness import memory_store as ms
    from harness.ratelimit import RateLimited
    get = get or _get_json
    now = time.time() if now is None else float(now)
    row = ms.source_row(conn, SOURCE) or {}
    days = due_dates(row.get("last_read_at"), now, force)
    out = []
    for day in days:
        try:
            entries = get(API, {} if day is None else {"date": day}) or []
        except RateLimited as exc:
            ms.record_source(conn, SOURCE, kind=KIND, url=API, deferred=True,
                             error=str(exc), at=now)
            return out
        except Exception as exc:  # noqa: BLE001
            ms.record_source(conn, SOURCE, kind=KIND, url=API, ok=False,
                             error=str(exc), at=now)
            return out
        for entry in entries:
            seen = proposal(entry)
            if seen is None:
                continue
            ms.record(conn, seen, at=now)
            out.append(seen)
    if days:
        ms.record_source(conn, SOURCE, kind=KIND, url=API, at=now)
    return out
