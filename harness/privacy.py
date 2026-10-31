"""Find one person's home setup in text meant for strangers. Issue #136.

This repo is public. Every issue, PR body and doc is published, and prose
describing the author's desk -- a named volume, a spare drive in a particular
tower, which box plays games -- teaches a reader nothing and dates fast.

A MEASUREMENT KEEPS ITS HARDWARE. "Measured on an RTX 4070" is provenance and
must survive; the card is part of the instrument. What this refuses is the
domestic arrangement around it.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from harness import repo

#: Opt out when a match is genuinely generic or is the anti-pattern being
#: quoted: put the marker on the line, or on the line above it for something
#: that will not take a trailing comment. Costs a visible marker, which is the
#: point -- an exemption should be readable as a decision.
ALLOW = re.compile(r"privacy-ok")

#: (name, pattern, what to write instead). Ordered most specific first so a
#: line reports the sharpest reason rather than the broadest.
PATTERNS: list[tuple[str, re.Pattern[str], str]] = [
    (
        "named-volume",
        # A real volume name carries a lowercase letter. ALL-CAPS is the
        # placeholder convention here, so /Volumes/FAST passes and
        # /Volumes/Models does not. /System/Volumes is Apple's, not a drive.
        re.compile(r"(?<!System)/Volumes/(?=\w*[a-z])\w+"),
        "one person's drive; use an ALL-CAPS placeholder or $HF_ROOT",
    ),
    (
        "home-path",
        re.compile(r"/(?:Users|home)/(?!<)(?!\w*\b(?:you|user|USER)\b)\w+/"),
        "a real account name; use ~/ or a placeholder",
    ),
    (
        "private-host",
        # `.local` is mDNS, and a real hostname there identifies a person's
        # LAN. `cluster.local` is Kubernetes' own DNS suffix, byte-identical on
        # every cluster on earth, so `postgres.localharness.svc.cluster.local`
        # is a protocol constant rather than an address. Excluded by name
        # rather than by loosening the rule.
        re.compile(r"\b(?:10|192\.168|172\.(?:1[6-9]|2\d|3[01]))\.\d+\.\d+\b"
                   r"|(?<![\w<])(?!cluster\.local)[a-z0-9-]+\.local\b"),
        "a LAN address; use <host> or a documented placeholder",
    ),
    (
        "spare-drive",
        re.compile(r"\bspare\s+(?:nvme|ssd|drive|disk)\b", re.I),
        "how one machine was built; say what the machine IS, not how it got there",
    ),
    (
        "same-box",
        re.compile(r"\b(?:in|on)\s+(?:the|that)\s+same\s+"
                   r"(?:desktop|tower|case|chassis)\b", re.I),
        "a physical arrangement nobody else has",
    ),
    (
        "gaming-box",
        re.compile(r"\b(?:plays?\s+games|main\s+job\s+is\s+games|"
                   r"gaming\s+(?:box|rig|desktop|machine))\b", re.I),
        "what this machine does after hours; say 'a machine with a day job'",
    ),
    (
        "machine-nickname",
        re.compile(r"\b(?:the|this|my|our)\s+mini\b", re.I),
        "a nickname for one box; name the runtime or the role",
    ),
]

#: People's names cannot ship in this file -- the checker would publish what it
#: exists to hide. One name per line in an untracked file, or in LH_PRIVATE_NAMES
#: separated by commas. Absent means the structural patterns still run.
NAMES_FILE = ".privacy-names"


ROOT = Path(__file__).resolve().parent.parent


def main_checkout(root: Path) -> Path | None:
    """The checkout `root`'s git worktree belongs to, or None outside git. #1308."""
    try:
        _, common = repo.git_dirs(root)
    except (OSError, IndexError, UnicodeDecodeError):
        return None
    return common.parent if common.is_dir() else None


def name_files(root: Path) -> list[Path]:
    """`root`'s names file, and the main checkout's, which a worktree lacks. #1308."""
    here = root / NAMES_FILE
    main = main_checkout(root)
    there = main / NAMES_FILE if main else None
    return [here] + ([there] if there and there.resolve() != here.resolve() else [])


def names(root: Path) -> list[str]:
    import os

    raw = os.environ.get("LH_PRIVATE_NAMES", "")
    for f in name_files(root):
        if f.exists():
            raw += "," + f.read_text(encoding="utf-8")
    found = [n.strip() for n in raw.replace("\n", ",").split(",") if n.strip()]
    return list(dict.fromkeys(found + home_names()))


