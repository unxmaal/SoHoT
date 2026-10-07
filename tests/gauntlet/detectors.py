"""Trigger detectors for tier-2 gauntlet classes: each finds the sites where a class's trigger question fires (#492 B)."""

import ast
import re
from collections import namedtuple
from pathlib import Path

from harness import repo
from tests.gauntlet import scanners

HERE = Path(__file__).resolve().parent
BACKLOG_FILE = HERE / "backlog.json"

Hit = namedtuple("Hit", "site line why")


# The agent lane's case repos are broken on purpose; they are inputs to a model, not code here.
NOT_PRODUCTION = ("tests/", "evals/cases/")


def _production(rel):
    return not rel.startswith(NOT_PRODUCTION)


def sources(root, tests=False):
    root = Path(root)
    out = {}
    for path in repo.publishable(root):
        rel = path.relative_to(root).as_posix()
        if not path.is_file() or not scanners.is_python(path):
            continue
        if _production(rel) or (tests and rel.startswith("tests/") and "/fixtures/" not in rel):
            out[rel] = path.read_text(encoding="utf-8", errors="replace")
    return out


def parse(files):
    out = {}
    for rel, text in files.items():
        try:
            out[rel] = ast.parse(text)
        except SyntaxError:
            continue
    return out


def _prod(trees):
    return {rel: t for rel, t in trees.items() if _production(rel)}


def _str(node):
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _upper(name):
    return bool(re.fullmatch(r"_?[A-Z][A-Z0-9_]*", name or ""))


def _scopes(tree):
    # (qualname, node) for every function, so a hit can name the function it sits in.
    def walk(node, prefix):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = prefix + child.name
                yield name, child
                yield from walk(child, name + ".")
            elif isinstance(child, ast.ClassDef):
                yield from walk(child, prefix + child.name + ".")
            else:
                yield from walk(child, prefix)
    yield from walk(tree, "")


def _innermost(tree):
    # node id -> qualname of the innermost function holding it.
    owner = {}
    for name, fn in _scopes(tree):
        for n in ast.walk(fn):
            owner[id(n)] = name
    return owner


def _assign_targets(tree):
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name):
            yield stmt.targets[0].id, stmt.value, stmt.lineno
        elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name) and stmt.value is not None:
            yield stmt.target.id, stmt.value, stmt.lineno


def closed_tables(trees):
    prod = _prod(trees)
    tables = {}
    for rel, tree in prod.items():
        for name, value, line in _assign_targets(tree):
            if (_upper(name) and isinstance(value, ast.Dict) and len(value.keys) >= 3
                    and all(_str(k) is not None for k in value.keys)):
                tables.setdefault(name, []).append((rel, line))
    out = []
    for rel, tree in prod.items():
        for n in ast.walk(tree):
            if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "get"
                    and n.args and _str(n.args[0]) is None):
                continue
            recv = n.func.value
            if isinstance(recv, ast.Name) and recv.id in tables:
                homes = [h for h in tables[recv.id] if h[0] == rel]
            elif isinstance(recv, ast.Attribute) and recv.attr in tables:
                homes = tables[recv.attr]
            else:
                continue
            name = recv.id if isinstance(recv, ast.Name) else recv.attr
            for home, line in homes:
                out.append(Hit(f"{home}:{name}", line,
                               f"a fixed table looked up with a fallback at {rel}:{n.lineno}; an unlisted key "
                               "falls through to a default"))
    return out


_NEWEST = re.compile(r"(?is)\bORDER\s+BY\s+[^;]*?\bDESC\s+LIMIT\s+1\b(?!\s*,|\d)")


