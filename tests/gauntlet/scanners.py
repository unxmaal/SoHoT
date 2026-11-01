"""Repo-wide scans for the tier-1 gauntlet classes; each takes (text, path) and returns findings (#492 C)."""

import ast
import re
from pathlib import Path

from harness import repo

_MUTABLE_CALLS = {"list", "dict", "set", "bytearray", "defaultdict", "OrderedDict", "Counter", "deque"}


def _parse(text, rel):
    try:
        return ast.parse(text), []
    except SyntaxError as e:
        return None, [f"{rel}:{e.lineno or 0}: does not parse, so it was not scanned"]


def _call_name(node):
    f = node.func
    return f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""


def mutable_defaults(text, rel):
    tree, out = _parse(text, rel)
    if tree is None:
        return out
    for n in ast.walk(tree):
        if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        for d in n.args.defaults + [k for k in n.args.kw_defaults if k is not None]:
            if (isinstance(d, (ast.List, ast.Dict, ast.Set, ast.ListComp, ast.DictComp, ast.SetComp))
                    or (isinstance(d, ast.Call) and _call_name(d) in _MUTABLE_CALLS)):
                out.append(f"{rel}:{d.lineno}: mutable default argument, shared across calls")
    return out


def _empty(body):
    return all(isinstance(s, ast.Pass) or (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))
               for s in body)


def swallowed_python(text, rel):
    tree, out = _parse(text, rel)
    if tree is None:
        return out
    for n in ast.walk(tree):
        if not isinstance(n, ast.ExceptHandler):
            continue
        if n.type is None:
            out.append(f"{rel}:{n.lineno}: bare except catches everything, KeyboardInterrupt included")
        elif _empty(n.body):
            out.append(f"{rel}:{n.lineno}: caught exception with an empty body")
    return out


_TIMEOUTS = {"TimeoutExpired", "TimeoutException", "ReadTimeout", "ConnectTimeout", "TimeoutError", "timeout",
             "AudioTimeout", "ServeStartTimeout"}
#: An exception caught here may be a timeout: parent -> the timeout subclass a handler must catch first.
_TIMEOUT_PARENTS = {"AudioError": "AudioTimeout"}


def _final_name(node):
    return node.id if isinstance(node, ast.Name) else node.attr if isinstance(node, ast.Attribute) else None


def _classed(call):
    if any(k.arg in ("failure_class", None) for k in call.keywords):
        return True
    return (_final_name(call.func) or "").endswith("CompletionError") and len(call.args) >= 2


def _caught(h):
    types = h.type.elts if isinstance(h.type, ast.Tuple) else [h.type]
    return {_final_name(t) for t in types}


def _unclassed(body, rel):
    """Raises of a runner error, and failing results returned, that carry no failure_class."""
    out = []
    for n in (m for stmt in body for m in ast.walk(stmt)):
        if isinstance(n, ast.Raise) and isinstance(n.exc, ast.Call):
            callee = _final_name(n.exc.func) or ""
            if callee.endswith(("RunnerError", "CompletionError")) and not _classed(n.exc):
                out.append(f"{rel}:{n.lineno}: a timeout raised with no failure_class")
        elif isinstance(n, ast.Return) and isinstance(n.value, ast.Call) and n.value.args:
            first = n.value.args[0]
            if isinstance(first, ast.Constant) and first.value is False and not _classed(n.value):
                out.append(f"{rel}:{n.lineno}: a timeout returned as a failing result with no failure_class")
    return out


def _timeout_test(test):
    return any(isinstance(c, ast.Call) and _final_name(c.func) == "isinstance" and len(c.args) == 2
               and any(_final_name(t) in _TIMEOUTS for t in
                       (c.args[1].elts if isinstance(c.args[1], ast.Tuple) else [c.args[1]]))
               for c in ast.walk(test))


def unclassed_timeouts(text, rel):
    """A timeout handler, isinstance branch, or timeout-parent handler that raises or returns with no failure_class (#693)."""
    tree, out = _parse(text, rel)
    if tree is None:
        return out
    for t in ast.walk(tree):
        if not isinstance(t, ast.Try):
            continue
        before = set()
        for h in t.handlers:
            if h.type is None:
                continue
            names = _caught(h)
            if names & _TIMEOUTS:
                out += _unclassed(h.body, rel)
            elif any(p in names and c not in before for p, c in _TIMEOUT_PARENTS.items()):
                out += [f for f in _unclassed(h.body, rel) if "returned" in f]
            for n in (m for stmt in h.body for m in ast.walk(stmt)):
                if isinstance(n, ast.If) and _timeout_test(n.test):
                    out += _unclassed(n.body, rel)
            before |= names
    return sorted(set(out), key=lambda f: int(f.split(":")[1]))


_OR_TRUE = re.compile(r"\|\|\s*(?:true|:)(?=\s|;|\)|$)")


def _code_lines(text):
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.lstrip().startswith("#"):
            yield number, line


def swallowed_shell(text, rel):
    return [f"{rel}:{n}: `|| true` discards the exit status" for n, line in _code_lines(text)
            if _OR_TRUE.search(line)]


