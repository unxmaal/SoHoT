"""The weekly adversarial review: headless Claude Code finds, a sandboxed reproduction and a refuter verify, issues dedup. #1149."""
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from hashlib import sha256
from pathlib import Path

from harness import cuts, headless, knobs, paths

MODEL = "claude-opus-5-5"
#: Read-only: a finder or refuter reads the worktree and can change nothing.
TOOLS = "Read,Glob,Grep"
DIMENSIONS = ("rot", "efficiency", "gauntlet", "tests")
#: Issues one run may file.
MAX_FINDINGS = 3
#: Findings one finder may report; the rest are dropped unexamined.
CANDIDATES = 5
#: Summed claude -p usage (input, output, cache read and cache creation) after which no call starts.
TOKEN_BUDGET = 20_000_000
#: --max-turns for each claude -p call.
TURNS = 30
#: Seconds one claude -p call may take.
CALL_TIMEOUT_S = 1800.0
#: Seconds one reproduction may take in its sandbox.
REPRO_TIMEOUT_S = 300.0
#: Closed issues this recent are searched for a duplicate; open ones always are.
DEDUP_DAYS = 90
#: Issues one `gh issue list` page holds; a full page means the dedup cannot see every issue.
ISSUE_LIMIT = 1000
#: Lines either side of the stated line that the quote may sit on.
QUOTE_SLACK = 3
#: Hours the review waits for a running discovery loop before skipping the week.
WAIT_H = 3.0
POLL_S = 300.0
GH_TIMEOUT_S = 60.0
#: A dimension is switched off below this precision once MIN_CLOSED of its issues closed over PRECISION_WEEKS.
MIN_PRECISION = 0.5
MIN_CLOSED = 3
PRECISION_WEEKS = 4
#: Lines of a reproduction's output an issue body carries.
OUTPUT_LINES = 40

FILE_ENV = "LH_REVIEW_FILE"
LABEL = "review-bot"
FINGERPRINT = "review-fingerprint:"
GH_REPO = "unxmaal/SoHoT"
REPO_URL = f"https://github.com/{GH_REPO}"
PROBE = "tests/test_review_probe.py"
USAGE = ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
MARKER = ".review-fixture"

ASK = {
    "rot": "Correctness rot: branches that can no longer run, comments or docstrings that assert a fact the code "
           "beside them contradicts, references to functions, files, flags or knobs that no longer exist, and code "
           "nothing calls.",
    "efficiency": "Inefficiency: the same file or JSON parsed again inside a loop, one subprocess call or query per "
                  "item where one call would do, loops with no bound, and waits, polls, joins or subprocess calls "
                  "with no timeout.",
    "gauntlet": "The gauntlet classes: tests/gauntlet/skill_classes.json lists logical failure classes, each with a "
                "trigger question and a test shape. Ask each trigger of the files in scope and report a site where "
                "the trigger fires and the code has the flaw.",
    "tests": "Test rot: tests that pass whatever the code does, such as a test with no assertion, an assertion on a "
             "value the test itself set, a mock asserting its own return value, or a try/except that swallows the "
             "assertion.",
}

FIND = """You are reviewing the repository in the current directory at commit {sha} for one kind of defect.

{ask}

{scope}

Report only defects you are sure of. Every finding is checked mechanically on this commit, in a clean copy of \
the repository with no network:
- `quote` must be the verbatim text of line `line` of `file`, and `symbol` (the function, class, constant or \
test the finding is about) must be named in that file at or above that line.
- `repro` must show the defect. Either {{"kind": "test", "body": "<a complete pytest file>"}}, written to \
{probe} and run with pytest: it must FAIL (pytest exit 1) because of the defect and pass once it is fixed, and \
every wait in it must be bounded, since a test that hangs proves nothing. Or {{"kind": "command", "argv": \
["..."], "expect": "<text>"}}, run from the repository root, where the defect is shown when the output \
contains `expect`; "python" runs this project's Python.
A separate reviewer then tries to refute each finding. A finding that fails any check is dropped, so one solid \
finding is worth more than several weak ones. Report at most {n}.

Reply with one JSON object in a ```json fence and nothing after it:
{{"findings": [{{"title": "...", "file": "path/from/root.py", "line": 12, "quote": "...", "symbol": "...", \
"claim": "what is wrong and what it causes", "repro": {{...}}}}]}}
An empty list is the right answer when nothing is certain."""

