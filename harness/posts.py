"""Techniques from practitioners' posts: a `techniques` feed's entries and a person's `soh propose <url>`. #993."""
from __future__ import annotations

import html
import re
import time

KIND = "techniques"
#: The source a person's proposal is sighted under.
PERSON = "person"
#: The same cut as a paper's description, which lanes.technique_route reads.
DESCRIPTION_CHARS = 600


def name_of(url: str) -> str:
    """The proposal a post is: arxiv:<id> when it is a paper, else post:<host and path>."""
    from harness import technique_triage as tt
    key = tt.key_of(url)
    return key if key.startswith("arxiv:") else f"post:{key}"


def seen(url: str, title: str, body: str, source: str):
    """One post as a technique sighting, laned by its prose as a paper is."""
    from harness import feeds, papers
    from harness import memory_store as ms
    title = " ".join(str(title or "").split())
    body = " ".join(str(body or "").split())
    lane = papers.lane_of(title, body)
    if len(f"{title}. {body}") > DESCRIPTION_CHARS:
        from harness import cuts
        cuts.cut("papers_description_chars", f"{name_of(url)}: the post kept to its head")
    return ms.Seen(name=name_of(url), source=source, url=url, why=title[:160],
                   relevance=feeds.relevance(f"{title} {body}"), lane=lane,
                   lane_source="prose" if lane else "",
                   description=f"{title}. {body}"[:DESCRIPTION_CHARS], category=ms.TECHNIQUE)


def sweep(conn, sources=None, reader=None, now: float | None = None) -> list:
    """Read every enabled `techniques` feed; each entry with a link is a technique proposal. A failed feed is recorded and skipped."""
    from harness import feeds
    from harness import memory_store as ms
    sources = feeds.load_sources() if sources is None else sources
    reader = reader or (lambda s: feeds.read(s, store=conn))
    now = time.time() if now is None else float(now)
    out = []
    for src in sources:
        if src.kind != KIND or not src.enabled:
            continue
        try:
            entries = reader(src)
        except Exception as exc:  # noqa: BLE001 - one feed's failure is its row, not the sweep's
            ms.record_source(conn, src.name, kind=src.kind, url=src.url, ok=False, error=str(exc)[:300], at=now,
                             deferred=isinstance(exc, feeds.RateLimitedFeed))
            continue
        for e in entries:
            if not e.link:
                continue
            s = seen(e.link, e.title, e.body, src.name)
            ms.record(conn, s, at=now)
            out.append(s)
        ms.record_source(conn, src.name, kind=src.kind, url=src.url, at=now)
    return out


def fetch_page(url: str) -> str:
    from harness import feeds
    return feeds.fetch(url)


def page_text(raw: str) -> tuple[str, str]:
    """(title, text) of an HTML page, scripts and styles left out."""
    from harness import feeds
    m = re.search(r"<title[^>]*>(.*?)</title>", raw or "", re.I | re.S)
    title = " ".join(html.unescape(m.group(1)).split()) if m else ""
    body = re.sub(r"<(script|style|head)\b.*?</\1>", " ", raw or "", flags=re.I | re.S)
    return title, feeds.strip_html(body)


def propose(conn, url: str, title: str = "", note: str = "", fetch=None, now: float | None = None):
    """A person's technique: the page's title and text unless a title is given, then the next triage reads it."""
    from harness import memory_store as ms
    body = note
    if not title:
        title, text = page_text((fetch or fetch_page)(url))
        body = " ".join(x for x in (note, text) if x)
    s = seen(url, title or url, body, PERSON)
    ms.record(conn, s, at=now)
    return s
