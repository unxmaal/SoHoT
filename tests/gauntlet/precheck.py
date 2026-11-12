"""`make precheck`: only the registration ratchets of make check, each failure with the line that fixes it (#1697)."""
from __future__ import annotations

import ast
import os
import sys
import time
from collections import namedtuple
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from harness import scaffold

REPO = Path(__file__).resolve().parent.parent.parent

Problem = namedtuple("Problem", "ratchet subject fix")


def _p(ratchet: str, subject: str, *fix: str) -> Problem:
    return Problem(ratchet, subject, list(fix))


def pinned(root, rel: str, name: str):
    """A literal a test module pins at top level, read without importing the test (its imports need pytest's path)."""
    tree = ast.parse((Path(root) / rel).read_text(encoding="utf-8"))
    for node in tree.body:
        target = node.target if isinstance(node, ast.AnnAssign) else (node.targets[0] if isinstance(node, ast.Assign) else None)
        if isinstance(target, ast.Name) and target.id == name and node.value is not None:
            return ast.literal_eval(node.value)
    raise KeyError(f"{rel} pins no {name}")


def knob_sites(root=REPO) -> list[Problem]:
    """tests/test_knobs.py test_no_new_gating_constant_is_unregistered and the sensitivity inventory count."""
    from harness import knob_backlog, knobs
    new = sorted(set(knobs.unregistered(knobs.inventory(root))) - set(knob_backlog.sites(root)))
    return [_p("knobs", f"{s} gates an outcome and is not registered", *scaffold.register_fix(s)) for s in new]


def knob_backlog_lines(root=REPO) -> list[Problem]:
    """tests/test_knobs.py: the knob backlog only shrinks, and no site joins it against origin/main."""
    from harness import knob_backlog, knobs
    found = set(knobs.unregistered(knobs.inventory(root)))
    out = [_p("knob backlog", f"{s} is registered or gone",
              f"delete this line from {knob_backlog.DIR}/{_backlog_file(s)}: {s}")
           for s in sorted(set(knob_backlog.sites(root)) - found)]
    for s in knob_backlog.added(root) or []:
        out.append(_p("knob backlog", f"{s} joined the backlog, which is closed to additions (#1085)",
                      f"delete this line from {knob_backlog.DIR}/{_backlog_file(s)}: {s}", *scaffold.register_fix(s)))
    return out


def _backlog_file(site: str) -> str:
    return site.split(":", 1)[0].rsplit("/", 1)[0].replace("/", "_") + ".txt"


def knob_entries(root=REPO) -> list[Problem]:
    """tests/test_knobs.py: every NOT_GATING site is still found, and each area lists KNOBS in name order."""
    from harness import knobs
    found, out = set(knobs.inventory(root)), []
    sites = {s for k in knobs.KNOBS.values() for s in k.sites}
    for site, why in sorted(knobs.NOT_GATING.items()):
        area = scaffold.holder(site, "NOT_GATING") or "<its area>"
        if site not in found:
            out.append(_p("NOT_GATING", f"{site} is no longer found",
                          f"delete from {scaffold.KNOBS_DIR}/{area}.py NOT_GATING: {scaffold.q(site)}"))
        elif site in sites:
            out.append(_p("NOT_GATING", f"{site} is both a knob site and NOT_GATING",
                          f"delete from {scaffold.KNOBS_DIR}/{area}.py NOT_GATING: {scaffold.q(site)}"))
        elif not why.strip():
            out.append(_p("NOT_GATING", f"{site} gives no reason", scaffold.why_line(site, scaffold.WHY)))
    for area, mod in knobs.areas().items():
        names = knobs.entries(mod)
        if names != sorted(names):
            out.append(_p("knobs", f"{scaffold.KNOBS_DIR}/{area}.py lists KNOBS out of name order",
                          "order them: " + ", ".join(sorted(names))))
    return out


