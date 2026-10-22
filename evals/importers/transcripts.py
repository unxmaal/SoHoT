"""Requests from Claude Code sessions, linked to the merged commits that resolved them, as redacted repo-lane cases. #1095."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from evals import redact, repo
from evals.importers import Imported, history, provenance

LANE = "repo"
SOURCE = "claude-code:transcripts"
DATASET = "Claude Code session requests, redacted"
URL = "https://github.com/unxmaal/SoHoT/issues/1095"
LICENSE = "generated"
#: sha1 of the committed manifest's tasks, so a hand edit of the manifest is caught at import.
REVISION = "97d170e1550eee4afc0af065b78cda302a97674c"
MANIFEST = Path(__file__).with_name("transcripts.json")
VERSION = 1
VARIANT = "request"
#: A request this short ("merge it", "yes, go") says nothing a model could act on.
MIN_REQUEST_WORDS = 8
#: A request that resolved in more than this many merged tasks specifies none of them alone.
MAX_TASKS_PER_REQUEST = 1
#: How long before the tool output a commit's committer date may fall (hooks, a push after it), and after.
COMMIT_BEFORE_S = 1800
COMMIT_AFTER_S = 120
TRANSFORM = ("the user's own message from a Claude Code session, redacted by evals/redact.py "
             "(secrets, ids, emails, home and volume paths, hosts, IPs, pasted chat, handles, "
             "account and person names as typed placeholders); linked to the merged commit through a "
             "commit hash or PR URL printed by a tool in that request; base = fix^; fail_to_pass and "
             f"pass_to_pass from {history.RUNS} sandboxed pytest runs per side, as evals/importers/history.py")

#: Prompt sources whose words the model wrote: an accepted suggestion, a system-sent turn.
NOT_TYPED = ("suggestion_accepted", "system")
_HEX = re.compile(r"\b[0-9a-f]{7,40}\b")
#: Evidence kinds, the strongest first: a fix found by two keeps the first.
EVIDENCE = ("pr", "commit", "trailer")
_COMMIT = re.compile(r"\bgit(?:\s+-[Cc]\s+(?:\"[^\"]*\"|'[^']*'|\S+))*\s+commit\b")
_PR_URL = re.compile(r"https://github\.com/([\w.-]+)/([\w.-]+)/pull/(\d+)")
_GITHUB = re.compile(r"github\.com[:/]([\w.-]+)/([\w.-]+?)(?:\.git)?/?$")


@dataclass(frozen=True)
class Request:
    session: str
    project: str
    prompt_id: str
    at: float
    text: str


@dataclass(frozen=True)
class Evidence:
    session: str
    at: float
    anchor: float
    kind: str
    value: str


def default_root() -> Path:
    return Path(os.environ.get("SOH_CLAUDE_PROJECTS") or Path.home() / ".claude" / "projects")


def _ts(value) -> float:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def records(path: Path):
    """Each JSON line of a transcript; a torn last line is skipped."""
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if isinstance(rec, dict):
                yield rec


def _text(content) -> str:
    if isinstance(content, str):
        return content
    return "\n".join(b.get("text") or "" for b in content or [] if isinstance(b, dict) and b.get("type") == "text")


def human_text(rec: dict) -> str | None:
    """What the person typed, for a record they typed; None for tool results, reminders and other agents."""
    if rec.get("type") != "user" or rec.get("isMeta") or rec.get("isSidechain") or rec.get("isCompactSummary"):
        return None
    if str(rec.get("entrypoint") or "").startswith("sdk-") or rec.get("promptSource") in NOT_TYPED:
        return None
    origin = rec.get("origin")
    content = (rec.get("message") or {}).get("content")
    if origin is not None:
        return _text(content) if (origin or {}).get("kind") == "human" else None
    if rec.get("toolUseResult") is not None or rec.get("userType") != "external":
        return None
    if isinstance(content, list) and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
        return None
    return _text(content) or None


def sessions(root: Path) -> list[tuple[str, Path, list[Path]]]:
    """(project dir, main transcript, its subagent transcripts) for every session under `root`."""
    out = []
    for main in sorted(Path(root).glob("*/*.jsonl")):
        subs = sorted((main.parent / main.stem / "subagents").glob("*.jsonl"))
        out.append((main.parent.name, main, subs))
    return out


def _tool_outputs(recs):
    """(prompt id, time, command, output) of every Bash call in `recs` that has a result."""
    calls = {}
    for rec in recs:
        content = (rec.get("message") or {}).get("content")
        if not isinstance(content, list):
            continue
        for b in content:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "tool_use" and b.get("name") == "Bash":
                calls[b.get("id")] = str((b.get("input") or {}).get("command") or "")
            elif b.get("type") == "tool_result" and b.get("tool_use_id") in calls:
                yield rec.get("promptId"), _ts(rec.get("timestamp")), calls.pop(b["tool_use_id"]), _text(b.get("content"))


def evidence_in(command: str, output: str) -> list[tuple[str, str]]:
    """(kind, value) a command's output proves was written: commit hashes from `git commit`, PR URLs from `gh pr create`."""
    out = []
    if _COMMIT.search(command):
        out += [("commit", h) for h in dict.fromkeys(_HEX.findall(output))]
    if "gh pr create" in command:
        out += [("pr", f"{o}/{n.removesuffix('.git')}#{p}") for o, n, p in dict.fromkeys(_PR_URL.findall(output))]
    return out


