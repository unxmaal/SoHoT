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
