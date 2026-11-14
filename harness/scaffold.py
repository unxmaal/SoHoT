"""New code written together with every registration the make check ratchets ask of it, and the lines they ask for (#1697)."""
from __future__ import annotations

import ast
import json
import math
import re
import stat
from pathlib import Path

from harness import atomic_file, stale_temp

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


class Plan(list):
    """The files one scaffold run writes, by first touch, held until every check has passed and then written together."""

    def __init__(self, root):
        super().__init__()
        self.root, self.text, self.modes = Path(root), {}, {}

    def exists(self, rel: str) -> bool:
        return self.text[rel] is not None if rel in self.text else (self.root / rel).exists()

    def read(self, rel: str) -> str:
        if rel in self.text:
            if self.text[rel] is None:
                raise ScaffoldError(f"{rel} is removed by this scaffold")
            return self.text[rel]
        return _read(self.root, rel)

    def write(self, rel: str, text: str, mode: int | None = None) -> None:
        self.text[rel] = text
        if mode is not None:
            self.modes[rel] = mode
        if rel not in self:
            self.append(rel)

    def remove(self, rel: str) -> None:
        self.text[rel] = None
        if rel not in self:
            self.append(rel)

    def commit(self) -> list[str]:
        """Write every file; on any failure put back what was there, remove what was not, and raise."""
        undo, made = [], []
        try:
            for rel in self:
                path = self.root / rel
                old = (path.read_bytes(), stat.S_IMODE(path.stat().st_mode)) if path.is_file() else None
                undo.append((path, old))
                if self.text[rel] is None:
                    path.unlink(missing_ok=True)
                    continue
                for d in reversed([p for p in path.parents if not p.exists()]):
                    d.mkdir()
                    made.append(d)
                _put(path, self.text[rel].encode("utf-8"), self.modes.get(rel, old[1] if old else None))
        except BaseException as exc:
            lost = []
            for path, old in reversed(undo):
                try:
                    if old is None:
                        path.unlink(missing_ok=True)
                    elif not path.is_file() or path.read_bytes() != old[0]:
                        _put(path, *old)
                except OSError as why:
                    lost.append(f"{path.relative_to(self.root).as_posix()} ({why})")
            for d in reversed(made):
                if d.is_dir() and not any(d.iterdir()):
                    d.rmdir()
            if lost:
                raise ScaffoldError(f"the scaffold failed ({exc}) and could not put back: {', '.join(lost)}") from exc
            raise
        return list(self)


def _put(path: Path, data: bytes, mode: int | None) -> None:
    tmp = stale_temp.temp(path, ".{name}.{pid}.{thread}.scaffold")
    try:
        tmp.write_bytes(data)
        if mode is not None:
            tmp.chmod(mode)
        atomic_file.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _plan(root: Path, done: list) -> Plan:
    return done if isinstance(done, Plan) else Plan(root)


def _finish(plan: Plan, done: list) -> None:
    """A helper handed a plain list writes its own plan at once."""
    if plan is not done:
        done.extend(rel for rel in plan.commit() if rel not in done)


# --- checking inputs ---------------------------------------------------------

def _check(pattern: str, value: str, what: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(pattern, value):
        raise ScaffoldError(f"{what} {value!r}: does not match {pattern}")
    return value


def _check_area(area: str) -> str:
    if area == "base":
        raise ScaffoldError("area 'base' is the registry's own module, not an area")
    return _check(r"[a-z][a-z0-9_]*", area, "area")


def _check_line(text: str, what: str) -> str:
    if not text.strip() or "\n" in text or '"""' in text:
        raise ScaffoldError(f"{what} {text!r}: one non-empty line, no triple quotes")
    return text


def numbers(text, what: str, *, required: bool = False) -> list:
    """Comma-separated ints and floats, each finite; ScaffoldError on anything else."""
    parts = [v.strip() for v in text.split(",") if v.strip()] if isinstance(text, str) else list(text)
    try:
        got = [v if not isinstance(v, str) else int(v) if v.lstrip("-").isdigit() else float(v) for v in parts]
    except ValueError:
        raise ScaffoldError(f"{what} {text!r}: comma-separated numbers") from None
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in got):
        raise ScaffoldError(f"{what} {text!r}: finite numbers only")
    if required and not got:
        raise ScaffoldError(f"{what}: give at least one value")
    return got