def scan_session(session: str, project: str, main: Path, subs) -> tuple[list[Request], list[Evidence], set]:
    """The person's requests, the evidence its tools printed anchored at its prompt's start, and the session's URLs."""
    started, requests, found, urls = {}, [], [], set()
    main_recs = list(records(main))
    for rec in main_recs:
        att = rec.get("attachment") or {}
        if att.get("type") == "remote_session_change" and str(att.get("url") or "").startswith("https://"):
            urls.add(att["url"])
        pid, at = rec.get("promptId"), _ts(rec.get("timestamp"))
        if pid and at:
            started.setdefault(pid, at)
        text = human_text(rec)
        if text is not None and at:
            requests.append(Request(session, project, pid or str(rec.get("uuid")), at, text))
    for i, recs in enumerate([main_recs] + [list(records(s)) for s in subs]):
        spawned = next((r.get("promptId") for r in recs if r.get("promptId")), None) if i else None
        for pid, at, cmd, output in _tool_outputs(recs):
            anchor = started.get(spawned or pid) or at
            found += [Evidence(session, at, anchor, k, v) for k, v in evidence_in(cmd, output)]
    return sorted(requests, key=lambda r: r.at), found, urls


_TRAILER = re.compile(r"^Claude-Session:\s*(\S+)\s*$", re.M)
_SQUASH = re.compile(r"\(#\d+\)$")


def trailers(repos, url_session: dict) -> dict[str, list[Evidence]]:
    """session -> trailer evidence: each local commit naming that session's URL, anchored at its commit time.

    A PR's squash on main is left out: its time is the merge, which can fall under a later request.
    """
    out = defaultdict(list)
    for r in repos:
        got = subprocess.run(["git", "-C", str(r.path), "log", "--all", "-F", "--grep=Claude-Session:",
                              "--format=%H%x00%ct%x00%s%x00%B%x1e"], capture_output=True, text=True)
        for row in got.stdout.split("\x1e"):
            parts = row.strip("\n").split("\0")
            if len(parts) < 4 or _SQUASH.search(parts[2]):
                continue
            for url in _TRAILER.findall(parts[3]):
                if url in url_session:
                    t = float(parts[1])
                    out[url_session[url]].append(Evidence(url_session[url], t, t, "trailer", f"{r.path}\0{parts[0]}"))
    return out


def request_for(requests: list[Request], anchor: float) -> Request | None:
    """The person's last request at or before `anchor`: the one the work was done under."""
    got = None
    for r in requests:
        if r.at <= anchor:
            got = r
    return got


def screen_request(text: str) -> str | None:
    body = text.strip()
    if re.match(r"<[\w-]+>", body) or re.match(r"/[\w:-]+(\s|$)", body) or body.startswith("[Request interrupted"):
        return "command"
    if len(body.split()) < MIN_REQUEST_WORDS:
        return "request_too_short"
    return None


