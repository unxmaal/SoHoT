"""Which gating limits leave a trace when they bind: a limit results or verdicts record, or a harness.cuts call naming them (#1087)."""
from __future__ import annotations

import ast
import re
from pathlib import Path

from harness import knobs

DIR = "tests/gauntlet/untraced"
#: The harness.cuts calls, by the position of the argument naming the knob or site they record.
CALLS = {"cut": 0, "timeout": 0, "take": 2, "filled": 2}


def file_of(site: str) -> str:
    """The inventory file a site belongs in: one per source directory, as the knob backlog splits."""
    return site.split(":", 1)[0].rsplit("/", 1)[0].replace("/", "_") + ".txt"


def _text(node) -> str:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else ""


def _knob_param(name: str | None) -> bool:
    return bool(name) and (name == "knob" or name.endswith("_knob"))


def names_in(text: str, rel: str) -> list[tuple[str, str]]:
    """(name, rel:line) for each knob or site a module hands to a cut: a cuts call, a *_knob name, argument or default, a --*-knob option."""
    out = []
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            a = node.args
            pos = a.posonlyargs + a.args
            pairs = list(zip(pos[len(pos) - len(a.defaults):], a.defaults)) + [
                (arg, d) for arg, d in zip(a.kwonlyargs, a.kw_defaults) if d is not None]
            out += [(_text(d), f"{rel}:{node.lineno}") for arg, d in pairs if _knob_param(arg.arg) and _text(d)]
        field = knobs._field(node)
        if field and _knob_param(field[0]):
            out += [(t, f"{rel}:{node.lineno}") for t in _texts(field[1])]
        if isinstance(node, (ast.List, ast.Tuple)):
            pairs = zip(node.elts, node.elts[1:])
            out += [(_text(b), f"{rel}:{node.lineno}") for a, b in pairs if _text(a).endswith("-knob") and _text(b)]
        if not isinstance(node, ast.Call):
            continue
        callee = knobs._dotted(node.func).split(".")
        name = _name_arg(node)
        if name is not None:
            out += [(t, f"{rel}:{node.lineno}") for t in _texts(name)]
        option = callee[-1] == "add_argument" and any(_text(x).endswith("-knob") for x in node.args)
        for kw in node.keywords:
            if _knob_param(kw.arg) or (option and kw.arg == "default"):
                out += [(t, f"{rel}:{node.lineno}") for t in _texts(kw.value)]
    return out


def _texts(node) -> list[str]:
    """Every string literal an expression can yield: a constant, either arm of a conditional, an `or` fallback."""
    if _text(node):
        return [_text(node)]
    if isinstance(node, ast.IfExp):
        return _texts(node.body) + _texts(node.orelse)
    if isinstance(node, ast.BoolOp):
        return [t for v in node.values for t in _texts(v)]
    return []


def _name_arg(node):
    """The argument of a harness.cuts call that names its knob or site; None for any other call."""
    callee = knobs._dotted(node.func).split(".")
    if len(callee) < 2 or callee[-2] != "cuts" or callee[-1] not in CALLS:
        return None
    at = CALLS[callee[-1]]
    return node.args[at] if len(node.args) > at else None


def unnamed_in(text: str, rel: str) -> list[str]:
    """rel:line of each cuts call whose name is neither a literal nor a *_knob variable, which no scan can read."""
    out = []
    for node in ast.walk(ast.parse(text)):
        if not isinstance(node, ast.Call):
            continue
        callee = knobs._dotted(node.func).split(".")
        if len(callee) < 2 or callee[-2] != "cuts" or callee[-1] not in CALLS:
            continue
        name = _name_arg(node)
        if name is not None and (_texts(name) or (isinstance(name, ast.Name) and _knob_param(name.id))):
            continue
        out.append(f"{rel}:{node.lineno}")
    return out


def _modules(root):
    from harness import repo
    root = Path(root)
    for path in repo.publishable(root):
        rel = path.relative_to(root).as_posix()
        if path.is_file() and knobs._production(rel) and rel != "harness/cuts.py":
            yield rel, path.read_text(encoding="utf-8", errors="replace")


def named(root=knobs.REPO) -> dict[str, list[str]]:
    """Every knob or site production code hands to a cut, with where."""
    out: dict[str, list[str]] = {}
    for rel, text in _modules(root):
        for name, where in names_in(text, rel):
            out.setdefault(name, []).append(where)
    return out


