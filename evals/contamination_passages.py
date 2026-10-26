"""Passages of known training status for the contamination HIT; `uv run python -m evals.contamination_passages` rebuilds them (#727)."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from pathlib import Path

MANIFEST = Path(__file__).resolve().parent / "contamination" / "passages.jsonl"
API = "https://en.wikipedia.org/w/api.php"
SQUAD = "https://raw.githubusercontent.com/rajpurkar/SQuAD-explorer/master/dataset/{split}-v2.0.json"
GUTENBERG = "https://www.gutenberg.org/cache/epub/{id}/pg{id}.txt"
AGENT = "SoHoT contamination calibration (https://github.com/unxmaal/SoHoT)"
WIKI_LICENSE = "CC BY-SA 4.0"
#: A clean article was created after every probed model was released; an old one before SQuAD's 2016 crawl.
CLEAN_AFTER = "2026-10-10T00:00:00Z"
OLD_BEFORE = "2016-01-01T00:00:00Z"
#: Words kept per passage; the probe needs its 32-word prefix and 16 hidden words.
WORDS = 64
PER_SET = 40
#: Public-domain passages every web crawl holds many times over: (Gutenberg ebook, where the passage starts).
CANON = [
    (1342, "It is a truth universally acknowledged"), (98, "It was the best of times"),
    (2701, "Call me Ishmael"), (1, "When in the Course of human events"), (5, "We the People of the United States"),
    (10, "In the beginning God created the heaven"), (1524, "To be, or not to be"),
    (11, "Alice was beginning to get very tired"), (46, "Marley was dead"), (1399, "Happy families are all alike"),
    (5200, "One morning, when Gregor Samsa"), (1661, "To Sherlock Holmes she is always"),
    (1260, "There was no possibility of taking a walk that day"), (64317, "In my younger and more vulnerable years"),
    (4300, "Stately, plump Buck Mulligan"), (84, "You will rejoice to hear that no disaster"),
    (1041, "Shall I compare thee to a summer"), (2600, "Well, Prince, so Genoa and Lucca"),
    (174, "The studio was filled with the rich odour of roses"), (76, "You don't know about me without you have read"),
    (1400, "My father's family name being Pirrip"), (4, "Four score and seven years ago"),
    (20, "Of Mans First Disobedience"), (996, "In a village of La Mancha"),
    (1184, "On the 24th of February, 1815"), (36, "No one would have believed in the last years"),
    (35, "The Time Traveller (for so it will be convenient"), (219, "The Nellie, a cruising yawl"),
    (120, "Squire Trelawney, Dr. Livesey"), (1952, "It is very seldom that mere ordinary people"),
    (158, "Emma Woodhouse, handsome, clever, and rich"), (161, "The family of Dashwood"),
    (1727, "Tell me, O muse, of that ingenious hero"), (1001, "Midway upon the journey of our life"),
    (345, "Left Munich at 8:35 P. M."), (55, "Dorothy lived in the midst of the great Kansas prairies"),
    (768, "In the year 1801"), (2554, "On an exceptionally hot evening early in July"),
    (215, "Buck did not read the newspapers"), (113, "When Mary Lennox was sent to Misselthwaite Manor"),
]
#: Ebooks whose text carries chapter:verse numbers no quotation repeats.
VERSE_BOOKS = {10}
_VERSE = re.compile(r"\b\d+:\d+\b")


def passage(text: str, at: int = 0, verses: bool = False) -> str:
    """WORDS words from character `at`, Gutenberg italics marks dropped, and verse numbers when `verses`."""
    text = _VERSE.sub(" ", text[at:]) if verses else text[at:]
    return " ".join(text.replace("_", " ").split()[:WORDS])


def _wiki(get, **params) -> dict:
    return get(API, {"format": "json", "formatversion": "2", **params})


def extracts(get, titles: list[str]) -> dict:
    """title -> (lead paragraph as plain text, latest revision id), for up to 20 titles."""
    got = _wiki(get, action="query", prop="extracts|revisions", exintro="1", explaintext="1",
                rvprop="ids", titles="|".join(titles))
    out = {}
    for page in got.get("query", {}).get("pages", []):
        text = (page.get("extract") or "").strip()
        revs = page.get("revisions") or [{}]
        if text and "may refer to" not in text[:200]:
            out[page["title"]] = (text, revs[0].get("revid"))
    return out


def created(get, title: str) -> str:
    got = _wiki(get, action="query", prop="revisions", rvdir="newer", rvlimit="1", rvprop="timestamp", titles=title)
    pages = got.get("query", {}).get("pages", [{}])
    return ((pages[0].get("revisions") or [{}])[0]).get("timestamp", "")


def _row(kind: str, k: int, text: str, **att) -> dict:
    return {"id": f"{kind}-{k:03d}", "set": kind, "text": text, **att}


def _keep(text: str) -> bool:
    return len(text.split()) >= WORDS


def clean(get, n: int = PER_SET, after: str = CLEAN_AFTER) -> list[dict]:
    """Lead paragraphs of articles created after `after`, newest first."""
    out, cont = [], {}
    while len(out) < n:
        got = _wiki(get, action="query", list="logevents", letype="create", lenamespace="0", lelimit="100",
                    leend=after, **cont)
        titles = [e["title"] for e in got.get("query", {}).get("logevents", [])]
        for i in range(0, len(titles), 20):
            for title, (text, rev) in extracts(get, titles[i:i + 20]).items():
                when = created(get, title)
                if _keep(text) and when >= after and len(out) < n:
                    out.append(_row("clean", len(out), passage(text), title=title, revision=rev, created=when,
                                    source=f"https://en.wikipedia.org/w/index.php?oldid={rev}", license=WIKI_LICENSE))
        if "continue" not in got:
            break
        cont = got["continue"]
    return out


def squad_titles(get_bytes) -> set:
    out = set()
    for split in ("train", "dev"):
        data = json.loads(get_bytes(SQUAD.format(split=split)))
        out |= {a["title"].replace("_", " ") for a in data["data"]}
    return out


def wiki(get, squad: set, n: int = PER_SET, before: str = OLD_BEFORE, tries: int = 400) -> list[dict]:
    """Lead paragraphs of random articles created before `before` whose title is no SQuAD article."""
    out = []
    for _ in range(tries):
        if len(out) >= n:
            break
        got = _wiki(get, action="query", list="random", rnnamespace="0", rnlimit="20")
        titles = [p["title"] for p in got.get("query", {}).get("random", []) if p["title"] not in squad]
        for title, (text, rev) in extracts(get, titles).items():
            if not _keep(text) or len(out) >= n:
                continue
            when = created(get, title)
            if when and when < before:
                out.append(_row("wiki", len(out), passage(text), title=title, revision=rev, created=when,
                                source=f"https://en.wikipedia.org/w/index.php?oldid={rev}", license=WIKI_LICENSE))
    return out


def canon(get_text) -> tuple[list[dict], list[str]]:
    """(the canon passages found, the anchors not found in their ebook)."""
    out, missing = [], []
    for book, anchor in CANON:
        text = re.sub(r"\s+", " ", get_text(GUTENBERG.format(id=book)))
        at = text.find(anchor)
        got = passage(text, at, book in VERSE_BOOKS) if at >= 0 else ""
        if len(got.split()) < WORDS:
            missing.append(f"{book}: {anchor}")
            continue
        out.append(_row("canon", len(out), got, title=f"Project Gutenberg ebook {book}",
                        source=f"https://www.gutenberg.org/ebooks/{book}", license="public domain"))
    return out, missing


def manifest(path: Path = MANIFEST) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def _http():
    import httpx
    client = httpx.Client(headers={"User-Agent": AGENT}, timeout=120, follow_redirects=True)

    def get(url, params=None):
        time.sleep(0.2)
        return client.get(url, params=params).raise_for_status().json()

    def get_bytes(url):
        return client.get(url).raise_for_status().content

    def get_text(url):
        return client.get(url).raise_for_status().text
    return get, get_bytes, get_text


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=str(MANIFEST))
    ap.add_argument("--per-set", type=int, default=PER_SET)
    ap.add_argument("--canon-only", action="store_true", help="rebuild the canon rows, keep the Wikipedia ones")
    a = ap.parse_args(argv)
    get, get_bytes, get_text = _http()
    rows, missing = canon(get_text)
    if a.canon_only:
        rows += [r for r in manifest(Path(a.out)) if r["set"] != "canon"]
    else:
        rows += clean(get, a.per_set) + wiki(get, squad_titles(get_bytes), a.per_set)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(r, sort_keys=True, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    counts = {k: sum(r["set"] == k for r in rows) for k in ("clean", "canon", "wiki")}
    print(f"{out}: {counts}; sha256 {hashlib.sha256(out.read_bytes()).hexdigest()}", file=sys.stderr)
    for m in missing:
        print(f"  canon anchor not found: {m}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