@dataclass(frozen=True)
class LocalRepo:
    path: Path
    url: str
    slug: str
    owner: str
    name: str


def https_url(url: str) -> str:
    m = _GITHUB.search(url.strip())
    return f"https://github.com/{m.group(1)}/{m.group(2)}.git" if m else url.strip()


def local_repos(roots) -> list[LocalRepo]:
    """Every main checkout (a .git directory, not a worktree's .git file) under `roots`, with its origin."""
    out = []
    for root in roots:
        for git_dir in sorted(Path(root).glob("*/*/.git")) + sorted(Path(root).glob("*/.git")):
            if not git_dir.is_dir():
                continue
            got = subprocess.run(["git", "-C", str(git_dir.parent), "remote", "get-url", "origin"],
                                 capture_output=True, text=True)
            url = got.stdout.strip() if got.returncode == 0 else ""
            m = _GITHUB.search(url)
            owner, name = (m.group(1), m.group(2)) if m else ("", git_dir.parent.name)
            out.append(LocalRepo(git_dir.parent, https_url(url) if m else url, name.lower(), owner, name))
    return out


def resolve(repos: list[LocalRepo], tokens) -> dict[str, list[tuple[LocalRepo, str, float]]]:
    """token -> (repo, full sha, committer time) for each local repo holding a commit it abbreviates."""
    tokens = sorted(set(tokens))
    out = defaultdict(list)
    if not tokens:
        return out
    for r in repos:
        got = subprocess.run(["git", "-C", str(r.path), "cat-file", "--batch-check=%(objectname) %(objecttype)"],
                             input="".join(f"{t}\n" for t in tokens), capture_output=True, text=True)
        rows = got.stdout.splitlines()
        hits = {t: row.split()[0] for t, row in zip(tokens, rows) if row.endswith(" commit")}
        if not hits:
            continue
        shown = subprocess.run(["git", "-C", str(r.path), "show", "-s", "--format=%H %ct", *sorted(set(hits.values()))],
                               capture_output=True, text=True).stdout.split()
        when = {shown[i]: float(shown[i + 1]) for i in range(0, len(shown) - 1, 2)}
        for t, sha in hits.items():
            if sha in when:
                out[t].append((r, sha, when[sha]))
    return out


_PRS = ("query($owner:String!,$name:String!,$endCursor:String){repository(owner:$owner,name:$name){"
        "pullRequests(first:100,after:$endCursor){pageInfo{hasNextPage endCursor} nodes{number state "
        "mergeCommit{oid} commits(first:100){nodes{commit{oid}}}}}}}")
_ROW = ".data.repository.pullRequests.nodes[] | [.number, .state, (.mergeCommit.oid // \"\"), [.commits.nodes[].commit.oid]]"


def _gh(*args) -> str:
    got = subprocess.run(["gh", *args], capture_output=True, text=True)
    if got.returncode:
        raise RuntimeError(f"gh {args[0]} {args[1]}: {got.stderr.strip()[-300:]}")
    return got.stdout


def pulls(owner: str, name: str) -> dict:
    """{"private": bool, "prs": {n: (state, merge sha)}, "by_commit": {sha: [n, ...]}} from GitHub."""
    private = json.loads(_gh("repo", "view", f"{owner}/{name}", "--json", "isPrivate"))["isPrivate"]
    prs, by_commit = {}, defaultdict(list)
    for line in _gh("api", "graphql", "--paginate", "-f", f"owner={owner}", "-f", f"name={name}",
                    "-f", f"query={_PRS}", "--jq", _ROW).splitlines():
        number, state, merge, commits = json.loads(line)
        prs[number] = (state, merge)
        for sha in commits:
            by_commit[sha].append(number)
    return {"private": bool(private), "prs": prs, "by_commit": dict(by_commit)}


def _has_path(mirror: Path, sha: str, path: str) -> bool:
    return not subprocess.run(["git", "--git-dir", str(mirror), "cat-file", "-e", f"{sha}:{path}"],
                              capture_output=True).returncode


