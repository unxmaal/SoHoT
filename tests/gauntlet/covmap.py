"""Which test files execute each function, recorded by a coverage run on main, for choosing a pull request's tests (#1571).

python -m tests.gauntlet.covmap build [--data .coverage] [--out FILE] [--commit SHA]
python -m tests.gauntlet.covmap fetch --out FILE [--repo OWNER/NAME]
"""

import argparse
import ast
import functools
import io
import json
import os
import re
import subprocess
import sys
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
VERSION = 1
ARTIFACT = "coverage-map"
FILE = "coverage-map.json"
# The nightly makes one a day; older than this and main has moved too far for its call edges to hold.
MAX_AGE_DAYS = 3
#: Set by the run that records the map: each test starts with empty function caches, so its coverage is its own.
ENV = "SOHOT_COVERAGE_MAP"
MODULE = "<module>"
_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", re.M)


@dataclass(frozen=True)
class Layout:
    unit: dict          # line -> ("f", qualname) for a function body, ("s", index) for a module-level statement
    stmts: tuple        # per module-level statement: (kind, bound names); kind bind|import|opaque|doc|main
    bodies: dict        # unit -> its source lines joined
    strings: dict       # unit -> the string constants written in it


def _bound(stmt):
    """(names a module-level statement binds, whether every one comes from an import)."""
    if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return {stmt.name}, False
    names, imports = set(), set()
    loops = {id(x) for n in ast.walk(stmt) if isinstance(n, (ast.For, ast.AsyncFor, ast.comprehension))
             for x in ast.walk(n.target)}
    for n in ast.walk(stmt):
        if id(n) in loops:
            continue
        if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
            names.add(n.id)
        elif (isinstance(n, (ast.Subscript, ast.Attribute)) and isinstance(n.ctx, (ast.Store, ast.Del))) or (
                isinstance(n, ast.Expr) and isinstance(n.value, ast.Call) and isinstance(n.value.func, ast.Attribute)):
            base = n.value.func if isinstance(n, ast.Expr) else n
            while isinstance(base, (ast.Subscript, ast.Attribute)):
                base = base.value
            if isinstance(base, ast.Name):
                names.add(base.id)
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(n.name)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            imports |= {(a.asname or a.name).split(".")[0] for a in n.names if a.name != "*"}
    return names | imports, bool(imports) and not names


def _kind(stmt, names, only_imports):
    if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
        return "doc"
    if (isinstance(stmt, ast.If) and isinstance(stmt.test, ast.Compare)
            and isinstance(stmt.test.left, ast.Name) and stmt.test.left.id == "__name__"):
        return "main"
    if not names:
        return "opaque"
    return "import" if only_imports else "bind"