REFUTE = """Someone claims the repository in the current directory, at commit {sha}, has the defect below. \
Your job is to refute it: find the guard, timeout, caller, test or context that makes the claim wrong, or a \
reason the reproduction shows something other than the claimed defect. Confirm it only if you cannot refute it.

Claim: {title}
{file}:{line}: {quote}
{claim}

Reproduction ({kind}):
{repro}

Its result on this commit: {result}

Reply with one JSON object in a ```json fence: {{"verdict": "confirmed" or "refuted", "why": "one sentence"}}"""

FIXTURES = {
    "planted": {
        "waits.py": '"""Polling helpers."""\nimport time\n\n\ndef wait_for(ready, poll_s=0.01):\n'
                    '    """Return True once ready() holds."""\n    while not ready():\n'
                    '        time.sleep(poll_s)\n    return True\n',
        "tests/test_waits.py": "from waits import wait_for\n\n\ndef test_ready_at_once():\n"
                               "    assert wait_for(lambda: True)\n",
    },
    "clean": {
        "waits.py": '"""Polling helpers."""\nimport time\n\n\ndef wait_for(ready, poll_s=0.01, deadline_s=1.0):\n'
                    '    """Return True once ready() holds; raise TimeoutError after deadline_s seconds."""\n'
                    "    end = time.monotonic() + deadline_s\n    while not ready():\n"
                    "        if time.monotonic() >= end:\n"
                    '            raise TimeoutError(f"not ready after {deadline_s} s")\n'
                    "        time.sleep(poll_s)\n    return True\n",
        "tests/test_waits.py": "from waits import wait_for\n\n\ndef test_ready_at_once():\n"
                               "    assert wait_for(lambda: True)\n",
    },
}
#: The planted defect a fixture run must report: file and symbol.
PLANTED = ("waits.py", "wait_for")
SHOWN = ("would file", "filed")


class CallFailed(RuntimeError):
    def __init__(self, msg: str, usage: dict | None = None, limit: str = ""):
        super().__init__(msg)
        self.usage, self.limit = usage or {}, limit


def home() -> Path:
    return paths.home() / "review"


def is_off() -> bool:
    return (home() / "off").exists()


def switch(on: bool) -> None:
    flag = home() / "off"
    if on:
        flag.unlink(missing_ok=True)
    else:
        flag.parent.mkdir(parents=True, exist_ok=True)
        flag.write_text("soh review off\n", encoding="utf-8")


def tokens(usage: dict) -> int:
    return sum(int(usage.get(k) or 0) for k in USAGE)


def fingerprint(file: str, quote: str) -> str:
    """Stable across line moves: the file and the quoted line with its whitespace collapsed."""
    return sha256(f"{file}\n{' '.join(quote.split())}".encode("utf-8")).hexdigest()[:16]


