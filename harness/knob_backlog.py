"""The knob backlog: the sites it holds, the ones a branch added, and how often each one's limit is quoted in a stored reason (#1085)."""
from __future__ import annotations

import ast
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from harness import knobs

DIR = "tests/gauntlet/knob_backlog"
BASE = "origin/main"
#: Verdict outcomes that pass a candidate on; every other verdict is a wait, a skip or a decline.
PASSED = ("measured", "screened")
#: Letters a reason template's literal text needs before it is matched, or `{} GiB` would match everything.
LITERAL_LETTERS = 8


def sites(root=knobs.REPO, directory: str = DIR) -> list[str]:
    """Every backlog line under `root`'s working tree, file by file."""
    return [line for path in sorted((Path(root) / directory).glob("*.txt"))
            for line in path.read_text(encoding="utf-8").splitlines()]


def _git(root, *args) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)


def merge_base(root=knobs.REPO, base: str = BASE) -> str:
    """The commit HEAD forked from `base`, or "" when this clone does not hold `base`."""
    got = _git(root, "merge-base", base, "HEAD")
    return got.stdout.strip() if got.returncode == 0 else ""


def at(root, ref: str, directory: str = DIR) -> list[str]:
    """The backlog lines committed at `ref`."""
    listed = _git(root, "ls-tree", "--name-only", f"{ref}:{directory}")
    if listed.returncode != 0:
        return []
    out = []
    for name in sorted(n for n in listed.stdout.splitlines() if n.endswith(".txt")):
        out += _git(root, "show", f"{ref}:{directory}/{name}").stdout.splitlines()
    return out


def added(root=knobs.REPO, base: str = BASE, directory: str = DIR) -> list[str] | None:
    """Backlog sites the working tree holds and the merge base with `base` does not; None without a merge base or a list there."""
    fork = merge_base(root, base)
    if not fork or _git(root, "ls-tree", "--name-only", f"{fork}:{directory}").returncode != 0:
        return None
    return sorted(set(sites(root, directory)) - set(at(root, fork, directory)))


@dataclass(frozen=True)
class Quote:
    """One f-string: where it is, its literal text with {} per hole, and what each hole reads."""
    rel: str
    line: int
    scope: str
    text: str
    #: (dotted name a hole reads, the sites that name may carry) in source order.
    reads: tuple[tuple[str, tuple[str, ...]], ...]

    def sites(self, among) -> set[str]:
        return {site for _, got in self.reads for site in got if site in among}

    def pattern(self) -> re.Pattern | None:
        """A regex for text this f-string produced; None when its literal text is too short to tell."""
        parts = self.text.split("{}")
        if sum(c.isalpha() for c in "".join(parts)) < LITERAL_LETTERS:
            return None
        return re.compile("(?:.+?)".join(re.escape(p) for p in parts), re.S)


def _names(node) -> list[str]:
    """The dotted names an expression reads, outermost chain only."""
    if isinstance(node, (ast.Name, ast.Attribute)):
        got = knobs._dotted(node)
        if got:
            return [got]
    if isinstance(node, ast.Call):
        callee = [node.func.value] if isinstance(node.func, ast.Attribute) else []
        return [n for child in (*callee, *node.args, *(k.value for k in node.keywords)) for n in _names(child)]
    out = []
    for child in ast.iter_child_nodes(node):
        out += _names(child)
    return out


def _module_rel(root: Path, dotted: str) -> str:
    rel = dotted.replace(".", "/")
    for cand in (f"{rel}.py", f"{rel}/__init__.py"):
        if (root / cand).is_file():
            return cand
    return ""


def _imports(tree, root: Path) -> dict[str, str]:
    """alias -> 'rel.py' for an imported module, 'rel.py:NAME' for an imported name, "" for one outside the repo."""
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                out[a.asname or a.name.split(".")[0]] = _module_rel(root, a.name) if a.asname else ""
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            for a in node.names:
                rel = _module_rel(root, f"{node.module}.{a.name}")
                here = _module_rel(root, node.module)
                out[a.asname or a.name] = rel or (f"{here}:{a.name}" if here else "")
    return out


def _module_names(tree) -> set[str]:
    return {f[0] for f in map(knobs._field, tree.body) if f}


def _defaults(fn) -> dict:
    a = fn.args
    pos = a.posonlyargs + a.args
    out = {arg.arg: None for arg in pos + a.kwonlyargs}
    out.update({arg.arg: d for arg, d in zip(pos[len(pos) - len(a.defaults):], a.defaults)})
    out.update({arg.arg: d for arg, d in zip(a.kwonlyargs, a.kw_defaults) if d is not None})
    return out


def _locals(fn) -> dict:
    """name -> value of each plain `name = value` in a function's own body, nested functions aside."""
    out, todo = {}, list(fn.body)
    while todo:
        node = todo.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        field = knobs._field(node)
        if field:
            out.setdefault(*field)
        todo += list(ast.iter_child_nodes(node))
    return out