def landing(sha: str, index: dict, mirror: Path) -> tuple[int | None, str | None, str | None]:
    """(PR, merged fix sha, drop reason) for a commit: the merge of the PR that carried it, or itself if it is on main."""
    merged = sorted(n for n in index["by_commit"].get(sha, []) if index["prs"][n][0] == "MERGED")
    if merged:
        return merged[0], index["prs"][merged[0]][1], None
    if index["by_commit"].get(sha):
        return index["by_commit"][sha][0], None, "pr_not_merged"
    if repo._has(mirror, sha) and not subprocess.run(
            ["git", "--git-dir", str(mirror), "merge-base", "--is-ancestor", sha, "HEAD"]).returncode:
        return None, sha, None
    return None, None, "not_landed"


def describe(mirror: Path, fix: str) -> dict | str:
    """A history-shaped candidate for the change `fix` made over its first parent, or a drop reason."""
    parents = history.git(mirror, "rev-list", "--parents", "-n", "1", fix).split()[1:]
    if not parents:
        return "root_commit"
    base = parents[0]
    files = {}
    for row in history.git(mirror, "diff", "--numstat", "--no-renames", base, fix).splitlines():
        added, deleted, path = row.split("\t")
        files[path] = 10 ** 6 if added == "-" else int(added) + int(deleted)
    source = sorted(p for p in files if not repo.is_test_path(p))
    context, new = history.split_new(mirror, base, fix, source)
    date, subject = history.git(mirror, "show", "-s", "--format=%cI%x00%s", fix).strip().split("\0", 1)
    return {"fix": fix, "base": base, "date": date[:10], "subject": subject, "source_files": source,
            "context_files": context, "new_files": new,
            "test_files": sorted(p for p in files if repo.is_test_path(p)),
            "lines": sum(files[p] for p in source)}


def source_for(url: str, slug: str) -> history.Repo:
    """The history source registered for this repo, whose markers, pytest args and extras its tests need; else a bare one."""
    return next((r for r in history.repos() if r.url == url),
                history.Repo(slug, slug, url, "", "", markers="", pytest_args=(), extras=()))


def session_hash(session: str) -> str:
    return hashlib.sha256(session.encode("utf-8")).hexdigest()[:16]


def _unit(stats, project, request, why=None):
    s = stats.setdefault(project, {"sessions": set(), "requests": set(), "linked": set(), "tasks": 0,
                                   "dropped": Counter()})
    if request is not None:
        s["sessions"].add(request.session)
        s["linked"].add((request.session, request.prompt_id))
    if why:
        s["dropped"][why] += 1
    return s