def _bare(text: str, tag: str) -> str:
    """The text without a trailing period or a trailing copy of the issue tag it is about to be given."""
    text = text.strip().rstrip(".").rstrip()
    return re.sub(rf"\s*\(?{re.escape(tag)}\)?$", "", text).rstrip(" .,;") or text


def _cited(text: str, tag: str) -> str:
    return f"{_bare(text, tag)} ({tag})"


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
    plan = _plan(root, done)
    rel = f"{KNOBS_DIR}/{_check_area(area)}.py"
    _check(r'[^:\s"]+:[^\n"]+', site, "site")
    _check_line(why, "why")
    text = plan.read(rel) if plan.exists(rel) else _area_text(area, issue)
    lines = text.splitlines()
    span = _block(lines, f"{table} = {{", "}")
    if span and any(line.strip().startswith(q(site) + ":") for line in lines[span[0]:span[1]]):
        raise ScaffoldError(f"{rel} {table} already names {site}")
    if span is None:
        lines += ["", f"{table} = {{", why_line(site, why), "}"]
    else:
        lines.insert(span[1], why_line(site, why))
    plan.write(rel, "\n".join(lines) + "\n")
    _finish(plan, done)
    return rel


def add_knob(root: Path, area: str, name: str, site: str, values, note: str, unit: str, issue: str,
             done: list) -> str:
    """Add a knob to an area's KNOBS at its place in name order, and take its site out of the knob backlog."""
    plan = _plan(root, done)
    rel = f"{KNOBS_DIR}/{_check_area(area)}.py"
    _check(r"[a-z][a-z0-9_]*", name, "knob name")
    _check(r'[^:\s"]+:[^\n"]+', site, "site")
    _check_line(note, "note")
    values = numbers(values, "values", required=True)
    text = plan.read(rel) if plan.exists(rel) else _area_text(area, issue)
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
    plan.write(rel, "\n".join(lines) + "\n")
    unbacklog(root, site, plan)
    _finish(plan, done)
    return rel


def unbacklog(root: Path, site: str, done: list) -> None:
    plan = _plan(root, done)
    for path in sorted((Path(root) / BACKLOG_DIR).glob("*.txt")):
        rel = path.relative_to(root).as_posix()
        if not plan.exists(rel):
            continue
        lines = plan.read(rel).splitlines()
        if site in lines:
            kept = [line for line in lines if line != site]
            if kept:
                plan.write(rel, "\n".join(kept) + "\n")
            else:
                plan.remove(rel)
    _finish(plan, done)


def add_to_capability(root: Path, capability: str, rel: str, done: list) -> None:
    plan = _plan(root, done)
    lines = plan.read(CAPABILITIES).splitlines()
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
    plan.write(CAPABILITIES, "\n".join(lines) + "\n")
    _finish(plan, done)


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
    root = Path(root)
    if not re.fullmatch(r"(harness|evals)/[\w/]+\.py", rel) or rel.startswith("harness/commands/"):
        raise ScaffoldError(f"{rel}: give a module path under harness/ or evals/ (the command module is --command)")
    _check_line(summary, "summary")
    plan = Plan(root)
    if plan.exists(rel):
        raise ScaffoldError(f"{rel} exists")
    capability = capability or owner(root, rel)
    if not capability:
        raise ScaffoldError(f"{rel}: name its --capability (openspec/capabilities.yaml)")
    tag = _issue(issue)
    plan.write(rel, f'"""{_cited(summary, tag)}."""\nfrom __future__ import annotations\n')
    add_to_capability(root, capability, rel, plan)
    if command:
        _command(root, rel, summary, capability, tag, plan)
    return plan.commit()