def claude_ask(prompt: str, cwd: Path, role: str, *, execute=subprocess.run, environ=None) -> dict:
    """One headless `claude -p` on the subscription login: no API key or gateway reaches it; usage in tokens."""
    argv = ["claude", "-p", "--model", MODEL, "--output-format", "json", "--no-session-persistence",
            "--strict-mcp-config", "--setting-sources", "", "--max-turns", str(TURNS),
            "--tools", TOOLS, "--allowedTools", TOOLS]
    try:
        proc = execute(argv, cwd=cwd, env=headless.control_env(environ), input=prompt, capture_output=True,
                       text=True, encoding="utf-8", timeout=CALL_TIMEOUT_S)
    except subprocess.TimeoutExpired as exc:
        cuts.cut("review_call_timeout_s", f"review {role}", kept=0, dropped=1)
        raise CallFailed(f"{role}: no answer in {CALL_TIMEOUT_S:g} s",
                         limit=knobs.limit("review_call_timeout_s", CALL_TIMEOUT_S, "s")) from exc
    try:
        body = json.loads(proc.stdout or "")
    except ValueError:
        body = {}
    if not isinstance(body, dict):
        body = {}
    usage = {k: int((body.get("usage") or {}).get(k) or 0) for k in USAGE}
    if body.get("subtype") == "error_max_turns":
        cuts.cut("review_turns", f"review {role}", kept=0, dropped=1)
        raise CallFailed(f"{role}: stopped at {TURNS} turns", usage, knobs.limit("review_turns", TURNS, "turns"))
    if proc.returncode != 0 or body.get("is_error") or not body:
        why = (proc.stderr or "").strip() or str(body.get("result") or "")[:300] or f"exit {proc.returncode}"
        raise CallFailed(f"{role}: {why[:300]}", usage)
    return {"text": str(body.get("result") or ""), "usage": usage}


