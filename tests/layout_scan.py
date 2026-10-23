"""AST scans behind tests/test_module_layout.py: who imports what, who reads what, who patches what. #484."""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CODE_ROOTS = ("harness", "evals", "gateway")
SCAN_ROOTS = CODE_ROOTS + ("scripts", "tests", "tools")
TEXT_SUFFIXES = {".md", ".yaml", ".yml", ".sh", ".toml", ".plist", ".tpl", ".txt", ".json"}
SKIP_DIRS = {".venv", ".git", "__pycache__", "node_modules", "golden"}


def module_name(path: Path, root: Path = REPO) -> str:
    rel = path.relative_to(root).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def py_files(roots, root: Path = REPO):
    for r in roots:
        base = root / r
        if not base.exists():
            continue
        for p in sorted(base.rglob("*.py")):
            if not SKIP_DIRS.intersection(p.relative_to(root).parts):
                yield p


def code_modules(root: Path = REPO) -> dict[str, str]:
    """Every module under the code roots: dotted name -> source."""
    return {module_name(p, root): p.read_text(encoding="utf-8")
            for p in py_files(CODE_ROOTS, root)}


def _absolute(mod: str, node: ast.ImportFrom, is_pkg: bool) -> str:
    if not node.level:
        return node.module or ""
    base = mod.split(".") if is_pkg else mod.split(".")[:-1]
    base = base[:len(base) - (node.level - 1)] if node.level > 1 else base
    return ".".join(base + ([node.module] if node.module else []))


@dataclass
class Facts:
    """What one source file binds, reads and patches."""
    aliases: dict = field(default_factory=dict)      # local name -> module
    top_from: dict = field(default_factory=dict)     # local name -> (module, name), module level
    local_from: list = field(default_factory=list)   # (module, name) imported inside a function
    bare: set = field(default_factory=set)           # names loaded bare
    attrs: list = field(default_factory=list)        # (module, name, ctx) read as alias.name
    patches: list = field(default_factory=list)      # (module, name, line)
    imported: list = field(default_factory=list)     # (module, name) from-imported anywhere


def _chain(node, aliases, modules):
    """The module a Name/Attribute chain denotes, or None."""
    if isinstance(node, ast.Name):
        return aliases.get(node.id)
    if isinstance(node, ast.Attribute):
        base = _chain(node.value, aliases, modules)
        if base and f"{base}.{node.attr}" in modules:
            return f"{base}.{node.attr}"
    return None


_FUNCS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)


def _collect(tree):
    """One traversal: import nodes, attribute and call nodes, and each bare load with its enclosing functions."""
    imports, attrs, calls, loads = [], [], [], []
    deep: dict = {}  # id(function) -> every ImportFrom inside it, at any depth
    stack = [(tree, ())]
    while stack:
        node, fns = stack.pop()
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            imports.append(node)
            if isinstance(node, ast.ImportFrom):
                for fn in fns:
                    deep[fn].append(node)
        elif isinstance(node, ast.Attribute):
            attrs.append(node)
        elif isinstance(node, ast.Call):
            calls.append(node)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            loads.append((node, fns))
        if isinstance(node, _FUNCS):
            deep[id(node)] = []
            fns = fns + (id(node),)
        stack.extend((child, fns) for child in ast.iter_child_nodes(node))
    return imports, attrs, calls, loads, deep


_FACTS: dict = {}


def facts(mod: str, src: str, modules: set, is_pkg: bool = False) -> Facts:
    """What `src` binds, reads and patches; the tests of a worker share one scan of each file. #1146."""
    key = (mod, src, is_pkg, frozenset(modules))
    if key not in _FACTS:
        _FACTS[key] = _facts(mod, src, modules, is_pkg)
    return _FACTS[key]


def _facts(mod: str, src: str, modules: set, is_pkg: bool) -> Facts:
    tree = ast.parse(src)
    f = Facts()
    top = set(map(id, tree.body))
    for stmt in tree.body:
        if isinstance(stmt, (ast.If, ast.Try)):
            top.update(map(id, ast.walk(stmt)))
    imports, attrs, calls, loads, deep = _collect(tree)
    for node in sorted(imports, key=lambda n: (n.lineno, n.col_offset)):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.asname:
                    f.aliases[a.asname] = a.name
                else:
                    head = a.name.split(".")[0]
                    f.aliases[head] = head
        else:
            src_mod = _absolute(mod, node, is_pkg)
            for a in node.names:
                local = a.asname or a.name
                if f"{src_mod}.{a.name}" in modules:
                    f.aliases[local] = f"{src_mod}.{a.name}"
                    continue
                f.imported.append((src_mod, a.name, node.lineno))
                if id(node) in top:
                    f.top_from[local] = (src_mod, a.name)
    _bare_reads(loads, deep, f, mod, is_pkg, modules)
    for node in attrs:
        m = _chain(node.value, f.aliases, modules)
        if m:
            f.attrs.append((m, node.attr, type(node.ctx).__name__, node.lineno))
            if isinstance(node.ctx, ast.Store):
                f.patches.append((m, node.attr, node.lineno))
    for node in calls:
        if isinstance(node.func, ast.Attribute) and node.func.attr == "setattr" and node.args:
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str) \
                    and "." in first.value:
                m, _, name = first.value.rpartition(".")
                if m in modules:
                    f.patches.append((m, name, node.lineno))
            elif len(node.args) >= 2 and isinstance(node.args[1], ast.Constant) \
                    and isinstance(node.args[1].value, str):
                m = _chain(first, f.aliases, modules)
                if m:
                    f.patches.append((m, node.args[1].value, node.lineno))
    return f