_SET_OPTS = re.compile(r"^\s*set\s+(.*)$", re.M)
_QUOTED = re.compile(r"'[^']*'|\"(?:\\.|[^\"\\])*\"")
_COMMANDS = re.compile(r";|&&|\|\||\bthen\b|\bdo\b")
# `producer | grep -q` fails closed without pipefail, and lies with it (RULE #235), so it is not flagged.
_PROBE = re.compile(r"\s*grep\s+-[a-zA-Z]*q")
_CD = re.compile(r"(?:^|[;&(]|\bthen|\bdo|\belse)\s*cd(?:\s|$)")
_CD_GUARDED = re.compile(r"\bcd\b[^;|&]*(?:\|\||&&)")


def _unprobed_pipeline(line):
    for command in _COMMANDS.split(_QUOTED.sub("''", line)):
        stages = command.split("|")
        if len(stages) > 1 and not _PROBE.match(stages[-1]):
            return True
    return False


def _options(text):
    shorts, longs = set(), set()
    for m in _SET_OPTS.finditer(text):
        words = m.group(1).split()
        for i, w in enumerate(words):
            if re.fullmatch(r"-[a-zA-Z]+", w):
                shorts.update(w[1:])
            # `set -uo pipefail`: a short group ending in o takes the next word as a long option.
            if re.fullmatch(r"-[a-zA-Z]*o", w) and i + 1 < len(words):
                longs.add(words[i + 1])
    return ("e" in shorts or "errexit" in longs), ("pipefail" in longs)


def unchecked_status_shell(text, rel):
    errexit, pipefail = _options(text)
    executable = text.startswith("#!")
    out = []
    for n, line in _code_lines(text):
        # Reported once, at the first pipeline: the fix is one line at the top.
        if executable and not pipefail and _unprobed_pipeline(line):
            pipefail = True
            out.append(f"{rel}:{n}: a pipeline with no `set -o pipefail`, so a failing producer is invisible")
        if not errexit and _CD.search(line) and not _CD_GUARDED.search(line):
            out.append(f"{rel}:{n}: unchecked cd with no errexit; the next command runs in the wrong directory")
    return out


_SERVERS = re.compile(r"(?:bind|Server|create_server)$")
_ABS = re.compile(r"^(?:/|[A-Za-z]:[\\/])")
_WRITERS = {"write_text", "write_bytes", "mkdir", "touch", "symlink_to"}


def _abs_literal(node):
    return isinstance(node, ast.Constant) and isinstance(node.value, str) and bool(_ABS.match(node.value))


def _fixed_port(call):
    if not call.args or not isinstance(call.args[0], ast.Tuple) or len(call.args[0].elts) < 2:
        return None
    port = call.args[0].elts[1]
    if isinstance(port, ast.Constant) and type(port.value) is int and port.value != 0:
        return port.value
    return None


def _write_mode(call):
    mode = call.args[1] if len(call.args) > 1 else next((k.value for k in call.keywords if k.arg == "mode"), None)
    return isinstance(mode, ast.Constant) and isinstance(mode.value, str) and bool(set(mode.value) & set("wax+"))


def fixed_resources(text, rel):
    tree, out = _parse(text, rel)
    if tree is None:
        return out
    found = []
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call):
            continue
        name = _call_name(n)
        if _SERVERS.search(name) and _fixed_port(n) is not None:
            found.append((n.lineno, f"binds fixed port {_fixed_port(n)}; bind port 0 and ask the OS"))
        elif (name in _WRITERS and isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Call)
              and n.func.value.args and _abs_literal(n.func.value.args[0])):
            found.append((n.lineno, "writes a fixed absolute path; use tmp_path"))
        elif name == "open" and isinstance(n.func, ast.Name) and n.args and _abs_literal(n.args[0]) \
                and _write_mode(n):
            found.append((n.lineno, "writes a fixed absolute path; use tmp_path"))
    return out + [f"{rel}:{line}: {why}" for line, why in sorted(found)]


# Names Windows's os and signal modules do not have, and modules it does not ship.
POSIX_ONLY = {
    "os": {"killpg", "getpgid", "setpgid", "setpgrp", "setsid", "getsid", "fork", "forkpty", "getuid",
           "geteuid", "getgid", "getegid", "chown", "lchown", "fchown", "uname", "getloadavg", "wait3",
           "wait4", "WNOHANG", "nice", "mkfifo", "statvfs", "sysconf", "openpty", "pipe2"},
    "signal": {"SIGKILL", "SIGHUP", "SIGUSR1", "SIGUSR2", "SIGCHLD", "SIGALRM", "SIGQUIT", "SIGPIPE",
               "SIGTSTP", "SIGCONT", "SIGSTOP", "alarm", "setitimer", "getitimer", "pause", "siginterrupt",
               "pthread_kill"},
}
POSIX_MODULES = {"fcntl", "pwd", "grp", "resource", "termios", "pty", "tty", "posix"}
_PLATFORM_NAME = re.compile(r"(?i)windows|posix|win32|darwin|linux|platform")
_GUARD_ERRORS = {"AttributeError", "ImportError", "ModuleNotFoundError", "Exception", "BaseException"}


def _is_platform_test(node):
    for n in ast.walk(node):
        if isinstance(n, ast.Attribute) and n.attr in ("platform", "name", "system") \
                and isinstance(n.value, ast.Name) and n.value.id in ("sys", "os", "platform"):
            return True
        if isinstance(n, ast.Call) and _call_name(n) == "hasattr":
            return True
        if isinstance(n, ast.Name) and _PLATFORM_NAME.search(n.id):
            return True
    return False


