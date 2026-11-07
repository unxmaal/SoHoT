"""The test files a change can break, for a pull request's CI run; main, nightly and full-ci run everything (#1567, #1571).

python -m tests.gauntlet.scope [--base REF] [--files F ...] [--map FILE] [--out FILE]
python -m tests.gauntlet.scope --replay N [--junit FILE] [--map FILE]
"""

import argparse
import ast
import functools
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

from tests.gauntlet import covmap
from tests.gauntlet.mutation import REPO, imported

FULL = ("pyproject.toml", "uv.lock", "Makefile", ".python-version")
FULL_UNDER = (".github/workflows/",)
# Repo-wide ratchets: they read every source file, so any change can add a site they guard.
ALWAYS = (
    "tests/test_gauntlet_detectors.py", "tests/test_gauntlet_mutation.py", "tests/test_gauntlet_scanners.py",
    "tests/test_harness_privacy.py", "tests/test_json_everywhere.py", "tests/test_knob_backlog_1085.py",
    "tests/test_knobs.py", "tests/test_limit_trace_1087.py", "tests/test_mcp_import_guard_1221.py",
    "tests/test_module_layout.py", "tests/test_no_drop_column.py", "tests/test_portability.py",
    "tests/test_privacy_names_1308.py", "tests/test_prose_references.py", "tests/test_script_modes.py",
    "tests/test_specs_1363.py", "tests/test_timeouts_classed.py", "tests/test_verdict_reasons.py",
)
# Data trees, not code: never parsed, but a change there is traced by who names it.
DATA = ("evals/cases/", "tests/fixtures/", "tests/golden/")
# Imports every command only to register it: a test reaches one through its verb, not through the hub.
HUBS = ("harness/cli.py",)
_DOTTED = re.compile(r"\b(?:harness|evals|tests|gateway)(?:\.[A-Za-z_]\w*)+")


def module_name(path):
    parts = path[:-3].split("/")
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def package_of(path):
    name = module_name(path)
    return name if path.endswith("__init__.py") else name.rpartition(".")[0]


def full_reason(path):
    if path in FULL or path.startswith(FULL_UNDER) or Path(path).name == "conftest.py":
        return f"{path} changed"
    return ""


def is_test(path):
    return path.startswith("tests/") and Path(path).name.startswith("test_") and path.endswith(".py")


def graph(texts):
    """({path: module-level importers}, {path: function-level importers or namers}, {path: files naming it in a string})."""
    mods = {module_name(p): p for p in texts}
    eager, lazy, said = defaultdict(set), defaultdict(set), defaultdict(set)
    for path, text in texts.items():
        try:
            tree = ast.parse(text)
            now = imported(text, package_of(path), lazy=False)
            later = imported(text, package_of(path)) - now
        except SyntaxError:
            continue
        words = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
        strs = {m for w in words for m in _DOTTED.findall(w)}
        if "harness.cli" in now | later:
            strs |= {"harness.commands." + w.replace("-", "_") for w in words if w.replace("-", "_").isidentifier()}
        later |= strs
        for users, names in ((eager, now), (lazy, later), (said, strs)):
            for name in names:
                parts = name.split(".")
                hits = [".".join(parts[:i]) for i in range(1, len(parts) + 1)]
                if path.startswith("tests/"):
                    hits.append("tests." + name)
                for h in hits:
                    dep = mods.get(h)
                    if dep and dep != path:
                        users[dep].add(path)
    return eager, lazy, said


def reach(seeds, eager, lazy, tests, named=()):
    """Test files reached: module-level importers transitively; a function-level user or a namer and its tests one hop."""
    seen, todo = set(), list(seeds)
    for u in named:
        seen.add(u)
        seen.update(t for t in eager.get(u, set()) | lazy.get(u, set()) if t in tests)
    while todo:
        q = todo.pop()
        if q in seen:
            continue
        seen.add(q)
        if q in HUBS and q not in seeds:
            continue
        todo.extend(eager.get(q, ()))
        for u in lazy.get(q, ()):
            seen.add(u)
            seen.update(t for t in eager.get(u, set()) | lazy.get(u, set()) if t in tests)
    return {q for q in seen if q in tests}


def _naming(word, path, texts):
    pat = re.compile(r"[\"'/]" + re.escape(word) + r"[\"'/]")
    return {p for p, t in texts.items() if p != path and pat.search(t)}


