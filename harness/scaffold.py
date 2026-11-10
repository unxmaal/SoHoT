"""New code written together with every registration the make check ratchets ask of it, and the lines they ask for (#1697)."""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

KNOBS_DIR = "harness/knobs"
CAPABILITIES = "openspec/capabilities.yaml"
LAUNCHD = "scripts/launchd.sh"
UNIT_TABLE = "harness/inventory_weight.py"
BACKLOG_DIR = "tests/gauntlet/knob_backlog"
WHY = "<why it gates no outcome>"
PACES = "<why it only paces work and never cuts any>"


class ScaffoldError(ValueError):
    pass


def q(text: str) -> str:
    return json.dumps(text)


def knob_line(name: str, site: str, values, note: str, unit: str = "") -> str:
    """One KNOBS entry of an area module, as the area modules write them."""
    u = f", unit={q(unit)}" if unit else ""
    vals = ", ".join(v if isinstance(v, str) else repr(v) for v in values)
    return f"    _k({q(name)}, [{q(site)}], [{vals}]{u},\n       note={q(note)}),"


def why_line(site: str, why: str) -> str:
    """One NOT_GATING or NEVER_CUTS entry."""
    return f"    {q(site)}: {q(why)},"


def unit_line(unit: str, table: str = "", col: str = "", cond: str = "", words=()) -> str:
    """One harness/inventory_weight.py UNIT_OUTPUTS entry."""
    cond_text = "PORT" if cond == "PORT" else q(cond)
    return f"    {q(unit)}: ({q(table)}, {q(col)}, {cond_text}, ({''.join(q(w) + ', ' for w in words).rstrip(' ')})),"


def module_line(rel: str) -> str:
    return f"      - {rel}"


def site_file(site: str) -> str:
    return site.split(":", 1)[0]


def area_name(site: str) -> str:
    """The area module named after the site's file: harness/x/y.py:N -> y, scripts/serve-a-b.sh:N -> a_b."""
    stem = Path(site_file(site)).stem
    return re.sub(r"\W", "_", stem.removeprefix("serve-")).strip("_") or "misc"


def area_of(site: str) -> str:
    """The area already holding most entries for the site's file, else the one named after it."""
    from harness import knobs
    rel, counts = site_file(site), {}
    for area, mod in knobs.areas().items():
        n = sum(site_file(s) == rel for k in getattr(mod, "KNOBS", []) for s in (k[1] if isinstance(k, tuple) else k).sites)
        n += sum(site_file(s) == rel for t in ("NOT_GATING", "NEVER_CUTS") for s in getattr(mod, t, {}))
        if n:
            counts[area] = n
    return max(sorted(counts), key=counts.get) if counts else area_name(site)


def holder(site: str, table: str) -> str:
    """The area module whose `table` names this site, or "" when none does."""
    from harness import knobs
    return next((a for a, mod in knobs.areas().items() if site in getattr(mod, table, {})), "")


def register_fix(site: str) -> list[str]:
    """What registers an unregistered gating site: the NOT_GATING line, or the KNOBS line and its cut."""
    path = f"{KNOBS_DIR}/{area_of(site)}.py"
    name = re.sub(r"\W+", "_", f"{area_of(site)}_{site.split(':', 1)[1]}").strip("_").lower()
    return [f"if it gates no outcome, add to {path} NOT_GATING:", why_line(site, WHY),
            f"else add to {path} KNOBS (name order) and record a cut where it binds (harness.cuts):",
            knob_line(name, site, ["<value now>", "<other values>"], "<what it limits, and the issue>")]


def trace_fix(site: str, knob: str) -> list[str]:
    path = f"{KNOBS_DIR}/{area_of(site)}.py"
    named = knob or site
    return [f"where it binds: `with cuts.timeout({q(named)}, what):` or `cuts.cut({q(named)}, what, kept=.., dropped=..)`;",
            f"if it only paces work, add to {path} NEVER_CUTS:", why_line(site, PACES)]


# --- editing files -----------------------------------------------------------

def _read(root: Path, rel: str) -> str:
    return (root / rel).read_text(encoding="utf-8")


def _write(root: Path, rel: str, text: str, done: list) -> None:
    (root / rel).parent.mkdir(parents=True, exist_ok=True)
    (root / rel).write_text(text, encoding="utf-8")
    if rel not in done:
        done.append(rel)


