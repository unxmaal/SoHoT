"""Mutation survivors as a ratcheted inventory, parsed without mutmut installed (#492 F3)."""

import json
from pathlib import Path

import pytest

from tests.gauntlet import mutation

REPO = Path(__file__).resolve().parent.parent
REAL_BASELINE = mutation._baseline


@pytest.fixture(autouse=True)
def _no_real_baseline(monkeypatch):
    monkeypatch.setattr(mutation, "_baseline", lambda tree, env, module, **kw: None)

MUTATED = '''
import os


def x_pick__mutmut_orig(xs):
    return next((x for x in xs if x > 0), "")


def x_pick__mutmut_1(xs):
    return next((x for x in xs if x >= 0), "")


def x_pick__mutmut_2(xs):
    return next((x for x in xs if x > 0), "XXXX")


def x_pick__mutmut_3(xs):
    return next((x for x in xs if x > 1), "")


def x_pick__mutmut_4(xs):
    return next((x for x in xs if x > 0), None)


class Box:
    def xǁBoxǁopen__mutmut_orig(self):
        return self.a and self.b

    def xǁBoxǁopen__mutmut_1(self):
        return self.a or self.b

    def xǁBoxǁopen__mutmut_2(self):
        return self.a and self.b
'''

META = {"exit_code_by_key": {
    "harness.thing.x_pick__mutmut_1": 0,
    "harness.thing.x_pick__mutmut_2": 1,
    "harness.thing.x_pick__mutmut_3": 33,
    "harness.thing.x_pick__mutmut_4": 36,
    "harness.thing.xǁBoxǁopen__mutmut_1": 0,
}}


def test_survivors_and_untested_mutants_are_gaps_keyed_by_function_and_kind():
    got = mutation.survivors(META, MUTATED)
    assert got == sorted([
        "harness.thing:pick:x '>'->'>='",
        "harness.thing:pick:> '0'->'1'",
        "harness.thing:Box.open:a 'and'->'or'",
    ])


def test_killed_and_timed_out_mutants_are_not_gaps():
    got = mutation.survivors(META, MUTATED)
    assert not any("XXXX" in k or "None" in k for k in got)


def test_keys_survive_moved_lines_and_renumbered_mutants():
    shifted = "\n\n\nCONST = 1\n\n" + MUTATED.replace("__mutmut_3", "__mutmut_9")
    meta = {"exit_code_by_key": {k.replace("__mutmut_3", "__mutmut_9"): v
                                 for k, v in META["exit_code_by_key"].items()}}
    assert mutation.survivors(meta, shifted) == mutation.survivors(META, MUTATED)


def test_two_identical_mutations_in_one_function_get_distinct_keys():
    src = ('def x_f__mutmut_orig(a, b):\n    return a + 1, b + 1\n'
           'def x_f__mutmut_1(a, b):\n    return a - 1, b + 1\n'
           'def x_f__mutmut_2(a, b):\n    return a + 1, b - 1\n')
    meta = {"exit_code_by_key": {"m.x_f__mutmut_1": 0, "m.x_f__mutmut_2": 0}}
    got = mutation.survivors(meta, src)
    assert got == ["m:f:a '+'->'-'", "m:f:b '+'->'-'"]
    src2 = ('def x_f__mutmut_orig(a):\n    return a + 1, a + 1\n'
            'def x_f__mutmut_1(a):\n    return a - 1, a + 1\n'
            'def x_f__mutmut_2(a):\n    return a + 1, a - 1\n')
    assert mutation.survivors(meta, src2) == ["m:f:a '+'->'-'", "m:f:a '+'->'-' #2"]


def test_a_mutant_that_did_not_run_cleanly_breaks_the_run():
    for code in (None, -11, 35):
        meta = {"exit_code_by_key": {"harness.thing.x_pick__mutmut_1": code}}
        with pytest.raises(mutation.BrokenRun, match="x_pick__mutmut_1"):
            mutation.survivors(meta, MUTATED)


