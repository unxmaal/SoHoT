"""This repo's mutation registry: which modules, which tests kill their mutants, and the pin (#492 F3, #1785)."""

import json
from pathlib import Path

from gauntlet import mutation as gmutation

from tests.gauntlet import mutation

REPO = Path(__file__).resolve().parent.parent


def test_each_mutant_tree_gets_its_own_home_and_hf_cache(tmp_path):
    env = mutation.CONFIG.env(tmp_path)
    assert env == {"LOCALHARNESS_HOME": tmp_path / ".lh-home", "HF_HOME": tmp_path / ".hf-home"}
    assert set(mutation.CONFIG.env_dirs) == set(env)
    assert mutation.CONFIG.uv_groups == ("mutation", "mcp") and mutation.CONFIG.source_paths == ("harness",)


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
    found = {m: gmutation.unplaced(mutation.CONFIG, m) for m in mutation.MODULES}
    assert not any(found.values()), (
        "add each to tests/gauntlet/mutation.py MODULES (then re-pin) or LEFT_OUT: "
        + "; ".join(f"{m}: {', '.join(f)}" for m, f in found.items() if f) + "\n"
        + "\n".join(f'LEFT_OUT["{m}"] gains: "{name}",' for m, f in found.items() for name in f))
    for module, left in mutation.LEFT_OUT.items():
        for name in left:
            assert gmutation.imports((REPO / "tests" / name).read_text(encoding="utf-8"), module), (module, name)


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


def test_the_config_mutates_one_module_against_its_own_tests_in_a_forkserver():
    cfg = gmutation.config(mutation.CONFIG, "harness/reasons.py")
    import tomllib
    got = tomllib.loads(cfg)["tool"]["mutmut"]
    assert got["only_mutate"] == ["harness/reasons.py"]
    assert got["pytest_add_cli_args_test_selection"] == mutation.MODULES["harness/reasons.py"]
    assert got["process_isolation"] == "forkserver"
    # The timeout is CPU seconds; a store migration in a test outspends mutmut's default and flaps the pin.
    assert got["timeout_constant"] >= 60


def test_tests_that_read_harness_source_are_deselected_since_they_would_read_the_mutants():
    import tomllib
    args = tomllib.loads(gmutation.config(mutation.CONFIG, "harness/adopt.py"))["tool"]["mutmut"]["pytest_add_cli_args"]
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