def _command(root: Path, rel: str, summary: str, capability: str, tag: str, plan: Plan) -> None:
    stem = Path(rel).stem
    verb, cmd = stem.replace("_", "-"), f"harness/commands/{stem}.py"
    if not stem.isidentifier():
        raise ScaffoldError(f"{rel}: a command module's name must be a Python identifier")
    if plan.exists(cmd):
        raise ScaffoldError(f"{cmd} exists")
    for other in sorted((root / "harness/commands").glob("*.py")):
        if re.search(rf"\bsub\.add_parser\(\s*{re.escape(q(verb))}", other.read_text(encoding="utf-8")):
            raise ScaffoldError(f"soh {verb} is already a verb ({other.relative_to(root).as_posix()})")
    plan.write(cmd, (
        f'"""`soh {verb}`: {_cited(summary, tag)}."""\nfrom __future__ import annotations\n\n'
        "from harness.commands.common import emit\n\n\n"
        "def add_parser(sub) -> None:\n"
        f"    p = sub.add_parser({q(verb)}, help={q(_bare(summary, tag))})\n"
        f"    p.set_defaults(func=cmd_{stem})\n\n\n"
        f"def cmd_{stem}(a) -> int:\n"
        "    emit()\n    return 0\n"))
    add_to_capability(root, capability, cmd, plan)
    lines = plan.read("harness/cli.py").splitlines()
    if any(re.match(rf"from harness\.commands import {stem} as ", line) for line in lines):
        raise ScaffoldError(f"harness/cli.py already imports harness.commands.{stem}")
    imports = [i for i, line in enumerate(lines) if re.match(r"from harness\.commands import \w+ as \w+_cmd$", line)]
    calls = [i for i, line in enumerate(lines) if re.match(r"    \w+_cmd\.add_parser\(sub\)$", line)]
    if not imports or not calls:
        raise ScaffoldError("harness/cli.py: no `from harness.commands import x as x_cmd` / `x_cmd.add_parser(sub)` lines")
    lines.insert(calls[-1] + 1, f"    {stem}_cmd.add_parser(sub)")
    lines.insert(imports[-1] + 1, f"from harness.commands import {stem} as {stem}_cmd")
    plan.write("harness/cli.py", "\n".join(lines) + "\n")


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
    root = Path(root)
    if bool(why) == bool(knob):
        raise ScaffoldError("give exactly one of --why (it gates no outcome) or --knob (a registered limit)")
    _check(r"[A-Za-z_]\w*", name, "constant")
    seconds = numbers([value], "seconds") + numbers(values, "values")
    if any(s <= 0 for s in seconds):
        raise ScaffoldError(f"seconds {seconds}: each above 0")
    if knob:
        _check(r"[a-z][a-z0-9_]*", knob, "knob name")
    if not re.fullmatch(r"[\w./-]+\.py", rel) or ".." in rel.split("/") or not (root / rel).is_file():
        raise ScaffoldError(f"{rel} does not exist")
    plan = Plan(root)
    text = plan.read(rel)
    if re.search(rf"^{re.escape(name)}\s*=", text, re.M):
        raise ScaffoldError(f"{rel} already sets {name}")
    lines = text.splitlines()
    at = _after_imports(text)
    lines[at:at] = ["", f"{name} = {float(value)!r}"]
    new = "\n".join(lines) + "\n"
    site = f"{rel}:{name}"
    if site not in knobs.gating(new, rel):
        raise ScaffoldError(f"{site} is no inventory site; name it *_S or *TIMEOUT* so the ratchets see it")
    plan.write(rel, new)
    area = area or area_of(site)
    tag = _issue(issue)
    if why:
        add_why(root, area, "NOT_GATING", site, _cited(why, tag), tag, plan)
    else:
        vals = sorted({float(s) for s in seconds})
        add_knob(root, area, knob, site, vals, _cited(note or f"seconds {name}", tag), "s", tag, plan)
    return plan.commit()