def namers(path, texts, files=()):
    """Sources naming a changed file: by its shortest unique path suffix, its name, else its nearest named directory."""
    parts = path.split("/")
    k = 1
    while k < len(parts) and any(f != path and (f + "/").endswith("/" + "/".join(parts[-k:]) + "/") for f in files):
        k += 1
    words = ["/".join(parts[-k:]), parts[-1]]
    if not path.endswith(".py") or path.startswith(DATA):
        words += reversed(parts[2 if path.startswith(DATA) else 1:-1])
    for w in dict.fromkeys(words):
        found = _naming(w, path, texts)
        if found:
            return found
    return set()


_NONE = ((), ())


def _says(strings, match):
    subs, exact = match
    return any(s in exact or any(x in s for x in subs) for s in strings)


def _uses(f, src, names, texts):
    """A pattern for where file f reads these module-level names of src: bare in src, else through how f imports it."""
    if not names:
        return None
    alt = "|".join(map(re.escape, sorted(names)))
    if f == src:
        return re.compile(rf"\b(?:{alt})\b")
    mod = module_name(src)
    aliases, direct = covmap.spellings(texts[f], mod, package_of(f))
    bare = {local for orig, local in direct if orig in names} | (set(names) if ("*", "*") in direct else set())
    ways = [rf"\b{re.escape(a)}\.(?:{alt})\b" for a in sorted(aliases | {mod})]
    if bare:
        ways.append(r"\b(?:" + "|".join(map(re.escape, sorted(bare))) + r")\b")
    return re.compile("|".join(ways))


def _spread(starts, cmap, texts, tests, edges, stale):
    """(tests, files to trace by import): who uses a name or string; a module-level use passes on the names it binds."""
    eager, lazy, _ = edges
    hit, fall, todo, done = set(), set(), list(starts), set()
    while todo:
        key = todo.pop()
        f, src, names, match = key
        if key in done or f not in texts or Path(f).name == "conftest.py" or not (names or match != _NONE):
            continue
        done.add(key)
        word = _uses(f, src, names, texts)
        lay = covmap.layout(texts[f])
        units = [u for u, body in lay.bodies.items()
                 if (word and word.search(body)) or _says(lay.strings.get(u, ()), match)]
        if not units:
            continue
        if f in tests:
            hit.add(f)
            continue
        if f not in cmap["files"] or f in stale:
            fall.add(f)
            continue
        for u in units:
            if u[0] == "f":
                if u[1] in cmap["files"][f]["import"]:
                    fall.add(f)
                hit |= covmap.tests_of(cmap, f, {u[1]})
                continue
            kind, bound = lay.stmts[u[1]]
            if kind == "opaque":
                fall.add(f)
            elif kind in ("bind", "import"):
                hit |= covmap.tests_of(cmap, f, set(bound) | {covmap.MODULE})
                todo.append((f, f, bound, _NONE))
                if kind == "bind":
                    todo.extend((x, f, bound, _NONE) for x in eager.get(f, set()) | lazy.get(f, set()))
    return hit, fall


def mapped(p, change, cmap, texts, tests, files, edges, stale=frozenset()):
    """(test files the coverage map ties to one file's diff, or None to trace it by import, how)."""
    eager, lazy, said = edges
    old, new, hs = change
    t = covmap.touched(old, new, hs)
    if t.opaque:
        return None, "a module-level statement binding no name changed"
    early = sorted(t.funcs & set(cmap["files"][p]["import"]))
    if early:
        return None, f"{early[0]} runs at import"
    hit = covmap.tests_of(cmap, p, t.funcs | t.names)
    users = eager.get(p, set()) | lazy.get(p, set())
    starts = [(p, p, frozenset(t.names | t.own), _NONE)]
    if t.names:
        starts += [(u, p, frozenset(t.names), _NONE) for u in users]
    # A subprocess runs code coverage cannot see: whoever names the file or module in a string is reached too.
    namers_ = {u for u in said.get(p, set()) | namers(p, texts, files) if Path(u).name != "conftest.py"}
    hit |= namers_ & tests
    verb = (Path(p).stem,) if p.startswith("harness/commands/") else ()
    starts += [(u, p, frozenset(), ((module_name(p), p), verb + tuple(v.replace("_", "-") for v in verb)))
               for u in namers_ - tests]
    got, fall = _spread(starts, cmap, texts, tests, edges, stale)
    for q in stale & (users | said.get(p, set())):
        if q in tests:
            hit.add(q)
        elif q in cmap["files"]:
            hit |= covmap.tests_of(cmap, q)
        else:
            fall.add(q)
    hit |= got
    if fall:
        hit |= reach(fall, eager, lazy, tests)
    return hit, "coverage map"