def link(scanned, repos, index_of, mirror_of) -> tuple[list[dict], dict]:
    """Candidate tasks (one per request and merged fix) from scanned sessions, and per-project counts with drops."""
    stats = {}
    every = [e for _, (_, found, _) in scanned for e in found]
    hits = resolve(repos, {e.value for e in every if e.kind == "commit"})
    by_slug = {r.slug: r for r in repos if r.owner}
    units = {}
    for session, (requests, found, _) in scanned:
        for e in found:
            req = request_for(requests, e.anchor)
            if e.kind == "trailer":
                path, sha = e.value.split("\0")
                r, pr = next(x for x in repos if str(x.path) == path), None
            elif e.kind == "commit":
                near = [(r, sha) for r, sha, t in hits.get(e.value, [])
                        if e.at - COMMIT_BEFORE_S <= t <= e.at + COMMIT_AFTER_S]
                if not near:
                    continue
                if len({r.path for r, _ in near}) > 1:
                    _unit(stats, "(ambiguous)", req, "ambiguous_commit")
                    continue
                (r, sha), pr = near[0], None
            else:
                full, num = e.value.rsplit("#", 1)
                r = by_slug.get(full.split("/", 1)[1].lower())
                if r is None:
                    continue
                sha, pr = None, int(num)
            if req is None:
                _unit(stats, r.slug, None, "no_request")
                continue
            units.setdefault((req.session, req.prompt_id, r.slug), (req, r, []))[2].append((e.kind, sha, pr))
    out, per_request = [], Counter()
    for (_, _, slug), (req, r, items) in units.items():
        if not r.owner:
            _unit(stats, slug, req, "not_github")
            continue
        try:
            index = index_of(r)
        except RuntimeError:
            _unit(stats, slug, req, "github_unreadable")
            continue
        if index["private"]:
            _unit(stats, slug, req, "private_repo")
            continue
        mirror = mirror_of(r)
        fixes, why = {}, Counter()
        for kind, sha, pr in sorted(items, key=lambda i: EVIDENCE.index(i[0])):
            if pr is not None and sha is None:
                state, merge = index["prs"].get(pr, ("", ""))
                got = (pr, merge, None) if state == "MERGED" and merge else (pr, None, "pr_not_merged")
            else:
                got = landing(sha, index, mirror)
            if got[2]:
                why[got[2]] += 1
            else:
                fixes.setdefault(got[1], (got[0], kind))
        if not fixes:
            _unit(stats, slug, req, why.most_common(1)[0][0] if why else "not_landed")
            continue
        for fix, (pr, kind) in fixes.items():
            per_request[(req.session, req.prompt_id)] += 1
            out.append({"request": req, "repo": r, "fix": fix, "pr": pr, "evidence": kind})
    for c in out:
        _unit(stats, c["repo"].slug, c["request"])
    return out, stats


def task_id(slug: str, pr: int | None, fix: str) -> str:
    return f"{slug}-{f'pr{pr}' if pr else fix[:10]}-{VARIANT}"