def _exits(body):
    last = body[-1] if body else None
    if isinstance(last, ast.Try):
        return _exits(last.body + last.orelse) and all(_exits(h.body) for h in last.handlers)
    if isinstance(last, ast.If):
        return _exits(last.body) and _exits(last.orelse)
    return isinstance(last, (ast.Return, ast.Raise, ast.Continue, ast.Break)) or (
        isinstance(last, ast.Expr) and isinstance(last.value, ast.Call) and _call_name(last.value) == "skip")


def _catches(handler, names):
    t = handler.type
    elts = t.elts if isinstance(t, ast.Tuple) else [t] if t is not None else []
    return t is None or any(isinstance(e, ast.Name) and e.id in names for e in elts)


def _guarded(node, parents):
    child, cur = node, parents.get(node)
    while cur is not None:
        if isinstance(cur, (ast.If, ast.IfExp, ast.While)) and child is not cur.test and _is_platform_test(cur.test):
            return True
        if isinstance(cur, ast.Try) and child in cur.body and any(_catches(h, _GUARD_ERRORS) for h in cur.handlers):
            return True
        if isinstance(cur, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) \
                and any(_is_platform_test(d) for d in cur.decorator_list):
            return True
        for field in ("body", "orelse", "finalbody"):
            stmts = getattr(cur, field, None)
            if isinstance(stmts, list) and child in stmts:
                for prev in stmts[:stmts.index(child)]:
                    if isinstance(prev, ast.If) and _is_platform_test(prev.test) and _exits(prev.body):
                        return True
                    if isinstance(prev, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "pytestmark"
                                                            for t in prev.targets) and _is_platform_test(prev.value):
                        return True
        child, cur = cur, parents.get(cur)
    return False


def posix_primitives(text, rel):
    tree, out = _parse(text, rel)
    if tree is None:
        return out
    parents = {c: p for p in ast.walk(tree) for c in ast.iter_child_nodes(p)}
    found = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) \
                and n.attr in POSIX_ONLY.get(n.value.id, ()) and not _guarded(n, parents):
            found.append((n.lineno, f"{n.value.id}.{n.attr} does not exist on Windows; guard it by platform"))
        elif isinstance(n, (ast.Import, ast.ImportFrom)) and not _guarded(n, parents):
            names = [a.name for a in n.names] if isinstance(n, ast.Import) else [n.module or ""]
            for m in names:
                if m.split(".")[0] in POSIX_MODULES and not (isinstance(n, ast.ImportFrom) and n.level):
                    found.append((n.lineno, f"imports {m}, which Windows does not ship; guard it by platform"))
    return out + [f"{rel}:{line}: {why}" for line, why in sorted(found)]


_SHELLS = {"bash", "sh", "zsh"}
_SPAWNS = {"run", "Popen", "check_output", "check_call", "call"}


def bare_shells(text, rel):
    """A subprocess argv starting with a bare shell name: on Windows "bash" is the WSL launcher (tests/shells.py)."""
    tree, out = _parse(text, rel)
    if tree is None:
        return out
    found = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and _call_name(n) in _SPAWNS and n.args and isinstance(n.args[0], ast.List) \
                and n.args[0].elts and isinstance(n.args[0].elts[0], ast.Constant) \
                and n.args[0].elts[0].value in _SHELLS:
            found.append((n.lineno, f"runs a bare {n.args[0].elts[0].value!r}; use tests.shells.resolve()"))
    return out + [f"{rel}:{line}: {why}" for line, why in sorted(found)]


SMALL_FILE = 1 << 20


def grown_files(text, rel):
    """truncate() that grows a file: sparse on APFS and ext4, real clusters on NTFS (#838)."""
    tree, out = _parse(text, rel)
    if tree is None:
        return out
    for n in sorted(ast.walk(tree), key=lambda n: getattr(n, "lineno", 0)):
        if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "truncate"):
            continue
        is_os = isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name) and n.func.value.id == "os"
        args = n.args[1:] if is_os else n.args
        size = args[0] if args else next((k.value for k in n.keywords if k.arg in ("size", "length")), None)
        if size is None or (isinstance(size, ast.Constant) and isinstance(size.value, int)
                            and size.value <= SMALL_FILE):
            continue
        out.append(f"{rel}:{n.lineno}: truncate() grows a file, which allocates every byte on Windows; "
                   "fake the size where it is read")
    return out


TEMPFILES = {"NamedTemporaryFile", "TemporaryFile", "SpooledTemporaryFile"}


def text_tempfiles(text, rel):
    """A tempfile opened in text mode with no encoding=: the locale codepage, cp1252, on Windows (#1068)."""
    tree, out = _parse(text, rel)
    if tree is None:
        return out
    for n in sorted(ast.walk(tree), key=lambda n: getattr(n, "lineno", 0)):
        if not (isinstance(n, ast.Call) and getattr(n.func, "attr", getattr(n.func, "id", "")) in TEMPFILES):
            continue
        mode = n.args[0] if n.args else next((k.value for k in n.keywords if k.arg == "mode"), None)
        binary = mode is None or (isinstance(mode, ast.Constant) and "b" in str(mode.value))
        if binary or any(k.arg == "encoding" for k in n.keywords):
            continue
        out.append(f"{rel}:{n.lineno}: a text-mode temp file with no encoding= writes cp1252 on Windows")
    return out


