"""The agent lane's sandbox: a tmp copy of a case repo and four tools over it. #474.

Every path a model names is confined to the copy: absolute paths, `..`,
symlinked components and NUL bytes are refused before anything is opened. The
one tool that runs a process, run_tests, builds its argv from an allowlist
(never a shell), and the child installs an audit hook before importing anything
the model wrote, refusing writes outside the copy, process spawns, sockets and
ctypes.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath

READ_CAP = 200_000
WRITE_CAP = 256_000
TEST_TIMEOUT_S = 60.0
OUTPUT_CAP = 6_000
HIDDEN_DIR = "_hidden_tests"

TOOLS = {
    "read_file": {
        "description": "Read a UTF-8 text file in the repository.",
        "parameters": {"type": "object", "additionalProperties": False,
                       "required": ["path"],
                       "properties": {"path": {
                           "type": "string",
                           "description": "Path relative to the repository root."}}}},
    "write_file": {
        "description": "Create or overwrite a text file in the repository "
                       "with the full new content.",
        "parameters": {"type": "object", "additionalProperties": False,
                       "required": ["path", "content"],
                       "properties": {
                           "path": {"type": "string",
                                    "description": "Path relative to the repository root."},
                           "content": {"type": "string",
                                       "description": "The complete file content."}}}},
    "list_dir": {
        "description": "List a directory in the repository; directories end in /.",
        "parameters": {"type": "object", "additionalProperties": False,
                       "properties": {"path": {
                           "type": "string",
                           "description": "Directory relative to the repository "
                                          "root; default is the root."}}}},
    "run_tests": {
        "description": "Run the repository's unittest suite, or one test file "
                       "under tests/, and return the output.",
        "parameters": {"type": "object", "additionalProperties": False,
                       "properties": {"path": {
                           "type": "string",
                           "description": "Optional test file such as "
                                          "tests/test_x.py; default runs all."}}}},
}

#: The only processes the sandbox starts, by name; argv is built, never parsed.
COMMANDS = ("unittest",)

_TEST_FILE = re.compile(r"^tests/[A-Za-z0-9_]+(/[A-Za-z0-9_]+)*\.py$")

#: Runs in the child before any repo code: confine writes, refuse escapes.
BOOTSTRAP = r'''
import os, sys
ROOT = os.path.realpath(sys.argv[1])
_W = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC
_DENY = ("subprocess.Popen", "os.system", "os.exec", "os.posix_spawn",
         "os.spawn", "os.fork", "os.forkpty", "os.startfile", "pty.spawn",
         "ctypes.dlopen", "ctypes.dlsym", "ctypes.cdata", "ctypes.call_function",
         "socket.connect", "socket.bind", "socket.getaddrinfo", "socket.sendto",
         "socket.gethostbyname", "socket.__new__", "_winapi.CreateProcess",
         "os.kill", "os.killpg", "signal.pthread_kill", "winreg.SetValue",
         "sys.remote_exec", "webbrowser.open")
_PATHS = {"os.remove": (0,), "os.rmdir": (0,), "os.rename": (0, 1),
          "os.mkdir": (0,), "os.symlink": (0, 1), "os.link": (0, 1),
          "os.chmod": (0,), "os.chown": (0,), "os.truncate": (0,),
          "os.utime": (0,), "shutil.rmtree": (0,), "os.chflags": (0,),
          "os.lchmod": (0,), "os.mkfifo": (0,), "os.mknod": (0,)}

def _inside(p):
    if isinstance(p, int) or p is None:
        return True
    p = os.fsdecode(p)
    if p == os.devnull:
        return True
    p = os.path.realpath(os.path.join(ROOT, p))
    return p == ROOT or p.startswith(ROOT + os.sep)

def _hook(event, args):
    if event in _DENY:
        raise PermissionError(f"sandbox: {event} is not allowed")
    if event == "open":
        path, mode, flags = (list(args) + [None, None, None])[:3]
        writing = (isinstance(mode, str) and any(c in mode for c in "wax+")) \
            or (isinstance(flags, int) and flags & _W)
        if writing and not _inside(path):
            raise PermissionError(f"sandbox: write outside the repo: {path}")
    elif event in _PATHS:
        for i in _PATHS[event]:
            if i < len(args) and not _inside(args[i]):
                raise PermissionError(f"sandbox: {event} outside the repo")

try:
    import ctypes  # its import dlopens the interpreter itself; later loads and calls are refused
except ImportError:
    pass
sys.addaudithook(_hook)
sys.dont_write_bytecode = True
import unittest
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.argv = ["unittest"] + sys.argv[2:]
unittest.main(module=None)
'''


class Refused(ValueError):
    """A tool argument the sandbox will not act on."""


@dataclass
class Call:
    """One tool call as the model made it, and what the sandbox made of it."""
    name: str
    raw: str
    parsed: bool = False
    schema_ok: bool = False
    real: bool = False
    ok: bool = False
    why: str = ""

    @property
    def valid(self) -> bool:
        return self.parsed and self.schema_ok and self.real


def _absolute(path: str) -> bool:
    return (PurePosixPath(path).is_absolute() or PureWindowsPath(path).is_absolute()
            or bool(PureWindowsPath(path).drive) or path.startswith(("/", "\\", "~")))


class Sandbox:
    def __init__(self, root: Path, tools=tuple(TOOLS), test_timeout: float = TEST_TIMEOUT_S):
        self.root = Path(os.path.realpath(root))
        self.tools = tuple(tools)
        self.test_timeout = test_timeout
        self._owned: Path | None = None

    @classmethod
    def create(cls, source: Path, extra: dict | None = None, **kw) -> "Sandbox":
        """A fresh tmp copy of `source`, plus `extra` files (padding)."""
        _refuse_links(Path(source))
        top = Path(tempfile.mkdtemp(prefix="soh-agent-"))
        root = top / "repo"
        shutil.copytree(source, root, symlinks=True,
                        ignore=shutil.ignore_patterns("__pycache__"))
        box = cls(root, **kw)
        box._owned = top
        for rel, text in (extra or {}).items():
            box.write_file(rel, text)
        return box

    def cleanup(self) -> None:
        if self._owned is not None:
            shutil.rmtree(self._owned, ignore_errors=True)
            self._owned = None

    def resolve(self, rel) -> Path:
        """The path `rel` names inside the root, or Refused."""
        if not isinstance(rel, str):
            raise Refused("path must be a string")
        rel = rel.strip() or "."
        if "\x00" in rel:
            raise Refused("path contains a NUL byte")
        if _absolute(rel):
            raise Refused(f"absolute paths are not allowed: {rel}")
        parts = [p for p in re.split(r"[\\/]+", rel) if p not in ("", ".")]
        if ".." in parts:
            raise Refused(f"'..' is not allowed: {rel}")
        here = self.root
        for part in parts:
            here = here / part
            if here.is_symlink():
                raise Refused(f"symlinks are not followed: {rel}")
        real = Path(os.path.realpath(here))
        if real != self.root and self.root not in real.parents:
            raise Refused(f"outside the repository: {rel}")
        return real

    def rel(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix() or "."

    def read_file(self, path) -> str:
        p = self.resolve(path)
        if not p.is_file():
            raise Refused(f"no such file: {path}")
        if p.stat().st_size > READ_CAP:
            raise Refused(f"file is larger than {READ_CAP} bytes: {path}")
        try:
            return p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            raise Refused(f"not a UTF-8 text file: {path}") from None

    def write_file(self, path, content) -> str:
        if not isinstance(content, str):
            raise Refused("content must be a string")
        data = content.encode("utf-8")
        if len(data) > WRITE_CAP:
            raise Refused(f"content is larger than {WRITE_CAP} bytes")
        p = self.resolve(path)
        if p == self.root or p.is_dir():
            raise Refused(f"is a directory: {path}")
        self._mkdirs(p.parent)
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0) \
            | getattr(os, "O_BINARY", 0)
        fd = os.open(p, flags, 0o644)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        return f"wrote {len(data)} bytes to {self.rel(p)}"

    def _mkdirs(self, d: Path) -> None:
        if d == self.root or d.is_dir():
            if d.is_symlink():
                raise Refused("symlinks are not followed")
            return
        self._mkdirs(d.parent)
        d.mkdir()

    def list_dir(self, path=".") -> str:
        p = self.resolve(path if path is not None else ".")
        if not p.is_dir():
            raise Refused(f"no such directory: {path}")
        out = []
        for child in sorted(p.iterdir(), key=lambda c: c.name):
            if child.name in ("__pycache__", HIDDEN_DIR):
                continue
            out.append(child.name + ("/" if child.is_dir() and not child.is_symlink() else ""))
        return "\n".join(out) or "(empty)"

    def argv(self, command: str, args: list[str]) -> list[str]:
        """The argv for an allowlisted command. Nothing else is ever run."""
        if command not in COMMANDS:
            raise Refused(f"command not allowed: {command}")
        return [sys.executable, "-I", "-X", "utf8", "-c", BOOTSTRAP,
                str(self.root), *args]

    def run_tests(self, path=None) -> str:
        if path in (None, "", ".", "tests", "tests/"):
            args = ["discover", "-s", "tests"]
        else:
            if not isinstance(path, str) or not _TEST_FILE.match(path):
                raise Refused("path must name a test file like tests/test_x.py")
            if not self.resolve(path).is_file():
                raise Refused(f"no such test file: {path}")
            args = [path[:-3].replace("/", ".")]
        rc, out = self.execute("unittest", args)
        return f"exit code {rc}\n{out}"

    def execute(self, command: str, args: list[str]) -> tuple[int, str]:
        env = {"PYTHONIOENCODING": "utf-8", "HOME": str(self.root),
               "TMPDIR": str(self.root), "PATH": ""}
        if os.name == "nt":
            env["SYSTEMROOT"] = os.environ.get("SYSTEMROOT", "")
        try:
            done = subprocess.run(self.argv(command, args), cwd=self.root,
                                  env=env, stdin=subprocess.DEVNULL,
                                  capture_output=True, text=True,
                                  encoding="utf-8", errors="replace",
                                  timeout=self.test_timeout, shell=False)
        except subprocess.TimeoutExpired:
            return 124, f"timed out after {self.test_timeout:g}s"
        out = (done.stdout or "") + (done.stderr or "")
        if len(out) > OUTPUT_CAP:
            out = "...\n" + out[-OUTPUT_CAP:]
        return done.returncode, out

    def call(self, name, arguments) -> tuple[Call, str]:
        """Validate and run one tool call; never raises on the model's input."""
        import json
        raw = arguments if isinstance(arguments, str) else json.dumps(arguments)
        call = Call(str(name), raw)
        if name not in self.tools:
            call.why = f"unknown tool {name!r}; available: {', '.join(self.tools)}"
            return call, f"error: {call.why}"
        call.real = True
        try:
            args = json.loads(raw) if isinstance(arguments, str) else arguments
            if args is None or args == "":
                args = {}
        except ValueError as exc:
            call.why = f"arguments are not JSON: {exc}"
            return call, f"error: {call.why}"
        if not isinstance(args, dict):
            call.why = "arguments must be a JSON object"
            return call, f"error: {call.why}"
        call.parsed = True
        problem = schema_problem(TOOLS[name]["parameters"], args)
        if problem:
            call.why = problem
            return call, f"error: {problem}"
        call.schema_ok = True
        try:
            result = getattr(self, name)(**args)
        except Refused as exc:
            call.why = str(exc)
            return call, f"error: {exc}"
        except OSError as exc:
            call.why = f"{type(exc).__name__}: {exc}"
            return call, f"error: {call.why}"
        call.ok = True
        return call, result