def survey(root: Path, repo_roots, log, known: redact.Known | None = None, probes: int | None = None,
           run: bool = True, keep: dict | None = None, timeout=history.TIMEOUT_S, env=None,
           index_of=None, mirror_of=None) -> dict:
    """Scan every session, link, screen, redact and probe; the manifest holds counts and redacted prompts only."""
    known = redact.known_here() if known is None else known
    repos = local_repos(repo_roots)
    index_of = index_of or _cached(lambda r: pulls(r.owner, r.name))
    mirror_of = mirror_of or _cached(lambda r: _mirror(r.url))
    scanned, by_dir = [], defaultdict(lambda: {"sessions": 0, "requests": 0})
    for project, main, subs in sessions(root):
        got = scan_session(main.stem, project, main, subs)
        scanned.append((main.stem, got))
        by_dir[project]["sessions"] += 1
        by_dir[project]["requests"] += len(got[0])
    by_url = {u: session for session, (_, _, urls) in scanned for u in urls}
    for session, extra in trailers([r for r in repos if r.owner], by_url).items():
        next(got for s, got in scanned if s == session)[1].extend(extra)
    found, stats = link(scanned, repos, index_of, mirror_of)
    old = {t["fix"]: t for t in (keep or {}).get("tasks", [])}
    spans = Counter((c["request"].session, c["request"].prompt_id) for c in found)
    kept, seen, ran, pending = [], set(), 0, []
    for c in sorted(found, key=lambda c: c["request"].at):
        req, r, fix = c["request"], c["repo"], c["fix"]
        s = _unit(stats, r.slug, req)
        why = ("duplicate_task" if fix in seen else screen_request(req.text)
               or ("request_spans_tasks" if spans[(req.session, req.prompt_id)] > MAX_TASKS_PER_REQUEST else None))
        cand = None
        if why is None:
            cand = describe(mirror_of(r), fix)
            why = cand if isinstance(cand, str) else history.screen(cand)
        if why is None and not _has_path(mirror_of(r), cand["base"], "uv.lock"):
            why = "no_uv_lock"
        red = redact.redact(req.text, known) if why is None else None
        if why is None and redact.detect(red.text, known):
            why = "redaction_residue"
        if why is None and not run:
            pending.append({"id": task_id(r.slug, c["pr"], fix), "fix": fix,
                            "size": history.size_of({"files": len(cand["source_files"]), "lines": cand["lines"]})})
            seen.add(fix)
            continue
        res = ({k: old[fix][k] for k in ("fail_to_pass", "pass_to_pass")} | {"test_s": old[fix]["strata"]["test_s"]}
               if why is None and fix in old else None)
        if why is None and res is None and probes is not None and ran >= probes:
            why = "not_probed"
        if why is None and res is None:
            t0, ran = time.monotonic(), ran + 1
            res = history.probe(mirror_of(r), cand, log, timeout, env=env, src=source_for(r.url, r.slug))
            why = res.get("drop")
            print(f"{task_id(r.slug, c['pr'], fix)} {why or 'kept'} {time.monotonic() - t0:.0f}s",
                  file=sys.stderr, flush=True)
        if why:
            s["dropped"][why] += 1
            continue
        seen.add(fix)
        s["tasks"] += 1
        kept.append({"id": task_id(r.slug, c["pr"], fix), "repo": r.url, "slug": r.slug, "pr": c["pr"],
                     "base": cand["base"], "fix": fix, "date": cand["date"],
                     "context_files": cand["context_files"], "new_files": cand["new_files"],
                     "test_files": cand["test_files"],
                     **({"pytest_args": list(src.pytest_args)} if (src := source_for(r.url, r.slug)).pytest_args else {}),
                     **({"extras": list(src.extras)} if src.extras else {}),
                     "fail_to_pass": res["fail_to_pass"],
                     "pass_to_pass": res["pass_to_pass"], "prompt": red.text,
                     "strata": {"files": len(cand["source_files"]), "lines": cand["lines"], "test_s": res["test_s"],
                                "area": history.area(cand["source_files"]),
                                "size": history.size_of({"files": len(cand["source_files"]), "lines": cand["lines"]})},
                     "provenance": {"session": session_hash(req.session), "evidence": c["evidence"],
                                    "redactions": red.counts}})
    kept += [t for f, t in old.items() if f not in {c["fix"] for c in found}]
    projects = {p: {"sessions": len(s["sessions"]), "requests_linked": len(s["linked"]), "tasks": s["tasks"],
                    "dropped": dict(sorted(s["dropped"].items()))} for p, s in sorted(stats.items())}
    return {"version": VERSION, "source": SOURCE,
            "criteria": {"min_request_words": MIN_REQUEST_WORDS, "max_tasks_per_request": MAX_TASKS_PER_REQUEST,
                         "commit_window_s": [COMMIT_BEFORE_S, COMMIT_AFTER_S], "runs": history.RUNS,
                         "max_source_files": history.MAX_SOURCE_FILES, "max_lines": history.MAX_LINES,
                         "probes": probes},
            "transcripts": {p: dict(v) for p, v in sorted(by_dir.items())}, "projects": projects,
            "tasks": sorted(kept, key=lambda t: t["id"]), **({} if run else {"pending": pending})}


def _cached(make):
    held = {}

    def get(r):
        if r.slug not in held:
            held[r.slug] = make(r)
        return held[r.slug]
    return get


def _mirror(url: str) -> Path:
    m = repo.mirror(url)
    history._fetch(m, "HEAD")
    return m


def report(got: dict) -> list[str]:
    """The dry run's table: transcripts per project dir, then per repo the sessions, linked requests, tasks and drops."""
    lines = ["transcripts: " + ", ".join(f"{p} {v['sessions']} sessions {v['requests']} requests"
                                         for p, v in got["transcripts"].items())]
    lines.append(f"{'project':<16} {'sessions':>8} {'linked':>7} {'tasks':>6}  drops")
    for p, v in got["projects"].items():
        drops = ", ".join(f"{r} {n}" for r, n in sorted(v["dropped"].items(), key=lambda kv: (-kv[1], kv[0])))
        lines.append(f"{p:<16} {v['sessions']:>8} {v['requests_linked']:>7} {v['tasks']:>6}  {drops}")
    if got.get("pending"):
        lines.append(f"pending a probe: {len(got['pending'])}")
    lines.append(f"tasks: {len(got['tasks'])}")
    return lines


def revision(got: dict) -> str:
    return hashlib.sha1(json.dumps(got["tasks"], sort_keys=True).encode("utf-8")).hexdigest()