def _relative_to(node):
    return isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "relative_to"


def native_relpaths(text, rel):
    """str() or an f-string of Path.relative_to(): backslashes on Windows, so a posix spelling never matches (#1077)."""
    tree, out = _parse(text, rel)
    if tree is None:
        return out
    for n in sorted(ast.walk(tree), key=lambda n: getattr(n, "lineno", 0)):
        if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "str" and n.args and _relative_to(n.args[0]):
            out.append(f"{rel}:{n.lineno}: str() of a relative path is native-separated; use .as_posix()")
        elif isinstance(n, ast.JoinedStr):
            out += [f"{rel}:{n.lineno}: an f-string of a relative path is native-separated; use .as_posix()"
                    for v in n.values if isinstance(v, ast.FormattedValue) and _relative_to(v.value)]
    return out


def unguarded_imports(text, rel):
    """(line, top-level module) for each absolute import no ImportError handler covers."""
    tree, _ = _parse(text, rel)
    if tree is None:
        return []
    parents = {c: p for p in ast.walk(tree) for c in ast.iter_child_nodes(p)}
    found = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            names = [a.name for a in n.names]
        elif isinstance(n, ast.ImportFrom) and not n.level and n.module:
            names = [n.module]
        else:
            continue
        child, cur, covered = n, parents.get(n), False
        while cur is not None and not covered:
            covered = isinstance(cur, ast.Try) and child in cur.body and any(
                _catches(h, {"ImportError", "ModuleNotFoundError", "Exception", "BaseException"})
                for h in cur.handlers)
            child, cur = cur, parents.get(cur)
        if not covered:
            found += [(n.lineno, m.split(".")[0]) for m in names]
    return found


def module_skips(text, rel):
    """Top-level modules a module-level pytest.importorskip makes the whole file skip without."""
    tree, _ = _parse(text, rel)
    if tree is None:
        return set()
    out = set()
    for stmt in tree.body:
        value = getattr(stmt, "value", None)
        if isinstance(value, ast.Call) and _call_name(value) == "importorskip" and value.args \
                and isinstance(value.args[0], ast.Constant) and isinstance(value.args[0].value, str):
            out.add(value.args[0].value.split(".")[0])
    return out


# The one place the live home may be derived; everything else asks it, so conftest's redirect reaches it.
LIVE_HOME_OWNER = "harness/paths.py"
_LIVE_DIR = "localharness"


def _is_home(node):
    if not isinstance(node, ast.Call):
        return False
    name = _call_name(node)
    if name == "home":
        return True
    return (name == "expanduser" and node.args and isinstance(node.args[0], ast.Constant)
            and node.args[0].value == "~")


def _strings(nodes):
    return [n.value for n in nodes if isinstance(n, ast.Constant) and isinstance(n.value, str)]


def _div_chain(node):
    parts = []
    while isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        parts.append(node.right)
        node = node.left
    return node, parts


def _names_live_dir(strings):
    return bool(strings) and strings[0].strip("/").split("/")[0] == _LIVE_DIR


def _calls_paths(node):
    return any(isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
               and isinstance(c.func.value, ast.Name) and c.func.value.id == "paths"
               for c in ast.walk(node))


def _import_time(tree):
    for stmt in tree.body:
        if isinstance(stmt, (ast.Assign, ast.AnnAssign)) and stmt.value is not None and _calls_paths(stmt.value):
            yield stmt.lineno, "resolves a live path at import, before any test can redirect it"
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for d in stmt.args.defaults + [k for k in stmt.args.kw_defaults if k is not None]:
                if _calls_paths(d):
                    yield d.lineno, "a default argument resolves a live path at import"


def live_home_python(text, rel):
    if rel == LIVE_HOME_OWNER:
        return []
    tree, out = _parse(text, rel)
    if tree is None:
        return out
    found = list(_import_time(tree))
    why = "derives the live home outside harness/paths.py, so LOCALHARNESS_HOME cannot redirect it"
    for n in ast.walk(tree):
        if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Div):
            base, parts = _div_chain(n)
            if _is_home(base) and _names_live_dir(_strings(reversed(parts))):
                found.append((n.lineno, why))
        elif isinstance(n, ast.Call) and _call_name(n) == "join" and n.args and _is_home(n.args[0]) \
                and _names_live_dir(_strings(n.args[1:])):
            found.append((n.lineno, why))
        elif isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value.startswith("~/" + _LIVE_DIR):
            found.append((n.lineno, why))
    return out + [f"{rel}:{line}: {w}" for line, w in sorted(set(found))]


_SH_DEFAULTED = re.compile(r"\$\{LOCALHARNESS_HOME:-[^}]*\}")
_SH_LIVE = re.compile(r"(?:\$HOME|\$\{HOME\}|~)/" + _LIVE_DIR + r"\b")


def live_home_shell(text, rel):
    return [f"{rel}:{n}: names the live home instead of ${{LOCALHARNESS_HOME:-...}}"
            for n, line in _code_lines(text) if _SH_LIVE.search(_SH_DEFAULTED.sub("", line))]