def limit_traces(root=REPO) -> list[Problem]:
    """tests/test_limit_trace_1087.py: every limit records its cut or is NEVER_CUTS, and every cut names a knob."""
    from harness import knobs, limit_trace
    sites = limit_trace.limits(root)
    unregistered = set(knobs.unregistered(sites))
    out = [_p("limit trace", f"{s} records no cut when it binds", *scaffold.trace_fix(s, sites[s]))
           for s in limit_trace.untraced(root) if s not in unregistered]
    out += [_p("limit trace", f"a cut names {n}, neither a registered knob nor a gating site",
               "name a knob from harness/knobs/ or a site the inventory finds, or register that site first")
            for n in limit_trace.unknown(root)]
    out += [_p("limit trace", f"{w}: the knob a cut records is not a literal a scan can read",
               "pass the knob as a literal, a *_knob parameter default, or a site_knob= keyword (RULE #1348)")
            for w in limit_trace.unnamed(root)]
    out += [_p("NEVER_CUTS", p, f"fix or delete its entry in {scaffold.KNOBS_DIR}/"
               f"{scaffold.holder(p.split(': ', 1)[0], 'NEVER_CUTS') or '<its area>'}.py NEVER_CUTS")
            for p in limit_trace.exemption_problems(knobs.NEVER_CUTS, root)]
    return out


def module_layout(root=REPO) -> list[Problem]:
    """tests/test_module_layout.py budget and harness/specs.py's capability map."""
    from harness import specs
    budget, excused = pinned(root, "tests/test_module_layout.py", "BUDGET"), pinned(root, "tests/test_module_layout.py", "OVER_BUDGET")
    over = {p.relative_to(root).as_posix(): n for p in sorted((Path(root) / "harness").rglob("*.py"))
            if (n := len(p.read_text(encoding="utf-8").splitlines())) > budget}
    out = [_p("module layout", f"{rel} is {n} lines, over the {budget} budget",
              "split it, or add to tests/test_module_layout.py OVER_BUDGET:",
              scaffold.why_line(rel, "<why it is not split yet>"))
           for rel, n in over.items() if rel not in excused]
    out += [_p("module layout", f"tests/test_module_layout.py OVER_BUDGET names {rel}, now within budget",
               f"delete its OVER_BUDGET entry: {scaffold.q(rel)}")
            for rel in sorted(set(excused) - set(over))]
    for problem in specs.check(Path(root)):
        rel, _, said = problem.partition(": ")
        if said.startswith("in no capability"):
            cap = scaffold.owner(Path(root), rel) or "<the capability that owns it>"
            out.append(_p("capabilities", problem, f"add under {scaffold.CAPABILITIES} '{cap}' modules:",
                          scaffold.module_line(rel)))
        else:
            out.append(_p("capabilities", problem, "uv run python -m harness.specs names the rule it breaks"))
    return out


def unit_outputs(root=REPO) -> list[Problem]:
    """tests/test_inventory_weight_1148.py: every launchd unit declares its output in UNIT_OUTPUTS."""
    from harness import inventory_weight as iw
    units = iw.services((Path(root) / scaffold.LAUNCHD).read_text(encoding="utf-8"))
    out = []
    for u in units:
        if u not in iw.UNIT_OUTPUTS:
            served = "PORT:-" in _text(Path(root) / f"scripts/serve-{u}.sh")
            line = (scaffold.unit_line(u, "gateway_requests", "at", "PORT") if served else
                    scaffold.unit_line(u, "<store table it writes>", "<its time column>", "", (u,)))
            out.append(_p("UNIT_OUTPUTS", f"launchd unit {u} declares no output",
                          f"add to {scaffold.UNIT_TABLE} UNIT_OUTPUTS:", line))
    out += [_p("UNIT_OUTPUTS", f"UNIT_OUTPUTS names {u}, which is no unit in {scaffold.LAUNCHD}",
               f"delete its entry from {scaffold.UNIT_TABLE} UNIT_OUTPUTS: {scaffold.q(u)}")
            for u in sorted(set(iw.UNIT_OUTPUTS) - set(units))]
    for u, (table, _col, _cond, words) in iw.UNIT_OUTPUTS.items():
        if not (table or words):
            out.append(_p("UNIT_OUTPUTS", f"{u} names neither a table nor a word its readers would name",
                          scaffold.unit_line(u, "<store table it writes>", "<its time column>", "", (u,))))
    return out