#: Names an importer learned on this machine (film titles, a library's folder), one per line. #1207.
HOME_NAMES_FILE = "private-names.txt"
#: Shorter names are common words, not something to hide.
MIN_HOME_NAME = 4


def _home_file() -> Path:
    from harness import paths
    return paths.home() / HOME_NAMES_FILE


def home_names() -> list[str]:
    """The names importers registered under this machine's home, or [] where none were."""
    f = _home_file()
    if not f.is_file():
        return []
    return [n.strip() for n in f.read_text(encoding="utf-8").splitlines() if n.strip()]


def register(found) -> list[str]:
    """Add names to the home's list, once each; returns the ones added."""
    have = set(home_names())
    new, short = [], 0
    for n in found:
        n = " ".join(str(n or "").split())
        short += 0 < len(n) < MIN_HOME_NAME
        if len(n) >= MIN_HOME_NAME and n not in have:
            have.add(n)
            new.append(n)
    if short:
        from harness import cuts
        cuts.cut("vision_min_private_name", "privacy.register: names too short to hide", dropped=short)
    if new:
        f = _home_file()
        f.parent.mkdir(parents=True, exist_ok=True)
        with f.open("a", encoding="utf-8") as out:
            out.writelines(f"{n}\n" for n in new)
    return new


def name_pattern(root: Path, more=()) -> tuple[str, re.Pattern[str], str] | None:
    found = names(root) + [n for n in more if n]
    if not found:
        return None
    alt = "|".join(re.escape(n) for n in sorted(set(found), key=len, reverse=True))
    return ("person-name", re.compile(rf"\b(?:{alt})\b", re.I),
            "a real person; say the role, or restructure to passive")


#: What git tracks, because that is exactly what gets published. An ignored
#: fixture full of local paths is nobody's business but this machine's.
TEXT_SUFFIXES = {".md", ".py", ".sh", ".yaml", ".yml", ".toml", ".txt", ".cfg"}


@dataclass(frozen=True)
class Finding:
    origin: str
    line: int
    name: str
    advice: str
    excerpt: str

    def __str__(self) -> str:
        return f"{self.origin}:{self.line}: {self.name}: {self.excerpt}\n    -> {self.advice}"


def scan(text: str, origin: str,
         extra: tuple[str, re.Pattern[str], str] | None = None) -> list[Finding]:
    out: list[Finding] = []
    patterns = PATTERNS + ([extra] if extra else [])
    lines = text.splitlines()
    for n, raw in enumerate(lines, 1):
        if ALLOW.search(raw) or (n > 1 and ALLOW.search(lines[n - 2])):
            continue
        for name, pat, advice in patterns:
            m = pat.search(raw)
            if m:
                out.append(Finding(origin, n, name, advice, m.group(0).strip()))
                break
    return out


#: A detector's own fixtures must contain what it detects, so these two are
#: never scanned. Nothing else gets an exemption without a privacy-ok marker.
SELF = {"harness/privacy.py", "tests/test_harness_privacy.py"}


def tracked(root: Path) -> list[Path]:
    """What a push would publish, not what a commit already did. See
    harness/repo.publishable: a check that cannot see the file you just wrote
    goes green on your desk and red on the runner, on the same content."""
    return repo.publishable(root)


def scan_paths(root: Path) -> list[Finding]:
    extra = name_pattern(root)
    out: list[Finding] = []
    for p in tracked(root):
        rel = p.relative_to(root).as_posix()
        if p.suffix not in TEXT_SUFFIXES or rel in SELF:
            continue
        out.extend(scan(p.read_text(encoding="utf-8", errors="replace"), rel, extra))
    return out


def _gh(*args: str) -> list[dict]:
    r = subprocess.run(("gh", *args), capture_output=True, text=True, check=True)
    return json.loads(r.stdout)


def _api(path: str) -> list[dict]:
    return _gh("api", path)


#: Comment listings of the whole repo: conversation comments on issues and PRs, and PR review comments. #1296.
COMMENT_LISTINGS = ("repos/{owner}/{repo}/issues/comments", "repos/{owner}/{repo}/pulls/comments")