def ratchet(found, pin, what):
    if len(found) > pin:
        return (f"{len(found)} {what}, pinned at {pin}: a new one was added. The inventory may only shrink.\n  "
                + "\n  ".join(found))
    if len(found) < pin:
        return f"{len(found)} {what}, pinned at {pin}: some were fixed, so lower the pin to {len(found)}"
    return None


OFFLINE_OWNER = ("harness/env.py", {"online", "apply"})
_OFFLINE = "HF_HUB_OFFLINE"
_ENV_WRITERS = {"setdefault", "pop", "update", "__setitem__", "__delitem__"}


def _is_environ(node):
    return (isinstance(node, ast.Attribute) and node.attr == "environ") or (
        isinstance(node, ast.Name) and node.id == "environ")


def _names_offline(node):
    return isinstance(node, ast.Constant) and node.value == _OFFLINE


def _flips_offline(n):
    if isinstance(n, (ast.Assign, ast.AugAssign, ast.AnnAssign, ast.Delete)):
        targets = n.targets if isinstance(n, (ast.Assign, ast.Delete)) else [n.target]
        return any((isinstance(t, ast.Subscript) and _is_environ(t.value) and _names_offline(t.slice))
                   or (isinstance(t, ast.Attribute) and t.attr == _OFFLINE) for t in targets)
    if not isinstance(n, ast.Call):
        return False
    name = _call_name(n)
    named = any(_names_offline(a) for a in n.args) or any(k.arg == _OFFLINE for k in n.keywords)
    if name in _ENV_WRITERS and isinstance(n.func, ast.Attribute) and _is_environ(n.func.value):
        return named
    return name in ("putenv", "unsetenv", "setattr") and named


def offline_flips(text, rel):
    """Writes to HF_HUB_OFFLINE outside harness.env.online(): huggingface_hub read it at import (#931)."""
    tree, out = _parse(text, rel)
    if tree is None:
        return out
    exempt = set()
    if rel == OFFLINE_OWNER[0]:
        for f in tree.body:
            if isinstance(f, ast.FunctionDef) and f.name in OFFLINE_OWNER[1]:
                exempt |= {id(x) for x in ast.walk(f)}
    lines = sorted({n.lineno for n in ast.walk(tree) if id(n) not in exempt and _flips_offline(n)})
    return out + [f"{rel}:{line}: sets HF_HUB_OFFLINE by hand; huggingface_hub read it at import, "
                  "so lift it with harness.env.online()" for line in lines]


LISTING_OWNER = "harness/variants.py"


def _names_siblings(node):
    return any((isinstance(x, ast.Name) and "sibling" in x.id.lower())
               or (isinstance(x, ast.Attribute) and x.attr == "siblings")
               or (isinstance(x, ast.Constant) and x.value == "siblings") for x in ast.walk(node))


def _reads_size(node):
    return any((isinstance(x, ast.Constant) and x.value == "size")
               or (isinstance(x, ast.Attribute) and x.attr == "size") for x in ast.walk(node))


def _sizes_of_siblings(node):
    return (isinstance(node, (ast.GeneratorExp, ast.ListComp))
            and any(_names_siblings(g.iter) for g in node.generators) and _reads_size(node.elt))


def listing_sums(text, rel):
    """A whole HF listing's sizes added up outside harness/variants.py, the one place a listing is sized (#964)."""
    if rel == LISTING_OWNER:
        return []
    tree, out = _parse(text, rel)
    if tree is None:
        return out
    named = {t.id for n in ast.walk(tree) if isinstance(n, ast.Assign) and _sizes_of_siblings(n.value)
             for t in n.targets if isinstance(t, ast.Name)}
    lines = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and _call_name(n) == "sum" and n.args:
            a = n.args[0]
            if _sizes_of_siblings(a) or (isinstance(a, ast.Name) and a.id in named):
                lines.add(n.lineno)
        elif isinstance(n, ast.For) and _names_siblings(n.iter):
            lines |= {x.lineno for x in ast.walk(n) if isinstance(x, ast.AugAssign)
                      and isinstance(x.op, ast.Add) and _reads_size(x.value)}
    return out + [f"{rel}:{line}: adds up a listing's file sizes; size it through harness.variants "
                  "(inspect.size_listing) so every reader reports the variant inspect runs" for line in sorted(lines)]


def _shebang(path):
    with open(path, "rb") as f:
        first = f.readline(200)
    return first.decode("utf-8", "replace") if first.startswith(b"#!") else ""


def is_python(path):
    return path.suffix == ".py" or (path.suffix == "" and "python" in _shebang(path))


def is_shell(path):
    return path.suffix in (".sh", ".bash") or (
        path.suffix == "" and bool(re.search(r"\b(?:ba|z)?sh\b", _shebang(path))))


def scan_tree(root, scanner, want, only=None):
    root = Path(root)
    out = []
    for path in repo.publishable(root):
        rel = path.relative_to(root).as_posix()
        if not path.is_file() or not want(path) or (only is not None and not only(rel)):
            continue
        out += scanner(path.read_text(encoding="utf-8", errors="replace"), rel)
    return out


AUDIT_FILE = "harness/live_audit.py"
LOOP_FILE = "harness/commands/loop.py"


def _top_functions(tree):
    return {f.name: f for f in tree.body if isinstance(f, ast.FunctionDef)}