def test_exit_255_is_a_crashed_test_runner_not_a_kill():
    meta = {"exit_code_by_key": {"harness.thing.x_pick__mutmut_1": 255, "harness.thing.x_pick__mutmut_2": 0}}
    assert mutation.unsettled(meta) == ["harness.thing.x_pick__mutmut_1"]
    with pytest.raises(mutation.BrokenRun, match="x_pick__mutmut_1"):
        mutation.survivors(meta, MUTATED)


def test_a_segfaulted_worker_is_rerun_like_a_crashed_one():
    """#840: mlx_parallel mutant 1 was killed twice and ended -11 once, so one crash broke a whole module."""
    meta = {"exit_code_by_key": {"m.x_a__mutmut_1": -11, "m.x_a__mutmut_2": 255, "m.x_a__mutmut_3": 1}}
    assert mutation.unsettled(meta) == ["m.x_a__mutmut_1", "m.x_a__mutmut_2"]


def test_unsettled_mutants_are_rerun_by_name_until_they_settle(monkeypatch, tmp_path):
    rel = "harness/reasons.py"
    calls = []
    codes = iter([{"m.x_pick__mutmut_1": 255, "m.x_pick__mutmut_2": 1}, {"m.x_pick__mutmut_1": 0}])

    def fake(tree, env, log, names):
        calls.append(list(names))
        base = tree / "mutants" / rel
        base.parent.mkdir(parents=True, exist_ok=True)
        base.write_text(MUTATED, encoding="utf-8")
        meta = Path(f"{base}.meta")
        old = json.loads(meta.read_text(encoding="utf-8"))["exit_code_by_key"] if meta.exists() else {}
        meta.write_text(json.dumps({"exit_code_by_key": {**old, **next(codes)}}), encoding="utf-8")
    monkeypatch.setattr(mutation, "_mutmut", fake)
    got = mutation.run_module(tmp_path, rel, "", None)
    assert calls == [[], ["m.x_pick__mutmut_1"]]
    assert got == ["m:pick:x '>'->'>='"]


def test_mutmut_workers_never_ask_macos_for_proxies(monkeypatch, tmp_path):
    """#840: urllib's _scproxy lookup reads CFPreferences, which segfaults in a forked worker (exit -11)."""
    import urllib.request
    seen = {}

    def fake(tree, env, log, names):
        seen.update(env)
        raise mutation.BrokenRun("stop")
    monkeypatch.setattr(mutation, "_mutmut", fake)
    with pytest.raises(mutation.BrokenRun):
        mutation.run_module(tmp_path, "harness/reasons.py", "", None)
    for k in [k for k in list(__import__("os").environ) if k.lower().endswith("_proxy")]:
        monkeypatch.delenv(k)
    for k, v in seen.items():
        if k.lower().endswith("_proxy"):
            monkeypatch.setenv(k, v)
    assert urllib.request.getproxies_environment(), "an environment proxy setting is what skips _scproxy"
    assert urllib.request.proxy_bypass_environment("127.0.0.1")


def test_a_selected_test_that_fails_unmutated_is_named_before_mutmut_hides_it(monkeypatch, tmp_path):
    """#840: on the CI runner mutmut said only "exited 1"; its stats run swallows which test failed."""
    import subprocess
    seen = {}

    def run(argv, **kw):
        seen["argv"] = argv
        return subprocess.CompletedProcess(argv, 1, stdout="..F\nFAILED tests/test_x.py::test_y - boom\n"
                                                          "ERROR tests/test_z.py::test_w\n1 failed\n")
    monkeypatch.setattr(mutation.subprocess, "run", run)
    with pytest.raises(mutation.BrokenRun) as e:
        REAL_BASELINE(tmp_path, {}, "harness/reasons.py")
    assert "tests/test_x.py::test_y" in str(e.value) and "tests/test_z.py::test_w" in str(e.value)
    assert mutation.MODULES["harness/reasons.py"][0] in seen["argv"]
    assert mutation.READS_SOURCE[0] in seen["argv"]
    monkeypatch.setattr(mutation.subprocess, "run",
                        lambda argv, **kw: subprocess.CompletedProcess(argv, 0, stdout="ok\n"))
    assert REAL_BASELINE(tmp_path, {}, "harness/reasons.py") is None