def gh_run(argv: list[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(["gh", *argv, "-R", GH_REPO], capture_output=True, text=True, encoding="utf-8",
                              timeout=GH_TIMEOUT_S)
    except (OSError, subprocess.SubprocessError) as exc:
        return subprocess.CompletedProcess(["gh", *argv], 1, "", str(exc))


def _git(repo: Path, *args, check=True) -> str:
    got = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8",
                         timeout=GH_TIMEOUT_S)
    if check and got.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {got.stderr.strip()[:300]}")
    return got.stdout if got.returncode == 0 else ""


def fixture(kind: str, root: Path) -> Path:
    """A throwaway git repo holding the planted unbounded wait, or the same wait with a deadline."""
    root.mkdir(parents=True, exist_ok=True)
    for rel, text in {**FIXTURES[kind], MARKER: kind + "\n"}.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")
    _git(root, "init", "-q")
    _git(root, "config", "user.name", "review fixture")
    _git(root, "config", "user.email", "review@example.invalid")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", f"review fixture: {kind}")
    return root


def fixture_kind(source: Path) -> str:
    try:
        return (source / MARKER).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _worktree(source: Path, sha: str, where: Path) -> Path:
    where.parent.mkdir(parents=True, exist_ok=True)
    _git(source, "worktree", "add", "-q", "--detach", str(where), sha)
    return where


def _drop(source: Path, where: Path) -> None:
    _git(source, "worktree", "remove", "--force", str(where), check=False)
    shutil.rmtree(where, ignore_errors=True)
    _git(source, "worktree", "prune", check=False)


def _json(text: str):
    """The last ```json block in text, else the whole text, parsed; None when neither parses."""
    blocks = re.findall(r"```(?:json)?\s*\n(.*?)```", text or "", re.S)
    for chunk in [*reversed(blocks), text or ""]:
        try:
            return json.loads(chunk)
        except ValueError:
            continue
    return None


def _valid(f) -> str:
    """Why a finding cannot be checked, or ""."""
    if not isinstance(f, dict):
        return "not an object"
    for key in ("title", "file", "quote", "symbol", "claim"):
        if not isinstance(f.get(key), str) or not f[key].strip():
            return f"no {key}"
    if not isinstance(f.get("line"), int) or f["line"] < 1:
        return "no line"
    rel = Path(f["file"])
    if rel.is_absolute() or ".." in rel.parts:
        return "file outside the repository"
    r = f.get("repro")
    if not isinstance(r, dict):
        return "no repro"
    if r.get("kind") == "test" and isinstance(r.get("body"), str) and r["body"].strip():
        return ""
    if (r.get("kind") == "command" and isinstance(r.get("argv"), list) and r["argv"]
            and all(isinstance(a, str) for a in r["argv"]) and isinstance(r.get("expect"), str) and r["expect"]):
        return ""
    return "repro is neither a test body nor a command with expected text"


def quoted(source: Path, sha: str, f: dict) -> str:
    """Why the quote is not at its line at sha, or ""."""
    text = _git(source, "show", f"{sha}:{f['file']}", check=False)
    if not text:
        return f"{f['file']} is not in {sha[:12]}"
    want = " ".join(f["quote"].split())
    lines = text.splitlines()
    lo, hi = max(0, f["line"] - 1 - QUOTE_SLACK), min(len(lines), f["line"] + QUOTE_SLACK)
    if not want or not any(want in " ".join(line.split()) for line in lines[lo:hi]):
        if want and any(want in " ".join(line.split()) for line in lines):
            cuts.cut("review_quote_slack", "review finding quoted further from its line", kept=0, dropped=1)
        return f"the quote is not within {QUOTE_SLACK} lines of {f['file']}:{f['line']}"
    if not re.search(rf"(?<!\w){re.escape(f['symbol'])}(?!\w)", "\n".join(lines[:hi])):
        return f"{f['symbol']!r} is not in {f['file']} at or above line {f['line']}"
    return ""


def reproduce(f: dict, work: Path, repro) -> tuple[str, str, str]:
    """(reproduced, unreproduced or unverifiable, why, output) of the finding's reproduction run in `work`."""
    r = f["repro"]
    if r["kind"] == "test":
        (work / PROBE).parent.mkdir(parents=True, exist_ok=True)
        (work / PROBE).write_text(r["body"], encoding="utf-8")
        argv = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--tb=short", PROBE]
    else:
        argv = list(r["argv"])
        if argv[0] in ("python", "python3"):
            argv[0] = sys.executable
    try:
        rc, out, timed = repro(argv, work, REPRO_TIMEOUT_S)
    except Exception as exc:  # noqa: BLE001 - a host with no sandbox verifies nothing
        return "unverifiable", f"could not run: {exc}", ""
    for prefix in {str(work.resolve()), str(work)}:
        out = out.replace(prefix + os.sep, "").replace(prefix + "/", "").replace(prefix, ".")
    if timed:
        cuts.cut("review_repro_timeout_s", "review reproduction", kept=0, dropped=1)
        return "unreproduced", f"timed out after {REPRO_TIMEOUT_S:g} s", out
    if r["kind"] == "test":
        if rc == 1:
            return "reproduced", "pytest exit 1", out
        return "unreproduced", "the test passes on this commit" if rc == 0 else f"pytest exit {rc}, not a test failure", out
    if r["expect"] in out:
        return "reproduced", f"output holds {r['expect']!r}", out
    return "unreproduced", f"output does not hold {r['expect']!r} (exit {rc})", out


def issues(gh, now: float) -> list[dict] | None:
    """Open issues and those closed within DEDUP_DAYS; None when either list cannot be read whole."""
    since = time.strftime("%Y-%m-%d", time.gmtime(now - DEDUP_DAYS * 86400))
    fields = ["--limit", str(ISSUE_LIMIT), "--json", "number,title,body,state"]
    out = []
    for argv in (["issue", "list", "--state", "open", *fields],
                 ["issue", "list", "--state", "closed", "--search", f"closed:>={since}", *fields]):
        got = gh(argv)
        try:
            rows = json.loads(got.stdout or "") if got.returncode == 0 else None
        except ValueError:
            rows = None
        if not isinstance(rows, list):
            return None
        if len(cuts.filled(rows, ISSUE_LIMIT, "review_issue_limit", "review dedup issue list")) >= ISSUE_LIMIT:
            return None
        out += rows
    return out


def duplicate_of(rows: list[dict], fp: str, file: str, symbol: str) -> int | None:
    """The issue that carries the fingerprint, or names both the file and the symbol."""
    word = re.compile(rf"(?<!\w){re.escape(symbol)}(?!\w)")
    for row in rows:
        text = f"{row.get('title') or ''}\n{row.get('body') or ''}"
        if fp in text or ((file in text or Path(file).name in text) and word.search(text)):
            return int(row["number"])
    return None


def _repro_text(f: dict) -> str:
    r = f["repro"]
    if r["kind"] == "test":
        return f"```python\n{r['body'].rstrip()}\n```"
    return f"```sh\n{shlex.join(r['argv'])}\n```\nThe defect shows when the output contains `{r['expect']}`."


def body_for(f: dict, cand: dict, sha: str, output: str) -> str:
    tail = "\n".join(output.rstrip().splitlines()[-OUTPUT_LINES:])
    return (f"The weekly adversarial review (#1149) found this at {sha[:12]} and reproduced it there.\n\n"
            f"**Where**: [`{f['file']}:{f['line']}`]({REPO_URL}/blob/{sha}/{f['file']}#L{f['line']}), "
            f"`{f['symbol']}`\n```\n{f['quote'].strip()}\n```\n\n"
            f"**Claim**: {f['claim'].strip()}\n\n"
            f"**Reproduction**, run in a clean worktree of {sha[:12]} with no network:\n{_repro_text(f)}\n\n"
            f"Observed ({cand['why']}):\n```\n{tail}\n```\n\n"
            f"**Refuted?** A separate session asked to disprove it confirmed it: {cand.get('refuter', '')}\n\n"
            f"**Prior art checked**: open issues and issues closed in the last {DEDUP_DAYS} days, by fingerprint "
            f"and by file and symbol; none matched.\n\n{FINGERPRINT} {cand['fingerprint']}\n")


def leaked(body: str, sha: str, fp: str) -> dict:
    """What redaction finds in a body, leaving out the SHA and fingerprint the review wrote itself."""
    from evals import redact
    for ours in (sha, sha[:12], fp):
        body = body.replace(ours, "")
    return redact.detect(body, redact.known_here())


def file_issue(gh, title: str, body: str) -> int:
    names = gh(["label", "list", "--search", LABEL, "--json", "name"])
    try:
        have = {r.get("name") for r in json.loads(names.stdout or "[]")}
    except ValueError:
        have = set()
    if LABEL not in have:
        gh(["label", "create", LABEL, "--description", "Filed by the weekly adversarial review (#1149)",
            "--color", "5319e7"])
    made = gh(["issue", "create", "--title", title, "--body", body, "--label", LABEL])
    hit = re.search(r"/issues/(\d+)", made.stdout or "")
    if made.returncode != 0 or not hit:
        raise RuntimeError(f"gh issue create: {(made.stderr or made.stdout or '').strip()[:300]}")
    return int(hit.group(1))


def receipts() -> list[dict]:
    out = []
    for path in sorted(home().glob("review-*.json")):
        try:
            r = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(r, dict):
            out.append(r)
    return sorted(out, key=lambda r: float(r.get("started") or 0))


def write(receipt: dict) -> dict:
    d = home()
    d.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(receipt["started"]))
    path, n = d / f"review-{stamp}.json", 1
    while path.exists():
        path, n = d / f"review-{stamp}-{n}.json", n + 1
    path.write_text(json.dumps(receipt, indent=1, sort_keys=True), encoding="utf-8")
    receipt["path"] = str(path)
    return receipt