def _calls(node):
    return {_call_name(n) for n in ast.walk(node) if isinstance(n, ast.Call)} - {""}


def _reach(names, store):
    seen, todo = set(), [n for n in names if n in store]
    while todo:
        name = todo.pop()
        if name not in seen:
            seen.add(name)
            todo += [n for n in _calls(store[name]) if n in store]
    return seen


def _walked(func):
    return {_call_name(n.iter) for n in ast.walk(func)
            if isinstance(n, (ast.For, ast.comprehension)) and isinstance(n.iter, ast.Call)} - {""}


def _assigned(tree, name):
    return next((n.value for n in tree.body if isinstance(n, ast.Assign)
                 and any(isinstance(t, ast.Name) and t.id == name for t in n.targets)), None)


def _marks(func):
    return {n.args[0].attr for n in ast.walk(func) if isinstance(n, ast.Call) and _call_name(n) == "mark"
            and n.args and isinstance(n.args[0], ast.Attribute)}


def unwaited_repairs(audit, loop, stores):
    """live_audit checks a loop step repairs, where REPAIRED_BY names no heartbeat key that step marks (#972)."""
    atree, out = _parse(audit, AUDIT_FILE)
    ltree, more = _parse(loop, LOOP_FILE)
    out += more
    store = {}
    for rel, text in stores.items():
        tree, more = _parse(text, rel)
        out += more
        store.update(_top_functions(tree) if tree else {})
    if atree is None or ltree is None:
        return out
    verdicts = _assigned(atree, "VERDICTS")
    names = [e.value for e in verdicts.elts] if isinstance(verdicts, ast.Tuple) else []
    table = _assigned(atree, "REPAIRED_BY")
    waits = {k.value: v.attr for k, v in zip(table.keys, table.values)} if isinstance(table, ast.Dict) else {}
    checks = _top_functions(atree)
    # A step repairs the queries whose rows a store function it reaches walks, not every helper it shares.
    steps = {name: (set().union(*(_walked(store[w]) for w in _reach(_calls(f), store))), _marks(f))
             for name, f in _top_functions(ltree).items()}
    for name in names:
        check = checks.get(f"_{name}")
        if check is None:
            continue
        asks = {n for n in _calls(check) if n in store}
        repairs = {step: marked for step, (reach, marked) in steps.items() if asks & reach}
        if not repairs:
            continue
        if name not in waits:
            out.append(f"{AUDIT_FILE}:{check.lineno}: {name} is repaired by the loop's {', '.join(sorted(repairs))}; "
                       "name the heartbeat key it waits on in REPAIRED_BY, or it gates on a backlog from the deploy")
        elif not any(waits[name] in marked for marked in repairs.values()):
            out.append(f"{AUDIT_FILE}:{check.lineno}: {name} waits on heartbeat.{waits[name]}, which its repair "
                       f"{', '.join(sorted(repairs))} never marks")
    return out


#: Namespaces spread from the very parser the callee's verb reads; "rel:function->callee" -> why. #974.
SAME_PARSER = {
    "harness/commands/loop.py:_run_loop_held->cmd_discover":
        "a is the namespace `soh discover --loop` parsed, handed back to soh discover with one tier flag set",
    "harness/commands/loop.py:_loop_spend->cmd_discover":
        "a is the namespace `soh discover --loop` parsed, handed back to soh discover for its screen tier",
    "harness/commands/discover.py:_report_sweep->cmd_discover":
        "a is soh discover's own namespace, re-dispatched one source tier at a time",
}
_VERB = re.compile(r"^(?:cmd_|_report_)")


def _is_namespace(node):
    return isinstance(node, ast.Call) and _call_name(node) == "Namespace"


def _another_verb(call):
    f = call.func
    return bool(_VERB.match(_call_name(call))) or (
        isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id.endswith("_cmd"))


def namespace_handoffs(text, rel):
    """Every argparse.Namespace built by hand and passed to a verb: [(rel:function->callee, line)]."""
    tree, _ = _parse(text, rel)
    if tree is None:
        return []
    out = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        bound = sorted((n.lineno, t.id, n.value) for n in ast.walk(fn) if isinstance(n, ast.Assign)
                       for t in n.targets if isinstance(t, ast.Name))

        def last(name, before):
            values = [v for line, i, v in bound if i == name and line < before]
            return values[-1] if values else None

        for n in ast.walk(fn):
            if not (isinstance(n, ast.Call) and _another_verb(n)):
                continue
            for arg in list(n.args) + [k.value for k in n.keywords]:
                value = last(arg.id, n.lineno) if isinstance(arg, ast.Name) else arg
                if value is not None and _is_namespace(value):
                    out.append((f"{rel}:{fn.name}->{_call_name(n)}", value.lineno))
    return out


def handmade_namespaces(text, rel):
    return [f"{rel}:{line}: {key.partition(':')[2]} is handed a hand-made argparse.Namespace, which carries only "
            f"the fields its writer thought of; build it with common.parsed(<verb>, ...)"
            for key, line in namespace_handoffs(text, rel) if key not in SAME_PARSER]