def test_the_baseline_runs_at_the_workers_asked_for_else_one_per_cpu(monkeypatch, tmp_path):
    """A local --jobs run must not start a pytest worker per core before mutmut honours the cap (#1666)."""
    import subprocess
    seen = []
    monkeypatch.setattr(mutation.subprocess, "run",
                        lambda argv, **kw: seen.append(argv) or subprocess.CompletedProcess(argv, 0, stdout="ok\n"))
    REAL_BASELINE(tmp_path, {}, "harness/reasons.py", jobs=6)
    REAL_BASELINE(tmp_path, {}, "harness/reasons.py")
    assert [a[a.index("-n") + 1] for a in seen] == ["6", "auto"]


def test_a_mutant_that_never_settles_breaks_the_run(monkeypatch, tmp_path):
    rel = "harness/reasons.py"

    def fake(tree, env, log, names):
        base = tree / "mutants" / rel
        base.parent.mkdir(parents=True, exist_ok=True)
        base.write_text(MUTATED, encoding="utf-8")
        Path(f"{base}.meta").write_text(json.dumps({"exit_code_by_key": {"m.x_pick__mutmut_1": 255}}), encoding="utf-8")
    monkeypatch.setattr(mutation, "_mutmut", fake)
    with pytest.raises(mutation.BrokenRun, match="x_pick__mutmut_1"):
        mutation.run_module(tmp_path, rel, "", None)


def test_a_survivor_whose_source_is_missing_breaks_the_run():
    meta = {"exit_code_by_key": {"harness.thing.x_gone__mutmut_1": 0}}
    with pytest.raises(mutation.BrokenRun, match="x_gone"):
        mutation.survivors(meta, MUTATED)


def test_the_ratchet_is_quiet_when_the_inventory_matches_the_pin():
    assert mutation.ratchet(["a", "b"], ["b", "a"], "harness/x.py") == []


def test_the_ratchet_fails_on_a_new_survivor():
    got = mutation.ratchet(["a", "b", "c"], ["a", "b"], "harness/x.py")
    assert len(got) == 1 and "new" in got[0] and "c" in got[0]


def test_the_ratchet_fails_when_a_pinned_survivor_is_killed_and_left_in():
    got = mutation.ratchet(["a"], ["a", "b"], "harness/x.py")
    assert len(got) == 1 and "remove" in got[0] and "b" in got[0]


def test_a_swap_is_both_a_new_survivor_and_a_stale_pin():
    got = mutation.ratchet(["a", "c"], ["a", "b"], "harness/x.py")
    assert len(got) == 2


def test_gate_ratchets_pinned_modules_and_only_reports_unpinned_ones():
    found = {"harness/a.py": ["k1"], "harness/b.py": ["k2", "k3"]}
    problems, notes = mutation.gate(found, {"harness/a.py": ["k1"]})
    assert problems == [] and len(notes) == 1 and "harness/b.py" in notes[0]
    problems, _ = mutation.gate(found, {"harness/a.py": []})
    assert len(problems) == 1 and "k1" in problems[0]


def test_every_module_and_its_selected_tests_exist():
    assert set(mutation.MODULES) == {
        "harness/memory_store/transitions.py", "harness/screen.py", "harness/adopt.py",
        "harness/reasons.py", "harness/serving.py", "harness/router.py"}
    for module, tests in mutation.MODULES.items():
        assert (REPO / module).is_file(), module
        assert tests, module
        for t in tests:
            assert (REPO / t).is_file(), (module, t)


def test_every_test_file_that_imports_a_mutated_module_is_selected_or_left_out_on_purpose():
    """#840: tests for new code went into new files that mutmut never ran, so the nightly saw survivors."""
    found = {m: mutation.unplaced(m) for m in mutation.MODULES}
    assert not any(found.values()), (
        "add each to tests/gauntlet/mutation.py MODULES (then re-pin) or LEFT_OUT: "
        + "; ".join(f"{m}: {', '.join(f)}" for m, f in found.items() if f))
    for module, left in mutation.LEFT_OUT.items():
        for name in left:
            assert mutation.imports((REPO / "tests" / name).read_text(encoding="utf-8"), module), (module, name)