def select(changed, texts, tests, files=(), edges=None, cmap=None, diff=None, stale=frozenset()):
    """(sorted test files or None for the full suite, why lines); sources a current coverage map has seen go by it."""
    if not changed:
        return None, ["nothing changed against the base; full suite"]
    for p in changed:
        why = full_reason(p)
        if why:
            return None, [f"{why}; full suite"]
    edges = edges or graph(texts)
    (eager, lazy, _), why, seen, traced = edges, [], set(), set()
    for p in sorted(changed):
        seeds, named = {p}, namers(p, texts, files)
        mod = module_name(p) if p.endswith(".py") else ""
        code = p.endswith(".py") and not p.startswith(DATA)
        if code and p not in texts:
            seeds |= {q for q, t in texts.items() if mod in _safe_imported(t, q)}
        if not code and not p.endswith(".md") and not named:
            return None, [f"nothing names {p}; full suite"]
        hit = reach(seeds, eager, lazy, tests, named)
        traced |= hit
        how = ""
        if cmap is not None and code and p in texts and not is_test(p):
            if p not in cmap["files"] or p in stale or p not in (diff or {}):
                how = " (import graph: " + ("changed since the map" if p in stale else
                                             "not in the map" if p not in cmap["files"] else "no diff") + ")"
            else:
                got, how = mapped(p, diff[p], cmap, texts, tests, files, edges, stale)
                hit, how = (hit, f" (import graph: {how})") if got is None else (got | ({p} & tests), f" ({how})")
        why.append(f"  {p}: {len(hit)} test files{how}")
        seen |= hit
    if cmap is not None:
        unseen = (tests - set(cmap["tests"])) | (tests & stale)
        seen |= traced & unseen
    always = {t for t in ALWAYS if t in tests}
    chosen = sorted(seen | always)
    return chosen, why + [f"  always: {len(always)} repo-wide ratchets"]


@functools.cache
def _listed(listing):
    f = Path(listing)
    return frozenset(f.read_text(encoding="utf-8").split()) if f.is_file() else None


def ignored(path, root, listing):
    """Whether pytest skips collecting a test file the listing leaves out; an unreadable listing skips nothing."""
    chosen = _listed(listing)
    path = Path(path)
    if chosen is None or not (path.name.startswith("test_") and path.suffix == ".py"):
        return False
    try:
        rel = path.resolve().relative_to(Path(root).resolve()).as_posix()
    except ValueError:
        return False
    return rel.startswith("tests/") and rel not in chosen


def _safe_imported(text, path):
    try:
        return imported(text, package_of(path))
    except SyntaxError:
        return set()


def tracked(root=REPO):
    out = subprocess.run(["git", "ls-files", "-z"], cwd=root, capture_output=True, text=True, check=True).stdout
    return [p for p in out.split("\0") if p]


def sources(files, root=REPO):
    return {p: (root / p).read_text(encoding="utf-8", errors="replace") for p in files
            if p.endswith(".py") and not p.startswith(DATA) and (root / p).is_file()}


def merge_base(base, root=REPO):
    return subprocess.run(["git", "merge-base", base, "HEAD"], cwd=root, capture_output=True, text=True,
                          check=True).stdout.strip()


def changed_since(base, root=REPO):
    out = subprocess.run(["git", "diff", "--name-only", "--no-renames", merge_base(base, root), "HEAD"], cwd=root,
                         capture_output=True, text=True, check=True).stdout
    return [p for p in out.splitlines() if p]


def _show(ref, path, root):
    got = subprocess.run(["git", "show", f"{ref}:{path}"], cwd=root, capture_output=True, text=True)
    return got.stdout if got.returncode == 0 else ""


def diff_of(paths, old, new=None, root=REPO):
    """{path: (old text, new text, hunks)} for each Python file changed between two refs (new None: the working tree)."""
    paths = [p for p in paths if p.endswith(".py")]
    if not paths:
        return {}
    got = subprocess.run(["git", "diff", "-U0", "--no-renames", old, *([new] if new else []), "--", *paths], cwd=root,
                         capture_output=True, text=True, check=True).stdout
    out = {}
    for p, hs in covmap.hunks(got).items():
        if new:
            after = _show(new, p, root)
        else:
            after = (root / p).read_text(encoding="utf-8", errors="replace") if (root / p).is_file() else ""
        out[p] = (_show(old, p, root), after, hs)
    return out