_CLOCKS = {"perf_counter", "perf_counter_ns", "monotonic", "monotonic_ns", "time", "time_ns"}
_KEEPS_MEASURE = {"abs", "round", "float", "int", "min", "max", "sum"}
_DURATION = re.compile(r"^(?:took|elapsed|wall\w*|seconds|duration\w*|ttft\w*|\w+_s)$")
# Durations a fake clock or an estimate produces, so a load cannot move them: "rel:function" -> why.
WALL_BOUND_WAIVERS = {
    "tests/test_busy_wait_timing_776.py:test_a_best_of_row_stays_under_one_poll_when_its_pool_threads_wait":
        "FakeTime clock: the row's seconds are fake time the replies add, never the machine's",
    "tests/test_busy_wait_timing_776.py:test_a_craft_case_deadline_is_not_spent_by_a_busy_wait":
        "Clock patched onto agent and craft_runner time: the wall is fake time",
    "tests/test_busy_wait_timing_776.py:test_a_repo_repair_case_deadline_and_wall_leave_out_a_busy_wait":
        "Clock patched onto agent and repo_repair time: the seconds are fake time",
    "tests/test_throttle_1084.py:test_outside_the_capped_hours_it_runs_at_line_rate":
        "clock=lambda: w.t, a simulated line: the seconds are the simulation's",
    "tests/test_over_budget_796.py:test_a_receipt_at_a_smaller_reply_budget_bounds_the_incumbent":
        "incumbent_s is an estimate from stored rows, compared with another estimate; nothing is timed",
}


def _clock_call(node):
    f = node.func if isinstance(node, ast.Call) else None
    if isinstance(f, ast.Attribute):
        return f.attr in _CLOCKS and isinstance(f.value, ast.Name) and f.value.id == "time"
    return isinstance(f, ast.Name) and f.id in _CLOCKS - {"time", "time_ns"}


def _stamp(node, stamps):
    if _clock_call(node) or (isinstance(node, ast.Name) and node.id in stamps):
        return True
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Sub):
        return _stamp(node.left, stamps) and isinstance(node.right, ast.Constant)
    return isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add) and (
        _stamp(node.left, stamps) != _stamp(node.right, stamps))


def _duration_named(node):
    key = node.slice if isinstance(node, ast.Subscript) else None
    name = (node.id if isinstance(node, ast.Name) else node.attr if isinstance(node, ast.Attribute)
            else key.value if isinstance(key, ast.Constant) and isinstance(key.value, str) else "")
    return bool(_DURATION.match(name))


def _duration(node, stamps, spans):
    if (isinstance(node, ast.Name) and node.id in spans) or _duration_named(node):
        return True
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Sub) and not _stamp(node, stamps) and (
            _stamp(node.left, stamps) or _stamp(node.right, stamps)):
        return True
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult)):
        return _duration(node.left, stamps, spans) or _duration(node.right, stamps, spans)
    if isinstance(node, ast.UnaryOp):
        return _duration(node.operand, stamps, spans)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _KEEPS_MEASURE:
        return any(_duration(a, stamps, spans) for a in node.args)
    return False


def _bound_names(fn, holds):
    names, grew = set(), True
    while grew:
        grew = False
        for n in ast.walk(fn):
            value = n.value if isinstance(n, (ast.Assign, ast.AnnAssign)) else None
            if value is None or not holds(value, names):
                continue
            targets = n.targets if isinstance(n, ast.Assign) else [n.target]
            new = {t.id for t in targets if isinstance(t, ast.Name)} - names
            names |= new
            grew = grew or bool(new)
    return names


def wall_bounds(text, rel, waivers=None):
    tree, out = _parse(text, rel)
    if tree is None:
        return out
    waivers = WALL_BOUND_WAIVERS if waivers is None else waivers
    found, waived = set(), set()
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        stamps = _bound_names(fn, _stamp)
        spans = _bound_names(fn, lambda v, names: _duration(v, stamps, names))
        for a in ast.walk(fn):
            if not isinstance(a, ast.Assert):
                continue
            for c in (n for n in ast.walk(a.test) if isinstance(n, ast.Compare)):
                sides = [c.left, *c.comparators]
                for left, op, right in zip(sides, c.ops, sides[1:]):
                    ld, rd = _duration(left, stamps, spans), _duration(right, stamps, spans)
                    if ld != rd and isinstance(op, (ast.Gt, ast.GtE) if rd else (ast.Lt, ast.LtE)):
                        (waived if f"{rel}:{fn.name}" in waivers else found).add(c.lineno)
    return out + [f"{rel}:{line}: an upper bound on measured wall time fails on a loaded machine; assert order, "
                  f"a count, a lower bound or a structural fact, or inject the clock"
                  for line in sorted(found - waived)]