LOADS_METAL = ("mlx.core", "mlx_lm")
FIRST_TO_LOAD = """
import importlib, sys
for f in sys.argv[2:]:
    try:
        importlib.import_module(f[:-3].replace("/", "."))
    except BaseException:
        pass
    if any(m in sys.modules for m in sys.argv[1].split(",")):
        print(f)
        break
"""


def test_no_selected_test_file_loads_metal_when_imported():
    """Metal loaded at import segfaults a forked mutmut worker at exit and breaks the module's whole run (#728, #1588)."""
    import subprocess
    import sys
    files = sorted({t for tests in mutation.MODULES.values() for t in tests})
    got = subprocess.run([sys.executable, "-c", FIRST_TO_LOAD, ",".join(LOADS_METAL), *files], cwd=REPO,
                         capture_output=True, text=True, encoding="utf-8")
    assert got.returncode == 0, got.stderr[-2000:]
    assert got.stdout.strip() == "", f"{got.stdout.strip()} loads mlx at import: import it inside the function that runs it"


def test_an_import_is_recognised_in_each_spelling():
    for src in ("import harness.router\n", "from harness import router, screen\n",
                "from harness.router import Watch\n", "from harness import (\n    adopt,\n    router,\n)\n"):
        assert mutation.imports(src, "harness/router.py"), src
    for src in ("from harness import routers\n", "import harness.routerx\n", "x = 'harness.router'\n",
                "from .router import Watch\n"):
        assert not mutation.imports(src, "harness/router.py"), src
    assert mutation.imports("from harness.memory_store import transitions\n", "harness/memory_store/transitions.py")


def test_the_config_mutates_one_module_against_its_own_tests_in_a_forkserver():
    cfg = mutation.config("harness/reasons.py")
    import tomllib
    got = tomllib.loads(cfg)["tool"]["mutmut"]
    assert got["only_mutate"] == ["harness/reasons.py"]
    assert got["pytest_add_cli_args_test_selection"] == mutation.MODULES["harness/reasons.py"]
    assert got["process_isolation"] == "forkserver"
    # The timeout is CPU seconds; a store migration in a test outspends mutmut's default and flaps the pin.
    assert got["timeout_constant"] >= 60


def test_tests_that_read_harness_source_are_deselected_since_they_would_read_the_mutants():
    import tomllib
    args = tomllib.loads(mutation.config("harness/adopt.py"))["tool"]["mutmut"]["pytest_add_cli_args"]
    assert args[::2] == ["--deselect"] * len(mutation.READS_SOURCE)
    assert args[1::2] == list(mutation.READS_SOURCE)
    assert "tests/test_verdict_reasons.py::test_every_production_verdict_says_why" in args
    for nodeid in args[1::2]:
        path, _, name = nodeid.partition("::")
        assert f"def {name}(" in (REPO / path).read_text(encoding="utf-8"), nodeid


def test_the_committed_pin_is_well_formed():
    pin = json.loads(mutation.PIN_FILE.read_text(encoding="utf-8"))
    assert set(pin) <= set(mutation.MODULES)
    for module, keys in pin.items():
        assert keys == sorted(set(keys)), module
        dotted = module[:-3].replace("/", ".")
        assert all(k.startswith(dotted + ":") for k in keys), module


def _fake_run(monkeypatch, tmp_path, results, seen=None):
    seen = [] if seen is None else seen
    def run_module(tree, module, pyproject, log, functions=(), jobs=None):
        seen.append((module, tuple(functions), jobs))
        if isinstance(results[module], Exception):
            raise results[module]
        return results[module]
    monkeypatch.setattr(mutation, "copy_tree", lambda dest: (dest / "pyproject.toml").write_text("", encoding="utf-8"))
    monkeypatch.setattr(mutation, "run_module", run_module)
    monkeypatch.setattr(mutation, "PIN_FILE", tmp_path / "pin.json")


