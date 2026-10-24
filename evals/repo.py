"""The repo lane's executor: restore a commit, build its environment, apply a diff, grade it sandboxed. #887."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import uuid
from fnmatch import fnmatchcase
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

SANDBOX_EXEC = "/usr/bin/sandbox-exec"
TEST_TIMEOUT_S = 600.0
ENV_TIMEOUT_S = 1800.0
GIT_TIMEOUT_S = 600.0
#: Runs per side a case control takes; an id whose outcome changes between them makes the case flaky. #920.
VALIDATION_RUNS = 3
_SHA = re.compile(r"^[0-9a-f]{40}$")
#: Lock and manifest files whose bytes decide the environment; one venv per digest of them.
ENV_FILES = ("uv.lock", "pyproject.toml", ".python-version")
#: Documentation a hunk may fail to apply in and leave the rest graded, when no test names the file. #1107.
DOC_PATTERNS = ("*.md", "*.rst", "docs/**", "CHANGELOG*")
#: The warning a row carries for each documentation file whose hunks were left out. #1107.
DOC_HUNK_SKIPPED = "doc_hunk_skipped"
PROFILE = """(version 1)
(allow default)
(deny network*)
(deny file-write*)
(allow file-write* (subpath (param "TASK")) (literal "/dev/null") (literal "/dev/zero")
       (regex #"^/dev/tty") (regex #"^/dev/fd/"))
"""
#: Fence info strings whose block may hold the diff.
_DIFF_INFO = ("", "diff", "patch", "udiff")
_HUNK = re.compile(r"^@@ -\d+(?:,(\d+))? \+\d+(?:,(\d+))? @@")
#: SWE-Llama's trained reply shape (#922); an unclosed tag is a reply cut off mid-patch.
_TAG = re.compile(r"<(patch|diff)>(.*?)(?:</\1>|\Z)", re.S)
REPLY = ("Reply with one unified diff (as `git diff` prints it, paths a/ and b/ from the "
         "repository root) that fixes the issue, and nothing else. Do not change tests.")
#: The variant whose prompt is a cut Claude Code session (#1095); it is asked as a quotation. #1129.
SESSION_VARIANT = "request"
QUOTE_HEAD = ("Each line below that starts with > quotes the record of an earlier Claude Code session, "
              "cut just before the agent's first edit to the code. That session is over: its tool calls "
              "ran then, none can run now, and it is not a conversation to continue. Write the change "
              "it was heading toward.\n\n")
QUOTE_END = "\n\n(End of the quoted session.)"
STATED_HEAD = "What the finished change does (stated for this exam; the session had not reached it):"
#: Tool-call markup an agent-trained model emits (#921 codebook class tool_call).
_TOOL_CALL = re.compile(r"<tool_call>|<function=")


class RepoEnvError(RuntimeError):
    """The mirror, the checkout or the environment could not be built: nothing is known about the model."""


@dataclass
class Grade:
    resolved: bool = False
    patch_applied: bool = False
    detail: str = ""
    test_s: float = 0.0
    failed: list = field(default_factory=list)
    #: The `limit:` body when the tests ran past our timeout, else "".
    limit: str = ""
    #: {"path", "why"} of each documentation file left out because its hunks did not apply. #1107.
    skipped: list = field(default_factory=list)
    #: Failing id -> the tail of pytest's failure text for it, so a grade can be audited without a rerun. #1141.
    failures: dict = field(default_factory=dict)


#: The grader's own directory in a task: sandbox profile, HOME, TMPDIR, junit report. #899.
HARNESS_DIR = ".grade"


def cache_root() -> Path:
    from harness import paths
    return paths.home() / "repo-cache"


def is_test_path(path: str) -> bool:
    """A file the model may not change and the grader supplies: under tests/, test_*.py, *_test.py, conftest.py."""
    parts = Path(path).parts
    name = parts[-1] if parts else ""
    return ("tests" in parts or "test" in parts or name.startswith("test_")
            or name.endswith("_test.py") or name == "conftest.py")


def validate(name: str, params: dict) -> None:
    """Refuse a repo case that cannot be graded, naming the field. #887."""
    for key in ("source_repo", "base", "fix", "fail_to_pass", "context_files"):
        if not params.get(key):
            raise ValueError(f"{name}: a repo case needs params.{key}")
    for key in ("base", "fix"):
        if not _SHA.match(str(params[key])):
            raise ValueError(f"{name}: params.{key} must be a 40-hex commit sha")
    if params.get("variant") not in ("spec", "symptom", "request"):
        raise ValueError(f"{name}: params.variant must be spec, symptom or request")
    if params.get("context") != "oracle":
        raise ValueError(f"{name}: params.context must be oracle")
    for key in ("fail_to_pass", "pass_to_pass", "context_files", "new_files", "pytest_args", "extras", "interface"):
        if not isinstance(params.get(key) or [], list):
            raise ValueError(f"{name}: params.{key} must be a list")
    for key in ("pytest_args", "extras", "interface"):
        odd = [x for x in params.get(key) or [] if not isinstance(x, str)]
        if odd:
            raise ValueError(f"{name}: params.{key} must be strings, not {odd}")
    new = params.get("new_files") or []
    shown = [p for p in [*params["context_files"], *new] if is_test_path(p)]
    if shown:
        raise ValueError(f"{name}: context_files would show the model tests: {shown}")
    both = sorted(set(params["context_files"]) & set(new))
    if both:
        raise ValueError(f"{name}: {both} cannot be both shown at base and created by the fix")


def _git(args, cwd=None, check=True, input=None) -> subprocess.CompletedProcess:
    timeout = GIT_TIMEOUT_S
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_NOSYSTEM": "1"}
    got = subprocess.run(["git", *args], cwd=cwd, capture_output=True, timeout=timeout,
                         env=env, input=input)
    if check and got.returncode:
        raise RepoEnvError(f"git {' '.join(map(str, args[:3]))}: "
                                f"{got.stderr.decode(errors='replace').strip()[-400:]}")
    return got


def _has(mirror: Path, sha: str) -> bool:
    return not _git(["--git-dir", str(mirror), "cat-file", "-e", f"{sha}^{{commit}}"],
                    check=False).returncode


def mirror_path(source: str) -> Path:
    """Where `source`'s mirror lives: its last path component, capped, and a digest of the whole."""
    key = hashlib.sha256(source.encode("utf-8")).hexdigest()[:12]
    # Either separator: a whole Windows path kept as the name overran MAX_PATH. #897.
    last = re.split(r"[/\\]", source.rstrip("/\\"))[-1]
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "-", last).removesuffix(".git")[:40]
    return cache_root() / "mirrors" / f"{stem}-{key}.git"


def mirror(source: str, need=()) -> Path:
    """A bare mirror of `source` under the cache, fetched until it holds every commit in `need`."""
    path = mirror_path(source)
    try:
        if not path.is_dir():
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(f"{path.name}.{uuid.uuid4().hex[:8]}")
            _git(["clone", "--mirror", "--quiet", source, str(tmp)])
            try:
                tmp.rename(path)
            except OSError:
                shutil.rmtree(tmp, ignore_errors=True)
        if not all(_has(path, sha) for sha in need):
            _git(["--git-dir", str(path), "fetch", "--quiet", "--prune", "origin"])
    except subprocess.TimeoutExpired as exc:
        raise RepoEnvError(f"mirror {source}: timed out after {exc.timeout:g}s") from exc
    missing = [sha for sha in need if not _has(path, sha)]
    if missing:
        raise RepoEnvError(f"mirror {source} does not hold {', '.join(missing)}")
    return path


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def sweep(mirror_path: Path | None = None) -> None:
    """Remove attempt dirs a killed run left behind, and the mirror's records of them."""
    work = cache_root() / "work"
    for d in work.glob("*") if work.is_dir() else ():
        pid = d.name.split("-", 1)[0]
        if pid.isdigit() and not _alive(int(pid)):
            shutil.rmtree(d, ignore_errors=True)
    if mirror_path is not None:
        _git(["--git-dir", str(mirror_path), "worktree", "prune"], check=False)


def restore(mirror_path: Path, sha: str) -> Path:
    """A detached worktree of `sha` in a fresh attempt dir; remove with discard()."""
    sweep(mirror_path)
    dest = cache_root() / "work" / f"{os.getpid()}-{uuid.uuid4().hex[:10]}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    _git(["--git-dir", str(mirror_path), "worktree", "add", "--detach", "--quiet", str(dest), sha])
    return dest.resolve()


def discard(mirror_path: Path, task: Path) -> None:
    _git(["--git-dir", str(mirror_path), "worktree", "remove", "--force", str(task)], check=False)
    shutil.rmtree(task, ignore_errors=True)
    _git(["--git-dir", str(mirror_path), "worktree", "prune"], check=False)


def env_digest(task: Path, extras=()) -> str:
    h = hashlib.sha256()
    for name in ENV_FILES:
        f = task / name
        h.update(name.encode("utf-8") + b"\x00" + (f.read_bytes() if f.is_file() else b"") + b"\x00")
    if extras:
        h.update(b"extras\x00" + "\x00".join(sorted(extras)).encode("utf-8"))
    return h.hexdigest()[:16]


def prepare(task: Path, extras=()) -> Path:
    """The venv `uv sync --frozen` builds from the pristine base checkout, cached per lockfile digest and extras."""
    if not (task / "uv.lock").is_file():
        raise RepoEnvError("the base commit has no uv.lock to build an environment from")
    venv = cache_root() / "envs" / env_digest(task, extras)
    if (venv / ".built").is_file():
        return venv
    tmp = venv.with_name(f"{venv.name}.{os.getpid()}-{uuid.uuid4().hex[:6]}")
    uv = shutil.which("uv") or "uv"
    env = {**os.environ, "UV_PROJECT_ENVIRONMENT": str(tmp)}
    env.pop("VIRTUAL_ENV", None)
    try:
        got = subprocess.run([uv, "sync", "--frozen", "--no-install-project", "--quiet",
                              *(a for x in sorted(extras) for a in ("--extra", x))], cwd=task,
                             capture_output=True, text=True, timeout=ENV_TIMEOUT_S, env=env)
    except subprocess.TimeoutExpired as exc:
        shutil.rmtree(tmp, ignore_errors=True)
        raise RepoEnvError(f"uv sync timed out after {exc.timeout:g}s") from exc
    if got.returncode:
        shutil.rmtree(tmp, ignore_errors=True)
        raise RepoEnvError(f"uv sync --frozen failed: {got.stderr.strip()[-400:]}")
    (tmp / ".built").write_text(env_digest(task, extras), encoding="utf-8")
    try:
        tmp.rename(venv)
    except OSError:
        shutil.rmtree(tmp, ignore_errors=True)
    return venv


def python_of(venv: Path) -> Path:
    return venv / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def context_block(task: Path, files) -> str:
    """Each context file at the base commit, under its path."""
    out = []
    for rel in files:
        f = task / rel
        if not f.is_file():
            raise RepoEnvError(f"context file {rel} is not in the base commit")
        out.append(f"--- {rel} ---\n{f.read_text(encoding='utf-8', errors='replace')}")
    return "\n\n".join(out)


def prompt_for(issue: str, task: Path, files, new=()) -> str:
    """The issue, the context files at base, and the files the fix creates, which base does not have. #913."""
    create = ("Files to create (they do not exist at the commit to fix): "
              f"{', '.join(new)}\n\n") if new else ""
    return (f"{issue.strip()}\n\nThe relevant files at the commit to fix:\n\n"
            f"{context_block(task, files)}\n\n{create}{REPLY}")


def quoted(prompt: str) -> str:
    """A session-cut prompt as a quotation: the importer's lead replaced, every session line behind > ."""
    from evals.session_cut import HEAD
    body = prompt[len(HEAD):] if prompt.startswith(HEAD) else prompt
    lines = body.strip("\n").splitlines()
    return QUOTE_HEAD + "\n".join(f"> {line}" if line else ">" for line in lines) + QUOTE_END


def as_asked(case):
    """The case with the issue text and system prompt (params.system) it is asked with. #1129."""
    import dataclasses

    from harness import completion
    prompt = case.prompt
    if case.params.get("variant") == SESSION_VARIANT:
        from evals import interface
        shown = interface.block(case.params.get("interface") or [])
        stated = case.params.get("stated") or ""
        prompt = (quoted(prompt) + (f"\n\n{shown}" if shown else "")
                  + (f"\n\n{STATED_HEAD}\n{stated.strip()}" if stated else ""))
    return dataclasses.replace(case, prompt=prompt, params={**case.params, "system": completion.SYSTEM["repo"]})


def calls_tools(reply: str, diff: str) -> bool:
    """A reply that holds no diff and calls tools instead, as an agent would. #1129."""
    return not (diff or "").strip() and bool(_TOOL_CALL.search(str(reply or "")))


def _fenced(text: str):
    """(info, body) of each fenced block; in a diff block a ``` line closes it only outside a hunk's counted lines. #1131."""
    lines, i = text.splitlines(keepends=True), 0
    while i < len(lines):
        head = lines[i].strip()
        i += 1
        if not head.startswith("```"):
            continue
        info, body, old, new = head[3:].strip(), [], 0, 0
        while i < len(lines):
            bare = lines[i].rstrip("\r\n")
            tag = bare[:1]
            if (old > 0 or new > 0) and tag in (" ", "+", "-", "\\", ""):
                old -= tag in (" ", "", "-")
                new -= tag in (" ", "", "+")
            elif bare.strip() == "```":
                break
            else:
                hunk = _HUNK.match(bare) if info in _DIFF_INFO else None
                old, new = (int(hunk.group(1) or 1), int(hunk.group(2) or 1)) if hunk else (0, 0)
            body.append(lines[i])
            i += 1
        i += 1
        yield info, "".join(body)


def extract_diff(reply: str) -> str:
    """The diff in a reply: a <patch>/<diff> body, else a fenced block that looks like one, else from the first header on."""
    text = str(reply or "")
    for _, block in _TAG.findall(text):
        block = block.lstrip("\r\n")
        if re.search(r"^(diff --git |--- |@@ )", block, re.M):
            return block if block.endswith("\n") else block + "\n"
    for info, block in _fenced(text):
        if info in _DIFF_INFO and re.search(r"^(diff --git |--- |@@ )", block, re.M):
            return block if block.endswith("\n") else block + "\n"
    m = re.search(r"^(diff --git |--- a/|--- )", text, re.M)
    if not m:
        return ""
    body = text[m.start():]
    return body if body.endswith("\n") else body + "\n"


_SIDE = re.compile(r"^(?:---|\+\+\+) (?:[ab]/(\S+)|(/dev/null))(?:\t.*)?\r?\n?$")
_EXTENDED = re.compile(r"^(index |old mode |new mode |new file mode |deleted file mode |similarity index "
                       r"|dissimilarity index |rename from |rename to |copy from |copy to )")


def _headed(lines: list[str], i: int) -> bool:
    j = i - 1
    while j >= 0 and _EXTENDED.match(lines[j]):
        j -= 1
    return j >= 0 and lines[j].startswith("diff --git ")


def _header_at(lines: list[str], i: int) -> bool:
    return lines[i].startswith("--- ") and i + 2 < len(lines) and lines[i + 1].startswith("+++ ") \
        and lines[i + 2].startswith("@@ ")


def _creates(lines: list[str], i: int) -> bool:
    """Whether every hunk of the file headed at line i has an empty old side (`@@ -0,0 `). #1174."""
    j, hunks = i + 2, []
    while j < len(lines) and not lines[j].startswith("diff --git ") and not (j > i + 2 and _header_at(lines, j)):
        if lines[j].startswith("@@ "):
            hunks.append(lines[j])
        j += 1
    return bool(hunks) and all(h.startswith("@@ -0,0 ") for h in hunks)


def with_git_headers(diff: str, exists=None) -> str:
    """A `diff --git` line before each ---/+++/@@ file header lacking one, so --recount stops at it (#940); with
    `exists(path)`, an `a/` side whose hunks are all -0,0 on a path absent at base becomes a creation (#1174)."""
    lines = diff.splitlines(keepends=True)
    out = []
    for i, line in enumerate(lines):
        if _header_at(lines, i) and not _headed(lines, i):
            old, new = _SIDE.match(line), _SIDE.match(lines[i + 1])
            path = old and new and (new.group(1) or old.group(1))
            if path:
                out.append(f"diff --git a/{path} b/{path}\n")
                created = (exists is not None and old.group(1) and new.group(1) and _creates(lines, i)
                           and not exists(old.group(1)))
                if old.group(2) or created:
                    out.append("new file mode 100644\n")
                if created:
                    line = "--- /dev/null" + line[len(line.rstrip("\r\n")):]
        out.append(line)
    return "".join(out)


def _at_base(task: Path):
    return lambda path: (task / path).exists()


def apply(task: Path, diff: str) -> tuple[bool, str]:
    """git apply, then git apply --3way; (applied, plain apply's error). git refuses paths that leave the tree."""
    if not diff.strip():
        return False, "the reply holds no diff"
    diff = with_git_headers(diff, _at_base(task))
    tries = (["apply", "--recount", "--whitespace=nowarn"],
             ["apply", "--3way", "--recount", "--whitespace=nowarn"])
    why = ""
    for args in tries:
        got = _git([*args, "-"], cwd=task, check=False, input=diff.encode("utf-8"))
        if not got.returncode:
            return True, ""
        # A diff with no index lines always fails --3way with "lacks the necessary blob", hiding why. #913.
        why = why or got.stderr.decode(errors="replace").strip()[-400:]
        _git(["reset", "--hard", "--quiet"], cwd=task, check=False)
        _git(["clean", "-fdq"], cwd=task, check=False)
    return False, f"git apply: {why}"


def is_doc(path: str) -> bool:
    """A documentation file by DOC_PATTERNS (a pattern without / matches the file name); never a test or .py file."""
    if is_test_path(path) or path.endswith(".py"):
        return False
    name = Path(path).name
    return any(fnmatchcase(path if "/" in pat else name, pat) for pat in DOC_PATTERNS)


_GIT_LINE = re.compile(r"^diff --git a/(\S+) b/(\S+)")


def file_chunks(diff: str) -> list[tuple[str, str]]:
    """(path, text) of each `diff --git` section of a diff that with_git_headers has headed."""
    out = []
    for line in diff.splitlines(keepends=True):
        m = _GIT_LINE.match(line)
        if m:
            out.append([m.group(2), line])
        elif out:
            out[-1][1] += line
    return [(p, t) for p, t in out]


def named_by_tests(mirror_path: Path, base: str, fix: str, path: str, ids=()) -> bool:
    """Whether a test file the grader runs (hidden tests, the ids' files, their conftest.py) names `path`'s file name."""
    files = set(hidden_tests(mirror_path, base, fix)) | {i.partition("::")[0] for i in ids}
    files |= {"/".join([*f.split("/")[:n], "conftest.py"]) for f in list(files) for n in range(f.count("/") + 1)}
    name = Path(path).name.encode("utf-8")
    return any(name in (_blob(mirror_path, fix, f) or _blob(mirror_path, base, f) or b"") for f in sorted(files))


def apply_docs_aside(task: Path, diff: str, named) -> tuple[bool, str, list]:
    """apply; when it fails and only documentation files no test names (`named(path)`) fail alone, apply the rest."""
    applied, why = apply(task, diff)
    if applied or not diff.strip():
        return applied, why, []
    chunks = file_chunks(with_git_headers(diff, _at_base(task)))
    failed = {}
    for path, text in chunks:
        got = _git(["apply", "--check", "--recount", "--whitespace=nowarn", "-"], cwd=task, check=False,
                   input=text.encode("utf-8"))
        if got.returncode:
            failed.setdefault(path, got.stderr.decode(errors="replace").strip()[-300:])
    rest = "".join(t for p, t in chunks if p not in failed)
    if not failed or any(not is_doc(p) or named(p) for p in failed):
        return False, why, []
    applied, _ = apply(task, rest)
    if not applied:
        return False, why, []
    return True, "", [{"path": p, "why": failed[p]} for p in sorted(failed)]


def changed(mirror_path: Path, base: str, fix: str) -> list[tuple[str, str]]:
    """(status, path) of every file base..fix touched."""
    got = _git(["--git-dir", str(mirror_path), "diff", "--name-status", "--no-renames", base, fix])
    return [tuple(line.split("\t", 1)) for line in got.stdout.decode().splitlines() if "\t" in line]


def hidden_tests(mirror_path: Path, base: str, fix: str) -> list[str]:
    """The test files the fix commit added or changed, which the model never sees."""
    return [p for s, p in changed(mirror_path, base, fix) if is_test_path(p) and s != "D"]


def reference_diff(mirror_path: Path, base: str, fix: str) -> str:
    """The fix commit's non-test changes: the control that must resolve."""
    paths = [p for _, p in changed(mirror_path, base, fix) if not is_test_path(p)]
    if not paths:
        return ""
    return _git(["--git-dir", str(mirror_path), "diff", "--no-renames", base, fix, "--", *paths]
                ).stdout.decode("utf-8")


def _blob(mirror_path: Path, sha: str, path: str) -> bytes | None:
    got = _git(["--git-dir", str(mirror_path), "show", f"{sha}:{path}"], check=False)
    return None if got.returncode else got.stdout


def install_tests(mirror_path: Path, task: Path, base: str, fix: str) -> None:
    """Every test file the model touched goes back to the fix (else base) version; the fix's tests go in."""
    touched = _git(["status", "--porcelain", "--untracked-files=all", "--no-renames"], cwd=task
                   ).stdout.decode().splitlines()
    paths = {line[3:].strip() for line in touched if line[3:].strip()}
    paths = {p for p in paths if Path(p).parts[:1] != (HARNESS_DIR,)}
    for rel in sorted({p for p in paths if is_test_path(p)} | set(hidden_tests(mirror_path, base, fix))):
        data = _blob(mirror_path, fix, rel)
        if data is None:
            data = _blob(mirror_path, base, rel)
        f = task / rel
        if data is None:
            f.unlink(missing_ok=True)
            continue
        f.parent.mkdir(parents=True, exist_ok=True)
        if f.is_symlink():
            f.unlink()
        f.write_bytes(data)


def _junit_ids(xml: Path) -> tuple[set, set]:
    """(passed, not passed) node ids from pytest's junit report."""
    ok, bad = set(), set()
    for case in ET.parse(xml).getroot().iter("testcase"):
        cls, name = case.get("classname") or "", case.get("name") or ""
        key = f"{cls}::{name}"
        (bad if any(child.tag in ("failure", "error", "skipped") for child in case) else ok).add(key)
    return ok, bad


def junit_key(node: str) -> str:
    """tests/test_x.py::Cls::test_f[p] as junit writes it: tests.test_x.Cls::test_f[p]."""
    path, _, rest = node.partition("::")
    head, bracket, param = rest.partition("[")
    parts = head.split("::")
    module = path.removesuffix(".py").replace("/", ".")
    # A parametrize id may hold "::" itself ([::1]); only the name before "[" is split. #889.
    return f"{'.'.join([module, *parts[:-1]])}::{parts[-1]}{bracket}{param}"


def sandboxed(argv: list, task: Path) -> list:
    """argv under sandbox-exec: no network, no write outside the task dir."""
    if sys.platform != "darwin" or not Path(SANDBOX_EXEC).is_file():
        raise RepoEnvError(f"grading needs {SANDBOX_EXEC} (macOS); this host has none")
    profile = task / HARNESS_DIR / "profile.sb"
    profile.parent.mkdir(parents=True, exist_ok=True)
    profile.write_text(PROFILE, encoding="utf-8")
    return [SANDBOX_EXEC, "-f", str(profile), "-D", f"TASK={task}", *argv]


def run_sandboxed(argv: list, task: Path, timeout: float) -> tuple[int, str, bool]:
    """(returncode, output tail, timed out) of argv run sandboxed in task with HOME and TMPDIR inside it."""
    home, tmp = task / HARNESS_DIR / "home", task / HARNESS_DIR / "tmp"
    home.mkdir(parents=True, exist_ok=True)
    tmp.mkdir(parents=True, exist_ok=True)
    env = {"PATH": "/usr/bin:/bin", "HOME": str(home), "TMPDIR": str(tmp),
           "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1", "NO_COLOR": "1"}
    proc = subprocess.Popen(sandboxed(argv, task), cwd=task, env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, start_new_session=True)
    try:
        out, _ = proc.communicate(timeout=timeout)
        return proc.returncode, out.decode(errors="replace")[-2000:], False
    except subprocess.TimeoutExpired:
        if sys.platform == "win32":
            proc.kill()
        else:
            os.killpg(proc.pid, signal.SIGKILL)
        out, _ = proc.communicate()
        return -9, out.decode(errors="replace")[-2000:], True


def grade(task: Path, python: Path, fail_to_pass, pass_to_pass, args=()) -> Grade:
    """Run the named tests sandboxed, with the source's own pytest `args`; resolved when every one passed."""
    timeout = TEST_TIMEOUT_S
    ids = [*fail_to_pass, *pass_to_pass]
    report, want = task / HARNESS_DIR / "junit.xml", task / HARNESS_DIR / "grade.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.unlink(missing_ok=True)
    want.write_text(json.dumps(sorted(ids)), encoding="utf-8")
    started = time.perf_counter()
    # Whole files, keeping the named ids: one id that does not collect must not stop the rest from running. #1141.
    rc, tail, late = run_sandboxed([str(python), "-c", _ONLY, str(want), "-p", "no:cacheprovider", "-q",
                                    "-o", "addopts=", *args, "--continue-on-collection-errors",
                                    f"--junitxml={report}", *sorted({i.partition("::")[0] for i in ids})],
                                   task, timeout)
    took = round(time.perf_counter() - started, 3)
    if late:
        return Grade(False, True, f"tests timed out after {timeout:g}s", took, ids,
                     f"repo_test_timeout_s>{timeout:g}")
    if not report.is_file():
        return Grade(False, True, f"pytest wrote no report (exit {rc}): {tail[-300:]}", took, ids)
    ok, _ = _junit_ids(report)
    failed = [i for i in ids if junit_key(i) not in ok]
    if rc or failed:
        f2p = [i for i in fail_to_pass if i in failed]
        p2p = [i for i in pass_to_pass if i in failed]
        why = "; ".join(x for x in (f"fail_to_pass still failing: {', '.join(f2p)}" if f2p else "",
                                    f"pass_to_pass broken: {', '.join(p2p)}" if p2p else "") if x)
        return Grade(False, True, why or f"pytest exited {rc}: {tail[-300:]}", took, failed,
                     failures=failure_text(report, failed))
    return Grade(True, True, "", took, [])


FAILURE_CHARS = 1500


def failure_text(xml: Path, ids) -> dict:
    """Each of `ids`' failure or error text from a junit report, its last FAILURE_CHARS; "missing" when it never ran."""
    from harness import cuts
    got, long = {}, 0
    for case in ET.parse(xml).getroot().iter("testcase"):
        bad = next((child for child in case if child.tag in ("failure", "error")), None)
        if bad is not None:
            text = f"{bad.get('message') or ''}\n{bad.text or ''}".strip()
            long += len(text) > FAILURE_CHARS
            got[f"{case.get('classname') or ''}::{case.get('name') or ''}"] = text[-FAILURE_CHARS:]
    if long:
        cuts.cut("repo_failure_chars", "junit failure texts kept by their tail only", dropped=long)
    return {i: got.get(junit_key(i), "missing: the test did not run") for i in ids}


@dataclass
class Attempt:
    """One case's checkout, with its environment, ready for a diff."""
    mirror: Path
    task: Path
    python: Path
    params: dict

    @classmethod
    def open(cls, params: dict, env=None) -> "Attempt":
        m = mirror(str(params["source_repo"]), need=(params["base"], params["fix"]))
        task = restore(m, params["base"])
        try:
            extras = params.get("extras") or ()
            venv = env(task) if env else prepare(task, extras) if extras else prepare(task)
        except BaseException:
            discard(m, task)
            raise
        return cls(m, task, python_of(Path(venv)), params)

    def prompt(self, issue: str) -> str:
        return prompt_for(issue, self.task, self.params["context_files"],
                          self.params.get("new_files") or ())

    def submit(self, diff: str) -> Grade:
        p = self.params
        ids = [*p["fail_to_pass"], *(p.get("pass_to_pass") or [])]
        applied, why, skipped = apply_docs_aside(
            self.task, diff, lambda path: named_by_tests(self.mirror, p["base"], p["fix"], path, ids))
        if not applied:
            return Grade(False, False, why)
        install_tests(self.mirror, self.task, p["base"], p["fix"])
        got = grade(self.task, self.python, p["fail_to_pass"], p.get("pass_to_pass") or [],
                    p.get("pytest_args") or ())
        got.skipped = skipped
        return got

    def close(self) -> None:
        discard(self.mirror, self.task)


#: pytest on whole files, keeping only the named ids, so an id the base cannot collect is missing, not a usage error.
_ONLY = ("import json, sys, pytest\n"
         "want = set(json.load(open(sys.argv[1], encoding='utf-8')))\n"
         "class Only:\n"
         "    def pytest_collection_modifyitems(self, config, items):\n"
         "        config.hook.pytest_deselected(items=[i for i in items if i.nodeid not in want])\n"
         "        items[:] = [i for i in items if i.nodeid in want]\n"
         "sys.exit(pytest.main(sys.argv[2:], plugins=[Only()]))\n")


def _junit_outcomes(xml: Path) -> tuple[dict, dict]:
    """(junit key -> passed|failed|skipped|error, the test file or directory that failed to collect -> why)."""
    out, broken = {}, {}
    for case in ET.parse(xml).getroot().iter("testcase"):
        tags = {child.tag for child in case}
        if not case.get("classname") and "error" in tags:
            broken[(case.get("name") or "").replace(".", "/")] = collect_error(case.find("error").text or "")
            continue
        out[f"{case.get('classname') or ''}::{case.get('name') or ''}"] = (
            "failed" if "failure" in tags else "error" if "error" in tags
            else "skipped" if "skipped" in tags else "passed")
    return out, broken


def collect_errors(xml: Path) -> dict:
    return _junit_outcomes(xml)[1]


#: The collection error at base that counts as a failing test (SWE-bench's rule): it names the fix's own symbol. #1098.
ADMIT = "repo_symbol"
_RAISED = re.compile(r"^E\s+(ModuleNotFoundError|ImportError|AttributeError|SyntaxError|IndentationError)\b:?\s*(.*)$", re.M)
_NAMED = re.compile(r"No module named '([\w.]+)'|cannot import name '\w+' from '([\w.]+)'|^module '([\w.]+)' has no attribute ")


def collect_error(text: str) -> dict:
    """{"kind": import|attribute|syntax|conftest|other, "module": the module the error names, else ""}."""
    raised = _RAISED.findall(text)
    if re.search(r"^\S*conftest\.py:\d+: in ", text, re.M):
        return {"kind": "conftest", "module": ""}
    if not raised:
        return {"kind": "other", "module": ""}
    exc, msg = raised[-1]
    named = _NAMED.search(msg)
    module = next((g for g in named.groups() if g), "") if named else ""
    kind = ("syntax" if exc in ("SyntaxError", "IndentationError") else
            "attribute" if exc == "AttributeError" else "import")
    return {"kind": kind if module or kind == "syntax" else "other", "module": module}


def owns(tree: Path | None, module: str) -> bool:
    """Whether `module` is a file or package of the checkout at `tree` (its root or a src/ layout)."""
    rel = module.replace(".", "/")
    return bool(tree and module) and any(
        (root / f"{rel}.py").is_file() or (root / rel).is_dir() for root in (tree, tree / "src"))


def collect_cause(err: dict, tree: Path | None) -> str:
    """Why a test file did not collect, judged against the reference checkout: ADMIT, or an environment cause."""
    kind, module = err.get("kind"), err.get("module") or ""
    if kind in ("import", "attribute"):
        return ADMIT if owns(tree, module) else "third_party_module" if kind == "import" else "other"
    return {"syntax": "syntax_error", "conftest": "conftest"}.get(kind, "other")


def broken_key(path: str, broken) -> str | None:
    """The collection error covering test file `path`: its own, or its directory's (a conftest's)."""
    stem = path.removesuffix(".py")
    return next((k for k in broken if stem == k or stem.startswith(k + "/")), None)


def base_causes(ids, base: dict, causes: dict) -> dict:
    """id -> why it errored at base: its file's collection cause, else "setup" for an id that errored itself."""
    out = {}
    for i in ids:
        k = broken_key(i.partition("::")[0], causes)
        if k is not None:
            out[i] = causes[k]
        elif base.get(i) == "error":
            out[i] = "setup"
    return out


def run_ids(task: Path, python: Path, ids, args=()) -> dict:
    """{"ids": id -> passed|failed|skipped|error|missing, "error": why the run said nothing, else ""}."""
    timeout = TEST_TIMEOUT_S
    files = sorted({i.partition("::")[0] for i in ids})
    report, want = task / HARNESS_DIR / "control.xml", task / HARNESS_DIR / "control.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.unlink(missing_ok=True)
    want.write_text(json.dumps(sorted(ids)), encoding="utf-8")
    rc, tail, late = run_sandboxed([str(python), "-c", _ONLY, str(want), "-p", "no:cacheprovider", "-q",
                                    "-o", "addopts=", *args, "--continue-on-collection-errors",
                                    f"--junitxml={report}", *files], task, timeout)
    if late:
        return {"ids": {}, "error": f"tests timed out after {timeout:g}s"}
    if not report.is_file() or rc in (3, 4):
        said = "wrote no report" if not report.is_file() else "stopped on an internal or usage error"
        return {"ids": {}, "error": f"pytest {said} (exit {rc}): {tail[-300:]}"}
    got, broken = _junit_outcomes(report)
    return {"ids": {i: got.get(junit_key(i)) or ("error" if broken_key(i.partition("::")[0], broken) else "missing")
                    for i in ids}, "error": "", "collect": broken}


def verdict(base_runs: list, ref_runs: list, fail_to_pass, pass_to_pass, causes=None) -> str:
    """SWE-bench's check test by test: valid, invalid: <why>, flaky: <ids> or error: <why>; `causes` from collect_cause."""
    for side, runs in (("base", base_runs), ("reference", ref_runs)):
        bad = next((r["error"] for r in runs if r["error"]), "")
        if bad:
            return f"error: {side}: {bad}"
    shifting = sorted({i for runs in (base_runs, ref_runs) for r in runs for i in r["ids"]
                       if len({x["ids"].get(i) for x in runs}) > 1})
    if shifting:
        return f"flaky: {', '.join(shifting)}"
    base, ref = base_runs[0]["ids"], ref_runs[0]["ids"]
    why = {i: c for i, c in base_causes([*fail_to_pass, *pass_to_pass], base, causes or {}).items()
           if base.get(i) == "error"}
    held = [f"{i} ({c})" for i, c in why.items() if not (c == ADMIT and i in fail_to_pass)]
    if held:
        return f"error: base: did not collect or set up: {', '.join(held)}"
    base = {**base, **{i: "failed" for i in why}}
    checks = (("fail_to_pass passes at base", base, fail_to_pass, {"passed"}),
              ("fail_to_pass does not run at base", base, fail_to_pass, {"skipped"}),
              ("pass_to_pass fails at base", base, pass_to_pass, {"failed", "skipped", "missing", None}),
              ("reference fails", ref, [*fail_to_pass, *pass_to_pass],
               {"failed", "error", "skipped", "missing", None}))
    why = []
    for label, got, ids, bad in checks:
        off = [f"{i} ({got.get(i) or 'missing'})" for i in ids if got.get(i) in bad]
        if off:
            why.append(f"{label}: {', '.join(off)}")
    return f"invalid: {'; '.join(why)}" if why else "valid"


def controls(case, env=None, runs=None, memo=None) -> dict:
    """Validate one case the way a candidate meets it: prompt, then each test at base+hidden tests and with the reference."""
    p = case.params
    runs = runs or VALIDATION_RUNS
    f2p, p2p = list(p["fail_to_pass"]), list(p.get("pass_to_pass") or [])
    out = {"verdict": "", "prompt": "", "env_digest": "", "base": [], "reference": [], "collect": {}}
    try:
        a = Attempt.open(p, env)
    except RepoEnvError as exc:
        return {**out, "verdict": f"error: environment: {exc}"}
    try:
        out["env_digest"] = env_digest(a.task, p.get("extras") or ())
        try:
            a.prompt(case.prompt)
        except RepoEnvError as exc:
            out["prompt"] = str(exc)
            return {**out, "verdict": f"invalid: prompt: {exc}"}
        key = json.dumps([p["source_repo"], p["base"], p["fix"], f2p, p2p, out["env_digest"], runs,
                          *([p["pytest_args"]] if p.get("pytest_args") else [])])
        if memo is not None and key in memo:
            return {**out, **memo[key]}
        install_tests(a.mirror, a.task, p["base"], p["fix"])
        extra = p.get("pytest_args") or ()
        out["base"] = [run_ids(a.task, a.python, [*f2p, *p2p], extra) for _ in range(runs)]
        applied, why = apply(a.task, reference_diff(a.mirror, p["base"], p["fix"]))
        if not applied:
            return {**out, "verdict": f"invalid: reference does not apply: {why}"}
        install_tests(a.mirror, a.task, p["base"], p["fix"])
        out["reference"] = [run_ids(a.task, a.python, [*f2p, *p2p], extra) for _ in range(runs)]
        out["collect"] = {k: collect_cause(e, a.task) for k, e in (out["base"][0].get("collect") or {}).items()}
    finally:
        a.close()
    out["verdict"] = verdict(out["base"], out["reference"], f2p, p2p, out["collect"])
    if out["verdict"] == "valid":
        admitted = base_causes(f2p, {}, out["collect"])
        out["admitted_by"] = "base_collect_" + ADMIT if ADMIT in admitted.values() else "fails_at_base"
    if memo is not None:
        memo[key] = {k: out[k] for k in ("base", "reference", "verdict", "collect", "admitted_by") if k in out}
    return out


def validation_path(case_id: str) -> Path:
    from harness import paths
    return paths.home() / "validation" / "repo" / f"{case_id}.json"


def save_validation(case, got: dict, machine: str, commit: str, now: float) -> dict:
    """Keep `got` as this machine's latest validation of `case`, beside other machines' own."""
    from evals.core import cases_digest
    rec = {"case": case.id, "cases_digest": cases_digest([case]), "sohot_commit": commit,
           "machine": machine, "at": now, **got}
    path = validation_path(case.id)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        held = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        held = {}
    held[machine] = rec
    tmp = path.with_name(f"{path.name}.{os.getpid()}")
    tmp.write_text(json.dumps(held, indent=1) + "\n", encoding="utf-8")
    tmp.replace(path)
    return rec


def verdicts(cases, machine: str) -> dict:
    """case id -> this machine's latest verdict, "unvalidated" when none, "stale" when the case changed since."""
    from evals.core import cases_digest
    out = {}
    for case in cases:
        try:
            rec = json.loads(validation_path(case.id).read_text(encoding="utf-8")).get(machine)
        except (OSError, ValueError):
            rec = None
        out[case.id] = ("unvalidated" if not rec else
                        "stale" if rec.get("cases_digest") != cases_digest([case]) else rec["verdict"])
    return out
