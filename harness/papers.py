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
    """The days to ask for: [None] (the latest published page) on a first or forced read, else the missed days through yesterday UTC, oldest first; today is not published at the 01:00Z sweep. #704, #859."""
    if force or not last_read:
        return [None]
    days = []
    t = now - 86400
    while _day(t) > _day(last_read):
        days.append(_day(t))
        t -= 86400
    return sorted(days)[:MAX_DAYS]


def read_through(days: list, now: float) -> float:
    """What last_read becomes: the end of the newest day read (yesterday for the undated page), so the next sweep starts on the day after. #859."""
    import calendar
    newest = days[-1] if days and days[-1] is not None else _day(now - 86400)
    end = float(calendar.timegm(time.strptime(newest, "%Y-%m-%d"))) + 86399
    return min(end, now)


class Unpublished(Exception):
    """HF answered 400 for a dated page: that day is not published yet. #859."""


def _read_day(get, day):
    import httpx
    try:
        return get(API, {} if day is None else {"date": day}) or []
    except httpx.HTTPStatusError as exc:
        if day is not None and exc.response.status_code == 400:
            raise Unpublished(f"{day} not published yet (HTTP 400)") from exc
        raise


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
    out, read = [], []

    def stop(**how):
        if read:
            ms.record_source(conn, SOURCE, kind=KIND, url=API, at=read_through(read, now))
        ms.record_source(conn, SOURCE, kind=KIND, url=API, at=now, **how)
        return out

    for day in days:
        try:
            entries = _read_day(get, day)
        except (RateLimited, Unpublished) as exc:
            return stop(deferred=True, error=str(exc))
        except Exception as exc:  # noqa: BLE001
            return stop(ok=False, error=str(exc))
        for entry in entries:
            seen = proposal(entry)
            if seen is None:
                continue
            ms.record(conn, seen, at=now)
            out.append(seen)
        read.append(day)
    if days:
        ms.record_source(conn, SOURCE, kind=KIND, url=API, at=read_through(days, now))
    return out