def test_one_broken_module_does_not_hide_the_others_and_fails_the_run(monkeypatch, tmp_path, capsys):
    a, b = "harness/reasons.py", "harness/router.py"
    _fake_run(monkeypatch, tmp_path, {a: mutation.BrokenRun("boom"), b: ["harness.router:f:k"]})
    mutation.PIN_FILE.write_text(json.dumps({b: ["harness.router:f:k"]}), encoding="utf-8")
    rc = mutation.main(["run", "--module", a, "--module", b, "--workdir", str(tmp_path / "w")])
    out = capsys.readouterr().out
    assert rc == 1 and "boom" in out and f"{b}: 1 survivor" in out


def test_pinning_skips_a_broken_module(monkeypatch, tmp_path):
    a, b = "harness/reasons.py", "harness/router.py"
    _fake_run(monkeypatch, tmp_path, {a: mutation.BrokenRun("boom"), b: ["harness.router:f:k"]})
    rc = mutation.main(["run", "--module", a, "--module", b, "--pin", "--workdir", str(tmp_path / "w")])
    assert rc == 1
    assert json.loads(mutation.PIN_FILE.read_text(encoding="utf-8")) == {b: ["harness.router:f:k"]}


def test_a_clean_run_matching_the_pin_passes_and_a_new_survivor_fails(monkeypatch, tmp_path):
    b = "harness/router.py"
    _fake_run(monkeypatch, tmp_path, {b: ["harness.router:f:k"]})
    mutation.PIN_FILE.write_text(json.dumps({b: ["harness.router:f:k"]}), encoding="utf-8")
    assert mutation.main(["run", "--module", b, "--workdir", str(tmp_path / "w")]) == 0
    mutation.PIN_FILE.write_text(json.dumps({b: []}), encoding="utf-8")
    assert mutation.main(["run", "--module", b, "--workdir", str(tmp_path / "w")]) == 1


def test_the_counts_come_last_so_a_tail_that_cuts_the_new_keys_still_shows_them(monkeypatch, tmp_path, capsys):
    b = "harness/router.py"
    _fake_run(monkeypatch, tmp_path, {b: [f"harness.router:f:k{i}" for i in range(60)]})
    mutation.PIN_FILE.write_text(json.dumps({b: ["harness.router:f:old"]}), encoding="utf-8")
    assert mutation.main(["run", "--module", b, "--workdir", str(tmp_path / "w")]) == 1
    tail = capsys.readouterr().out.splitlines()[-40:]
    assert f"{b}: 60 new survivor(s), 1 pinned now killed" in tail


def test_a_ci_run_s_found_file_pins_only_its_own_modules(monkeypatch, tmp_path):
    a, b = "harness/reasons.py", "harness/router.py"
    _fake_run(monkeypatch, tmp_path, {a: mutation.BrokenRun("boom"), b: ["harness.router:f:k2", "harness.router:f:k1"]})
    mutation.PIN_FILE.write_text(json.dumps({a: ["harness.reasons:g:old"], b: ["harness.router:f:old"]}),
                                 encoding="utf-8")
    found = tmp_path / "ci" / "found.json"
    assert mutation.main(["run", "--module", a, "--module", b, "--found", str(found),
                          "--workdir", str(tmp_path / "w")]) == 1
    assert json.loads(found.read_text(encoding="utf-8")) == {b: ["harness.router:f:k2", "harness.router:f:k1"]}
    assert mutation.main(["pin", "--from", str(found)]) == 0
    assert json.loads(mutation.PIN_FILE.read_text(encoding="utf-8")) == {
        a: ["harness.reasons:g:old"], b: ["harness.router:f:k1", "harness.router:f:k2"]}


def test_a_found_file_naming_a_module_that_is_not_mutated_is_refused(monkeypatch, tmp_path):
    monkeypatch.setattr(mutation, "PIN_FILE", tmp_path / "pin.json")
    found = tmp_path / "found.json"
    found.write_text(json.dumps({"harness/nope.py": []}), encoding="utf-8")
    with pytest.raises(SystemExit, match="harness/nope.py"):
        mutation.main(["pin", "--from", str(found)])
    assert not mutation.PIN_FILE.exists()


