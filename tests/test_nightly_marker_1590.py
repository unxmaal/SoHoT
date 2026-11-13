"""A `nightly` test waits for the nightly only while a fast twin that every PR runs checks the same thing. #1590."""
import ast
from pathlib import Path
from types import SimpleNamespace

import yaml

from tests import conftest

TESTS = Path(__file__).resolve().parent
CI = TESTS.parent / ".github" / "workflows" / "ci.yml"


def _mark(dec, name):
    call = dec if isinstance(dec, ast.Call) else None
    func = call.func if call else dec
    return isinstance(func, ast.Attribute) and func.attr == name and "mark" in ast.unparse(func), call


def nightly_twins(root: Path = TESTS) -> list[tuple[str, str, list[str]]]:
    """(file, test, fast twins as file::name) for every test marked nightly."""
    out = []
    for path in sorted(root.glob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if not isinstance(node, ast.FunctionDef):
                continue
            for dec in node.decorator_list:
                hit, call = _mark(dec, "nightly")
                if not hit:
                    continue
                kw = {k.arg: k.value for k in (call.keywords if call else [])}
                fast = ast.literal_eval(kw["fast"]) if "fast" in kw else ()
                fast = [fast] if isinstance(fast, str) else list(fast)
                out.append((path.name, node.name, [f if "::" in f else f"tests/{path.name}::{f}" for f in fast]))
    return out


def _defs(rel: str) -> dict:
    tree = ast.parse((TESTS.parent / rel).read_text(encoding="utf-8"))
    return {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}


def problems(root: Path = TESTS) -> list[str]:
    bad = []
    for file, name, fast in nightly_twins(root):
        if not fast:
            bad.append(f"{file}::{name} is nightly with no fast twin")
        for twin in fast:
            rel, _, fn = twin.partition("::")
            node = _defs(rel).get(fn) if (TESTS.parent / rel).is_file() else None
            if node is None:
                bad.append(f"{file}::{name}: fast twin {twin} is not a test")
            elif any(_mark(d, m)[0] for d in node.decorator_list for m in ("nightly", "long", "slow")):
                bad.append(f"{file}::{name}: fast twin {twin} does not run on every PR")
    return bad


def test_every_nightly_test_names_a_fast_twin_that_every_pr_runs():
    assert len(nightly_twins()) >= 2
    assert problems() == []


def test_a_nightly_test_with_no_twin_or_a_slow_twin_is_named(tmp_path):
    (tmp_path / "test_a.py").write_text(
        "import pytest\n\n\n@pytest.mark.nightly\ndef test_x():\n    pass\n\n\n"
        "@pytest.mark.nightly(fast='tests/test_importers.py::test_the_whole_shipped_import_passes_its_reference_and_no_constant_657')\n"
        "def test_y():\n    pass\n\n\n@pytest.mark.nightly(fast='test_gone')\ndef test_z():\n    pass\n", encoding="utf-8")
    assert problems(tmp_path) == [
        "test_a.py::test_x is nightly with no fast twin",
        "test_a.py::test_y: fast twin tests/test_importers.py::test_the_whole_shipped_import_passes_its_reference_and_"
        "no_constant_657 does not run on every PR",
        "test_a.py::test_z: fast twin tests/test_a.py::test_gone is not a test"]


def test_push_and_pull_request_runs_leave_nightly_tests_to_the_nightly():
    env = yaml.safe_load(CI.read_text(encoding="utf-8"))["jobs"]["check-macos"]["env"]
    expr = env[conftest.NIGHTLY_ENV].replace(" ", "")
    assert "github.event_name=='push'" in expr and "github.event_name=='pull_request'" in expr
    assert "schedule" not in expr and "workflow_dispatch" not in expr and expr.endswith("&&'1'||'0'}}")


class _Item:
    def __init__(self, name, *marks):
        self.name, self.marks = name, marks

    def get_closest_marker(self, mark):
        return mark if mark in self.marks else None


def test_the_nightly_variable_deselects_only_nightly_tests(monkeypatch):
    from harness import store
    monkeypatch.setattr(store, "backend", lambda: store.SQLITE)
    monkeypatch.delenv(conftest.FAST_PATH_ENV, raising=False)
    gone = []
    config = SimpleNamespace(hook=SimpleNamespace(pytest_deselected=lambda items: gone.extend(items)))
    for flag, kept in (("1", ["fast", "long"]), ("0", ["fast", "slow", "long"])):
        items, gone[:] = [_Item("fast"), _Item("slow", "nightly"), _Item("long", "long")], []
        monkeypatch.setenv(conftest.NIGHTLY_ENV, flag)
        conftest.pytest_collection_modifyitems(config, items)
        assert [i.name for i in items] == kept and [i.name for i in gone] == (["slow"] if flag == "1" else [])