def suite_seconds(junit):
    """Seconds per test file from a JUnit XML, skipped tests left out."""
    import xml.etree.ElementTree as ET
    secs = defaultdict(float)
    for tc in ET.parse(junit).iter("testcase"):
        if tc.find("skipped") is None:
            secs[tc.get("classname", "").replace(".", "/") + ".py"] += float(tc.get("time") or 0)
    return secs


def replay(prs, texts, tests, files, secs=None, cmap=None, diffs=None):
    """What each merged PR's files would select on today's tree: (number, test files or None, share of suite time)."""
    edges = graph(texts)
    total = sum((secs or {}).values()) or 1.0
    out = []
    for pr in prs:
        chosen, _ = select([f["path"] for f in pr["files"]], texts, tests, files, edges, cmap,
                           (diffs or {}).get(pr["number"]))
        share = 1.0 if chosen is None else sum((secs or {}).get(t, 0.0) for t in chosen) / total
        out.append((pr["number"], chosen, share))
    return out


def median(values):
    v = sorted(values)
    return (v[(len(v) - 1) // 2] + v[len(v) // 2]) / 2 if v else 0.0


def _with_map(path, base, changed):
    """(map, diff, files changed on main since it) when the map at path is current against base, else (None, None, ())."""
    m = covmap.load(path)
    mb = merge_base(base)
    why = covmap.unusable(m, mb)
    if why:
        print(f"coverage map: {why}; tracing by import")
        return None, None, frozenset()
    stale = frozenset(covmap.since(m, mb))
    print(f"coverage map: recorded at {m['commit'][:12]}, {len(stale)} files changed on main since")
    return m, diff_of(changed, mb), stale


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m tests.gauntlet.scope", description=__doc__)
    ap.add_argument("--base", default="origin/main", help="diff against the merge base with this ref")
    ap.add_argument("--files", nargs="*", help="changed files, instead of the diff")
    ap.add_argument("--out", type=Path, help="write the selected test files here; removed when the suite is full")
    ap.add_argument("--map", type=Path, help="choose by this coverage map (tests.gauntlet.covmap) where it is current")
    ap.add_argument("--replay", type=int, help="replay the newest N merged PRs' files against today's tree")
    ap.add_argument("--junit", type=Path, help="with --replay: weigh each selection by this run's per-file seconds")
    a = ap.parse_args(argv)
    if a.replay:
        import json
        prs = json.loads(subprocess.run(["gh", "pr", "list", "-R", "unxmaal/SoHoT", "--state", "merged", "-L",
                                         str(a.replay), "--json", "number,files,mergeCommit"], capture_output=True,
                                        text=True, check=True, timeout=300).stdout)
        files = tracked()
        cmap = covmap.load(a.map) if a.map else None
        diffs = {pr["number"]: diff_of([f["path"] for f in pr["files"]], pr["mergeCommit"]["oid"] + "^",
                                       pr["mergeCommit"]["oid"]) for pr in prs} if cmap else None
        rows = replay(prs, sources(files), {p for p in files if is_test(p)}, files,
                      suite_seconds(a.junit) if a.junit else None, cmap, diffs)
        for n, chosen, share in rows:
            print(f"#{n}: " + ("full suite" if chosen is None else f"{len(chosen)} test files, {share:.2f} of the time"))
        scoped = [share for _, chosen, share in rows if chosen is not None]
        if scoped:
            print(f"{len(scoped)} of {len(rows)} scoped; median share {median(scoped):.2f} scoped, "
                  f"{median([s for _, _, s in rows]):.2f} of all")
        return 0
    changed = a.files if a.files is not None else changed_since(a.base)
    files = sorted(set(tracked()) | {p for p in changed if (REPO / p).is_file()})
    tests = {p for p in files if is_test(p)}
    cmap, diff, stale = _with_map(a.map, a.base, changed) if a.map else (None, None, frozenset())
    chosen, why = select(changed, sources(files), tests, files, None, cmap, diff, stale)
    print(f"changed: {len(changed)} files: {' '.join(changed[:30])}{' ...' if len(changed) > 30 else ''}")
    if chosen is None:
        print("selection: " + why[0])
        if a.out:
            a.out.unlink(missing_ok=True)
        return 0
    print(f"selection: {len(chosen)} of {len(tests)} test files")
    print("\n".join(why))
    if a.out:
        a.out.write_text("".join(t + "\n" for t in chosen), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