def unnamed(root=knobs.REPO) -> list[str]:
    return [w for rel, text in _modules(root) for w in unnamed_in(text, rel)]


def limits(root=knobs.REPO) -> dict[str, str]:
    """Every gating site the registry or the knob backlog holds, with its knob's name ("" for a backlog site)."""
    by_site = {s: k.name for k in knobs.KNOBS.values() for s in k.sites}
    found = {s: "" for s in knobs.inventory(root) if not knobs.not_gating(s)}
    return {**found, **by_site}


def traced(site: str, knob: str, names) -> bool:
    k = knobs.KNOBS[knob] if knob else None
    if k is not None and (k.limit or k.binds_via or knob in names):
        return True
    return site in names


def untraced(root=knobs.REPO) -> list[str]:
    """The gating sites nothing records when they bind and no NEVER_CUTS exempts, sorted."""
    names = named(root)
    return sorted(s for s, k in limits(root).items() if not traced(s, k, names) and s not in knobs.NEVER_CUTS)


#: Calls whose argument bounds how much work is done: a limit read inside one cuts.
BOUNDING = ("min", "max", "range", "islice", "take", "filled")
_STOPS = (ast.Break, ast.Return, ast.Raise, ast.Continue)


def _read(site: str):
    """(rel, the name code reads the site's value by, the function it is a parameter of or "") or None for a literal."""
    m = knobs._SITE.fullmatch(site)
    if m is None or m["keys"] or m["name"] == "environ" or "->" in site:
        return None
    if m["param"]:
        return m["rel"], m["param"], m["name"]
    return m["rel"], m["name"].rsplit(".", 1)[-1], ""


def _uses(node, name: str, bare: bool, attr: bool = True) -> bool:
    return any((bare and isinstance(n, ast.Name) and n.id == name)
               or (attr and isinstance(n, ast.Attribute) and n.attr == name) for n in ast.walk(node))


def _function(tree, qual: str):
    def walk(body, scope):
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                here = f"{scope}.{node.name}" if scope else node.name
                if here == qual and not isinstance(node, ast.ClassDef):
                    return node
                got = walk(node.body, here)
                if got is not None:
                    return got
        return None
    return walk(tree.body, "")


def _index(tree) -> tuple[set, list]:
    """The names a tree imports by `from`, and the nodes that could bound work: slices, bounding calls, stopping tests."""
    imported, nodes = set(), []
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom):
            imported |= {a.name for a in n.names}
        elif isinstance(n, ast.Slice) or (isinstance(n, ast.Call) and knobs._dotted(n.func).split(".")[-1] in BOUNDING):
            nodes.append(n)
        elif (isinstance(n, (ast.If, ast.While)) and isinstance(n.test, ast.Compare)
              and any(isinstance(b, _STOPS) for b in n.body)):
            nodes.append(n)
    return imported, nodes


def cutting_uses(texts: dict[str, str], site: str, trees: dict | None = None,
                 indexes: dict | None = None) -> list[str]:
    """rel:line of each place the site's value bounds work: a slice, a min/max/range bound, a test that stops a loop."""
    got = _read(site)
    if got is None:
        return []
    rel, name, func = got
    out = []
    for where, text in texts.items():
        if func and where != rel:
            continue
        tree = trees[where] if trees is not None else ast.parse(text)
        if func:
            tree = _function(tree, func)
            if tree is None:
                continue
            imported, nodes = _index(tree)
        elif indexes is not None:
            imported, nodes = indexes[where] if where in indexes else indexes.setdefault(where, _index(tree))
        else:
            imported, nodes = _index(tree)
        bare = where == rel or name in imported
        # A parameter is read by its bare name; `proc.poll` is not the parameter `poll`.
        attr = not func
        for node in nodes:
            if isinstance(node, ast.Slice):
                hit = any(_uses(p, name, bare, attr) for p in (node.lower, node.upper, node.step) if p is not None)
            elif isinstance(node, ast.Call):
                hit = any(_uses(a, name, bare, attr) for a in [*node.args, *(k.value for k in node.keywords)])
            else:
                hit = _uses(node.test, name, bare, attr)
            if hit:
                out.append(f"{where}:{node.lineno}")
    return out


