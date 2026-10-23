"""What the hidden tests call from the repo's own package, as signatures in the reference fix; never the tests. #1103."""
from __future__ import annotations

import ast
import re
from collections import Counter
from pathlib import Path

from evals import repo

HEAD = "The hidden tests call these names from the repository (signatures as a correct fix defines them):"
_DOTTED = re.compile(r"^[A-Za-z_]\w*(\.[A-Za-z_]\w*)+$")
_FOLLOW = 3
#: Line prefixes for interface a test names in a string, not an import. #1105.
TOOL, FLAG, ENV = "MCP tool: ", "CLI option: ", "environment variable: "
KINDS = (TOOL, FLAG, ENV)
_FLAG = re.compile(r"(?<![\w-])--[a-z][a-z0-9]*(?:-[a-z0-9]+)*")
_ENV = re.compile(r"^[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+$")


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


_EMPTY = ast.Module(body=[], type_ignores=[])


def offered(node) -> dict:
    """What a source file offers by name: {"tools": name -> def decorated as a tool, "literals"/"env": Counter of uses}."""
    tools, literals, env = {}, Counter(), Counter()
    for n in ast.walk(node):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and any("tool" in ast.unparse(d) for d in n.decorator_list):
            tools[n.name] = n
        elif isinstance(n, ast.Constant) and isinstance(n.value, str):
            literals[n.value] += 1
        elif isinstance(n, ast.Call) and n.args and "env" in ast.unparse(n.func).lower() \
                and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str):
            env[n.args[0].value] += 1
        elif isinstance(n, ast.Subscript) and "environ" in ast.unparse(n.value) \
                and isinstance(n.slice, ast.Constant) and isinstance(n.slice.value, str):
            env[n.slice.value] += 1
    return {"tools": tools, "literals": literals, "env": Counter({e: k for e, k in env.items() if _ENV.match(e)})}


def named(new: Tree, old: Tree, tests, sources) -> list[str]:
    """Tools, CLI options and environment variables the tests name in a string and the fix's source adds. #1105."""
    strings = {n.value for p in tests for n in ast.walk(new.parse(p) or _EMPTY)
               if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    tools, flags, env = {}, Counter(), Counter()
    for path in sources:
        if new.parse(path) is None:
            continue
        now, was = offered(new.parse(path)), offered((old.parse(path) if path in old.files else None) or _EMPTY)
        tools.update({n: fn for n, fn in now["tools"].items()
                      if n not in was["tools"] or signature(n, was["tools"][n]) != signature(n, fn)})
        # A flag or variable the fix uses more often than base did is one it adds, so a new subcommand's --out counts.
        flags += now["literals"] - was["literals"]
        env += now["env"] - was["env"]
    used = {f for s in strings for f in _FLAG.findall(s)}
    return (sorted(TOOL + signature(n, fn) for n, fn in tools.items() if n in strings)
            + sorted(FLAG + f for f in set(flags) & used)
            + sorted(ENV + e for e in env if any(re.search(rf"\b{e}\b", t) for t in strings)))


def tests_call(mirror: Path, base: str, fix: str, tests=None) -> list[str]:
    """Signature lines of what the fix's tests use from the repo that the fix adds or re-signs, then named strings."""
    new, old = Tree(mirror, fix), Tree(mirror, base)
    got = repo._git(["-C", str(mirror), "diff", "--name-status", "--no-renames", base, fix]).stdout.decode()
    rows = [line.split("\t", 1) for line in got.splitlines() if "\t" in line]
    sources = [p for s, p in rows if s != "D" and p.endswith(".py") and not repo.is_test_path(p)]
    if tests is None:
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
    return sorted(out) + named(new, old, tests, sources)


def block(lines) -> str:
    """The prompt's "tests call" block, or "" when the tests use nothing new."""
    return "\n".join([HEAD, *(_row(line) for line in lines)]) if lines else ""


def _row(line: str) -> str:
    kind = next((k for k in KINDS if line.startswith(k)), "")
    return f"- {kind}`{line[len(kind):]}`"


_WORD = re.compile(r"[A-Za-z_]\w*")


def _defined(node, top: bool = True) -> set:
    """Names a module defines: top-level defs, classes and assigned names, and its classes' methods."""
    out = set()
    for stmt in getattr(node, "body", []):
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.add(stmt.name)
            if isinstance(stmt, ast.ClassDef):
                out |= _defined(stmt, top=False)
        elif top and isinstance(stmt, (ast.Assign, ast.AnnAssign)):
            for target in stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]:
                out |= {n.id for n in ast.walk(target) if isinstance(n, ast.Name)}
    return out


def unlisted(mirror: Path, base: str, fix: str, prompt: str, ids=()) -> list[str]:
    """Names the fix's source adds that the hidden tests or graded ids spell and the prompt never does. #1141."""
    new, old = Tree(mirror, fix), Tree(mirror, base)
    got = repo._git(["-C", str(mirror), "diff", "--name-status", "--no-renames", base, fix]).stdout.decode()
    rows = [line.split("\t", 1) for line in got.splitlines() if "\t" in line]
    added = set()
    for path in (p for s, p in rows if s != "D" and p.endswith(".py") and not repo.is_test_path(p)):
        was = _defined(old.parse(path)) if path in old.files else set()
        added |= _defined(new.parse(path)) - was
    text = [repo._git(["-C", str(mirror), "show", f"{fix}:{p}"]).stdout.decode("utf-8", "replace")
            for s, p in rows if s != "D" and p.endswith(".py") and repo.is_test_path(p)]
    spelled = {w for t in [*text, *ids] for w in _WORD.findall(t)}
    shown = set(_WORD.findall(prompt))
    return sorted(n for n in added & spelled if n not in shown and not n.startswith("__"))