@functools.lru_cache(maxsize=4096)
def layout(text):
    """Each line's innermost function body, else its module-level statement; a file that does not parse has none."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return Layout({}, (), {}, {})
    unit, stmts = {}, []
    for i, stmt in enumerate(tree.body):
        start = min([stmt.lineno] + [d.lineno for d in getattr(stmt, "decorator_list", ())])
        for line in range(start, stmt.end_lineno + 1):
            unit[line] = ("s", i)
        names, only = _bound(stmt)
        stmts.append((_kind(stmt, names, only), frozenset(names)))

    def walk(node, prefix):
        for n in ast.iter_child_nodes(node):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                q = prefix + n.name
                for line in range(n.body[0].lineno, n.end_lineno + 1):
                    unit[line] = ("f", q)
                walk(n, q + ".")
            elif isinstance(n, ast.ClassDef):
                walk(n, prefix + n.name + ".")
            elif isinstance(n, ast.stmt):
                walk(n, prefix)
    walk(tree, "")
    lines = text.splitlines()
    bodies = defaultdict(list)
    for line, u in unit.items():
        if line <= len(lines):
            bodies[u].append(lines[line - 1])
    strings = defaultdict(set)
    for n in ast.walk(tree):
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and unit.get(n.lineno):
            strings[unit[n.lineno]].add(n.value)
    return Layout(unit, tuple(stmts), {u: "\n".join(b) for u, b in bodies.items()},
                  {u: frozenset(s) for u, s in strings.items()})


@functools.lru_cache(maxsize=65536)
def spellings(text, module, package=""):
    """(names a file reads module through, (name, local name) pairs it imports from module) by its imports."""
    aliases, direct = set(), set()
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return frozenset(), frozenset()
    parent, _, leaf = module.rpartition(".")
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            aliases.update(a.asname or module for a in n.names if a.name == module)
        elif isinstance(n, ast.ImportFrom):
            base = n.module or ""
            if n.level:
                up = package.split(".")[:len(package.split(".")) - n.level + 1] if package else []
                base = ".".join(up + ([n.module] if n.module else []))
            for a in n.names:
                if base == module:
                    direct.add((a.name, a.asname or a.name))
                elif base == parent and a.name == leaf:
                    aliases.add(a.asname or leaf)
    return frozenset(aliases), frozenset(direct)


@dataclass
class Touched:
    funcs: set
    names: set          # rebound at module level: reach every file that uses them
    own: set            # rebound only by an import: reach this file's own uses
    opaque: bool        # a module-level statement that binds nothing changed


def touched(old, new, hunks):
    """What a diff changes in one Python file, from both sides of each hunk: function bodies and module-level names."""
    out = Touched(set(), set(), set(), False)
    for text, side in ((old, 0), (new, 1)):
        lay = layout(text)
        for h in hunks:
            start, count = h[2 * side], h[2 * side + 1]
            for line in range(start, start + count):
                u = lay.unit.get(line)
                if u is None:
                    continue
                if u[0] == "f":
                    out.funcs.add(u[1])
                    continue
                kind, names = lay.stmts[u[1]]
                if kind == "opaque":
                    out.opaque = True
                elif kind == "bind":
                    out.names |= names
                elif kind == "import":
                    out.own |= names
    return out


def hunks(diff):
    """{path: [(old start, old count, new start, new count)]} from `git diff -U0` output."""
    out, path = {}, None
    for line in diff.splitlines():
        if line.startswith("diff --git "):
            path = line.split(" b/", 1)[1] if " b/" in line else None
            if path is not None:
                out.setdefault(path, [])
        elif path is not None and line.startswith("@@"):
            m = _HUNK.match(line)
            if m:
                out[path].append((int(m[1]), 1 if m[2] is None else int(m[2]), int(m[3]), 1 if m[4] is None else int(m[4])))
    return out


def _test_file(context):
    head = context.split("::", 1)[0]
    return head if head.startswith("tests/") and head.endswith(".py") else None


def build(data_file, root, commit):
    """The map from a coverage data file recorded with per-test contexts (pytest --cov-context=test)."""
    import coverage
    data = coverage.CoverageData(str(data_file))
    data.read()
    root = Path(root).resolve()
    index, files = {}, {}
    for measured in sorted(data.measured_files()):
        try:
            rel = Path(measured).resolve().relative_to(root).as_posix()
        except ValueError:
            continue
        path = root / rel
        if not path.is_file() or Path(rel).name.startswith("test_"):
            continue
        lay = layout(path.read_text(encoding="utf-8", errors="replace"))
        funcs, at_import = defaultdict(set), set()
        for line, contexts in (data.contexts_by_lineno(measured) or {}).items():
            u = lay.unit.get(line)
            q = u[1] if u and u[0] == "f" else MODULE
            for c in contexts:
                t = _test_file(c) if c else None
                if t is None:
                    if not c and q != MODULE:
                        at_import.add(q)
                    continue
                funcs[q].add(index.setdefault(t, len(index)))
        files[rel] = {"f": {q: sorted(ix) for q, ix in sorted(funcs.items())}, "import": sorted(at_import)}
    for c in data.measured_contexts():
        t = _test_file(c)
        if t is not None:
            index.setdefault(t, len(index))
    return {"version": VERSION, "commit": commit, "tests": [t for t, _ in sorted(index.items(), key=lambda kv: kv[1])],
            "files": files}


def load(path):
    """The map at path, or None when it is missing, unreadable or another format."""
    try:
        m = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(m, dict) or m.get("version") != VERSION:
        return None
    return m


def tests_of(m, path, quals=None):
    """Test files the map saw execute any of these functions of path (all of them for None); a class covers its methods."""
    entry = m["files"].get(path, {}).get("f", {})
    names = m["tests"]
    out = set()
    for q, ix in entry.items():
        if quals is None or q in quals or any(q.startswith(c + ".") for c in quals):
            out.update(names[i] for i in ix)
    return out


def _git(root, *args):
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=120)


def unusable(m, base, root=REPO):
    """Why the map cannot choose tests against base ("" when it can): missing, off this history, or too old."""
    if m is None:
        return "no coverage map"
    commit = m.get("commit") or ""
    if _git(root, "cat-file", "-e", f"{commit}^{{commit}}").returncode:
        return f"coverage map commit {commit[:12]} is not in this clone"
    if _git(root, "merge-base", "--is-ancestor", commit, base).returncode:
        return f"coverage map commit {commit[:12]} is not an ancestor of {base}"
    times = _git(root, "show", "-s", "--format=%ct", commit, base).stdout.split()
    age = (int(times[1]) - int(times[0])) / 86400 if len(times) == 2 else float("inf")
    if age > MAX_AGE_DAYS:
        return f"coverage map is {age:.1f} days older than {base}"
    return ""


def since(m, base, root=REPO):
    """Files changed between the map's commit and base: their recorded call edges may be out of date."""
    out = _git(root, "diff", "--name-only", "--no-renames", m["commit"], base)
    return {p for p in out.stdout.splitlines() if p}


