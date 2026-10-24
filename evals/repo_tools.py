"""The repair harness's tools over a repo attempt's checkout: list, search, read, patch, run visible tests, finish. #890."""
from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import sys
from pathlib import Path

from evals import repo, sandbox
from evals.sandbox import Refused

#: Bytes of one tool result the model is sent; the rest is cut with a note saying so.
OUTPUT_CAP = 8000
#: Directories no tool lists, reads or patches: the git link to the mirror that holds the fix, the grader's own.
HIDDEN = (".git", repo.HARNESS_DIR)
_SKIP_DIRS = {*HIDDEN, "__pycache__", ".venv", "node_modules", ".mypy_cache", ".ruff_cache", ".pytest_cache"}
_SEARCH_FILE_BYTES = 1_000_000

TOOLS = {
    "list_files": {
        "description": "List the repository's files under a directory, one path per line.",
        "parameters": {"type": "object", "additionalProperties": False, "properties": {
            "path": {"type": "string", "description": "Directory relative to the repository root; default the root."}}}},
    "search": {
        "description": "Search the repository's text files for a Python regular expression; prints path:line: text.",
        "parameters": {"type": "object", "additionalProperties": False, "required": ["pattern"], "properties": {
            "pattern": {"type": "string", "description": "Python regular expression."},
            "path": {"type": "string", "description": "Directory or file to search; default the root."}}}},
    "read_file": {
        "description": "Read a text file, or the lines start_line..end_line of it (1-based, inclusive).",
        "parameters": {"type": "object", "additionalProperties": False, "required": ["path"], "properties": {
            "path": {"type": "string", "description": "Path relative to the repository root."},
            "start_line": {"type": "integer", "description": "First line to show; default 1."},
            "end_line": {"type": "integer", "description": "Last line to show; default the end."}}}},
    "apply_patch": {
        "description": "Apply a unified diff (as `git diff` prints it, paths a/ and b/ from the repository root) "
                       "to the working tree. It applies whole or not at all; an error says why.",
        "parameters": {"type": "object", "additionalProperties": False, "required": ["patch"], "properties": {
            "patch": {"type": "string", "description": "The unified diff."}}}},
    "run_tests": {
        "description": "Run pytest on test files of the repository and return the output's tail. Default: the "
                       "test files this task's checks live in, where the repository has them.",
        "parameters": {"type": "object", "additionalProperties": False, "properties": {
            "path": {"type": "string", "description": "A test file or pytest node id, e.g. tests/test_x.py::test_y."}}}},
    "finish": {
        "description": "Say the change is done. The working tree as it stands is what gets graded.",
        "parameters": {"type": "object", "additionalProperties": False, "properties": {
            "summary": {"type": "string", "description": "One line on what changed."}}}},
}


def visible_tests(task: Path) -> set[str]:
    """Test files the base commit has: what a developer of the repository could run before the fix."""
    got = repo._git(["ls-files", "-z"], cwd=task).stdout.decode("utf-8", errors="replace")
    return {p for p in got.split("\0") if p.endswith(".py") and repo.is_test_path(p)
            and Path(p).name != "conftest.py" and (Path(p).name.startswith("test_") or p.endswith("_test.py"))}


def cut(text: str) -> str:
    data = text.encode("utf-8", errors="replace")
    if len(data) <= OUTPUT_CAP:
        return text
    return (data[:OUTPUT_CAP].decode("utf-8", errors="ignore")
            + f"\n... [cut: {len(data)} bytes, the first {OUTPUT_CAP} shown]")


def _readable_roots(python: Path) -> list[Path]:
    """The venv and the interpreter it was made from, which pytest must read under a profile that hides $HOME."""
    venv = python.parent.parent
    roots = [venv]
    cfg = venv / "pyvenv.cfg"
    if cfg.is_file():
        for line in cfg.read_text(encoding="utf-8", errors="replace").splitlines():
            key, _, value = line.partition("=")
            if key.strip() == "home" and value.strip():
                base = Path(value.strip()).parent
                roots += [base, Path(os.path.realpath(base))]
    roots.append(Path(os.path.realpath(python)).parent.parent)
    return roots


_BARE = re.compile(r"^(---|\+\+\+) (?!a/|b/|/dev/null)(\S.*)$")