def last_sha() -> str:
    done = [r for r in receipts() if r.get("source") == "repo" and r.get("sha") and not r.get("skipped")]
    return done[-1]["sha"] if done else ""


def stats(gh=gh_run, now: float | None = None) -> dict:
    """Per dimension, the filed issues' outcomes and precision, and whether the dimension is switched off."""
    now = time.time() if now is None else now
    filed: dict[int, tuple[str, float]] = {}
    for r in receipts():
        if r.get("source") != "repo":
            continue
        for c in r.get("candidates") or ():
            if c.get("fate") == "filed" and c.get("issue"):
                filed.setdefault(int(c["issue"]), (c["dimension"], float(r.get("started") or now)))
    if not filed:
        return {}
    got = gh(["issue", "list", "--label", LABEL, "--state", "all", "--limit", str(ISSUE_LIMIT),
              "--json", "number,state,stateReason"])
    try:
        state = {int(row["number"]): row for row in json.loads(got.stdout or "")} if got.returncode == 0 else {}
    except (ValueError, KeyError, TypeError):
        state = {}
    out: dict[str, dict] = {}
    for number, (dim, started) in sorted(filed.items()):
        s = out.setdefault(dim, {"filed": 0, "completed": 0, "not_planned": 0, "open": 0, "first": started})
        s["filed"] += 1
        s["first"] = min(s["first"], started)
        row = state.get(number) or {}
        if row.get("state") == "CLOSED" and row.get("stateReason") == "COMPLETED":
            s["completed"] += 1
        elif row.get("state") == "CLOSED":
            s["not_planned"] += 1
        else:
            s["open"] += 1
    for s in out.values():
        closed = s["completed"] + s["not_planned"]
        s["precision"] = round(s["completed"] / closed, 3) if closed else None
        s["weeks"] = round((now - s.pop("first")) / (7 * 86400), 1)
        low = s["precision"] is not None and s["precision"] < MIN_PRECISION
        s["off"] = bool(low and closed >= MIN_CLOSED and s["weeks"] >= PRECISION_WEEKS)
        s["held_by"] = "" if s["off"] or not low else (
            "review_min_closed" if closed < MIN_CLOSED else "review_precision_weeks")
    return out