def comments(api=None) -> list[tuple[str, str]]:
    """(origin, body) of every comment, read page by page until a short page. #1296."""
    from harness import github
    api = api or _api
    out = []
    for listing in COMMENT_LISTINGS:
        page = 1
        while True:
            rows = api(f"{listing}?per_page={github.PER_PAGE}&page={page}")
            for r in rows:
                hit = re.search(r"/(pull|issues)/(\d+)", r.get("html_url") or "")
                where = f"{'pr' if hit and hit.group(1) == 'pull' else 'issue'}#{hit.group(2) if hit else '?'}"
                out.append((f"{where} comment {r.get('id')}", r.get("body") or ""))
            if len(rows) < github.PER_PAGE:
                break
            page += 1
    return out


def scan_github(page: int = 300,
                extra: tuple[str, re.Pattern[str], str] | None = None,
                gh=None, api=None) -> tuple[list[Finding], dict[str, int]]:
    """Every issue, PR and comment, which are published the moment they are filed; returns the findings and how many of each were read."""
    gh = gh or _gh
    out: list[Finding] = []
    counts = {"issue": 0, "pr": 0, "comment": 0}
    for kind, cmd in (("issue", "issue"), ("pr", "pr")):
        limit = page
        while True:
            rows = gh(cmd, "list", "--state", "all", "--limit", str(limit),
                      "--json", "number,title,body")
            # A full answer may be a truncated one: ask again for more until fewer come back. #700.
            if len(rows) < limit:
                break
            limit *= 2
        for r in rows:
            body = f"{r['title']}\n{r['body'] or ''}"
            out.extend(scan(body, f"{kind}#{r['number']}", extra))
        counts[kind] = len(rows)
    said = comments(api)
    for origin, body in said:
        out.extend(scan(body, origin, extra))
    counts["comment"] = len(said)
    return out, counts


#: Revisions GitHub returns per body or comment in one query; more and the history scan refuses rather than skip.
HISTORY_EDITS = 100
#: Comments per issue or PR one history query reads; more and the scan refuses.
HISTORY_COMMENTS = 100
_EDITS = f"userContentEdits(first: {HISTORY_EDITS}) {{ totalCount nodes {{ editedAt diff }} }}"
_HISTORY = ("query($owner: String!, $name: String!, $n: Int!) { repository(owner: $owner, name: $name) { "
            "issueOrPullRequest(number: $n) { ... on Issue { %s comments(first: %d) { totalCount nodes "
            "{ databaseId %s } } } ... on PullRequest { %s comments(first: %d) { totalCount nodes "
            "{ databaseId %s } } } } } }") % (_EDITS, HISTORY_COMMENTS, _EDITS, _EDITS, HISTORY_COMMENTS, _EDITS)


def _whole(conn: dict, what: str) -> list[dict]:
    nodes = conn.get("nodes") or []
    if conn.get("totalCount", len(nodes)) > len(nodes):
        raise ValueError(f"privacy history: {what} has {conn['totalCount']}, one query reads {len(nodes)}")
    return nodes


def _graphql(number: int) -> dict:
    """{edits, comments: [{databaseId, edits}]} of one issue or PR, every revision GitHub keeps."""
    got = _gh("api", "graphql", "-F", "owner={owner}", "-F", "name={repo}", "-F", f"n={number}",
              "-f", f"query={_HISTORY}")
    node = got["data"]["repository"]["issueOrPullRequest"] or {}
    return {"edits": _whole(node.get("userContentEdits") or {}, f"#{number}'s edits"),
            "comments": [{"databaseId": c["databaseId"],
                          "edits": _whole(c.get("userContentEdits") or {}, f"#{number} comment {c['databaseId']}")}
                         for c in _whole(node.get("comments") or {}, f"#{number}'s comments")]}


def scan_history(numbers, extra: tuple[str, re.Pattern[str], str] | None = None, graphql=None) -> list[Finding]:
    """Every earlier revision of these issues and PRs and of their comments, which GitHub still shows. #1296."""
    out: list[Finding] = []
    for n in numbers:
        got = (graphql or _graphql)(int(n))
        for e in got["edits"]:
            out.extend(scan(e.get("diff") or "", f"#{n} edit {e.get('editedAt')}", extra))
        for c in got["comments"]:
            for e in c["edits"]:
                out.extend(scan(e.get("diff") or "", f"#{n} comment {c['databaseId']} edit {e.get('editedAt')}", extra))
    return out