def _text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def mutation_tests(root=REPO) -> list[Problem]:
    """tests/test_gauntlet_mutation.py: a test file importing a mutated module is selected for it or left out."""
    import dataclasses

    from gauntlet.mutation import unplaced

    from tests.gauntlet import mutation
    cfg = dataclasses.replace(mutation.CONFIG, root=Path(root))
    out = []
    for module in mutation.MODULES:
        for name in unplaced(cfg, module):
            out.append(_p("mutation", f"tests/{name} imports {module} and is neither selected nor left out",
                          f"add to tests/gauntlet/mutation.py LEFT_OUT[{scaffold.q(module)}]: {scaffold.q(name)},",
                          f"or to MODULES[{scaffold.q(module)}] (then re-pin): \"tests/{name}\","))
    return out


def eval_homes(root=REPO) -> list[Problem]:
    """tests/test_eval_home_1346.py: an eval or probe entry runs from a scratch home or says why not."""
    from gauntlet.scanners import is_python

    from tests import tree_cache
    from tests.gauntlet import scanners
    out = []
    for found in tree_cache.scan_tree(root, scanners.unhomed_evals, is_python):
        key = found.split("'")[1] if "'" in found else found
        out.append(_p("eval home", found, "call paths.eval_home in its handler and add to tests/gauntlet/scanners.py "
                      "EVAL_HOMED:", scaffold.why_line(key, "<the file whose handler calls paths.eval_home>"),
                      "or add to EVAL_WAIVED:", scaffold.why_line(key, "<why its rows never pass for real work>")))
    return out


def _trees(root, tests=False):
    from gauntlet import detectors

    from harness import repo
    from tests.gauntlet import registry
    return detectors.sources(root, tests=tests, production=registry.production, lister=repo.publishable)


def detector_bindings(root=REPO) -> list[Problem]:
    """tests/test_gauntlet_detectors.py for registry.PRECHECK_DETECTORS: a hit is bound, waived or in the backlog."""
    from gauntlet import detectors, ratchet

    from harness import knob_backlog
    from tests.gauntlet import classes, registry
    trees = detectors.parse(_trees(root))
    config = ratchet.detector_config(registry.REGISTRY)
    # A registered move table is read only where its module is in the tree checked.
    config["terminal_without_reader"]["tables"] = [t for t in registry.MOVES if t.site.split(":")[0] in trees]
    index = {cid: e for cid, e in classes.INDEX.items()
             if (named := set(detectors.names(e))) and named <= registry.PRECHECK_DETECTORS}
    run = detectors.run(trees, index, registry.production, None, config)
    led = detectors.ledger(run, detectors.bindings(_trees(root, tests=True)), index)
    backlog = registry.load_backlog(root)
    out = [_p("gauntlet", f"{cid}: {s} trips a gauntlet trigger with no bound test",
              f"mark the test that pins it: @pytest.mark.gauntlet({scaffold.q(cid)}, site={scaffold.q(s)})",
              f"or waive it in tests/gauntlet/classes.py INDEX[{scaffold.q(cid)}]['waivers']:",
              scaffold.why_line(s, "<why the trigger does not apply here>"))
           for cid, row in led.items() for s in row["unbound"] if s not in backlog.get(cid, [])]
    gone = [(cid, s) for cid, rows in backlog.items() if cid in index for s in rows
            if s not in led.get(cid, {}).get("unbound", [])]
    out += [_p("gauntlet", f"{cid}: {s} is bound, waived or gone",
               f"delete this line from {registry.BACKLOG_REL}:", f"{cid} {s}") for cid, s in gone]
    out += [_p("gauntlet", f"{row} joined the backlog after the merge base with {knob_backlog.BASE}",
               f"delete this line from {registry.BACKLOG_REL} and bind or waive the hit instead:", row)
            for row in registry.backlog_added(root) or []]
    return out


