"""The repo lane's executor: restore a commit, build its environment, apply a diff, grade it sandboxed. #887."""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

SANDBOX_EXEC = "/usr/bin/sandbox-exec"
TEST_TIMEOUT_S = 600.0
ENV_TIMEOUT_S = 1800.0
GIT_TIMEOUT_S = 600.0
_SHA = re.compile(r"^[0-9a-f]{40}$")
#: Lock and manifest files whose bytes decide the environment; one venv per digest of them.
ENV_FILES = ("uv.lock", "pyproject.toml", ".python-version")
PROFILE = """(version 1)
(allow default)
(deny network*)
(deny file-write*)
(allow file-write* (subpath (param "TASK")) (literal "/dev/null") (literal "/dev/zero")
       (regex #"^/dev/tty") (regex #"^/dev/fd/"))
"""
_FENCE = re.compile(r"```[ \t]*(?:diff|patch|udiff)?[ \t]*\n(.*?)```", re.S)
#: SWE-Llama's trained reply shape (#922); an unclosed tag is a reply cut off mid-patch.
_TAG = re.compile(r"<(patch|diff)>(.*?)(?:</\1>|\Z)", re.S)
REPLY = ("Reply with one unified diff (as `git diff` prints it, paths a/ and b/ from the "
         "repository root) that fixes the issue, and nothing else. Do not change tests.")


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
    if params.get("variant") not in ("spec", "symptom"):
        raise ValueError(f"{name}: params.variant must be spec or symptom")
    if params.get("context") != "oracle":
        raise ValueError(f"{name}: params.context must be oracle")
    for key in ("fail_to_pass", "pass_to_pass", "context_files", "new_files"):
        if not isinstance(params.get(key) or [], list):
            raise ValueError(f"{name}: params.{key} must be a list")
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


def env_digest(task: Path) -> str:
    h = hashlib.sha256()
    for name in ENV_FILES:
        f = task / name
        h.update(name.encode("utf-8") + b"\x00" + (f.read_bytes() if f.is_file() else b"") + b"\x00")
    return h.hexdigest()[:16]


def prepare(task: Path) -> Path:
    """The venv `uv sync --frozen` builds from the pristine base checkout, cached per lockfile digest; network only here."""
    if not (task / "uv.lock").is_file():
        raise RepoEnvError("the base commit has no uv.lock to build an environment from")
    venv = cache_root() / "envs" / env_digest(task)
    if (venv / ".built").is_file():
        return venv
    tmp = venv.with_name(f"{venv.name}.{os.getpid()}-{uuid.uuid4().hex[:6]}")
    uv = shutil.which("uv") or "uv"
    env = {**os.environ, "UV_PROJECT_ENVIRONMENT": str(tmp)}
    env.pop("VIRTUAL_ENV", None)
    try:
        got = subprocess.run([uv, "sync", "--frozen", "--no-install-project", "--quiet"], cwd=task,
                             capture_output=True, text=True, timeout=ENV_TIMEOUT_S, env=env)
    except subprocess.TimeoutExpired as exc:
        shutil.rmtree(tmp, ignore_errors=True)
        raise RepoEnvError(f"uv sync timed out after {exc.timeout:g}s") from exc
    if got.returncode:
        shutil.rmtree(tmp, ignore_errors=True)
        raise RepoEnvError(f"uv sync --frozen failed: {got.stderr.strip()[-400:]}")
    (tmp / ".built").write_text(env_digest(task), encoding="utf-8")
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


def extract_diff(reply: str) -> str:
    """The diff in a reply: a <patch>/<diff> body, else a fenced block that looks like one, else from the first header on."""
    text = str(reply or "")
    for _, block in _TAG.findall(text):
        block = block.lstrip("\r\n")
        if re.search(r"^(diff --git |--- |@@ )", block, re.M):
            return block if block.endswith("\n") else block + "\n"
    for block in _FENCE.findall(text):
        if re.search(r"^(diff --git |--- |@@ )", block, re.M):
            return block if block.endswith("\n") else block + "\n"
    m = re.search(r"^(diff --git |--- a/|--- )", text, re.M)
    if not m:
        return ""
    body = text[m.start():]
    return body if body.endswith("\n") else body + "\n"


def apply(task: Path, diff: str) -> tuple[bool, str]:
    """git apply, then git apply --3way; (applied, plain apply's error). git refuses paths that leave the tree."""
    if not diff.strip():
        return False, "the reply holds no diff"
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
    parts = rest.split("::")
    module = path.removesuffix(".py").replace("/", ".")
    return f"{'.'.join([module, *parts[:-1]])}::{parts[-1]}"


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


def grade(task: Path, python: Path, fail_to_pass, pass_to_pass) -> Grade:
    """Run the named tests sandboxed; resolved when pytest reports every one of them passed."""
    timeout = TEST_TIMEOUT_S
    ids = [*fail_to_pass, *pass_to_pass]
    report = task / HARNESS_DIR / "junit.xml"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.unlink(missing_ok=True)
    started = time.perf_counter()
    rc, tail, late = run_sandboxed([str(python), "-m", "pytest", "-p", "no:cacheprovider", "-q",
                                    "-o", "addopts=", f"--junitxml={report}", *ids], task, timeout)
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
        return Grade(False, True, why or f"pytest exited {rc}: {tail[-300:]}", took, failed)
    return Grade(True, True, "", took, [])


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
            venv = (env or prepare)(task)
        except BaseException:
            discard(m, task)
            raise
        return cls(m, task, python_of(Path(venv)), params)

    def prompt(self, issue: str) -> str:
        return prompt_for(issue, self.task, self.params["context_files"],
                          self.params.get("new_files") or ())

    def submit(self, diff: str) -> Grade:
        applied, why = apply(self.task, diff)
        if not applied:
            return Grade(False, False, why)
        p = self.params
        install_tests(self.mirror, self.task, p["base"], p["fix"])
        return grade(self.task, self.python, p["fail_to_pass"], p.get("pass_to_pass") or [])

    def close(self) -> None:
        discard(self.mirror, self.task)


def controls(params: dict, env=None) -> dict:
    """{empty: resolved?, reference: resolved?}: a sound task fails the first and passes the second."""
    out = {}
    for name in ("empty", "reference"):
        a = Attempt.open(params, env)
        try:
            diff = "" if name == "empty" else reference_diff(a.mirror, params["base"], params["fix"])
            if name == "empty":
                install_tests(a.mirror, a.task, params["base"], params["fix"])
                g = grade(a.task, a.python, params["fail_to_pass"], params.get("pass_to_pass") or [])
            else:
                g = a.submit(diff)
            out[name] = {"resolved": g.resolved, "detail": g.detail, "test_s": g.test_s}
        finally:
            a.close()
    return out