def exemption_problems(exempt: dict[str, str], root=knobs.REPO, texts: dict[str, str] | None = None) -> list[str]:
    """Why each NEVER_CUTS entry is refused: no reason, not a gating site, already traced, or a use that cuts."""
    texts = dict(_modules(root)) if texts is None else texts
    sites = limits(root) if root is not None else {}
    names = named(root) if root is not None else {}
    trees, indexes = {where: ast.parse(text) for where, text in texts.items()}, {}
    out = []
    for site, why in sorted(exempt.items()):
        if not (why or "").strip():
            out.append(f"{site}: no reason given")
        if root is not None and site not in sites:
            out.append(f"{site}: not a gating site the registry or the knob backlog holds")
        elif root is not None and traced(site, sites[site], names):
            out.append(f"{site}: already records its cuts")
        out += [f"{site}: cuts work at {w}" for w in cutting_uses(texts, site, trees, indexes)]
    return out


def unknown(root=knobs.REPO) -> list[str]:
    """Names handed to a cut that are neither a registered knob nor a gating site, with where."""
    names, sites = named(root), set(limits(root))
    return sorted(f"{n} ({', '.join(w)})" for n, w in names.items() if n not in knobs.KNOBS and n not in sites)


#: Until families that name no knob's limit: a lane's case count, a package version.
_OTHER_UNTILS = ("cases:", "version:")
_HEAD = re.compile(r"(?:^|[\s:(])[A-Za-z_][\w.]*$")
_LIMIT_NAME = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z0-9_{}]+)?$")


def _hand_fstring(node: ast.JoinedStr) -> bool:
    parts = node.values
    if any(isinstance(p, ast.Constant) and "<" in str(p.value) for p in parts):
        return False
    if isinstance(parts[0], ast.Constant) and str(parts[0].value).startswith(_OTHER_UNTILS):
        return False
    for i, p in enumerate(parts[:-1]):
        if not (isinstance(p, ast.Constant) and str(p.value).endswith(">") and isinstance(parts[i + 1], ast.FormattedValue)):
            continue
        head = str(p.value)[:-1]
        if (not head and i and isinstance(parts[i - 1], ast.FormattedValue)) or _HEAD.search(head):
            return True
    return False


def _arms(node) -> list:
    return _arms(node.body) + _arms(node.orelse) if isinstance(node, ast.IfExp) else [node]


def _limit_slots(tree) -> set[int]:
    """ids of the expressions written into a limit: an assignment to *limit, a limit= argument, an *Error or Cut argument."""
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(knobs._dotted(t).split(".")[-1].endswith("limit") for t in node.targets):
            out += _arms(node.value)
        if isinstance(node, ast.Call):
            out += [a for kw in node.keywords if kw.arg == "limit" for a in _arms(kw.value)]
            if knobs._dotted(node.func).split(".")[-1].endswith(("Error", "Cut")):
                out += [a for x in node.args for a in _arms(x)]
    return {id(n) for n in out}


def hand_built_in(text: str, rel: str) -> list[str]:
    """rel:line of each limit body built without knobs.hit: a `name>{N}` f-string or a (name, N) pair (#1193)."""
    tree, units, found = ast.parse(text), set(knobs.limit_units()), set()
    slots = _limit_slots(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr) and _hand_fstring(node):
            found.add(node.lineno)
        if isinstance(node, ast.Tuple) and len(node.elts) == 2 and _text(node.elts[0]) \
                and not isinstance(node.elts[1], ast.Constant) and _LIMIT_NAME.match(_text(node.elts[0])) \
                and (_text(node.elts[0]) in units or id(node) in slots):
            found.add(node.lineno)
    return [f"{rel}:{n}" for n in sorted(found)]


def hand_built(root=knobs.REPO) -> list[str]:
    return [w for rel, text in _modules(root) for w in hand_built_in(text, rel)]


def unit_calls_in(text: str, rel: str) -> list[tuple[str, str, str]]:
    """(name, unit, rel:line) of each knobs.hit or knobs.limit call naming both as literals (#1193)."""
    out = []
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.Call) and knobs._dotted(node.func).endswith(("knobs.hit", "knobs.limit")) \
                and len(node.args) == 3 and _text(node.args[0]) and _text(node.args[2]):
            out.append((_text(node.args[0]), _text(node.args[2]), f"{rel}:{node.lineno}"))
    return out


def unit_calls(root=knobs.REPO) -> list[tuple[str, str, str]]:
    return [c for rel, text in _modules(root) for c in unit_calls_in(text, rel)]