def _sql_text(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(v.value if isinstance(v, ast.Constant) else " x " for v in node.values)
    return None


def latest_row_state(trees):
    out = []
    for rel, tree in _prod(trees).items():
        owner = _innermost(tree)
        seen = set()
        for n in ast.walk(tree):
            text = _sql_text(n)
            if text is None or not _NEWEST.search(text):
                continue
            scope = owner.get(id(n), "<module>")
            if scope in seen:
                continue
            seen.add(scope)
            out.append(Hit(f"{rel}:{scope}", n.lineno, "state read from the newest row of an append table"))
    return out


_GUARD = re.compile(r"(?:check|guard|ensure|refuse|require)_\w+")


def _referenced(trees):
    names = {}
    for rel, tree in trees.items():
        for n in ast.walk(tree):
            name = (n.id if isinstance(n, ast.Name) else n.attr if isinstance(n, ast.Attribute)
                    else n.name.split(".")[-1] if isinstance(n, ast.alias) else None)
            if name:
                names.setdefault(name, set()).add(rel)
    return names


def unreached_guards(trees):
    prod = _prod(trees)
    refs = _referenced(prod)
    out = []
    for rel, tree in prod.items():
        for name, fn in _scopes(tree):
            short = name.rsplit(".", 1)[-1]
            if not _GUARD.fullmatch(short):
                continue
            if not refs.get(short):
                out.append(Hit(f"{rel}:{short}", fn.lineno, "a guard no production path invokes"))
    return out


def _dest(call):
    flags = [_str(a) for a in call.args if _str(a)]
    longs = [f for f in flags if f.startswith("--")]
    shown = longs[0] if longs else (flags[0] if flags else None)
    dest = next((_str(k.value) for k in call.keywords if k.arg == "dest" and _str(k.value)), None)
    if dest is None and shown:
        dest = shown.lstrip("-").replace("-", "_")
    return dest, shown or dest


def _add_argument_calls(tree):
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "add_argument":
            yield n


def ignored_options(trees):
    prod = _prod(trees)
    declared = {id(a) for tree in prod.values() for c in _add_argument_calls(tree)
                for a in c.args + [k.value for k in c.keywords if k.arg == "dest"]}
    read = set()
    for tree in prod.values():
        for n in ast.walk(tree):
            if isinstance(n, ast.Attribute):
                read.add(n.attr)
            elif isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in declared:
                read.add(n.value)
    out = []
    for rel, tree in prod.items():
        for n in _add_argument_calls(tree):
            dest, shown = _dest(n)
            if dest and dest not in read:
                out.append(Hit(f"{rel}:{shown}", n.lineno, f"parsed into `{dest}` and never read"))
    return out


_PER_MEMBER = re.compile(r"(?i)ctx|context|timeout|memory|ceiling|budget|batch|steps|max_tokens|threads|"
                         r"(?:^|_)gb(?:_|$)|temperature|reserve|wait")


def member_defaults(trees):
    out = []
    for rel, tree in _prod(trees).items():
        for name, fn in _scopes(tree):
            args = fn.args
            pos = args.posonlyargs + args.args
            pairs = list(zip(pos[len(pos) - len(args.defaults):], args.defaults))
            pairs += [(a, d) for a, d in zip(args.kwonlyargs, args.kw_defaults) if d is not None]
            for arg, d in pairs:
                const = d.id if isinstance(d, ast.Name) else d.attr if isinstance(d, ast.Attribute) else None
                if not _upper(const):
                    continue
                if _PER_MEMBER.search(arg.arg) or _PER_MEMBER.search(const):
                    out.append(Hit(f"{rel}:{name.rsplit('.', 1)[-1]}({arg.arg})", d.lineno,
                                   f"one constant {const} defaults a value that differs per model or machine"))
    return out


TERMINAL_VERDICTS = {"broken", "declined", "failed"}
_EXIT = re.compile(r"returncode|exit_?code|\bexited\b")


def _verdict_literals(nodes):
    for n in nodes:
        for m in ast.walk(n):
            if isinstance(m, ast.Constant) and m.value in TERMINAL_VERDICTS:
                yield m


def harness_verdicts(trees):
    out = []
    for rel, tree in _prod(trees).items():
        for name, fn in _scopes(tree):
            found = None
            for n in ast.walk(fn):
                if isinstance(n, ast.ExceptHandler):
                    found = found or next(_verdict_literals(n.body), None)
                elif isinstance(n, (ast.If, ast.IfExp)) and _EXIT.search(ast.unparse(n.test)):
                    body = n.body if isinstance(n.body, list) else [n.body]
                    orelse = n.orelse if isinstance(n.orelse, list) else [n.orelse]
                    found = found or next(_verdict_literals(body + orelse), None)
            inner = {id(m) for _, sub in _scopes(fn) for m in ast.walk(sub)}
            if found is not None and id(found) not in inner:
                out.append(Hit(f"{rel}:{name}", found.lineno,
                               "a terminal verdict written from an exception or exit status, which may be the "
                               "harness's fault rather than the subject's"))
    return out


def _literal_set(value):
    if isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id in ("frozenset", "set",
                                                                                              "tuple") \
            and len(value.args) == 1:
        value = value.args[0]
    if not isinstance(value, (ast.Tuple, ast.List, ast.Set)) or len(value.elts) < 2:
        return None
    items = [_str(e) for e in value.elts]
    if any(i is None for i in items):
        return None
    return frozenset(items)


def duplicated_literals(trees):
    by_value = {}
    for rel, tree in _prod(trees).items():
        for name, value, line in _assign_targets(tree):
            items = _literal_set(value)
            if _upper(name) and items and len(items) >= 2:
                by_value.setdefault(items, []).append((rel, name, line))
    out = []
    for items, homes in by_value.items():
        if len({rel for rel, _, _ in homes}) < 2:
            continue
        for rel, name, line in homes:
            others = ", ".join(f"{r}:{n}" for r, n, _ in homes if (r, n) != (rel, name))
            out.append(Hit(f"{rel}:{name}", line, f"the same list is written down in {others}"))
    return out


# Set by the OS or the shell, so there is no producer in this repo to agree with.
COMMON_ENV = {"HOME", "PATH", "USER", "LOGNAME", "SHELL", "TMPDIR", "TEMP", "TMP", "LANG", "LC_ALL", "PWD",
              "TERM", "CI", "GITHUB_ACTIONS", "VIRTUAL_ENV", "PYTHONPATH", "XDG_CACHE_HOME", "XDG_CONFIG_HOME",
              "USERPROFILE", "APPDATA", "LOCALAPPDATA", "SYSTEMROOT", "COLUMNS", "NO_COLOR"}


def _env_name(n):
    if isinstance(n, ast.Subscript) and isinstance(n.ctx, ast.Load) and _is_environ(n.value):
        return _str(n.slice)
    if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.args:
        if n.func.attr == "get" and _is_environ(n.func.value):
            return _str(n.args[0])
        if n.func.attr == "getenv" and isinstance(n.func.value, ast.Name) and n.func.value.id == "os":
            return _str(n.args[0])
    return None


def _is_environ(node):
    return (isinstance(node, ast.Attribute) and node.attr == "environ") or (
        isinstance(node, ast.Name) and node.id == "environ")


def env_seams(trees):
    first = {}
    for rel, tree in sorted(_prod(trees).items()):
        for n in ast.walk(tree):
            name = _env_name(n)
            if name and name not in COMMON_ENV and name not in first:
                first[name] = (rel, n.lineno)
    return [Hit(f"env:{name}", line, f"read at {rel}; whoever sets it is the other half of the seam")
            for name, (rel, line) in first.items()]


DETECTORS = {
    "closed_tables": closed_tables,
    "latest_row_state": latest_row_state,
    "unreached_guards": unreached_guards,
    "ignored_options": ignored_options,
    "member_defaults": member_defaults,
    "harness_verdicts": harness_verdicts,
    "duplicated_literals": duplicated_literals,
    "env_seams": env_seams,
}


def run(trees, index):
    out = {}
    for cid, entry in index.items():
        name = entry.get("detector")
        if name:
            hits = {}
            for h in DETECTORS[name](trees):
                hits.setdefault(h.site, h)
            out[cid] = sorted(hits.values())
    return out


def _marker(dec, consts):
    if not (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute) and dec.func.attr == "gauntlet"):
        return None

    def value(node):
        return consts.get(node.id) if isinstance(node, ast.Name) else _str(node)
    cid = value(dec.args[0]) if dec.args else None
    site = next((value(k.value) for k in dec.keywords if k.arg == "site"), None)
    return (cid, site) if cid and site else None


