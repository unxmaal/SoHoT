"""What the hidden tests call from the repo's own package, as signatures in the reference fix; never the tests. #1103."""
from __future__ import annotations

import ast
import re
from pathlib import Path

from evals import repo

HEAD = "The hidden tests call these names from the repository (signatures as a correct fix defines them):"
_DOTTED = re.compile(r"^[A-Za-z_]\w*(\.[A-Za-z_]\w*)+$")
_FOLLOW = 3


class Tree:
    """One commit of a mirror, read without a checkout."""

    def __init__(self, mirror: Path, sha: str):
        self.mirror, self.sha = mirror, sha
        got = repo._git(["-C", str(mirror), "ls-tree", "-r", "--name-only", sha]).stdout.decode()
        self.files = set(got.splitlines())
        self.dirs = {str(p) for f in self.files for p in Path(f).parents if str(p) != "."}
        self._ast: dict = {}

    def module_file(self, module: str) -> str | None:
        """The file that defines `module` (root or src/ layout); "" for a namespace package; None if not the repo's."""
        rel = module.replace(".", "/")
        for root in ("", "src/"):
            for path in (f"{root}{rel}.py", f"{root}{rel}/__init__.py"):
                if path in self.files:
                    return None if repo.is_test_path(path) else path
            if f"{root}{rel}" in self.dirs and not repo.is_test_path(f"{root}{rel}/x.py"):
                return ""
        return None

    def parse(self, path: str):
        if path not in self._ast:
            got = repo._git(["-C", str(self.mirror), "show", f"{self.sha}:{path}"], check=False)
            try:
                self._ast[path] = ast.parse(got.stdout.decode("utf-8", "replace")) if not got.returncode else None
            except SyntaxError:
                self._ast[path] = None
        return self._ast[path]


def _relative(path: str, level: int, module: str | None) -> str:
    parts = list(Path(path).with_suffix("").parts)
    parts = parts[1:] if parts[0] == "src" else parts
    package = parts[:-1]
    package = package[:len(package) - (level - 1)] if level > 1 else package
    return ".".join([*package, *([module] if module else [])])


def definition(tree: Tree, module: str, name: str, depth: int = 0):
    """The top-level node that defines `name` in `module`, following re-exports a few imports deep."""
    path = tree.module_file(module)
    node = tree.parse(path) if path else None
    if node is None:
        return None
    found = None
    for stmt in node.body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and stmt.name == name:
            found = stmt
        elif isinstance(stmt, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in stmt.targets):
            found = stmt
        elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name) and stmt.target.id == name:
            found = stmt
        elif isinstance(stmt, ast.ImportFrom) and depth < _FOLLOW:
            for alias in stmt.names:
                if (alias.asname or alias.name) == name:
                    src = _relative(path, stmt.level, stmt.module) if stmt.level else stmt.module or ""
                    found = definition(tree, src, alias.name, depth + 1) or found
    return found


def _args(fn) -> str:
    return ast.unparse(fn.args)


def signature(qual: str, node) -> str:
    """One line: a def with its parameters and return annotation, a class with its constructor's, a name with its type."""
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        ret = f" -> {ast.unparse(node.returns)}" if node.returns else ""
        return f"{'async ' if isinstance(node, ast.AsyncFunctionDef) else ''}{qual}({_args(node)}){ret}"
    if isinstance(node, ast.ClassDef):
        init = next((s for s in node.body if isinstance(s, ast.FunctionDef) and s.name == "__init__"), None)
        if init:
            args = ast.unparse(init.args)
            args = re.sub(r"^self(, )?", "", args)
            return f"class {qual}({args})"
        fields = [ast.unparse(s) for s in node.body if isinstance(s, ast.AnnAssign)]
        if fields and any("dataclass" in ast.unparse(d) for d in node.decorator_list):
            return f"class {qual}({', '.join(fields)})"
        return f"class {qual}"
    if isinstance(node, ast.AnnAssign):
        return f"{qual}: {ast.unparse(node.annotation)}"
    return qual


def _methods(node) -> dict:
    return {s.name: s for s in getattr(node, "body", []) if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef))}