def choose(artifacts):
    """The newest unexpired coverage-map artifact a run on main uploaded, or None."""
    ok = [a for a in artifacts if a.get("name") == ARTIFACT and not a.get("expired")
          and (a.get("workflow_run") or {}).get("head_branch") == "main"]
    return max(ok, key=lambda a: (a.get("created_at") or "", a.get("id") or 0), default=None)


def _gh(args, binary=False):
    got = subprocess.run(["gh", *args], capture_output=True, timeout=300)
    if got.returncode:
        raise RuntimeError(f"gh {' '.join(args[:2])}: {got.stderr.decode(errors='replace').strip()[:300]}")
    return got.stdout if binary else got.stdout.decode()


def fetch(out, repo, gh=_gh):
    """Download the newest coverage map main recorded to out; returns the artifact's commit."""
    listing = json.loads(gh(["api", f"repos/{repo}/actions/artifacts?name={ARTIFACT}&per_page=100"]))
    art = choose(listing.get("artifacts", []))
    if art is None:
        raise RuntimeError(f"no unexpired {ARTIFACT} artifact from main")
    blob = gh(["api", f"repos/{repo}/actions/artifacts/{art['id']}/zip"], binary=True)
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        Path(out).write_bytes(z.read(FILE))
    return (art.get("workflow_run") or {}).get("head_sha", "")


_seen: dict = {}


def clear_caches(prefixes=("harness", "evals", "gateway", "tests")):
    """Empty every functools cache in the repo's loaded modules, so a test's coverage does not hang on an earlier test's."""
    if _seen.get("n") != len(sys.modules):
        found = []
        for name, mod in list(sys.modules.items()):
            if name.split(".")[0] not in prefixes or mod is None:
                continue
            for value in list(vars(mod).values()):
                for v in [value, *(vars(value).values() if isinstance(value, type) else ())]:
                    if callable(getattr(v, "cache_clear", None)) and hasattr(v, "cache_info"):
                        found.append(v)
        _seen.update(n=len(sys.modules), found=found)
    for f in _seen["found"]:
        f.cache_clear()


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m tests.gauntlet.covmap", description=__doc__)
    sub = ap.add_subparsers(dest="verb", required=True)
    b = sub.add_parser("build", help="reduce a coverage data file with per-test contexts to the map")
    b.add_argument("--data", type=Path, default=Path(".coverage"))
    b.add_argument("--out", type=Path, default=Path(FILE))
    b.add_argument("--commit", default="", help="the commit the data was recorded at (default HEAD)")
    f = sub.add_parser("fetch", help="download the newest map main recorded")
    f.add_argument("--out", type=Path, required=True)
    f.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", "unxmaal/SoHoT"))
    a = ap.parse_args(argv)
    if a.verb == "build":
        commit = a.commit or _git(REPO, "rev-parse", "HEAD").stdout.strip()
        m = build(a.data, REPO, commit)
        a.out.write_text(json.dumps(m, separators=(",", ":"), sort_keys=True), encoding="utf-8")
        print(f"coverage map at {commit[:12]}: {len(m['tests'])} test files, {len(m['files'])} source files")
        return 0
    sha = fetch(a.out, a.repo)
    print(f"coverage map fetched: recorded at {sha[:12]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