def unit(root: Path, name: str, hours: str, command: str, summary: str, *, area: str = "", issue: str = "",
         table: str = "", col: str = "", cond: str = "", words=(), scheduler_only: bool = True) -> list[str]:
    """A periodic launchd unit: its serve script, its schedule, its knob and its declared output."""
    from harness import inventory_weight as iw
    root = Path(root)
    if not re.fullmatch(r"[a-z][a-z0-9-]*", name):
        raise ScaffoldError(f"unit name {name!r}: lower case, digits and dashes")
    if not re.fullmatch(r"\d{1,2}( \d{1,2})*", hours.strip()) or any(int(h) > 23 for h in hours.split()):
        raise ScaffoldError(f"hours {hours!r}: local hours 0-23, space separated")
    _check_line(summary, "summary")
    _check_line(command, "command")
    for value, what in ((table, "table"), (col, "time column")):
        if value:
            _check(r"[A-Za-z_]\w*", value, what)
    if area:
        _check_area(area)
    if any(not isinstance(w, str) or not w.strip() for w in words):
        raise ScaffoldError(f"words {words!r}: each a non-empty word")
    plan = Plan(root)
    text = plan.read(LAUNCHD)
    if name in iw.services(text):
        raise ScaffoldError(f"{name} is already a unit")
    words = tuple(words) or (name,)
    tag, var = _issue(issue), name.upper().replace("-", "_") + "_HOURS"
    if re.search(rf"^{var}=", text, re.M):
        raise ScaffoldError(f"{LAUNCHD} already sets {var}")
    script = f"scripts/serve-{name}.sh"
    if plan.exists(script):
        raise ScaffoldError(f"{script} exists")
    plan.write(script, (
        "#!/usr/bin/env bash\n"
        f"# {_bare(summary, tag)}, then exit. {tag}.\n"
        "set -euo pipefail\n"
        'cd "$(dirname "$0")/.."\n'
        f'echo "=== {name} $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="\n'
        "# After the header, so a refusal is logged under it. #1481.\n"
        "source scripts/env.sh\n"
        f"exec uv run {command}\n"), mode=0o755)
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
    lines[at:at] = [f"# {_bare(summary, tag)}, at these local hours. {tag}.", f'{var}="${{{var}:-{hours.strip()}}}"']
    plan.write(LAUNCHD, "\n".join(lines) + "\n")
    site = f"{LAUNCHD}:{var}"
    from harness import knobs
    if site in knobs.shell_defaults(plan.read(LAUNCHD), LAUNCHD):
        area = area or area_name(f"scripts/serve-{name}.sh:X")
        knob = f"{name.replace('-', '_')}_hours"
        add_knob(root, area, knob, site, [int(hours)], f"local hour the {name} unit runs ({tag})", "", tag, plan)
        add_why(root, area, "NEVER_CUTS", site, f"the hour the {name} unit starts; a schedule cuts no work ({tag})", tag, plan)
    lines = plan.read(UNIT_TABLE).splitlines()
    span = _block(lines, "UNIT_OUTPUTS = {", "}")
    if span is None:
        raise ScaffoldError(f"{UNIT_TABLE}: no UNIT_OUTPUTS table")
    lines.insert(span[1], unit_line(name, table, col, cond, words))
    plan.write(UNIT_TABLE, "\n".join(lines) + "\n")
    return plan.commit()


def scaffold_knob(root: Path, name: str, site: str, values, note: str, *, unit: str = "", area: str = "", issue: str = "") -> list[str]:
    """A gating site registered as a knob in its area, checked whole before any file is written."""
    plan, tag = Plan(root), _issue(issue)
    _check(r'[^:\s"]+:[^\n"]+', site, "site")
    _check_line(note, "note")
    add_knob(root, _check_area(area) if area else area_of(site), name, site, numbers(values, "values", required=True),
             _cited(note, tag), unit, tag, plan)
    return plan.commit()


def scaffold_not_gating(root: Path, site: str, why: str, *, area: str = "", issue: str = "") -> list[str]:
    """Why a site gates no outcome, in its area's NOT_GATING."""
    plan, tag = Plan(root), _issue(issue)
    _check(r'[^:\s"]+:[^\n"]+', site, "site")
    _check_line(why, "why")
    add_why(root, _check_area(area) if area else area_of(site), "NOT_GATING", site, _cited(why, tag), tag, plan)
    return plan.commit()