def _block(lines: list[str], opener: str, closer: str) -> tuple[int, int] | None:
    """(opening line, closing line) of a top-level `NAME = {` ... `}` block, or None."""
    start = next((i for i, line in enumerate(lines) if line.startswith(opener)), None)
    if start is None:
        return None
    if lines[start].rstrip().endswith(closer):
        lines[start:start + 1] = [lines[start].rstrip()[:-1], closer]
    end = next(i for i in range(start + 1, len(lines)) if lines[i].rstrip() == closer)
    return start, end


def _area_text(area: str, issue: str) -> str:
    return f'"""Knobs of {area.replace("_", " ")} ({issue})."""\n\nKNOBS = []\n'


def add_why(root: Path, area: str, table: str, site: str, why: str, issue: str, done: list) -> str:
    """Add `site: why` to an area's NOT_GATING or NEVER_CUTS, creating the area or the table."""
    rel = f"{KNOBS_DIR}/{area}.py"
    text = _read(root, rel) if (root / rel).exists() else _area_text(area, issue)
    lines = text.splitlines()
    span = _block(lines, f"{table} = {{", "}")
    if span and any(line.strip().startswith(q(site) + ":") for line in lines[span[0]:span[1]]):
        raise ScaffoldError(f"{rel} {table} already names {site}")
    if span is None:
        lines += ["", f"{table} = {{", why_line(site, why), "}"]
    else:
        lines.insert(span[1], why_line(site, why))
    _write(root, rel, "\n".join(lines) + "\n", done)
    return rel


def add_knob(root: Path, area: str, name: str, site: str, values, note: str, unit: str, issue: str,
             done: list) -> str:
    """Add a knob to an area's KNOBS at its place in name order, and take its site out of the knob backlog."""
    rel = f"{KNOBS_DIR}/{area}.py"
    text = _read(root, rel) if (root / rel).exists() else _area_text(area, issue)
    if "from harness.knobs.base import _k" not in text:
        doc = ast.get_docstring(ast.parse(text)) is not None
        lines = text.splitlines()
        at = next((i + 1 for i, line in enumerate(lines) if doc and line.rstrip().endswith('"""')), 0)
        lines.insert(at, "from harness.knobs.base import _k")
        text = "\n".join(lines) + "\n"
    lines = text.splitlines()
    span = _block(lines, "KNOBS = [", "]")
    if span is None:
        raise ScaffoldError(f"{rel} has no KNOBS list")
    start, end = span
    at = end
    for i in range(start + 1, end):
        m = re.match(r'\s+_k\("([^"]+)"', lines[i])
        if m and m[1] == name:
            raise ScaffoldError(f"{rel} already registers {name}")
        if m and m[1] > name:
            at = i
            break
    lines[at:at] = knob_line(name, site, values, note, unit).splitlines()
    _write(root, rel, "\n".join(lines) + "\n", done)
    unbacklog(root, site, done)
    return rel


def unbacklog(root: Path, site: str, done: list) -> None:
    for path in sorted((root / BACKLOG_DIR).glob("*.txt")):
        lines = path.read_text(encoding="utf-8").splitlines()
        if site in lines:
            rel = path.relative_to(root).as_posix()
            kept = [line for line in lines if line != site]
            if kept:
                _write(root, rel, "\n".join(kept) + "\n", done)
            else:
                path.unlink()
                done.append(rel)


def add_to_capability(root: Path, capability: str, rel: str, done: list) -> None:
    lines = _read(root, CAPABILITIES).splitlines()
    start = next((i for i, line in enumerate(lines) if line.strip() == f"- name: {capability}"), None)
    if start is None:
        names = [line.split(":", 1)[1].strip() for line in lines if line.strip().startswith("- name:")]
        raise ScaffoldError(f"no capability {capability!r} in {CAPABILITIES}; one of: {', '.join(names)}")
    i = start + 1
    while i < len(lines) and lines[i].strip() != "modules:" and not lines[i].strip().startswith("- name:"):
        i += 1
    if i == len(lines) or lines[i].strip() != "modules:":
        raise ScaffoldError(f"capability {capability!r} has no modules list")
    i += 1
    while i < len(lines) and lines[i].startswith("      - "):
        i += 1
    lines.insert(i, module_line(rel))
    _write(root, CAPABILITIES, "\n".join(lines) + "\n", done)