def test_a_function_run_mutates_only_that_functions_mutants(monkeypatch, tmp_path):
    """#1071: a daytime run on a shared machine mutates the functions under test, never a whole module."""
    import fnmatch
    rel = "harness/thing.py"
    pats = mutation.globs(rel, ["pick", "Box.open"])
    match = [n for n in ("harness.thing.x_pick__mutmut_1", "harness.thing.x_pick_more__mutmut_1",
                         "harness.thing.xǁBoxǁopen__mutmut_2", "harness.other.x_pick__mutmut_1")
             if any(fnmatch.fnmatch(n, p) for p in pats)]
    assert match == ["harness.thing.x_pick__mutmut_1", "harness.thing.xǁBoxǁopen__mutmut_2"]
    calls = []

    def fake(tree, env, log, names, **kw):
        calls.append((list(names), kw))
        base = tree / "mutants" / "harness/reasons.py"
        base.parent.mkdir(parents=True, exist_ok=True)
        base.write_text(MUTATED, encoding="utf-8")
        Path(f"{base}.meta").write_text(json.dumps({"exit_code_by_key": {
            "harness.thing.x_pick__mutmut_1": 0, "harness.thing.xǁBoxǁopen__mutmut_1": None}}), encoding="utf-8")
    monkeypatch.setattr(mutation, "_mutmut", fake)
    got = mutation.run_module(tmp_path, "harness/reasons.py", "", None, ("pick",), 3)
    assert got == ["harness.thing:pick:x '>'->'>='"]
    assert calls == [(["harness.reasons.x_pick__mutmut_*"], {"jobs": 3})]


def test_a_function_run_ratchets_and_pins_only_that_functions_keys(monkeypatch, tmp_path, capsys):
    b, seen = "harness/router.py", []
    _fake_run(monkeypatch, tmp_path, {b: ["harness.router:f:k1", "harness.router:f:new"]}, seen)
    mutation.PIN_FILE.write_text(json.dumps({b: ["harness.router:f:k1", "harness.router:g:other"]}),
                                 encoding="utf-8")
    run = ["run", "--module", b, "--function", "f", "--jobs", "2", "--workdir", str(tmp_path / "w")]
    assert mutation.main(run) == 1
    assert seen[-1] == (b, ("f",), 2)
    out = capsys.readouterr().out
    assert "harness.router:f:new" in out and "harness.router:g:other" not in out
    assert mutation.main([*run, "--pin"]) == 0
    assert json.loads(mutation.PIN_FILE.read_text(encoding="utf-8")) == {
        b: ["harness.router:f:k1", "harness.router:f:new", "harness.router:g:other"]}
    assert mutation.main(run) == 0
    for bad in (["--module", b, "--module", "harness/reasons.py"], ["--module", b, "--found", str(tmp_path / "f")]):
        with pytest.raises(SystemExit, match="--function"):
            mutation.main(["run", *bad, "--function", "f", "--workdir", str(tmp_path / "w")])


SHARDED = '''
def b(): pass
async def e(): pass
class C:
    def d(self): pass
    X = 1
def a():
    def inner(): pass
'''


def test_n_shards_split_a_modules_functions_between_them_and_the_first_owns_gone_pins():
    """#1588: adopt.py outgrew one 120-minute job, so N jobs each mutate every Nth function."""
    assert mutation.functions_of(SHARDED) == ["C.d", "a", "b", "e"]
    assert mutation.shard(SHARDED, "1/2") == ("C.d", "b")
    assert mutation.shard(SHARDED, "2/2") == ("a", "e")
    assert mutation.shard(SHARDED, "1/1") == ("C.d", "a", "b", "e")
    pinned = ["harness.m:gone:k", "harness.m:a:k"]
    assert mutation.shard(SHARDED, "1/2", pinned) == ("C.d", "b", "gone")
    assert mutation.shard(SHARDED, "2/2", pinned) == ("a", "e")
    for bad in ("0/2", "3/2"):
        with pytest.raises(SystemExit, match="K/N"):
            mutation.shard(SHARDED, bad)