def _prefixed(diff: str) -> str:
    """A diff whose ---/+++ paths lack git's a/ and b/ prefixes, given them, as `git apply -p0` would read it."""
    def fix(m):
        return f"{m.group(1)} {'a' if m.group(1) == '---' else 'b'}/{m.group(2)}"
    return "".join(_BARE.sub(fix, line.rstrip("\n")) + "\n" if _BARE.match(line) else line
                   for line in diff.splitlines(keepends=True))


def default_denied(attempt) -> list[Path]:
    """Where the fix and its tests can be read: $HOME (other checkouts), every mirror, the source repository."""
    out = [Path.home(), repo.cache_root() / "mirrors", Path(attempt.mirror)]
    source = Path(str(attempt.params.get("source_repo") or "")).expanduser()
    return out + ([source] if str(source) not in ("", ".") and source.is_dir() else [])


def hiding_profile(denied, readable) -> str:
    """The repo grading profile, plus file contents under `denied` unreadable except under `readable`."""
    return (repo.PROFILE + "".join(f'(deny file-read-data (subpath "{os.path.realpath(d)}"))\n' for d in denied)
            + "".join(f'(allow file-read-data (subpath "{os.path.realpath(r)}"))\n' for r in readable))


def run_hidden(argv: list, task: Path, timeout: float, denied, readable) -> tuple[int, str, bool]:
    """(returncode, output, timed out) of argv in task under sandbox-exec with `denied` unreadable."""
    if sys.platform != "darwin" or not Path(repo.SANDBOX_EXEC).is_file():
        raise repo.RepoEnvError(f"run_tests needs {repo.SANDBOX_EXEC} (macOS); this host has none")
    home, tmp = task / repo.HARNESS_DIR / "home", task / repo.HARNESS_DIR / "tmp"
    home.mkdir(parents=True, exist_ok=True)
    tmp.mkdir(parents=True, exist_ok=True)
    profile = task / repo.HARNESS_DIR / "tools.sb"
    profile.write_text(hiding_profile(denied, [task, *readable]), encoding="utf-8")
    env = {"PATH": "/usr/bin:/bin", "HOME": str(home), "TMPDIR": str(tmp),
           "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1", "NO_COLOR": "1"}
    proc = subprocess.Popen([repo.SANDBOX_EXEC, "-f", str(profile), "-D", f"TASK={task}", *argv], cwd=task,
                            env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
    try:
        out, _ = proc.communicate(timeout=timeout)
        return proc.returncode, out.decode(errors="replace"), False
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        out, _ = proc.communicate()
        return -9, out.decode(errors="replace"), True


class Workspace(sandbox.Sandbox):
    """One attempt's checkout as the model sees it; hidden tests are not in it until grading."""
    SCHEMAS = TOOLS

    def __init__(self, attempt, test_timeout=None, deadline=None, denied=None):
        super().__init__(attempt.task, tools=tuple(TOOLS))
        self.attempt = attempt
        self.visible = visible_tests(self.root)
        self.test_timeout = test_timeout
        #: () -> seconds left in the case; a test run never outlives it.
        self.deadline = deadline
        self.denied = default_denied(attempt) if denied is None else list(denied)
        self.touched: set[str] = set()
        self.finished: str | None = None
        self.test_runs = 0

    def call(self, name, arguments):
        got, out = super().call(name, arguments)
        return got, cut(out)

    def resolve(self, rel) -> Path:
        if isinstance(rel, str) and any(p in HIDDEN for p in re.split(r"[\\/]+", rel.strip())):
            raise Refused(f"not part of the repository: {rel}")
        return super().resolve(rel)

    def _files(self, top: Path):
        if top.is_file():
            yield top
            return
        for dirpath, dirnames, filenames in os.walk(top):
            dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS and not d.endswith(".egg-info"))
            for f in sorted(filenames):
                p = Path(dirpath) / f
                if not p.is_symlink():
                    yield p

    def list_files(self, path=".") -> str:
        top = self.resolve(path or ".")
        if not top.is_dir():
            raise Refused(f"no such directory: {path}")
        return "\n".join(self.rel(p) for p in self._files(top)) or "(empty)"

    def search(self, pattern, path=".") -> str:
        try:
            rx = re.compile(pattern)
        except re.error as exc:
            raise Refused(f"not a Python regular expression: {exc}") from None
        top = self.resolve(path or ".")
        if not top.exists():
            raise Refused(f"no such path: {path}")
        hits = []
        for p in self._files(top):
            if p.stat().st_size > _SEARCH_FILE_BYTES:
                continue
            try:
                lines = p.read_text(encoding="utf-8").splitlines()
            except (UnicodeDecodeError, OSError):
                continue
            hits += [f"{self.rel(p)}:{i}: {line[:300]}" for i, line in enumerate(lines, 1) if rx.search(line)]
        return "\n".join(hits) or "no match"

    def read_file(self, path, start_line=1, end_line=0) -> str:
        p = self.resolve(path)
        if not p.is_file():
            raise Refused(f"no such file: {path}")
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
        try:
            first = max(1, int(start_line or 1))
            last = min(len(lines), int(end_line)) if end_line else len(lines)
        except (TypeError, ValueError):
            raise Refused("start_line and end_line must be whole numbers") from None
        if first > max(len(lines), 1):
            raise Refused(f"{path} has {len(lines)} lines")
        return f"{self.rel(p)} lines {first}-{last} of {len(lines)}:\n" + "".join(lines[first - 1:last])

    def apply_patch(self, patch) -> str:
        text = repo.extract_diff(patch) or patch
        if not text.strip():
            raise Refused("the patch is empty")
        text = _prefixed(text if text.endswith("\n") else text + "\n")
        headed = repo.with_git_headers(text, lambda p: (self.root / p).exists())
        chunks = repo.file_chunks(headed)
        if not chunks:
            raise Refused("no file in the patch: it needs --- a/<path> and +++ b/<path> lines and @@ hunks")
        for rel, _ in chunks:
            if any(part in HIDDEN for part in Path(rel).parts):
                raise Refused(f"not part of the repository: {rel}")
            if repo.is_test_path(rel):
                raise Refused(f"{rel} is a test file; tests are the grader's and may not be changed")
        got = repo._git(["apply", "--recount", "--whitespace=nowarn", "-"], cwd=self.root, check=False,
                        input=headed.encode("utf-8"))
        if got.returncode:
            raise Refused("git apply: " + got.stderr.decode(errors="replace").strip()[-1500:])
        self.touched |= {rel for rel, _ in chunks}
        names = [rel for rel, _ in chunks]
        if not repo._git(["status", "--porcelain", "--", *names], cwd=self.root).stdout.strip():
            return f"applied to {', '.join(names)}, but they are unchanged from base: each - line equals its + line"
        return f"applied to {', '.join(names)}"

    def _targets(self, path) -> list[str]:
        if path:
            file = str(path).partition("::")[0].strip()
            if file not in self.visible:
                raise Refused(f"{file} is not a test file of this repository; run_tests takes one of: "
                              + ", ".join(sorted(self.visible)[:40]))
            return [str(path).strip()]
        p = self.attempt.params
        mine = sorted({i.partition("::")[0] for i in [*p["fail_to_pass"], *(p.get("pass_to_pass") or [])]}
                      & self.visible)
        if not mine:
            raise Refused("the repository has no test file for this task yet; pass path, one of: "
                          + ", ".join(sorted(self.visible)[:40]))
        return mine

    def run_tests(self, path="") -> str:
        targets = self._targets(path)
        timeout = float(self.test_timeout or repo.TEST_TIMEOUT_S)
        if self.deadline is not None:
            timeout = min(timeout, max(1.0, self.deadline()))
        self.test_runs += 1
        args = self.attempt.params.get("pytest_args") or ()
        rc, out, late = run_hidden([str(self.attempt.python), "-m", "pytest", "-p", "no:cacheprovider", "-q",
                                    "-o", "addopts=", *args, *targets], self.root, timeout,
                                   self.denied, _readable_roots(self.attempt.python))
        tail = out[-OUTPUT_CAP:]
        return (f"tests timed out after {timeout:g}s\n" if late else f"pytest exit {rc}\n") + tail

    def finish(self, summary="") -> str:
        self.finished = str(summary or "")
        return "finished"

    def diff(self) -> str:
        """The working tree's change to the files the model patched, vs base; the tree is then put back to base."""
        shutil.rmtree(self.root / repo.HARNESS_DIR, ignore_errors=True)
        paths = sorted(self.touched)
        out = ""
        if paths:
            repo._git(["add", "-N", "--", *[p for p in paths if (self.root / p).exists()]], cwd=self.root, check=False)
            out = repo._git(["diff", "--no-renames", "HEAD", "--", *paths], cwd=self.root).stdout.decode("utf-8")
        repo._git(["reset", "--hard", "--quiet"], cwd=self.root, check=False)
        repo._git(["clean", "-fdq"], cwd=self.root, check=False)
        return out


def openai_tools() -> list[dict]:
    return sandbox.openai_tools(TOOLS, TOOLS)