def owner(root: Path, rel: str) -> str:
    """The capability holding the module's sibling (harness/x.py for harness/commands/x.py and back), or ""."""
    from harness import specs
    stem = Path(rel).stem
    parent = Path(rel).parent.as_posix()
    near = {f"harness/{stem}.py", f"harness/commands/{stem}.py"} | (
        {f"{parent}/__init__.py"} if parent not in ("harness", "evals", "harness/commands") else set())
    near.discard(rel)
    for c in specs.load_map(root):
        if any(m in near for m in c.get("modules") or []):
            return c["name"]
    return ""


def _issue(issue: str) -> str:
    return f"#{issue.lstrip('#')}" if issue else "#<issue>"


def module(root: Path, rel: str, summary: str, *, capability: str = "", issue: str = "", command: bool = False) -> list[str]:
    """A new harness or evals module in its capability; with command, its `soh` verb registered in harness/cli.py."""
    root, done = Path(root), []
    if not re.fullmatch(r"(harness|evals)/[\w/]+\.py", rel) or rel.startswith("harness/commands/"):
        raise ScaffoldError(f"{rel}: give a module path under harness/ or evals/ (the command module is --command)")
    if (root / rel).exists():
        raise ScaffoldError(f"{rel} exists")
    capability = capability or owner(root, rel)
    if not capability:
        raise ScaffoldError(f"{rel}: name its --capability (openspec/capabilities.yaml)")
    tag = _issue(issue)
    _write(root, rel, f'"""{summary.rstrip(".")} ({tag})."""\nfrom __future__ import annotations\n', done)
    add_to_capability(root, capability, rel, done)
    if command:
        _command(root, rel, summary, capability, tag, done)
    return done


def _command(root: Path, rel: str, summary: str, capability: str, tag: str, done: list) -> None:
    stem = Path(rel).stem
    verb, cmd = stem.replace("_", "-"), f"harness/commands/{stem}.py"
    if (root / cmd).exists():
        raise ScaffoldError(f"{cmd} exists")
    _write(root, cmd, (
        f'"""`soh {verb}`: {summary.rstrip(".")} ({tag})."""\nfrom __future__ import annotations\n\n'
        "from harness.commands.common import emit\n\n\n"
        "def add_parser(sub) -> None:\n"
        f"    p = sub.add_parser({q(verb)}, help={q(summary.rstrip('.'))})\n"
        f"    p.set_defaults(func=cmd_{stem})\n\n\n"
        f"def cmd_{stem}(a) -> int:\n"
        "    emit()\n    return 0\n"), done)
    add_to_capability(root, capability, cmd, done)
    lines = _read(root, "harness/cli.py").splitlines()
    imports = [i for i, line in enumerate(lines) if re.match(r"from harness\.commands import \w+ as \w+_cmd$", line)]
    calls = [i for i, line in enumerate(lines) if re.match(r"    \w+_cmd\.add_parser\(sub\)$", line)]
    if not imports or not calls:
        raise ScaffoldError("harness/cli.py: no `from harness.commands import x as x_cmd` / `x_cmd.add_parser(sub)` lines")
    lines.insert(calls[-1] + 1, f"    {stem}_cmd.add_parser(sub)")
    lines.insert(imports[-1] + 1, f"from harness.commands import {stem} as {stem}_cmd")
    _write(root, "harness/cli.py", "\n".join(lines) + "\n", done)


def _after_imports(text: str) -> int:
    """The line index just past the module's docstring and top-level imports."""
    tree = ast.parse(text)
    last = 0
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)) or (
                isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)):
            last = node.end_lineno
        else:
            break
    return last


def timeout(root: Path, rel: str, name: str, value: float, *, area: str = "", why: str = "", knob: str = "",
            values=(), note: str = "", issue: str = "") -> list[str]:
    """A module constant of seconds, registered: NOT_GATING with `why`, or the knob `knob` (whose cut the caller writes)."""
    from harness import knobs
    root, done = Path(root), []
    if bool(why) == bool(knob):
        raise ScaffoldError("give exactly one of --why (it gates no outcome) or --knob (a registered limit)")
    if not (root / rel).is_file():
        raise ScaffoldError(f"{rel} does not exist")
    text = _read(root, rel)
    if re.search(rf"^{re.escape(name)}\s*=", text, re.M):
        raise ScaffoldError(f"{rel} already sets {name}")
    lines = text.splitlines()
    at = _after_imports(text)
    lines[at:at] = ["", f"{name} = {float(value)!r}"]
    new = "\n".join(lines) + "\n"
    site = f"{rel}:{name}"
    if site not in knobs.gating(new, rel):
        raise ScaffoldError(f"{site} is no inventory site; name it *_S or *TIMEOUT* so the ratchets see it")
    _write(root, rel, new, done)
    area = area or area_of(site)
    tag = _issue(issue)
    if why:
        add_why(root, area, "NOT_GATING", site, f"{why.rstrip('.')} ({tag})", tag, done)
    else:
        vals = sorted({float(value), *map(float, values)})
        add_knob(root, area, knob, site, vals, f"{note.rstrip('.') or 'seconds ' + name} ({tag})", "s", tag, done)
    return done