def _bare_reads(loads, deep, f: Facts, mod: str, is_pkg: bool, modules) -> None:
    """Bare loads at module scope, or in a function that does not import the name itself."""
    local_of: dict = {}

    def local(fns) -> dict:
        if fns not in local_of:
            got = dict(local(fns[:-1])) if fns else {}
            for sub in deep[fns[-1]] if fns else ():
                src = _absolute(mod, sub, is_pkg)
                for a in sub.names:
                    if f"{src}.{a.name}" not in modules:
                        got[a.asname or a.name] = (src, a.name)
            local_of[fns] = got
        return local_of[fns]
    for node, fns in loads:
        names = local(fns)
        if node.id in names:
            f.local_from.append(names[node.id])
        else:
            f.bare.add(node.id)


def _is_pkg(mod: str, root: Path = REPO) -> bool:
    return (root / Path(*mod.split(".")) / "__init__.py").exists()


class Graph:
    """Bindings of every code module, and which binding each read goes through."""

    def __init__(self, sources: dict[str, str], pkgs: set | None = None):
        self.modules = set(sources)
        pkgs = pkgs if pkgs is not None else {m for m in sources if _is_pkg(m)}
        self.facts = {m: facts(m, s, self.modules, m in pkgs) for m, s in sources.items()}
        self.edges: dict = {}
        for m, f in self.facts.items():
            for local, origin in f.top_from.items():
                self._link((m, local), origin)

    def _link(self, a, b):
        self.edges.setdefault(a, set()).add(b)
        self.edges.setdefault(b, set()).add(a)

    def component(self, binding) -> set:
        seen, todo = set(), [binding]
        while todo:
            b = todo.pop()
            if b in seen:
                continue
            seen.add(b)
            todo.extend(self.edges.get(b, ()))
        return seen

    def reads(self, binding) -> dict:
        """Every read of the value bound at `binding`: {binding read through: [reader module]}."""
        comp = self.component(binding)
        got: dict = {}
        for m, f in self.facts.items():
            for (mod, name) in comp:
                if mod == m and name in f.bare:
                    got.setdefault((mod, name), []).append(m)
            for (mod, name) in f.local_from:
                if (mod, name) in comp:
                    got.setdefault((mod, name), []).append(m)
            for (mod, name, ctx, _) in f.attrs:
                if ctx == "Load" and (mod, name) in comp:
                    got.setdefault((mod, name), []).append(m)
        return got

    def missed(self, module: str, name: str) -> dict:
        """Reads a patch of module.name does NOT reach: {binding: [reader]}."""
        return {b: sorted(set(r)) for b, r in self.reads((module, name)).items()
                if b != (module, name)}


def patches(paths) -> list:
    """(test file, line, module, name) for every monkeypatch.setattr / module.attr = x."""
    modules = set(code_modules())
    out = []
    for p in paths:
        f = facts(module_name(p), p.read_text(encoding="utf-8"), modules)
        out.extend((p.name, line, m, n) for m, n, line in f.patches)
    return out


def _watched(mod: str, prefixes) -> bool:
    return any(mod == p or mod.startswith(p + ".") for p in prefixes)


def ineffective(graph: Graph, found, strict=()) -> list[str]:
    """Patches that reach no reader of the name, or miss one inside `strict` modules."""
    bad = []
    for fname, line, mod, name in found:
        if mod not in graph.modules:
            continue
        reads = graph.reads((mod, name))
        missed = {b: sorted(set(r)) for b, r in reads.items() if b != (mod, name)}
        if reads and (mod, name) not in reads:
            bad.append(f"{fname}:{line} patches {mod}.{name}, which nothing reads; "
                       f"the code reads {', '.join(f'{m}.{n}' for m, n in missed)}")
            continue
        for (bm, bn), readers in missed.items():
            if _watched(mod, strict) or _watched(bm, strict):
                bad.append(f"{fname}:{line} patches {mod}.{name} but "
                           f"{', '.join(readers)} read it as {bm}.{bn}")
    return bad


_TEXT_REF = re.compile(r"\b(harness\.(?:cli|memory_store))[.:]([A-Za-z_]\w*)")


def references(watched=("harness.cli", "harness.memory_store")) -> set:
    """(module, name) every file in the repo takes from the watched modules."""
    modules = set(code_modules())
    got = set()
    for p in py_files(SCAN_ROOTS):
        f = facts(module_name(p), p.read_text(encoding="utf-8"), modules, _is_pkg(module_name(p)))
        for m, n, _ in f.imported:
            if m in watched:
                got.add((m, n))
        for m, n, ctx, _ in f.attrs:
            if m in watched and ctx == "Load":
                got.add((m, n))
        for m, n, _ in f.patches:
            if m in watched:
                got.add((m, n))
    for p in REPO.rglob("*"):
        if p.suffix in TEXT_SUFFIXES and p.is_file() \
                and not SKIP_DIRS.intersection(p.relative_to(REPO).parts):
            for m, n in _TEXT_REF.findall(p.read_text(encoding="utf-8", errors="ignore")):
                if n != "py" and m in watched:
                    got.add((m, n))
    return got