def check_post(text: str, root: Path | None = None) -> list[Finding]:
    """What the scan finds in text about to be posted to the tracker; [] when it may go. #1296."""
    return scan(text, "post", name_pattern(ROOT if root is None else root))


#: gh flags whose value is published text, and those naming a file of it ("-" is stdin).
POST_TEXT = ("--title", "-t", "--body", "-b")
POST_FILE = ("--body-file", "-F")


def post_texts(args, stdin=None) -> tuple[list[str], str | None]:
    """The text a gh issue or pr command would publish, and the stdin it reads its body from."""
    texts, fed = [], None
    i = 0
    while i < len(args):
        flag, eq, inline = args[i].partition("=")
        if flag in POST_TEXT + POST_FILE:
            if eq:
                value = inline
            else:
                i += 1
                value = args[i] if i < len(args) else ""
            if flag in POST_FILE:
                if value == "-":
                    fed = (stdin or sys.stdin).read()
                    value = fed
                else:
                    value = Path(value).read_text(encoding="utf-8")
            texts.append(value)
        i += 1
    return texts, fed


def post(args) -> int:
    """Run `gh <args>` only when the text it would publish passes the scan. #1296."""
    texts, fed = post_texts(args)
    found = [f for t in texts for f in check_post(t)]
    for f in found:
        print(f, file=sys.stderr)
    if found:
        print(f"refused: {len(found)} finding(s); nothing was sent to GitHub", file=sys.stderr)
        return 1
    return subprocess.run(["gh", *args], input=fed, text=True).returncode


def add(found) -> int:
    """Register names in the home's private-names.txt, which every checkout and worktree here reads. #1296."""
    short = [n for n in found if len(" ".join(n.split())) < MIN_HOME_NAME]
    if short:
        print(f"refused: shorter than {MIN_HOME_NAME} characters, a common word: {', '.join(short)}", file=sys.stderr)
        return 2
    new = register(found)
    for n in found:
        print(f"{'added' if ' '.join(n.split()) in new else 'already registered'}: {n}")
    return 0


def expand(items) -> list[Path]:
    """Each file as given, and every file under each directory, whatever its suffix."""
    out: list[Path] = []
    for item in items:
        p = Path(item)
        if p.is_dir():
            found = sorted(f for f in p.rglob("*") if f.is_file())
            if not found:
                raise FileNotFoundError(f"privacy scan: {p} holds no files to scan")
            out.extend(found)
        elif p.exists():
            out.append(p)
        else:
            raise FileNotFoundError(f"privacy scan: {p} does not exist")
    return out


def main(argv: list[str] | None = None) -> int:
    import argparse

    argv = sys.argv[1:] if argv is None else list(argv)
    if argv[:1] == ["add"]:
        return add(argv[1:])
    if argv[:1] == ["gh"]:
        return post(argv[1:])
    ap = argparse.ArgumentParser(prog="python -m harness.privacy",
                                 description=__doc__.splitlines()[0],
                                 epilog="also: `add NAME...` registers a name; `gh ARGS...` runs gh only on clean text")
    ap.add_argument("--github", action="store_true",
                    help="also scan every issue and PR body and every comment")
    ap.add_argument("--history", nargs="+", type=int, default=None, metavar="N",
                    help="also scan every earlier revision of these issues or PRs and their comments")
    ap.add_argument("--files", nargs="+", default=None,
                    help="scan only these files; a directory means every file under it")
    a = ap.parse_args(argv)

    root = ROOT
    if a.files:
        found = [f for p in expand(a.files) for f in scan(
            p.read_text(encoding="utf-8", errors="replace"), str(p),
            name_pattern(root))]
    else:
        found = scan_paths(root)
    read = None
    if a.github:
        more, read = scan_github(extra=name_pattern(root))
        found += more
    if a.history:
        found += scan_history(a.history, extra=name_pattern(root))
    for f in found:
        print(f)
    if read is not None:
        print(f"scanned {read['issue']} issue(s), {read['pr']} PR(s) and {read['comment']} comment(s)")
    if a.history:
        print(f"scanned the edit histories of {len(a.history)} issue(s) or PR(s)")
    print(f"{len(found)} finding(s)")
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main())
