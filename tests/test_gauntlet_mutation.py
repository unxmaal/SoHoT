"""Mutation survivors as a ratcheted inventory, parsed without mutmut installed (#492 F3)."""

import json
from pathlib import Path

import pytest

from tests.gauntlet import mutation

REPO = Path(__file__).resolve().parent.parent

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
    assert args == ["--deselect", "tests/test_verdict_reasons.py::test_every_production_verdict_says_why"]
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


def _fake_run(monkeypatch, tmp_path, results):
    def run_module(tree, module, pyproject, log):
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