def unit(root: Path, name: str, hours: str, command: str, summary: str, *, area: str = "", issue: str = "",
         table: str = "", col: str = "", cond: str = "", words=(), scheduler_only: bool = True) -> list[str]:
    """A periodic launchd unit: its serve script, its schedule, its knob and its declared output."""
    from harness import inventory_weight as iw
    root, done = Path(root), []
    if not re.fullmatch(r"[a-z][a-z0-9-]*", name):
        raise ScaffoldError(f"unit name {name!r}: lower case, digits and dashes")
    if not re.fullmatch(r"\d{1,2}( \d{1,2})*", hours.strip()) or any(int(h) > 23 for h in hours.split()):
        raise ScaffoldError(f"hours {hours!r}: local hours 0-23, space separated")
    text = _read(root, LAUNCHD)
    if name in iw.services(text):
        raise ScaffoldError(f"{name} is already a unit")
    words = tuple(words) or (name,)
    tag, var = _issue(issue), name.upper().replace("-", "_") + "_HOURS"
    script = f"scripts/serve-{name}.sh"
    _write(root, script, (
        "#!/usr/bin/env bash\n"
        f"# {summary.rstrip('.')}, then exit. {tag}.\n"
        "set -euo pipefail\n"
        'cd "$(dirname "$0")/.."\n'
        f'echo "=== {name} $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="\n'
        "# After the header, so a refusal is logged under it. #1481.\n"
        "source scripts/env.sh\n"
        f"exec uv run {command}\n"), done)
    (root / script).chmod(0o755)
    lines = text.splitlines()

    def append(pattern: str, close: str) -> None:
        i = next((i for i, line in enumerate(lines) if re.match(pattern, line)), None)
        if i is None:
            raise ScaffoldError(f"{LAUNCHD}: no line matching {pattern}")
        lines[i] = lines[i][:-len(close)] + f" {name}{close}"

    append(r'SERVICES="[^"]*"$', '"')
    append(r"declare -a PERIODIC=\(.*\)$", ")")
    if scheduler_only:
        append(r"declare -a SCHEDULER_ONLY=\(.*\)$", ")")
    sched = max((i for i, line in enumerate(lines) if re.match(r'\s+\[ "\$service" = [\w-]+ \] && hours="\$\w+"$', line)),
                default=None)
    if sched is None:
        raise ScaffoldError(f"{LAUNCHD}: no `[ \"$service\" = x ] && hours=\"$X_HOURS\"` line in _schedule")
    indent = re.match(r"\s*", lines[sched])[0]
    lines.insert(sched + 1, f'{indent}[ "$service" = {name} ] && hours="${var}"')
    at = next(i for i, line in enumerate(lines) if line.startswith("declare -a SCHEDULER_ONLY="))
    while lines[at - 1].startswith("#"):
        at -= 1
    lines[at:at] = [f"# {summary.rstrip('.')}, at these local hours. {tag}.", f'{var}="${{{var}:-{hours.strip()}}}"']
    _write(root, LAUNCHD, "\n".join(lines) + "\n", done)
    site = f"{LAUNCHD}:{var}"
    from harness import knobs
    if site in knobs.shell_defaults(_read(root, LAUNCHD), LAUNCHD):
        area = area or area_name(f"scripts/serve-{name}.sh:X")
        knob = f"{name.replace('-', '_')}_hours"
        add_knob(root, area, knob, site, [int(hours)], f"local hour the {name} unit runs ({tag})", "", tag, done)
        add_why(root, area, "NEVER_CUTS", site, f"the hour the {name} unit starts; a schedule cuts no work ({tag})", tag, done)
    lines = _read(root, UNIT_TABLE).splitlines()
    span = _block(lines, "UNIT_OUTPUTS = {", "}")
    if span is None:
        raise ScaffoldError(f"{UNIT_TABLE}: no UNIT_OUTPUTS table")
    lines.insert(span[1], unit_line(name, table, col, cond, words))
    _write(root, UNIT_TABLE, "\n".join(lines) + "\n", done)
    return done