def schema_problem(schema: dict, args: dict) -> str:
    """Why `args` does not fit a flat object schema, or ""."""
    props = schema.get("properties") or {}
    for key in schema.get("required") or []:
        if key not in args:
            return f"missing required argument {key!r}"
    for key, value in args.items():
        if key not in props:
            return f"unexpected argument {key!r}"
        if props[key].get("type") == "string" and not isinstance(value, str):
            return f"argument {key!r} must be a string"
    return ""


def openai_tools(names) -> list[dict]:
    return [{"type": "function", "function": {"name": n, **TOOLS[n]}} for n in names]


def _refuse_links(source: Path) -> None:
    for dirpath, dirnames, filenames in os.walk(source):
        for name in dirnames + filenames:
            if os.path.islink(os.path.join(dirpath, name)):
                raise ValueError(f"case repo contains a symlink: {name}")


def grade(box: Sandbox, hidden: Path | None, answer, final: str) -> dict:
    """Run the hidden tests in the sandbox and/or match the final answer."""
    out: dict = {"passed": True, "detail": ""}
    if answer:
        from evals.core import contains
        needles = answer if isinstance(answer, list) else [answer]
        missing = [n for n in needles
                   if not any(contains(final or "", str(o))
                              for o in (n if isinstance(n, list) else [n]))]
        out["answer_ok"] = not missing
        if missing:
            want = " or ".join(map(str, missing[0] if isinstance(missing[0], list)
                                   else [missing[0]]))
            out.update(passed=False, detail=f"final answer lacks {want}")
    if hidden is not None:
        dest = box.root / HIDDEN_DIR
        if dest.is_symlink() or dest.is_file():
            dest.unlink()
        elif dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(hidden, dest)
        rc, text = box.execute("unittest", ["discover", "-s", HIDDEN_DIR])
        ran = re.search(r"Ran (\d+) tests?", text)
        n = int(ran.group(1)) if ran else 0
        out.update(hidden_rc=rc, hidden_ran=n, hidden_output=text[-1500:])
        if rc != 0 or n == 0:
            out["passed"] = False
            out["detail"] = out["detail"] or f"hidden tests failed (exit {rc}, ran {n})"
    return out