def bindings(files):
    out = {}
    for rel, text in files.items():
        if not rel.startswith("tests/"):
            continue
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        consts = {name: _str(v) for name, v, _ in _assign_targets(tree) if _str(v) is not None}
        for stmt in tree.body:
            tests = [(stmt.name, stmt)] if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)) else []
            if isinstance(stmt, ast.ClassDef):
                tests = [(f"{stmt.name}::{f.name}", f) for f in stmt.body
                         if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))]
            for name, fn in tests:
                for dec in fn.decorator_list:
                    key = _marker(dec, consts)
                    if key:
                        out.setdefault(key, []).append(f"{rel}::{name}")
    return out


def ledger(hits, marks, index):
    out = {}
    for cid, found in hits.items():
        found_sites = [h.site for h in found]
        waivers = index.get(cid, {}).get("waivers", {})
        bound_sites = {s for c, s in marks if c == cid}
        out[cid] = {
            "bound": sorted(s for s in found_sites if s in bound_sites),
            "waived": sorted(s for s in found_sites if s in waivers and s not in bound_sites),
            "unbound": sorted(s for s in found_sites if s not in waivers and s not in bound_sites),
            "stale_bindings": sorted(s for s in bound_sites if s not in found_sites),
            "stale_waivers": sorted(s for s in waivers if s not in found_sites),
        }
    return out