def references(tree: Tree, node) -> tuple[set, set]:
    """({(module, name)} a parsed test file reaches in the repo's own package, {every attribute name it reads})."""
    for parent in ast.walk(node):
        for child in ast.iter_child_nodes(parent):
            child._parent = parent
    modules, names, attrs = {}, set(), set()

    def is_module(m: str) -> bool:
        return tree.module_file(m) is not None

    for stmt in ast.walk(node):
        if isinstance(stmt, ast.Import):
            for alias in stmt.names:
                if is_module(alias.name):
                    if alias.asname:
                        modules[alias.asname] = alias.name
                    else:
                        modules.setdefault(alias.name.split(".")[0], alias.name.split(".")[0])
        elif isinstance(stmt, ast.ImportFrom) and not stmt.level and stmt.module and is_module(stmt.module):
            for alias in stmt.names:
                full = f"{stmt.module}.{alias.name}"
                if alias.name != "*" and is_module(full):
                    modules[alias.asname or alias.name] = full
                elif alias.name != "*":
                    names.add((stmt.module, alias.name))
        elif isinstance(stmt, ast.Attribute):
            attrs.add(stmt.attr)

    def resolve(dotted: str):
        parts = dotted.split(".")
        if parts[0] not in modules:
            return None
        mod, rest = modules[parts[0]], parts[1:]
        while rest and is_module(f"{mod}.{rest[0]}"):
            mod, rest = f"{mod}.{rest[0]}", rest[1:]
        return (mod, rest[0]) if rest else None

    for stmt in ast.walk(node):
        if isinstance(stmt, ast.Attribute) and not isinstance(getattr(stmt, "_parent", None), ast.Attribute):
            try:
                got = resolve(ast.unparse(stmt))
            except Exception:
                got = None
            if got:
                names.add(got)
        elif isinstance(stmt, ast.Constant) and isinstance(stmt.value, str) and _DOTTED.match(stmt.value):
            parts = stmt.value.split(".")
            for k in range(len(parts) - 1, 0, -1):
                if tree.module_file(".".join(parts[:k])):
                    names.add((".".join(parts[:k]), parts[k]))
                    break
    # A bare name in a string (getattr, setattr, dir() checks) counts where a module the test uses defines it.
    used = set(modules.values()) | {m for m, _ in names}
    for stmt in ast.walk(node):
        if isinstance(stmt, ast.Constant) and isinstance(stmt.value, str) and stmt.value.isidentifier():
            names |= {(m, stmt.value) for m in used if definition(tree, m, stmt.value) is not None}
    return names, attrs


def tests_call(mirror: Path, base: str, fix: str, tests=None) -> list[str]:
    """Sorted signature lines of what the fix's test files use from the repo that the fix adds or re-signs."""
    new, old = Tree(mirror, fix), Tree(mirror, base)
    if tests is None:
        got = repo._git(["-C", str(mirror), "diff", "--name-status", "--no-renames", base, fix]).stdout.decode()
        rows = [line.split("\t", 1) for line in got.splitlines() if "\t" in line]
        tests = [p for s, p in rows if s != "D" and p.endswith(".py") and repo.is_test_path(p)]
    refs, attrs = set(), set()
    for path in tests:
        node = new.parse(path)
        if node is None:
            continue
        got, seen = references(new, node)
        refs |= got
        attrs |= seen
    out = set()
    for module, name in refs:
        now = definition(new, module, name)
        if now is None:
            continue
        was = definition(old, module, name)
        qual = f"{module}.{name}"
        if was is None or signature(qual, was) != signature(qual, now):
            out.add(signature(qual, now))
        if isinstance(now, ast.ClassDef):
            before = _methods(was) if isinstance(was, ast.ClassDef) else {}
            for m, fn in _methods(now).items():
                if m in attrs and not m.startswith("__") and (
                        m not in before or signature(m, before[m]) != signature(m, fn)):
                    out.add(signature(f"{qual}.{m}", fn))
    return sorted(out)


def block(lines) -> str:
    """The prompt's "tests call" block, or "" when the tests use nothing new."""
    return "\n".join([HEAD, *(f"- `{line}`" for line in lines)]) if lines else ""