def _scope(dim: str, since: str, sha: str, changed: list[str] | None) -> str:
    if changed is None:
        return "Scope: the whole repository."
    listed = "\n".join(f"- {name}" for name in changed)
    if dim == "gauntlet":
        return f"Scope: only the files changed since the last review ({since[:12]}..{sha[:12]}):\n{listed}"
    return (f"Scope: the whole repository, starting with the files changed since the last review "
            f"({since[:12]}..{sha[:12]}):\n{listed}")


def known_answer(kind: str, candidates: list[dict]) -> str:
    shown = [c for c in candidates if c["fate"] in SHOWN]
    if kind == "planted":
        return "found" if any((c.get("file"), c.get("symbol")) == PLANTED for c in shown) else "missed"
    return "false positive" if shown else "clean"


def run(source: Path | None = None, ref: str = "origin/main", *, fetch: bool = True, dimensions=DIMENSIONS,
        file: bool = False, ask=None, gh=None, repro=None, environ=None, wait: bool = True, say=print,
        now=time.time, sleep=time.sleep, since: str | None = None, wait_h: float | None = None) -> dict:
    """One review of `ref` in `source`; files only with `file` and LH_REVIEW_FILE=1; returns the receipt."""
    from evals import repo as repo_lane
    from harness import canary
    source = Path(source or paths.REPO)
    ask, gh = ask or claude_ask, gh or gh_run
    repro = repro or repo_lane.run_sandboxed
    environ = os.environ if environ is None else environ
    if is_off():
        say("the review is off (soh review on turns it back on)")
        return {"off": True, "candidates": [], "filed": []}
    kind = fixture_kind(source)
    filing = bool(file) and environ.get(FILE_ENV, "") == "1"
    started = now()
    head = {"started": started, "source": f"fixture:{kind}" if kind else "repo", "mode": "file" if filing else "dry",
            "candidates": [], "filed": [], "calls": [], "tokens": 0, "limits": [], "switched_off": {},
            "errors": {}}
    wait_h = WAIT_H if wait_h is None else wait_h
    deadline = started + wait_h * 3600
    while wait and canary.loop_running():
        if now() >= deadline:
            cuts.cut("review_wait_h", "review run skipped behind the discovery loop", kept=0, dropped=1)
            return write({**head, "finished": now(), "skipped": f"the discovery loop was still running after {wait_h:g} h"})
        say("  the discovery loop is running; waiting for it to finish")
        sleep(POLL_S)
    if fetch:
        _git(source, "fetch", "-q", "origin", "main")
    sha = _git(source, "rev-parse", f"{ref}^{{commit}}").strip()
    since = last_sha() if since is None and not kind else since
    changed = None
    if since and _git(source, "rev-parse", "--verify", "-q", f"{since}^{{commit}}", check=False).strip():
        changed = [n for n in _git(source, "diff", "--name-only", since, sha).splitlines() if n]
    else:
        since = ""
    receipt = {**head, "sha": sha, "since": since}
    for dim, s in stats(gh, now()).items():
        held = f"review dimension {dim} kept on below review_min_precision"
        if s["held_by"] == "review_min_closed":
            cuts.cut("review_min_closed", held, kept=1, dropped=0)
        elif s["held_by"] == "review_precision_weeks":
            cuts.cut("review_precision_weeks", held, kept=1, dropped=0)
        if s["off"]:
            cuts.cut("review_min_precision", f"review dimension {dim} switched off", kept=0, dropped=1)
            receipt["switched_off"][dim] = (f"precision {s['precision']} over {s['completed'] + s['not_planned']} "
                                            f"closed issues in {s['weeks']} weeks, below {MIN_PRECISION}")
    rows = issues(gh, now())
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(started)) + f"-{os.getpid()}"
    work = home() / "work"
    work.mkdir(parents=True, exist_ok=True)
    # sandbox-exec matches its write root by realpath.
    work = work.resolve()
    finder = _worktree(source, sha, work / f"{stamp}-find")
    seen: set[str] = set()
    shown = 0
    capped = 0

    def spent() -> int:
        return receipt["tokens"]

    def call(prompt: str, cwd: Path, role: str, dim: str) -> dict:
        began = time.monotonic()
        try:
            got = ask(prompt, cwd, role)
        except CallFailed as exc:
            receipt["calls"].append({"role": role, "dimension": dim, "tokens": _t(exc.usage), "error": str(exc),
                                     "wall_s": round(time.monotonic() - began, 1)})
            receipt["tokens"] += tokens(exc.usage)
            if exc.limit:
                receipt["limits"].append(exc.limit)
            raise
        receipt["calls"].append({"role": role, "dimension": dim, "tokens": _t(got["usage"]),
                                 "wall_s": round(time.monotonic() - began, 1)})
        receipt["tokens"] += tokens(got["usage"])
        return got

    def over_budget() -> bool:
        if spent() < TOKEN_BUDGET:
            return False
        limit = knobs.limit("review_token_budget", TOKEN_BUDGET, "tokens")
        if limit not in receipt["limits"]:
            receipt["limits"].append(limit)
            cuts.cut("review_token_budget", "review claude -p calls", kept=len(receipt["calls"]), dropped=1)
        return True

    try:
        for dim in dimensions:
            if dim in receipt["switched_off"]:
                say(f"  {dim}: switched off, {receipt['switched_off'][dim]}")
                continue
            if dim == "gauntlet" and changed == []:
                say("  gauntlet: nothing changed since the last review")
                continue
            if over_budget():
                break
            prompt = FIND.format(sha=sha, ask=ASK[dim], scope=_scope(dim, since, sha, changed), probe=PROBE,
                                 n=CANDIDATES)
            try:
                got = call(prompt, finder, f"find:{dim}", dim)
            except CallFailed as exc:
                receipt["errors"][dim] = str(exc)
                continue
            parsed = _json(got["text"])
            found = parsed.get("findings") if isinstance(parsed, dict) else None
            if not isinstance(found, list):
                receipt["errors"][dim] = "the finder's reply held no findings list"
                continue
            for f in cuts.take(found, CANDIDATES, "review_candidates", f"review {dim} findings"):
                cand = {"dimension": dim, "fate": "", "why": ""}
                receipt["candidates"].append(cand)
                why = _valid(f)
                if why:
                    cand.update(fate="malformed", why=why, title=str(f.get("title", ""))[:200] if isinstance(f, dict) else "")
                    continue
                fp = fingerprint(f["file"], f["quote"])
                cand.update(title=f["title"][:200], file=f["file"], line=f["line"], symbol=f["symbol"], fingerprint=fp)
                why = quoted(source, sha, f)
                if why:
                    cand.update(fate="unquoted", why=why)
                    continue
                if fp in seen:
                    cand.update(fate="duplicate", why="an earlier finding in this run quotes the same line")
                    continue
                seen.add(fp)
                if rows is None:
                    cand.update(fate="unchecked", why="the open and recently closed issues could not be read whole")
                    continue
                dup = duplicate_of(rows, fp, f["file"], f["symbol"])
                if dup is not None:
                    cand.update(fate="duplicate", issue=dup, why=f"#{dup} carries its fingerprint or names its "
                                                                  "file and symbol")
                    continue
                if shown >= MAX_FINDINGS:
                    capped += 1
                    cand.update(fate="capped", why=f"{MAX_FINDINGS} findings already shown this run")
                    continue
                if over_budget():
                    cand.update(fate="unverified", why="the token budget is spent")
                    continue
                verify = _worktree(source, sha, work / f"{stamp}-verify-{len(receipt['candidates'])}")
                try:
                    state, why, output = reproduce(f, verify, repro)
                    cand["why"] = why
                    if state != "reproduced":
                        cand["fate"] = state
                        continue
                    result = f"{why}\n{output[-1500:]}"
                    try:
                        said = call(REFUTE.format(sha=sha, title=f["title"], file=f["file"], line=f["line"],
                                                  quote=f["quote"].strip(), claim=f["claim"], kind=f["repro"]["kind"],
                                                  repro=_repro_text(f), result=result), verify, "refute", dim)
                    except CallFailed as exc:
                        cand.update(fate="unverified", why=f"the refuter did not answer: {exc}")
                        continue
                finally:
                    _drop(source, verify)
                verdict = _json(said["text"])
                if not isinstance(verdict, dict) or verdict.get("verdict") != "confirmed":
                    reason = verdict.get("why") if isinstance(verdict, dict) else said["text"][:200]
                    cand.update(fate="refuted", why=f"refuter: {reason}")
                    continue
                cand["refuter"] = str(verdict.get("why") or "")[:500]
                body = body_for(f, cand, sha, output)
                leaks = leaked(body, sha, fp)
                if leaks:
                    cand.update(fate="withheld", why=f"the body would hold {', '.join(sorted(leaks))}")
                    continue
                shown += 1
                title = f"review ({dim}): {f['title'][:150]}"
                if not filing:
                    cand.update(fate="would file", issue_title=title, body=body)
                    continue
                try:
                    number = file_issue(gh, title, body)
                except RuntimeError as exc:
                    cand.update(fate="not filed", why=str(exc))
                    continue
                cand.update(fate="filed", issue=number)
                receipt["filed"].append(number)
    finally:
        _drop(source, finder)
    if capped:
        receipt["limits"].append(knobs.limit("review_max_findings", MAX_FINDINGS, "issues"))
        cuts.cut("review_max_findings", "review findings shown", kept=shown, dropped=capped)
    if kind:
        receipt["known_answer"] = known_answer(kind, receipt["candidates"])
    receipt["finished"] = now()
    return write(receipt)


def _t(usage: dict) -> dict:
    return {**{k: int(usage.get(k) or 0) for k in USAGE}, "total": tokens(usage)}
