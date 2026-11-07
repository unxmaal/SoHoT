"""The test files a change can break, for a pull request's CI run; main, nightly and full-ci run everything (#1567).

python -m tests.gauntlet.scope [--base REF] [--files F ...] [--out FILE]
python -m tests.gauntlet.scope --replay N [--junit FILE]
"""

import argparse
import ast
import functools
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

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
    """({path: paths importing it at module level}, {path: paths importing it in a function or naming it})."""
    mods = {module_name(p): p for p in texts}
    eager, lazy = defaultdict(set), defaultdict(set)
    for path, text in texts.items():
        try:
            tree = ast.parse(text)
            now = imported(text, package_of(path), lazy=False)
            later = imported(text, package_of(path)) - now
        except SyntaxError:
            continue
        words = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
        later |= {m for w in words for m in _DOTTED.findall(w)}
        if "harness.cli" in now | later:
            later |= {"harness.commands." + w.replace("-", "_") for w in words if w.replace("-", "_").isidentifier()}
        for users, names in ((eager, now), (lazy, later)):
            for name in names:
                parts = name.split(".")
                hits = [".".join(parts[:i]) for i in range(1, len(parts) + 1)]
                if path.startswith("tests/"):
                    hits.append("tests." + name)
                for h in hits:
                    dep = mods.get(h)
                    if dep and dep != path:
                        users[dep].add(path)
    return eager, lazy


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


def select(changed, texts, tests, files=(), edges=None):
    """(sorted test files or None for the full suite, why lines)."""
    if not changed:
        return None, ["nothing changed against the base; full suite"]
    for p in changed:
        why = full_reason(p)
        if why:
            return None, [f"{why}; full suite"]
    (eager, lazy), why, seen = edges or graph(texts), [], set()
    for p in sorted(changed):
        seeds, named = {p}, namers(p, texts, files)
        mod = module_name(p) if p.endswith(".py") else ""
        code = p.endswith(".py") and not p.startswith(DATA)
        if code and p not in texts:
            seeds |= {q for q, t in texts.items() if mod in _safe_imported(t, q)}
        if not code and not p.endswith(".md") and not named:
            return None, [f"nothing names {p}; full suite"]
        hit = reach(seeds, eager, lazy, tests, named)
        why.append(f"  {p}: {len(hit)} test files")
        seen |= hit
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


def changed_since(base, root=REPO):
    mb = subprocess.run(["git", "merge-base", base, "HEAD"], cwd=root, capture_output=True, text=True, check=True)
    out = subprocess.run(["git", "diff", "--name-only", "--no-renames", mb.stdout.strip(), "HEAD"], cwd=root,
                         capture_output=True, text=True, check=True).stdout
    return [p for p in out.splitlines() if p]


def suite_seconds(junit):
    """Seconds per test file from a JUnit XML, skipped tests left out."""
    import xml.etree.ElementTree as ET
    secs = defaultdict(float)
    for tc in ET.parse(junit).iter("testcase"):
        if tc.find("skipped") is None:
            secs[tc.get("classname", "").replace(".", "/") + ".py"] += float(tc.get("time") or 0)
    return secs


def replay(prs, texts, tests, files, secs=None):
    """What each merged PR's files would select on today's tree: (number, test files or None, share of suite time)."""
    eager_lazy = graph(texts)
    total = sum((secs or {}).values()) or 1.0
    out = []
    for pr in prs:
        chosen, _ = select([f["path"] for f in pr["files"]], texts, tests, files, eager_lazy)
        share = 1.0 if chosen is None else sum((secs or {}).get(t, 0.0) for t in chosen) / total
        out.append((pr["number"], chosen, share))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m tests.gauntlet.scope", description=__doc__)
    ap.add_argument("--base", default="origin/main", help="diff against the merge base with this ref")
    ap.add_argument("--files", nargs="*", help="changed files, instead of the diff")
    ap.add_argument("--out", type=Path, help="write the selected test files here; removed when the suite is full")
    ap.add_argument("--replay", type=int, help="replay the newest N merged PRs' files against today's tree")
    ap.add_argument("--junit", type=Path, help="with --replay: weigh each selection by this run's per-file seconds")
    a = ap.parse_args(argv)
    if a.replay:
        import json
        prs = json.loads(subprocess.run(["gh", "pr", "list", "-R", "unxmaal/SoHoT", "--state", "merged", "-L",
                                         str(a.replay), "--json", "number,files"], capture_output=True, text=True,
                                        check=True, timeout=300).stdout)
        files = tracked()
        rows = replay(prs, sources(files), {p for p in files if is_test(p)}, files,
                      suite_seconds(a.junit) if a.junit else None)
        for n, chosen, share in rows:
            print(f"#{n}: " + ("full suite" if chosen is None else f"{len(chosen)} test files, {share:.2f} of the time"))
        scoped = sorted(share for _, chosen, share in rows if chosen is not None)
        if scoped:
            print(f"{len(scoped)} of {len(rows)} scoped; median share {scoped[len(scoped) // 2]:.2f}")
        return 0
    changed = a.files if a.files is not None else changed_since(a.base)
    files = sorted(set(tracked()) | {p for p in changed if (REPO / p).is_file()})
    tests = {p for p in files if is_test(p)}
    chosen, why = select(changed, sources(files), tests, files)
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