def move_tables(root=REPO) -> list[Problem]:
    """tests/test_gauntlet_detectors.py: every declared move table is registered for the soundness check, or waived."""
    from gauntlet import detectors

    from tests.gauntlet import registry
    found = [h.site for h in detectors.move_tables(detectors.parse(_trees(root)), registry.production)]
    known = {t.site for t in registry.MOVES} | set(registry.MOVE_WAIVERS)
    return [_p("move tables", f"{site} declares moves no MoveTable registers",
               "add to tests/gauntlet/registry.py MOVES: "
               f"MoveTable({scaffold.q(site)}, <module>.MOVES, initial=(<born in>,), terminal=(<nothing leaves>,)),",
               "or to MOVE_WAIVERS:", scaffold.why_line(site, "<why it is not checked>"))
            for site in sorted(set(found) - known)]


def _keys(root, rel: str, name: str) -> set[str]:
    """The string keys or members of a dict or set a test module pins at top level, whatever their values hold."""
    for node in ast.parse((Path(root) / rel).read_text(encoding="utf-8")).body:
        target = node.target if isinstance(node, ast.AnnAssign) else (node.targets[0] if isinstance(node, ast.Assign) else None)
        if isinstance(target, ast.Name) and target.id == name:
            items = node.value.keys if isinstance(node.value, ast.Dict) else node.value.elts
            return {k.value for k in items if isinstance(k, ast.Constant)}
    raise KeyError(f"{rel} pins no {name}")


def mode_flags(root=REPO, parser=None) -> list[Problem]:
    """tests/test_lent_store_1426.py: every store_true mode flag of a verb is run read-only there or says why not."""
    import argparse
    rel = "tests/test_lent_store_1426.py"
    if parser is None:
        from harness import cli
        parser = cli.build_parser()
    skip = {"--json", *_keys(root, rel, "FLAGS")}
    listed = _keys(root, rel, "READ_ONLY") | _keys(root, rel, "MODIFIERS") | _keys(root, rel, "NOT_RUN")

    def modes(p, path=()):
        for act in p._actions:
            if isinstance(act, argparse._SubParsersAction):
                for name, sub in act.choices.items():
                    yield from modes(sub, (*path, name))
            elif path and isinstance(act, argparse._StoreTrueAction) and act.option_strings[-1] not in skip:
                yield f"{' '.join(path)} {act.option_strings[-1]}"
    return [_p("mode flags", f"{f} is a new mode flag", f"if its mode never touches the store, add to {rel} NOT_RUN:",
               scaffold.why_line(f, "<why its mode is not run here>"),
               "if it selects a read-only mode, add its argv to READ_ONLY; if it only shapes another mode, to MODIFIERS")
            for f in sorted(set(modes(parser)) - listed)]


CHECKS = (knob_sites, knob_backlog_lines, knob_entries, limit_traces, module_layout, unit_outputs, mutation_tests,
          eval_homes, detector_bindings, move_tables, mode_flags)


#: Checks that each take knobs.inventory share one process, so the inventory is built once, not four times (#1590).
TOGETHER = (("knob_sites", "knob_backlog_lines", "knob_entries", "limit_traces"),)


def groups() -> list[tuple[str, ...]]:
    """CHECKS in order, as the batches one pool process runs; a batch sits where its first check does."""
    out, placed = [], set()
    for check in CHECKS:
        name = check.__name__
        if name not in placed:
            batch = next((g for g in TOGETHER if name in g), (name,))
            out.append(batch)
            placed.update(batch)
    return out


def _run(names: tuple[str, ...]) -> list[Problem]:
    return [p for name in names for p in next(c for c in CHECKS if c.__name__ == name)(REPO)]


def render(problems: list[Problem]) -> str:
    return "\n".join(f"[{p.ratchet}] {p.subject}\n" + "\n".join(f"    {line}" for line in p.fix) for p in problems)


def main(argv: list[str] | None = None) -> int:
    started = time.monotonic()
    names, batches = [c.__name__ for c in CHECKS], groups()
    workers = max(1, min(len(batches), os.cpu_count() or 1))
    with ProcessPoolExecutor(max_workers=workers) as pool:
        problems = [p for got in pool.map(_run, batches) for p in got]
    if problems:
        print(render(problems))
    print(f"precheck: {len(problems)} problem(s) in {len(names)} registration ratchets, "
          f"{time.monotonic() - started:.1f} s")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
