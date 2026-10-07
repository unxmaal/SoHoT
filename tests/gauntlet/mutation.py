"""Nightly mutation testing of the core modules, ratcheted against a pinned inventory (#492 F3).

python -m tests.gauntlet.mutation run [--module M ...] [--pin] [--workdir DIR]
"""

import argparse
import ast
import difflib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import tokenize
from pathlib import Path

from harness import repo

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
PIN_FILE = HERE / "mutation_survivors.json"
MUTMUT_GROUPS = ("--group", "mutation", "--group", "mcp")

MODULES = {
    "harness/memory_store/transitions.py": [
        "tests/test_store_state.py", "tests/test_store_retest.py",
        "tests/test_harness_store_retraction.py", "tests/test_store_retract_screens.py",
        "tests/test_harness_memory_store.py", "tests/test_verdict_reasons.py",
        "tests/test_harness_store.py"],
    "harness/reasons.py": [
        "tests/test_verdict_reasons.py", "tests/test_refusal_shapes.py",
        "tests/test_screen_server_death.py", "tests/test_screen_evidence.py",
        "tests/test_harness_engines_repo_id.py", "tests/test_mps_backend_abort.py"],
    "harness/screen.py": [
        "tests/test_harness_screen.py", "tests/test_harness_screen_spec.py",
        "tests/test_screen_evidence.py", "tests/test_screen_server_death.py",
        "tests/test_decide_lane.py", "tests/test_refusal_shapes.py",
        "tests/test_verdict_reasons.py", "tests/test_screen_case_fit.py", "tests/test_methods.py",
        "tests/test_ds4.py"],
    "harness/adopt.py": [
        "tests/test_harness_adopt.py", "tests/test_harness_adopt_receipt.py",
        "tests/test_adopt_by_spec.py", "tests/test_adoptions.py", "tests/test_adopt_cmd.py",
        "tests/test_human_verdicts.py", "tests/test_schema_lanes.py", "tests/test_holdout_power.py",
        "tests/test_power_budget.py", "tests/test_methods.py", "tests/test_adopt_scope.py",
        "tests/test_method_serving.py"],
    "harness/serving.py": [
        "tests/test_harness_serving.py", "tests/test_lane_routes.py", "tests/test_gguf_route.py",
        "tests/test_schema_lanes.py", "tests/test_ds4.py"],
    "harness/router.py": ["tests/test_router_unload.py", "tests/test_lane_routes.py"],
}

# mutmut 3 exit codes: survived and untested are gaps; anything unrecognised means the run is not trustworthy.
GAP = {0, 5, 33}
KILLED = {1, 3, 24, -24, 36, 37, 152}
# 255 is os._exit(-1) after the test runner raised in the worker, which flaps between runs, so it is retried.
UNSETTLED = 255
RETRIES = 3
SKIP_TOKENS = {tokenize.NEWLINE, tokenize.NL, tokenize.INDENT, tokenize.DEDENT,
               tokenize.COMMENT, tokenize.ENCODING, tokenize.ENDMARKER}
SEP = "ǁ"
# Tests that parse harness source with ast; under mutmut they would read the mutated file, not the module.
READS_SOURCE = ("tests/test_verdict_reasons.py::test_every_production_verdict_says_why",)


class BrokenRun(RuntimeError):
    pass


def config(module):
    lines = [
        "", "[tool.mutmut]",
        'source_paths = ["harness"]',
        f"only_mutate = {json.dumps([module])}",
        f"pytest_add_cli_args_test_selection = {json.dumps(MODULES[module])}",
        'process_isolation = "forkserver"',
        "timeout_constant = 60.0",
        f"pytest_add_cli_args = {json.dumps([a for t in READS_SOURCE for a in ('--deselect', t)])}",
        f"also_copy = {json.dumps(['evals', 'scripts', 'gateway', 'deploy', 'voice', 'tools', 'docs', 'Makefile'])}",
    ]
    return "\n".join(lines) + "\n"


def _split(mutant):
    stem, _, number = mutant.rpartition("__mutmut_")
    parts = stem.split(".")
    i = max(i for i, p in enumerate(parts) if p.startswith(("x_", "x" + SEP)))
    mangled = ".".join(parts[i:])
    if mangled.startswith("x" + SEP):
        _, cls, fn = mangled.split(SEP)
        shown = f"{cls}.{fn}"
    else:
        shown = mangled[2:]
    return ".".join(parts[:i]), mangled, shown, int(number)


def _tokens(node):
    out = []
    for t in tokenize.generate_tokens(io.StringIO(ast.unparse(node)).readline):
        if t.type not in SKIP_TOKENS and t.string != node.name:
            out.append(t.string)
    return out


def kind(orig, mutant):
    a, b = _tokens(orig), _tokens(mutant)
    pieces = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op != "equal":
            ctx = a[i1 - 1] if i1 else "^"
            pieces.append(f"{ctx} {' '.join(a[i1:i2])!r}->{' '.join(b[j1:j2])!r}")
    return "; ".join(pieces) or "identical"


def unsettled(meta):
    return sorted(k for k, v in meta["exit_code_by_key"].items() if v == UNSETTLED)


