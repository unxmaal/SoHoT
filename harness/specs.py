"""Behaviour specs under openspec/: each scenario names a real test or says untested; each module has one capability. #1363."""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
MAP = Path("openspec") / "capabilities.yaml"
SPECS = Path("openspec") / "specs"
STATUSES = ("written", "pending")
UNTESTED = "untested"
_REF = re.compile(r"^(tests/[\w./-]+\.py)::(\w+)(?:::(\w+))?$")
_NORMATIVE = re.compile(r"\b(SHALL|MUST)\b")


@dataclass
class Scenario:
    name: str
    line: int
    when: bool = False
    then: bool = False
    tests: list[tuple[int, str]] = field(default_factory=list)


@dataclass
class Requirement:
    name: str
    line: int
    normative: bool = False
    scenarios: list[Scenario] = field(default_factory=list)


def parse(text: str) -> tuple[bool, list[Requirement]]:
    """(has a ## Requirements section, its requirements in order)."""
    section, reqs, req, sc = False, [], None, None
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if raw.startswith("## ") and not raw.startswith("### "):
            section = line == "## Requirements"
            req = sc = None
        elif raw.startswith("### Requirement:") and section:
            req, sc = Requirement(raw.split(":", 1)[1].strip(), n), None
            reqs.append(req)
        elif raw.startswith("#### Scenario:") and req is not None:
            sc = Scenario(raw.split(":", 1)[1].strip(), n)
            req.scenarios.append(sc)
        elif line.startswith("Test:") and sc is not None:
            sc.tests.append((n, line[len("Test:"):].strip()))
        elif sc is not None:
            sc.when |= line.startswith("- **WHEN**")
            sc.then |= line.startswith("- **THEN**")
        elif req is not None and _NORMATIVE.search(line):
            req.normative = True
    return section, reqs


def _defs(path: Path) -> dict[str, set[str]]:
    """Top-level test names under '', and each class's test methods under its name; read, never imported."""
    out: dict[str, set[str]] = {"": set()}
    for node in ast.parse(path.read_text(encoding="utf-8"), filename=str(path)).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test"):
            out[""].add(node.name)
        elif isinstance(node, ast.ClassDef):
            out[node.name] = {b.name for b in node.body
                              if isinstance(b, (ast.FunctionDef, ast.AsyncFunctionDef)) and b.name.startswith("test")}
    return out


def ref_problem(ref: str, root: Path, cache: dict | None = None) -> str | None:
    """Why `ref` does not name a collected test under root, or None when it does (or says untested)."""
    if ref == UNTESTED:
        return None
    m = _REF.match(ref)
    if not m:
        return f"'{ref}' is not 'tests/<file>.py::<test>' or '{UNTESTED}'"
    rel, first, second = m.groups()
    path = root / rel
    if not path.is_file():
        return f"{ref}: no such file {rel}"
    cache = {} if cache is None else cache
    if rel not in cache:
        cache[rel] = _defs(path)
    defs = cache[rel]
    cls, name = (first, second) if second else ("", first)
    if name not in defs.get(cls, set()):
        return f"{ref}: no such test in {rel}"
    return None


def spec_problems(path: Path, root: Path, cache: dict | None = None) -> list[str]:
    rel = path.relative_to(root).as_posix()
    section, reqs = parse(path.read_text(encoding="utf-8"))
    out = [] if section else [f"{rel}: no '## Requirements' section"]
    for r in reqs:
        where = f"{rel}:{r.line} Requirement '{r.name}'"
        if not r.normative:
            out.append(f"{where}: its text says neither SHALL nor MUST")
        if not r.scenarios:
            out.append(f"{where}: no scenario")
        for s in r.scenarios:
            at = f"{rel}:{s.line} Scenario '{s.name}'"
            for word, has in (("WHEN", s.when), ("THEN", s.then)):
                if not has:
                    out.append(f"{at}: no - **{word}** line")
            if len(s.tests) != 1:
                out.append(f"{at}: needs exactly one Test: line, has {len(s.tests)}")
            for n, ref in s.tests:
                why = ref_problem(ref, root, cache)
                if why:
                    out.append(f"{rel}:{n} {why}")
    return out


def load_map(root: Path) -> list[dict]:
    return (yaml.safe_load((root / MAP).read_text(encoding="utf-8")) or {}).get("capabilities") or []


def trees(root: Path) -> list[str]:
    return (yaml.safe_load((root / MAP).read_text(encoding="utf-8")) or {}).get("trees") or []