# An option or subcommand that runs an eval or a probe; each is homed (calls paths.eval_home) or waived with a reason.
_EVAL_NAME = re.compile(r"^(?:--)?(?:[a-z]+-)*(?:evals?|probes?|redo|controls?|calibrate|self-?test|sensitivity|canary|chaos)$")
#: "<file> <parser variable> <option or subcommand>" -> the handler file that calls paths.eval_home. #1346
EVAL_HOMED = {
    "evals/analysis/demand/__main__.py p --controls": "evals/analysis/demand/__main__.py",
    "evals/claims_judge.py ap action=calibrate": "evals/claims_judge.py",
    "evals/importers/history.py ap --probes": "evals/importers/history.py",
    "evals/importers/transcripts.py ap --probes": "evals/importers/transcripts.py",
    "harness/cli.py d --control": "harness/commands/discover.py",
    "harness/commands/ask.py p --eval": "harness/commands/ask.py",
    "harness/commands/ask.py p --redo": "harness/commands/ask.py",
    "harness/commands/spans.py p --eval": "harness/commands/spans.py",
    "harness/commands/spans.py p --redo": "harness/commands/spans.py",
    "harness/cli.py sub sensitivity": "harness/commands/lanes.py",
    "harness/slot_probe.py __main__": "harness/slot_probe.py",
}
#: Same keys -> why the entry may write the store of the home it runs in. #1346
EVAL_WAIVED = {
    "harness/cli.py d --no-control": "skips the control: the judge's scores are the work",
    "harness/cli.py sub canary": "plants run in their own homes (canary.child_env); the parent writes a lease only",
    "harness/cli.py sub chaos": "scenarios run in chaos.scratch_home; the machine lock is a lease, not work",
    "harness/cli.py bch --probe": "contamination probes are the measurement adoption reads",
    "harness/cli.py bch --calibrate": "reads a read-only store and writes none",
    "harness/cli.py cas action=control": "writes the case validation files evals.run reads; no store rows",
    "harness/cli.py stg action=controls": "no store write",
    "harness/commands/vision.py act probe": "the vision reference row: files under runs, no store write",
    "harness/hf_task.py sub vision-probe": "a venv child that writes a predictions file",
    "scripts/pool-full-probe.py __main__": "stdlib only; with-gpu-lock's lease is coordination, not work",
}


def _parser_var(call):
    f = call.func
    return f.value.id if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) else "?"


def eval_entry_points(text, rel):
    """(line, key) for each argparse option, subcommand or action choice that names an eval or probe."""
    tree, _ = _parse(text, rel)
    if tree is None:
        return []
    out = []
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call) or _call_name(n) not in ("add_argument", "add_parser"):
            continue
        names = [s for s in _strings(n.args) if _EVAL_NAME.match(s)]
        for k in n.keywords:
            if k.arg == "choices" and isinstance(k.value, (ast.Tuple, ast.List, ast.Set)):
                names += [f"{_strings(n.args)[0] if _strings(n.args) else '?'}={s}"
                          for s in _strings(k.value.elts) if _EVAL_NAME.match(s)]
        out += [(n.lineno, f"{rel} {_parser_var(n)} {s}") for s in names]
    if _EVAL_NAME.match(Path(rel).stem.replace("_", "-")):
        out += [(n.lineno, f"{rel} __main__") for n in tree.body if isinstance(n, ast.If) and _is_main(n.test)]
    return out


def _is_main(test):
    return (isinstance(test, ast.Compare) and isinstance(test.left, ast.Name) and test.left.id == "__name__"
            and _strings(test.comparators) == ["__main__"])


def unhomed_evals(text, rel, homed=None, waived=None):
    homed = EVAL_HOMED if homed is None else homed
    waived = EVAL_WAIVED if waived is None else waived
    return [f"{rel}:{line}: {key!r} runs an eval or probe in whatever home it is given, the live one by default; "
            f"call paths.eval_home in its handler and list it in EVAL_HOMED, or waive it in EVAL_WAIVED"
            for line, key in eval_entry_points(text, rel) if key not in homed and key not in waived]


def _sniffs(n):
    if isinstance(n, ast.Attribute) and n.attr == "__module__":
        return True
    if (isinstance(n, ast.Call) and _call_name(n) in ("getattr", "hasattr") and len(n.args) > 1
            and isinstance(n.args[1], ast.Constant) and n.args[1].value == "__module__"):
        return True
    if isinstance(n, ast.Compare) and any(isinstance(o, (ast.Is, ast.IsNot)) for o in n.ops):
        sides = [n.left, *n.comparators]
        return bool({s.attr for s in sides if isinstance(s, ast.Attribute)}
                    & {s.id for s in sides if isinstance(s, ast.Name)})
    return False


def double_sniffs(text, rel):
    """Production code that asks whether a name is a test double: a __module__ read, or `pkg.f is f`. #1437."""
    tree, out = _parse(text, rel)
    if tree is None:
        return out
    return out + [f"{rel}:{line}: tells a stand-in from the real function; name the machine (or the fact) at its seam "
                  f"instead, so production code has one path" for line in sorted({n.lineno for n in ast.walk(tree) if _sniffs(n)})]


#: The names a test once replaced to change which machine this is; the seam is environment.identity. #1437.
MACHINE_STAND_INS = ("this_machine", "this_fingerprint")


def machine_stand_ins(text, rel):
    """A test that replaces this_machine or this_fingerprint instead of naming the machine at the seam. #1437."""
    tree, out = _parse(text, rel)
    if tree is None:
        return out
    for n in ast.walk(tree):
        if not (isinstance(n, ast.Call) and _call_name(n) == "setattr" and n.args):
            continue
        name = n.args[1] if len(n.args) > 1 and not isinstance(n.args[0], ast.Constant) else n.args[0]
        if isinstance(name, ast.Constant) and str(name.value).rsplit(".", 1)[-1] in MACHINE_STAND_INS:
            out.append(f"{rel}:{n.lineno}: replaces {name.value}; name the machine with conftest machine_is or "
                       f"machine_has, which reach it through environment.identity")
    return out