def survivors(meta, mutated_source):
    gaps = []
    for name, code in meta["exit_code_by_key"].items():
        if code in KILLED:
            continue
        if code not in GAP:
            raise BrokenRun(f"{name} ended with exit code {code}: the run is not trustworthy")
        gaps.append(name)
    if not gaps:
        return []
    defs = {n.name: n for n in ast.walk(ast.parse(mutated_source))
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    keyed = []
    for name in sorted(gaps, key=lambda n: _split(n)[3]):
        module, mangled, shown, number = _split(name)
        orig, mut = defs.get(f"{mangled}__mutmut_orig"), defs.get(f"{mangled}__mutmut_{number}")
        if orig is None or mut is None:
            raise BrokenRun(f"{name} has no source in the mutated file")
        keyed.append(f"{module}:{shown}:{kind(orig, mut)}")
    seen, out = {}, []
    for k in keyed:
        seen[k] = seen.get(k, 0) + 1
        out.append(k if seen[k] == 1 else f"{k} #{seen[k]}")
    return sorted(out)


def ratchet(found, pinned, module):
    found, pinned = set(found), set(pinned)
    problems = []
    new = sorted(found - pinned)
    if new:
        problems.append(f"{module}: {len(new)} new surviving mutant(s); add a test that kills each:\n  "
                        + "\n  ".join(new))
    gone = sorted(pinned - found)
    if gone:
        problems.append(f"{module}: {len(gone)} pinned survivor(s) now killed; remove from "
                        f"{PIN_FILE.name}:\n  " + "\n  ".join(gone))
    return problems


def gate(found_by_module, pin):
    problems, notes = [], []
    for module, found in sorted(found_by_module.items()):
        if module in pin:
            problems += ratchet(found, pin[module], module)
        else:
            notes.append(f"{module}: unpinned, {len(found)} survivor(s); run with --pin to start its ratchet")
    return problems, notes


def _paths(tree, module):
    base = Path(tree) / "mutants" / module
    return base, Path(f"{base}.meta")


def _mutmut(tree, env, log, names):
    r = subprocess.run(["uv", "run", "--python", "3.12", *MUTMUT_GROUPS, "mutmut", "run", *names],
                       cwd=tree, env=env, stdout=log, stderr=subprocess.STDOUT, check=False)
    if r.returncode != 0:
        raise BrokenRun(f"mutmut exited {r.returncode}")


def copy_tree(dest):
    for path in repo.publishable(REPO):
        if path.is_file():
            target = dest / path.relative_to(REPO)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)


def run_module(tree, module, pyproject, log):
    (tree / "pyproject.toml").write_text(pyproject + config(module), encoding="utf-8")
    shutil.rmtree(tree / "mutants", ignore_errors=True)
    env = dict(os.environ, LOCALHARNESS_HOME=str(tree / ".lh-home"), HF_HOME=str(tree / ".hf-home"),
               OBJC_DISABLE_INITIALIZE_FORK_SAFETY="YES")
    for d in (env["LOCALHARNESS_HOME"], env["HF_HOME"]):
        Path(d).mkdir(exist_ok=True)
    base, meta_path = _paths(tree, module)
    names = []
    for _ in range(1 + RETRIES):
        try:
            _mutmut(tree, env, log, names)
        except BrokenRun as e:
            raise BrokenRun(f"{module}: {e}") from None
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        names = unsettled(meta)
        if not names:
            break
    return survivors(meta, base.read_text(encoding="utf-8"))


def load_pin():
    return json.loads(PIN_FILE.read_text(encoding="utf-8")) if PIN_FILE.exists() else {}


def cmd_run(a):
    modules = a.module or list(MODULES)
    workdir = Path(a.workdir) if a.workdir else Path(tempfile.mkdtemp(prefix="mutation-"))
    tree = workdir / "tree"
    tree.mkdir(parents=True, exist_ok=True)
    copy_tree(tree)
    pyproject = (tree / "pyproject.toml").read_text(encoding="utf-8")
    found, broken = {}, []
    with open(workdir / "mutmut.log", "a", encoding="utf-8") as log:
        for module in modules:
            print(f"{module}: running", flush=True)
            try:
                found[module] = run_module(tree, module, pyproject, log)
            except BrokenRun as e:
                broken.append(str(e))
                print(f"{module}: BROKEN {e}", flush=True)
                continue
            print(f"{module}: {len(found[module])} survivor(s)", flush=True)
    pin = load_pin()
    if a.pin:
        pin.update(found)
        PIN_FILE.write_text(json.dumps(dict(sorted(pin.items())), indent=1, ensure_ascii=False) + "\n",
                            encoding="utf-8")
        print(f"pinned {', '.join(found)} -> {PIN_FILE.name}")
        return 1 if broken else 0
    problems, notes = gate(found, pin)
    problems += broken
    for line in notes + problems:
        print(line)
    print(f"mutmut log: {workdir / 'mutmut.log'}")
    return 1 if problems else 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m tests.gauntlet.mutation")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="mutate the core modules and ratchet survivors against the pin")
    r.add_argument("--module", action="append", choices=sorted(MODULES), help="default: all")
    r.add_argument("--pin", action="store_true", help="write today's survivors as the pin instead of gating")
    r.add_argument("--workdir", help="default: a fresh temporary directory")
    r.set_defaults(fn=cmd_run)
    a = p.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