def quotes(text: str, rel: str, root=knobs.REPO) -> list[Quote]:
    """Every f-string in one module, each hole resolved to the site it reads where that is knowable."""
    tree = ast.parse(text)
    root = Path(root)
    imports, module = _imports(tree, root), _module_names(tree)
    out = []

    def resolve(name: str, frames, depth: int = 0) -> tuple[str, ...]:
        head, _, rest = name.partition(".")
        if depth > 3:
            return ()
        for kind, qual, params, local in frames:
            if kind == "class" and head == "self" and rest:
                return (f"{rel}:{qual}.{rest.split('.')[0]}",)
            if kind == "def" and head in params and head != "self":
                d = params[head]
                if d is None:
                    return ()
                if knobs._literal(d):
                    return (f"{rel}:{qual}({head})",)
                return resolve(knobs._dotted(d), [], depth + 1) if knobs._dotted(d) else ()
            if kind == "def" and head in local and not rest:
                return tuple(s for n in _names(local[head]) for s in resolve(n, frames, depth + 1))
        if head in imports:
            target = imports[head]
            if not target:
                return ()
            if ":" in target:
                return (target,) if not rest else ()
            return (f"{target}:{rest.split('.')[0]}",) if rest else ()
        return (f"{rel}:{head}",) if head in module and not rest else ()

    def visit(node, frames):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            qual = f"{frames[0][1]}.{node.name}" if frames else node.name
            inner = [("def", qual, _defaults(node), _locals(node)), *frames]
            for child in node.body:
                visit(child, inner)
            return
        if isinstance(node, ast.ClassDef):
            qual = f"{frames[0][1]}.{node.name}" if frames else node.name
            inner = [("class", qual, {}, {}), *frames]
            for child in node.body:
                visit(child, inner)
            return
        if isinstance(node, ast.JoinedStr):
            text, reads = [], []
            for v in node.values:
                if isinstance(v, ast.FormattedValue):
                    text.append("{}")
                    reads += [(n, resolve(n, frames)) for n in _names(v.value) if ":" in imports.get(n, ":")]
                else:
                    text.append(str(v.value).replace("{}", "{ }"))
            out.append(Quote(rel, node.lineno, frames[0][1] if frames else "<module>", "".join(text), tuple(reads)))
            return
        for child in ast.iter_child_nodes(node):
            visit(child, frames)

    visit(tree, [])
    return out


def all_quotes(root=knobs.REPO) -> list[Quote]:
    """Every f-string in production Python under `root`."""
    from harness import repo
    root = Path(root)
    out = []
    for path in repo.publishable(root):
        rel = path.relative_to(root).as_posix()
        if path.is_file() and knobs._production(rel):
            out += quotes(path.read_text(encoding="utf-8", errors="replace"), rel, root)
    return out


def by_binding(conn, root=knobs.REPO, *, since: float | None = None) -> list[dict]:
    """Per backlog site, its limit_cuts rows and the waiting, skipped or declined verdicts a reason quoting it wrote."""
    backlog = sites(root)
    among = set(backlog)
    found = [(q, q.sites(among), q.pattern()) for q in all_quotes(root)]
    short = sum(1 for _, s, p in found if s and p is None)
    if short:
        from harness import cuts
        cuts.cut("knob_backlog_literal_letters", "reason templates too short to match a stored reason",
                 dropped=short, conn=conn)
    found = [(q, s, p, max(q.text.split("{}"), key=len)) for q, s, p in found if s and p is not None]
    rows = {s: {"site": s, "hits": 0, "tiers": {}, "quotes": [], "example": ""} for s in backlog}
    for q, quoted, _, _ in found:
        for s in quoted:
            rows[s]["quotes"].append(f"{q.rel}:{q.line}")
    sql = f"SELECT tier, detail, until FROM verdicts WHERE outcome NOT IN ({', '.join('?' for _ in PASSED)})"
    params: list = list(PASSED)
    if since is not None:
        sql += " AND decided_at >= ?"
        params.append(since)
    from harness import cuts
    for site, n in cuts.count(conn, since or 0.0).items():
        if site in rows:
            rows[site]["hits"] += n
            rows[site]["tiers"]["cut"] = rows[site]["tiers"].get("cut", 0) + n
    for tier, detail, until in conn.execute(sql, params):
        hit = set()
        for _, quoted, pat, word in found:
            for text in (detail or "", until or ""):
                if word in text and pat.search(text):
                    hit |= quoted
        for s in hit:
            r = rows[s]
            r["hits"] += 1
            r["tiers"][tier] = r["tiers"].get(tier, 0) + 1
            r["example"] = r["example"] or (detail or until or "")[:160]
    return sorted(rows.values(), key=lambda r: (-r["hits"], -len(r["quotes"]), r["site"]))