def test_a_shards_found_file_replaces_only_its_own_functions_pins(monkeypatch, tmp_path):
    b, seen = "harness/router.py", []
    src = (REPO / b).read_text(encoding="utf-8")
    mine, theirs = mutation.shard(src, "1/2")[0], mutation.shard(src, "2/2")[0]
    _fake_run(monkeypatch, tmp_path, {b: [f"harness.router:{mine}:new"]}, seen)
    mutation.PIN_FILE.write_text(json.dumps({b: [f"harness.router:{mine}:old", f"harness.router:{theirs}:k",
                                                 "harness.router:renamed_away:k"]}), encoding="utf-8")
    found = tmp_path / "found.json"
    run = ["run", "--module", b, "--shard", "1/2", "--found", str(found), "--workdir", str(tmp_path / "w")]
    assert mutation.main(run) == 1, "a new key, a pinned key now killed and a gone function's pin all fail shard 1"
    assert seen[-1][1] == mutation.shard(src, "1/2", [f"harness.router:{theirs}:k", "harness.router:renamed_away:k"])
    written = json.loads(found.read_text(encoding="utf-8"))
    assert written[b] == [f"harness.router:{mine}:new"] and "renamed_away" in written[mutation.FUNCTIONS_KEY][b]
    assert mutation.main(["pin", "--from", str(found)]) == 0
    assert json.loads(mutation.PIN_FILE.read_text(encoding="utf-8")) == {
        b: sorted([f"harness.router:{mine}:new", f"harness.router:{theirs}:k"])}
    with pytest.raises(SystemExit, match="--shard"):
        mutation.main(["run", "--module", b, "--module", "harness/reasons.py", "--shard", "1/2"])


def test_a_jobs_cap_reaches_mutmut_and_no_cap_leaves_it_one_worker_per_cpu(monkeypatch, tmp_path):
    import subprocess
    seen = []
    monkeypatch.setattr(mutation.subprocess, "run",
                        lambda argv, **kw: seen.append(argv) or subprocess.CompletedProcess(argv, 0))
    mutation._mutmut(tmp_path, {}, None, ["m.x_f__mutmut_*"], jobs=3)
    mutation._mutmut(tmp_path, {}, None, [])
    assert seen[0][-4:] == ["run", "--max-children", "3", "m.x_f__mutmut_*"]
    assert seen[1][-1] == "run"


OLD_MODULE = '''LIMIT = 1


def kept(x):
    return x + 1


class Box:
    def size(self):
        def inner():
            return 2
        return inner()


def dropped():
    return 3
'''
NEW_MODULE = '''LIMIT = 2


def kept(x):
    return x + 1


class Box:
    def size(self):
        def inner():
            return 5
        return inner()


def added():
    return 4
'''


def _git(root, *args):
    import subprocess
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=root, check=True,
                   capture_output=True)


def test_a_pull_request_mutates_the_functions_it_changes_or_adds_in_a_mutated_module(tmp_path):
    """#1663/#1665 changed screen functions whose only tests were LEFT_OUT, and no PR run mutated them (#1666)."""
    module = tmp_path / "harness" / "screen.py"
    module.parent.mkdir()
    module.write_text(OLD_MODULE, encoding="utf-8")
    (tmp_path / "harness" / "other.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "base")
    _git(tmp_path, "checkout", "-qb", "pr")
    module.write_text(NEW_MODULE, encoding="utf-8")
    (tmp_path / "harness" / "other.py").write_text("def f():\n    return 2\n", encoding="utf-8")
    _git(tmp_path, "commit", "-qam", "change")
    assert mutation.changed("main", root=tmp_path) == {"harness/screen.py": ["Box.size", "added"]}
    _git(tmp_path, "checkout", "-q", "main")
    assert mutation.changed("main", root=tmp_path) == {}


def test_changed_prints_one_tab_separated_line_per_module(monkeypatch, capsys):
    monkeypatch.setattr(mutation, "changed", lambda base: {"harness/screen.py": ["argv", "Box.size"]})
    assert mutation.main(["changed", "--base", "origin/main"]) == 0
    assert capsys.readouterr().out == "harness/screen.py\targv Box.size\n"
