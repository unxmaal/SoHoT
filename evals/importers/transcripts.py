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

from evals import interface, redact, repo, session_cut
from evals.importers import Imported, history, provenance
from harness import paths

LANE = "repo"
SOURCE = "claude-code:transcripts"
DATASET = "Claude Code session requests, redacted"
URL = "https://github.com/unxmaal/SoHoT/issues/1095"
LICENSE = "generated"
#: sha1 of the committed manifest's tasks, so a hand edit of the manifest is caught at import.
REVISION = "1e8faf00a7d7bb3e214f62621310beb1a2a7eed1"
MANIFEST = Path(__file__).with_name("transcripts.json")
VERSION = 1
VARIANT = "request"
#: Repos whose sessions read a chat archive: their tool outputs hold other people's messages, so none is imported.
THIRD_PARTY_DATA = ("infovore",)
#: Cases a privacy read found private in a way no detector names, with why; the survey drops them. #1095.
EXCLUDED: dict[str, str] = {
    "sohot-pr860-request": "a tool output lists the owner's project directories",
    "sohot-pr977-request": "a tool output shows the owner's daily cloud spend",
    "sohot-pr979-request": "a tool output shows the owner's daily cloud spend",
    "mcm-engine-pr155-request": "the request ties a project to the owner's employer",
    "mcm-engine-pr173-request": "a coworker's report and an internal plan file name",
    "mcm-engine-pr174-request": "a coworker's report and an internal plan file name",
    "sohot-pr1125-request": "a tool output lists the owner's store backups with their local times",
}
#: Cases the #1136 audit retired, with why: the cut heads toward another change, or the tests pin a design it never reached.
RETIRED: dict[str, str] = {
    "mcm-engine-pr138-request": "mismatch: the cut is mid-release and names the fix's issue only by number",
    "mcm-engine-pr184-request": "mismatch: the cut is still gathering material; the fix invents a snapshot api",
    "sohot-pr1010-request": "underspecified: the tests assert messages and keys the session never designed",
    "sohot-pr1029-request": "mismatch: the session is #1018, already merged at base; the fix is #1025",
    "sohot-pr1033-request": "mismatch: the session is #1018; the fix is #1027",
    "sohot-pr1035-request": "mismatch: the session is #1021 and its first edit was a heredoc; the fix is #1030",
    "sohot-pr1038-request": "mismatch: the session is #1024; the fix is #1032",
    "sohot-pr1042-request": "mismatch: the session is #1018, edited through heredocs; the fix is #1037",
    "sohot-pr1046-request": "mismatch: the session is #1018; the fix is #1045",
    "sohot-pr1051-request": "mismatch: the session is #1021; the fix is #1049",
    "sohot-pr1054-request": "underspecified: the tests pin arithmetic the fix invented after the cut",
    "sohot-pr933-request": "mismatch: the session writes a skill and files issues; the fix is #928",
    "sohot-pr957-request": "mismatch: the session is a labelling job and makes no code change; the fix is #954",
    "sohot-pr966-request": "mismatch: the session rewrites issue bodies and was told not to code; the fix is #964",
}
#: Base files beyond the fix's own that a repaired case shows the model. #1136.
CONTEXT: dict[str, list[str]] = {
    "sohot-pr1003-request": ["harness/gateway.py", "harness/paths.py"],
    "sohot-pr1063-request": ["harness/memory_store/transitions.py"],
    "sohot-pr861-request": ["harness/memory_store/migrations/__init__.py"],
}
#: What the finished change does, stated after the quoted session where the cut had not reached it. #1136.
STATED: dict[str, str] = {
    "mcm-engine-pr139-request": (
        "`SearchHit` gains an optional `snippet`: the backend's own highlight of the passage that matched "
        "(for `SqliteSearch`, the `FTS5` `snippet()` over all indexed columns; the postgres and opensearch "
        "adapters may fill theirs the same way). When `detail` is `summary`, each hit with a snippet gets one"
        " extra line under it showing that passage, whitespace collapsed and cut to 160 characters (env "
        "`MCM_SNIPPET_MAX`, 0 disables), so a term found only in a knowledge `detail` body still appears in "
        "summary output while a 500-word body never comes back whole. A hit found only by the `LIKE` fallback"
        " has no snippet and renders as before; `detail=\"full\"` is unchanged."),
    "mcm-engine-pr162-request": (
        "`SessionTracker.coverage` is a dict keyed by the topic lowercased and stripped; each value is a dict"
        " with `topic` (that key), `query`, `result_ids` (a list, `[]` for `None`), `searched_at` (epoch "
        "seconds) and `resident`. The same topic recorded again replaces its entry; a blank topic records "
        "nothing. `reconcile_coverage` changes only `resident`, and `reset_all` empties `coverage`. The "
        "`search` tool records its query as both topic and query, with the hits it returned as "
        "`(entity_type_name, id)` tuples such as `(\"KNOWLEDGE\", 1)`, even when nothing matched. "
        "`report_error` records its auto-search under the first 50 characters of `error_text`. "
        "`session_start` always marks coverage non-resident; `save_snapshot` does so only when "
        "`compaction=True`, and the pre-compact hook passes `compaction=True`."),
    "sohot-pr1003-request": (
        "`gateway_config` picks the base gateway config the audit reads: an explicit `config` or a set "
        "`GATEWAY_CONFIG` wins; otherwise, only when `paths.is_live(store)` is true, it asks "
        "`paths.runs_elsewhere()` and uses `gateway/config.yaml` inside that checkout. A store that is not "
        "live never calls `paths.runs_elsewhere` and gets `gateway.config_path()`, as does a live store with "
        "no deploy checkout. `audit()` resolves its config this way, and its result gains the key "
        "`served_config` holding `str(gateway.served_path(base))`; `report_text` prints a line containing "
        "`served config <that path>`. When the served file is missing, `served_matches_adoption` fails with "
        "one finding that names the served path and mentions no `sohot-` alias, not one per lane."),
    "sohot-pr1026-request": (
        "`model_dtype` returns `float32` on `cpu` whatever is forced or declared. The accelerator case "
        "returns `forced` when given, else the half the snapshot declares (`declared_dtype` of "
        "`snapshot(model, revision=revision)`), else `float16`; a repo declaring only `float32`, or not "
        "cached, gets `float16`. `read_image` loads the model and feeds pixels at that dtype and sets "
        "`runtime[\"dtype\"]` to its name. `--dtype` accepts only `bfloat16`, `float16`, `float32` (others exit"
        " through argparse) and reaches `read_image` as `dtype`. `hf-ocr` specs take a `dtype=` option: a "
        "value outside those three raises `ValueError` mentioning dtype; a pinned spec gets its own candidate"
        " name and `--dtype <value>` in argv, an unpinned one no `--dtype`. The runner copies `dtype` from "
        "the runtime file onto the row."),
    "sohot-pr1044-request": (
        "The `Excerpt` that `cut` returns has a property `errors -> list[str]`: the excerpt's exception lines "
        "(such as `ModuleNotFoundError: No module named 'soundfile'`), with the `|` and `+` bars an exception "
        "group indents them with stripped, read from the last line back so the exception the chain ends on "
        "comes first, each line once."),
    "sohot-pr1063-request": (
        "`reopens_to` gives `(\"screened\", SCREEN)` when the until key is `cases` or `limit` and the declined "
        "tier is measure or adopt, else `(\"queued\", INSPECT)`; `requeue_revisitable` retracts to that pair. "
        "`reopened_too_far` returns, sorted by name, dicts with `name`, `verdict_id`, `decided_at`, `until`, "
        "`tier` for proposals whose state verdict is still an inspect retraction starting `retracted: <until>"
        " is met` of a verdict `reopens_to` now sends to screen; other retractions, or ones inspect has since"
        " answered, are excluded. `requeue_reopened_too_far` moves them, returning names. `_move_past_screen`"
        " runs it, prints each name indented four spaces, marks `MOVED_PAST_SCREEN` from when it began, "
        "returns the names, and runs in the discover step before `_reopen_revisitable`. The audit check "
        "`reopened_past_screen`, in `REPAIRED_BY`, warns per row until that mark postdates it, then fails."),
    "sohot-pr1101-request": (
        "`grader_digest` parses source with `ast` under `root` (default: the repo root) and imports nothing. "
        "The walk starts at the lane's value in the dict literal that `registry` names as (module, "
        "attribute), default `(\"evals.core\", \"CHECKERS\")`, plus each `(module, name)` in `also`, default "
        "`((\"evals.core\", \"score\"),)`; `packages` defaults to `(\"harness\", \"evals\")`. The walk follows the "
        "names and attribute chains reached code uses, through imports at module level or inside function "
        "bodies, into modules of `packages`, and hashes each reached top-level statement only, so an "
        "unreached function, or a module imported but never used, changes nothing. The result is `{\"modules\":"
        " [...], \"names\": {\"<module>:<name>\": sha256}}`, `modules` being the sorted modules with a hashed "
        "statement. The exam part holds `grader` (the `names` map) and `grader_modules`. The registry "
        "statement is hashed only as the lane's own entry, under the key `<module>:<attr>[<lane>]` (such as "
        "`evals.core:CHECKERS[code]`), and is then treated as visited, so code that names the whole registry,"
        " as `score` does, never reaches the other lanes' checkers."),
    "sohot-pr861-request": (
        "This is schema 71: `SCHEMA_VERSION` becomes 71, and the new step module "
        "`harness/memory_store/migrations/v71.py` sets `VERSION = 71` and does the requeue in its "
        "`data(conn)` phase (the loader sorts step modules by `VERSION` and calls each phase function by "
        "name). The requeue sends a proposal back to `screened` only when its current state verdict is a "
        "`declined` adopt-tier verdict with reason `limit`, no run id, an empty until and a not-run "
        "budget-projection detail, and the verdict just before it for that proposal (by id) has outcome "
        "`screened`. A candidate with any other verdict between the screen and the refusal stays declined, as"
        " does any limit decline that fails one of these conditions."),
    "sohot-pr862-request": (
        "`pair_block` asks `home(candidate, gateway)` for (server, model, how many models that server holds "
        "at once, `None` for no limit), skips candidates with an empty server or model, and returns 1 when "
        "every server's distinct models fit its limit, else `PAIR_BLOCK`; any `ds4:` candidate gives `None`. "
        "`paired_segments` cuts `order` (case ids in run order) into windows of `block` positions, gives each"
        " candidate in turn its cases from `rest` (matched through `key`) inside the window, merges "
        "consecutive turns of one candidate, and returns (candidate index, cases) pairs; a falsy `block` "
        "returns each non-empty `rest` whole. `_execute` calls `pair_block(candidates, args.gateway)` "
        "positionally and runs those turns; a runner warms on its first turn, and on later turns only when "
        "`block` is not 1."),
    "sohot-pr883-request": (
        "`screen_detail` builds the detail `_report_screen` records for a screen verdict. When a receipt "
        "exists (`summary is not None`) it returns `why` alone, with no stderr. When there is none it drops "
        "each python warning line (`<path>:<line>: <Name>Warning: ...`) and the indented source line printed "
        "under it, collapses the remaining stderr whitespace to single spaces, keeps its last 300 characters,"
        " and returns `why || <tail>`, or just `why` when nothing is left; the result is capped at 600 "
        "characters. `METRIC_DIRECTION` also declares `attempts` as `lower` and `retries`, `stages` and "
        "`thinking_disabled` as `neutral`, so every metric a runner emits has a direction."),
    "sohot-pr927-request": (
        "`screenable_backlog` leaves out a ready candidate whose newest verdict is a screen-tier memory "
        "deferral (`reasons.MEMORY`); a later verdict of any other kind makes it backlog again. `deferred`, "
        "when given, is a name predicate used instead of reading the store. `memory_deferrals` walks a name's"
        " verdicts newest first and counts consecutive screen memory deferrals whose detail names the same "
        "`needs <N> GB` figure, stopping at any other verdict or figure; it returns the count and the figure "
        "as a string, e.g. `(3, \"26.5\")`, else `(0, \"\")`. The screen `limit` counts only screens actually "
        "started, so a deferral takes no slot. When the current refusal names the same figure and the count "
        "is already 3 (`MEMORY_DEFERRALS`), the screen writes no new verdict."),
}
#: A cut this small is the request and little else: the chatter a model cannot act on.
MIN_CUT_BYTES = 1000
#: How long before the tool output a commit's committer date may fall (hooks, a push after it), and after.
COMMIT_BEFORE_S = 1800
COMMIT_AFTER_S = 120
TRANSFORM = ("a Claude Code session from the person's request to just before the agent's first edit of a "
             "file the fix changes (evals/session_cut.py: user turns, assistant text, tool calls, reads and "
             "searches kept, large outputs dropped, to a byte budget), redacted by evals/redact.py "
             "(secrets, ids, emails, home and volume paths, hosts, IPs, pasted chat, handles, "
             "account and person names as typed placeholders) and refused if a fix line or a name-like word "
             "is left; linked to the merged commit through a commit hash or PR URL printed by a tool in that "
             "request or a Claude-Session trailer; since #1138 the subagent that printed it is the stream cut, "
             "`gh issue view` of the repo is kept whole, and a cut whose user turns and issue views never name "
             "the fix's issue is dropped; base = fix^; fail_to_pass and "
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
    stream: str = ""


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
        stream = subs[i - 1].stem if i else "main"
        for pid, at, cmd, output in _tool_outputs(recs):
            anchor = started.get(spawned or pid) or at
            found += [Evidence(session, at, anchor, k, v, stream) for k, v in evidence_in(cmd, output)]
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


def _sub_text(rec: dict) -> str | None:
    """What the parent agent sent a subagent: its spawning prompt or a later message."""
    if rec.get("type") != "user" or rec.get("isMeta"):
        return None
    content = (rec.get("message") or {}).get("content")
    if isinstance(content, list) and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
        return None
    return _text(content) or None


_STREAMS: dict = {}


def _stream(path: Path, main: bool) -> tuple[list, dict, str | None]:
    """(events, prompt id -> first time, the prompt id that spawned it) of one transcript, read once per run."""
    key = (str(path), main)
    if key not in _STREAMS:
        recs = list(records(path))
        started = {}
        for rec in recs:
            if rec.get("promptId") and _ts(rec.get("timestamp")):
                started.setdefault(rec["promptId"], _ts(rec.get("timestamp")))
        spawned = None if main else next((r.get("promptId") for r in recs if r.get("promptId")), None)
        _STREAMS[key] = (session_cut.events(recs, human_text if main else _sub_text, _ts), started, spawned)
    return _STREAMS[key]


def cut(main: Path, subs, requests: list[Request], req: Request, files, stream: str = "", repo=None) -> tuple[str, dict] | str:
    """The session cut just before the first edit of `files` made under `req`, as a prompt; or why there is none.

    The main stream counts from `req` to the next request; a subagent counts whole when `req` spawned it, and its
    cut opens with `req` itself. A subagent `stream` that printed the fix's evidence is the only one cut; main is cut
    when it made an edit. `repo` (owner, name) keeps its `gh issue view` outputs whole.
    """
    main_evs, started, _ = _stream(main, True)
    after = next((r.at for r in requests if r.at > req.at), float("inf"))
    streams = [("main", "main", [e for e in main_evs if req.at <= e.at < after])]
    for sub in subs:
        evs, _, spawned = _stream(sub, False)
        if request_for(requests, started.get(spawned) or 0.0) is req:
            streams.append(("subagent", sub.stem, [session_cut.Event(req.at, "user", body=req.text), *evs]))
    hits = [(evs[i].at, kind, name, evs, i) for kind, name, evs in streams
            if (i := session_cut.first_edit(evs, files)) is not None]
    if stream != "main" and stream in {name for _, name, _ in streams} or any(h[2] == stream == "main" for h in hits):
        hits = [h for h in hits if h[2] == stream]
    if not hits:
        return "no_edit"
    _, kind, _, evs, i = min(hits, key=lambda h: h[0])
    pin = (lambda e: session_cut.views_issue(e, *repo)) if repo else None
    text = session_cut.render(evs[:i], pin=pin)
    return session_cut.HEAD + text, {"stream": kind, "events": i, "bytes": len(text.encode("utf-8")), "until": evs[i].at}


def leak_lines(mirror: Path, cand: dict) -> list[str]:
    """The reference diff's added source lines that base never held: what a cut must not show."""
    diff = history.git(mirror, "diff", "--no-renames", cand["base"], cand["fix"], "--", *cand["source_files"])
    base = {p: history.git(mirror, "show", f"{cand['base']}:{p}") for p in cand["context_files"]}
    return session_cut.added_lines(diff, base)


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
    if not repo._has(mirror, fix):
        return "fix_not_fetchable"
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
    date, subject, body = history.git(mirror, "show", "-s", "--format=%cI%x00%s%x00%b", fix).split("\0", 2)
    return {"fix": fix, "base": base, "date": date[:10], "subject": subject, "issues": fix_issues(subject, body),
            "source_files": source,
            "context_files": context, "new_files": new,
            "test_files": sorted(p for p in files if repo.is_test_path(p)),
            "lines": sum(files[p] for p in source)}


_CLOSES = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#(\d+)", re.I)
_TAIL = re.compile(r"(?:\s*\((#\d+(?:,\s*#\d+)*)\))+\s*$")
_MERGE = re.compile(r"^Merge pull request #\d+ from [\w.-]+/(?:[\w.-]+/)?(\d+)-")


def fix_issues(subject: str, body: str = "") -> list[int]:
    """Issue numbers a fix commit says it resolves: Closes lines, the (#n) groups ending its title, a merged branch's
    number; the PR's own number is among them when the title ends with it."""
    titles = [subject] + ([body.strip().splitlines()[0]] if _MERGE.match(subject) and body.strip() else [])
    found = [int(n) for n in _CLOSES.findall(body)]
    for t in titles:
        m = _TAIL.search(t)
        found += [int(n) for n in re.findall(r"#(\d+)", m.group(0))] if m else []
    found += [int(m.group(1))] if (m := _MERGE.match(subject)) else []
    return sorted(set(found))


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
            units.setdefault((req.session, req.prompt_id, r.slug), (req, r, []))[2].append((e.kind, sha, pr, e.stream, e.at))
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
        for kind, sha, pr, stream, at in sorted(items, key=lambda i: EVIDENCE.index(i[0])):
            if pr is not None and sha is None:
                state, merge = index["prs"].get(pr, ("", ""))
                got = (pr, merge, None) if state == "MERGED" and merge else (pr, None, "pr_not_merged")
            else:
                got = landing(sha, index, mirror)
            if got[2]:
                why[got[2]] += 1
            else:
                fixes.setdefault(got[1], (got[0], kind, stream, at))
        if not fixes:
            _unit(stats, slug, req, why.most_common(1)[0][0] if why else "not_landed")
            continue
        for fix, (pr, kind, stream, at) in fixes.items():
            per_request[(req.session, req.prompt_id)] += 1
            out.append({"request": req, "repo": r, "fix": fix, "pr": pr, "evidence": kind, "stream": stream, "at": at})
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
    kept, seen, ran, pending, flagged, seen_in, refused = [], set(), 0, [], Counter(), {}, {}
    files_of = {main.stem: (main, subs) for _, main, subs in sessions(root)}
    requests_of = {session: got[0] for session, got in scanned}
    first = {}
    for c in sorted(found, key=lambda c: c["request"].at):
        first.setdefault(c["fix"], c)
    order = sorted(first.values(), key=lambda c: -c["request"].at)
    order += [c for c in found if first[c["fix"]] is not c]
    siblings = defaultdict(dict)
    for c in found:
        siblings[(c["request"].session, c["request"].prompt_id, c.get("stream", ""))][c["fix"]] = c.get("at", 0.0)
    for c in order:
        req, r, fix = c["request"], c["repo"], c["fix"]
        s = _unit(stats, r.slug, req)
        if fix in old and fix not in seen and old[fix]["id"] not in RETIRED and old[fix]["id"] not in EXCLUDED:
            seen.add(fix)
            s["tasks"] += 1
            kept.append(old[fix])
            continue
        why = ("duplicate_task" if fix in seen else "third_party_data" if r.slug in THIRD_PARTY_DATA
               else "excluded" if task_id(r.slug, c["pr"], fix) in EXCLUDED
               else "retired" if task_id(r.slug, c["pr"], fix) in RETIRED else None)
        cand = None
        if why is None:
            cand = describe(mirror_of(r), fix)
            why = cand if isinstance(cand, str) else history.screen(cand)
        if why is None and not _has_path(mirror_of(r), cand["base"], "uv.lock"):
            why = "no_uv_lock"
        got = cut(*files_of[req.session], requests_of[req.session], req, cand["source_files"], c.get("stream", ""),
                  (r.owner, r.name)) if why is None else None
        if isinstance(got, str):
            why = got
        elif got is not None and got[1]["bytes"] < MIN_CUT_BYTES:
            why = "cut_too_short"
        elif got is not None and not session_cut.on_task(got[0], set(cand["issues"]) - {c["pr"]}, cand["source_files"]):
            why = "mismatch"
        elif got is not None and _landed_before(mirror_of(r), cand["base"], {
                o for o, at in siblings[(req.session, req.prompt_id, c.get("stream", ""))].items()
                if o != fix and at >= got[1]["until"]}):
            why = "mismatch"
        red = redact.redact(got[0], known) if why is None else None
        if why is None and session_cut.leaks(red.text, leak_lines(mirror_of(r), cand)):
            why = "leak"
        if why is None and redact.detect(red.text, known):
            why = "redaction_residue"
        if why is None and _lint(red.text):
            why = "privacy_lint"
        if why is None and redact.name_like(red.text):
            why = "name_guard"
            for w in redact.name_like(red.text):
                flagged[w] += 1
                at = red.text.find(w)
                seen_in.setdefault(w, red.text[max(0, at - 50):at + len(w) + 30].replace("\n", " "))
        if why is None and not run:
            pending.append({"id": task_id(r.slug, c["pr"], fix), "fix": fix,
                            "size": history.size_of({"files": len(cand["source_files"]), "lines": cand["lines"]})})
            seen.add(fix)
            continue
        if why is None and probes is not None and ran >= probes:
            why = "not_probed"
        if why is None:
            t0, ran = time.monotonic(), ran + 1
            res = history.probe(mirror_of(r), cand, log, timeout, env=env, src=source_for(r.url, r.slug))
            why = res.get("drop")
            print(f"{task_id(r.slug, c['pr'], fix)} {why or 'kept'} {time.monotonic() - t0:.0f}s",
                  file=sys.stderr, flush=True)
        if why:
            s["dropped"][why] += 1
            continue
        row = {"id": task_id(r.slug, c["pr"], fix), "repo": r.url, "slug": r.slug, "pr": c["pr"],
                     "base": cand["base"], "fix": fix, "date": cand["date"],
                     "context_files": cand["context_files"], "new_files": cand["new_files"],
                     "test_files": cand["test_files"],
                     **({"pytest_args": list(src.pytest_args)} if (src := source_for(r.url, r.slug)).pytest_args else {}),
                     **({"extras": list(src.extras)} if src.extras else {}),
                     "fail_to_pass": res["fail_to_pass"],
                     "pass_to_pass": res["pass_to_pass"], "prompt": red.text,
                     "interface": history.tests_call(mirror_of(r), cand["base"], fix),
                     "strata": {"files": len(cand["source_files"]), "lines": cand["lines"], "test_s": res["test_s"],
                                "area": history.area(cand["source_files"]),
                                "size": history.size_of({"files": len(cand["source_files"]), "lines": cand["lines"]})},
                     "provenance": {"session": session_hash(req.session), "evidence": c["evidence"],
                                    "cut": {k: v for k, v in got[1].items() if k != "until"}, "redactions": red.counts}}
        row["unlisted"] = unlisted(mirror_of(r), row)
        try:
            made = convert(row, known)
            refuse(row, known=known)
        except ValueError as exc:
            s["dropped"]["refused"] += 1
            refused[row["id"]] = str(exc).split("still matches ", 1)[-1]
            continue
        why = admit(made.case, env)
        if why:
            s["dropped"][why] += 1
            continue
        seen.add(fix)
        s["tasks"] += 1
        kept.append(row)
    kept += [t for f, t in old.items() if f not in {c["fix"] for c in found} and t["id"] not in RETIRED
             and t["id"] not in EXCLUDED]
    projects = {p: {"sessions": len(s["sessions"]), "requests_linked": len(s["linked"]), "tasks": s["tasks"],
                    "dropped": dict(sorted(s["dropped"].items()))} for p, s in sorted(stats.items())}
    return {"version": VERSION, "source": SOURCE,
            "criteria": {"budget_bytes": session_cut.BUDGET_BYTES, "output_cap_bytes": session_cut.OUTPUT_CAP_BYTES,
                         "leak_min_chars": session_cut.LEAK_MIN_CHARS, "commit_window_s": [COMMIT_BEFORE_S, COMMIT_AFTER_S], "runs": history.RUNS,
                         "max_source_files": history.MAX_SOURCE_FILES, "max_lines": history.MAX_LINES,
                         "probes": probes},
            "transcripts": {p: dict(v) for p, v in sorted(by_dir.items())}, "projects": projects,
            "tasks": sorted(kept, key=lambda t: t["id"]), **({} if run else {"pending": pending}),
            "flagged": {w: [n, seen_in[w]] for w, n in flagged.most_common()}, "refused": refused}


def unlisted(mirror: Path, row: dict) -> list[str]:
    """The fix's new names its hidden tests or graded ids spell that the quoted request and interface never do. #1144."""
    return interface.unlisted(mirror, row["base"], row["fix"], f"{row['prompt']}\n\n{interface.block(row['interface'])}",
                              row["fail_to_pass"])


def refresh(got: dict, mirror_of=None) -> dict:
    """The manifest with every task's unlisted names recomputed from its mirror. #1144."""
    mirror_of = mirror_of or _mirror
    return {**got, "tasks": [{**t, "unlisted": unlisted(mirror_of(t["repo"]), t)} for t in got["tasks"]]}


def _landed_before(mirror: Path, base: str, others) -> bool:
    """Whether one of `others` (fixes the stream proved after the cut ends) is already in `base`: the cut heads there."""
    return any(not subprocess.run(["git", "--git-dir", str(mirror), "merge-base", "--is-ancestor", o, base],
                                  capture_output=True).returncode for o in sorted(others))


def admit(case: dict, env=None) -> str | None:
    """None when the gold patch passes the case as the grader runs it (fail_to_pass and pass_to_pass), else a drop."""
    from evals.core import Case
    got = repo.controls(Case(id=case["id"], modality=case["modality"], prompt=case["prompt"], params=case["params"]),
                        env=env)
    return None if got["verdict"] == "valid" else "gold_patch_" + got["verdict"].split(":", 1)[0]


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


def _lint(text: str) -> list:
    from harness import privacy
    return privacy.scan(text, "cut", privacy.name_pattern(Path(__file__).resolve().parents[2]))


def strings(obj) -> str:
    """Every string a case or row holds, one per line: what a detector reads, free of JSON's or YAML's escapes."""
    if isinstance(obj, str):
        return obj
    if isinstance(obj, dict):
        return "\n".join(strings(v) for v in obj.values())
    if isinstance(obj, (list, tuple)):
        return "\n".join(strings(v) for v in obj)
    return ""


def refuse(case: dict, text: str = "", known: redact.Known = redact.Known()) -> None:
    """Raise when a case's strings still match a redaction detector or the name guard, or `text` (the file as written)
    the privacy lint; names classes only."""
    from harness import privacy
    values = strings(case)
    left = redact.detect(values, known)
    lint = sorted({f.name for f in privacy.scan(text, case["id"])}) if text else []
    names = redact.name_like(values)
    if left or lint or names:
        more = [f"{len(names)} name-like word(s)"] if names else []
        raise ValueError(f"{case['id']}: refused, still matches {sorted(left) + lint + more}")


def convert(row: dict, known: redact.Known | None = None) -> Imported:
    from evals.importers import _dump
    case = {"id": row["id"], "modality": LANE, "prompt": row["prompt"],
            "params": {"source_repo": row["repo"], "base": row["base"], "fix": row["fix"], "variant": VARIANT,
                       "context": "oracle",
                       "context_files": sorted({*row["context_files"], *CONTEXT.get(row["id"], [])}),
                       **({"new_files": row["new_files"]} if row.get("new_files") else {}),
                       **{k: row[k] for k in ("pytest_args", "extras") if row.get(k)},
                       **({"interface": list(row["interface"])} if row.get("interface") else {}),
                       **({"stated": STATED[row["id"]]} if row["id"] in STATED else {}),
                       "fail_to_pass": row["fail_to_pass"], "pass_to_pass": row["pass_to_pass"]},
            "attribution": {**provenance(sys.modules[__name__], f"{row['slug']} PR #{row['pr']}" if row.get("pr")
                                         else f"{row['slug']} {row['fix'][:10]}", TRANSFORM, row["date"]),
                            "session": row["provenance"]["session"], "evidence": row["provenance"]["evidence"],
                            "redactions": row["provenance"]["redactions"]}}
    refuse(case, _dump(sys.modules[__name__], case), redact.known_here() if known is None else known)
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
    ap.add_argument("--refresh", action="store_true", help="recompute each task's unlisted names in the manifest at --out")
    a = ap.parse_args(argv)
    if a.table:
        print("\n".join(report(manifest(a.out))))
        return 0
    if a.refresh:
        got = refresh(manifest(a.out))
        a.out.write_text(json.dumps(got, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"set REVISION = {revision(got)!r}, then `soh cases import transcripts`", file=sys.stderr)
        return 0
    if a.log is None and not a.dry_run:
        ap.error("--log is required unless --dry-run")
    keep = None if a.restart or not a.out.is_file() else manifest(a.out)
    known = redact.known_here(a.names)
    paths.eval_home(reads_live=True)
    got = survey(a.root or default_root(), a.repos, a.log or Path(os.devnull), known=known, probes=a.probes,
                 run=not a.dry_run, keep=keep)
    print("\n".join(report(got)), file=sys.stderr)
    if a.report:
        a.report.write_text(json.dumps({k: got[k] for k in ("transcripts", "projects", "criteria", "flagged", "refused")}
                                       | {"tasks": len(got["tasks"]), "pending": len(got.get("pending", []))},
                                       indent=1) + "\n", encoding="utf-8")
    if not a.dry_run:
        for t in got["tasks"]:
            refuse(t, known=known)
        a.out.write_text(json.dumps({k: v for k, v in got.items() if k not in ("flagged", "refused")}, indent=1,
                                    ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"set REVISION = {revision(got)!r}, then `soh cases import transcripts`", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