def modules(root: Path) -> list[str]:
    return sorted(p.relative_to(root).as_posix() for t in trees(root) for p in (root / t).rglob("*.py")
                  if "__pycache__" not in p.parts)


def _covers(entry: str, mod: str) -> bool:
    return mod.startswith(entry) if entry.endswith("/") else mod == entry


def map_problems(root: Path, caps: list[dict]) -> list[str]:
    out, names = [], [c.get("name", "") for c in caps]
    for name in {n for n in names if names.count(n) > 1}:
        out.append(f"{MAP}: capability '{name}' is listed twice")
    for c in caps:
        name = c.get("name", "")
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name or ""):
            out.append(f"{MAP}: capability name '{name}' is not lower-kebab-case")
        if not (c.get("summary") or "").strip():
            out.append(f"{MAP}: '{name}' has no summary")
        if c.get("spec") not in STATUSES:
            out.append(f"{MAP}: '{name}' spec is '{c.get('spec')}', not one of {', '.join(STATUSES)}")
        exists = (root / SPECS / name / "spec.md").is_file()
        if c.get("spec") == "written" and not exists:
            out.append(f"{MAP}: '{name}' says written but {SPECS / name / 'spec.md'} does not exist")
        if c.get("spec") == "pending" and exists:
            out.append(f"{MAP}: '{name}' says pending but {SPECS / name / 'spec.md'} exists")
    if (root / SPECS).is_dir():
        for d in sorted(p.name for p in (root / SPECS).iterdir() if p.is_dir()):
            if d not in names:
                out.append(f"{SPECS / d}: '{d}' is not in {MAP}")
    mods = modules(root)
    owners: dict[str, list[str]] = {m: [] for m in mods}
    for c in caps:
        for entry in c.get("modules") or []:
            hit = [m for m in mods if _covers(entry, m)]
            if not hit:
                out.append(f"{MAP}: '{c.get('name')}' entry {entry} matches no module")
            for m in hit:
                owners[m].append(c.get("name", ""))
    for m, who in owners.items():
        if not who:
            out.append(f"{m}: in no capability in {MAP}")
        elif len(who) > 1:
            out.append(f"{m}: in more than one capability ({', '.join(who)})")
    return out


def _scenarios(root: Path, name: str) -> list[tuple[Requirement, Scenario]]:
    path = root / SPECS / name / "spec.md"
    if not path.is_file():
        return []
    return [(r, s) for r in parse(path.read_text(encoding="utf-8"))[1] for s in r.scenarios]


def counts(root: Path | None = None) -> list[dict]:
    root = ROOT if root is None else root
    out = []
    for c in load_map(root):
        got = _scenarios(root, c["name"])
        bare = sum(1 for _, s in got if [t for _, t in s.tests] == [UNTESTED])
        out.append({"name": c["name"], "spec": c.get("spec"), "scenarios": len(got),
                    "bound": len(got) - bare, "untested": bare})
    return out


def untested(root: Path | None = None) -> list[tuple[str, str, str]]:
    root = ROOT if root is None else root
    return [(c["name"], r.name, s.name) for c in load_map(root) for r, s in _scenarios(root, c["name"])
            if [t for _, t in s.tests] == [UNTESTED]]


def check(root: Path | None = None) -> list[str]:
    root = ROOT if root is None else root
    caps = load_map(root)
    out = map_problems(root, caps)
    cache: dict = {}
    for c in caps:
        path = root / SPECS / c.get("name", "") / "spec.md"
        if path.is_file():
            out += spec_problems(path, root, cache)
    pinned = {c.get("name"): c.get("untested") for c in caps}
    for row in counts(root):
        if row["spec"] != "written":
            continue
        pin = pinned.get(row["name"])
        if not isinstance(pin, int):
            out.append(f"{MAP}: '{row['name']}' is written but has no untested: count")
        elif row["untested"] > pin:
            out.append(f"{MAP}: '{row['name']}' has {row['untested']} untested scenarios, pinned at {pin}; "
                       "bind a test rather than add an untested one")
        elif row["untested"] < pin:
            out.append(f"{MAP}: '{row['name']}' has {row['untested']} untested scenarios; lower its pin from {pin}")
    return out


def main() -> int:
    got = check()
    for p in got:
        print(p)
    print(f"specs: {len(got)} problems" if got else "specs ok")
    return 1 if got else 0


if __name__ == "__main__":
    raise SystemExit(main())