def manifest(path: Path = MANIFEST) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def fetch(path: Path = MANIFEST) -> list[dict]:
    got = manifest(path)
    if revision(got) != REVISION:
        raise RuntimeError(f"{path.name} tasks hash to {revision(got)}, not REVISION")
    return got["tasks"]


def refuse(case: dict, text: str, known: redact.Known = redact.Known()) -> None:
    """Raise when a case file's text still matches a redaction detector or the privacy lint; names classes only."""
    from harness import privacy
    left = redact.detect(text, known)
    lint = sorted({f.name for f in privacy.scan(text, case["id"])})
    if left or lint:
        raise ValueError(f"{case['id']}: refused, still matches {sorted(left) + lint}")


def convert(row: dict) -> Imported:
    from evals.importers import _dump
    case = {"id": row["id"], "modality": LANE, "prompt": row["prompt"],
            "params": {"source_repo": row["repo"], "base": row["base"], "fix": row["fix"], "variant": VARIANT,
                       "context": "oracle", "context_files": row["context_files"],
                       **({"new_files": row["new_files"]} if row.get("new_files") else {}),
                       **{k: row[k] for k in ("pytest_args", "extras") if row.get(k)},
                       "fail_to_pass": row["fail_to_pass"], "pass_to_pass": row["pass_to_pass"]},
            "attribution": {**provenance(sys.modules[__name__], f"{row['slug']} PR #{row['pr']}" if row.get("pr")
                                         else f"{row['slug']} {row['fix'][:10]}", TRANSFORM, row["date"]),
                            "session": row["provenance"]["session"], "evidence": row["provenance"]["evidence"],
                            "redactions": row["provenance"]["redactions"]}}
    refuse(case, _dump(sys.modules[__name__], case), redact.known_here())
    return Imported(case)


RESPONDERS = history.RESPONDERS
passes = history.passes


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m evals.importers.transcripts")
    ap.add_argument("--root", type=Path, default=None, help="Claude Code projects dir; default ~/.claude/projects")
    ap.add_argument("--repos", type=Path, nargs="+", default=[Path.home() / "projects" / "github"],
                    help="dirs holding owner/name checkouts to resolve commits in")
    ap.add_argument("--dry-run", action="store_true", help="link and screen, probe nothing, write no manifest")
    ap.add_argument("--probes", type=int, default=None, help="probe at most this many new tasks")
    ap.add_argument("--restart", action="store_true", help="drop the committed manifest's tasks instead of keeping them")
    ap.add_argument("--yield", dest="table", action="store_true", help="print the table of the manifest at --out")
    ap.add_argument("--log", type=Path)
    ap.add_argument("--names", type=Path, nargs="*", default=[],
                    help="untracked files of people's and handles' names to redact, one per line")
    ap.add_argument("--report", type=Path, help="also write the counts as JSON here")
    ap.add_argument("--out", type=Path, default=MANIFEST)
    a = ap.parse_args(argv)
    if a.table:
        print("\n".join(report(manifest(a.out))))
        return 0
    if a.log is None and not a.dry_run:
        ap.error("--log is required unless --dry-run")
    keep = None if a.restart or not a.out.is_file() else manifest(a.out)
    known = redact.known_here(a.names)
    got = survey(a.root or default_root(), a.repos, a.log or Path(os.devnull), known=known, probes=a.probes,
                 run=not a.dry_run, keep=keep)
    print("\n".join(report(got)), file=sys.stderr)
    if a.report:
        a.report.write_text(json.dumps({k: got[k] for k in ("transcripts", "projects", "criteria")}
                                       | {"tasks": len(got["tasks"]), "pending": len(got.get("pending", []))},
                                       indent=1) + "\n", encoding="utf-8")
    if not a.dry_run:
        for t in got["tasks"]:
            refuse({"id": t["id"]}, json.dumps(t, indent=1), known)
        a.out.write_text(json.dumps(got, indent=1) + "\n", encoding="utf-8")
        print(f"set REVISION = {revision(got)!r}, then `soh cases import transcripts`", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
