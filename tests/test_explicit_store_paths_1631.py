"""A test that opens a store at an explicit path runs it on SQLite under check-postgres, so each one is listed with why. #1631."""
import ast
from pathlib import Path

import pytest

TESTS = Path(__file__).parent
LIST = TESTS / "gauntlet" / "explicit_store_paths.txt"
TODO = "#1631"
#: Sites still to move onto this home's store; may only fall.
TODO_PIN = 0
ALIASES = {"ms", "memory_store", "connection"}


def _marked(nodes) -> bool:
    return any("sqlite_store" in ast.unparse(d) for n in nodes for d in getattr(n, "decorator_list", ()))


def _module_marked(tree) -> bool:
    return any(isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "pytestmark" for t in n.targets)
               and "sqlite_store" in ast.unparse(n.value) for n in tree.body)


def scan(root: Path = TESTS) -> dict[str, int]:
    """{"tests/x.py::qualname": sites} for every memory_store.connect(<path>) outside a sqlite_store test."""
    found: dict[str, int] = {}
    for f in sorted(root.rglob("*.py")):
        rel = f.relative_to(root.parent).as_posix()
        if "/cases/" in rel:
            continue
        tree = ast.parse(f.read_text(encoding="utf-8"))
        if _module_marked(tree):
            continue

        def walk(node, stack):
            for child in ast.iter_child_nodes(node):
                inner = stack + [child] if isinstance(
                    child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) else stack
                if (isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute)
                        and child.func.attr == "connect" and isinstance(child.func.value, ast.Name)
                        and child.func.value.id in ALIASES and (child.args or child.keywords)
                        and not _marked(stack)):
                    key = f"{rel}::{'.'.join(s.name for s in stack) or '<module>'}"
                    found[key] = found.get(key, 0) + 1
                walk(child, inner)
        walk(tree, [])
    return found


def listed(path: Path = LIST) -> dict[str, str]:
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            key, _, reason = line.partition(" ")
            out[key] = reason.strip()
    return out


def test_every_explicit_store_path_in_a_test_is_listed_with_a_reason():
    got, have = scan(), listed()
    new = sorted(set(got) - set(have))
    assert not new, ("open this home's store (ms.connect(), ms.db_path()) so check-postgres runs the SQL, mark the "
                     "test sqlite_store if the SQLite file is its subject, or list it with why in "
                     f"{LIST.name}:\n  " + "\n  ".join(new))
    gone = sorted(set(have) - set(got))
    assert not gone, f"no explicit store path left: remove from {LIST.name}:\n  " + "\n  ".join(gone)
    assert all(have.values()), [k for k, v in have.items() if not v]


def test_the_sites_left_to_move_only_shrink():
    todo = [k for k, v in listed().items() if v == TODO]
    assert len(todo) <= TODO_PIN, f"{len(todo)} sites listed {TODO}, pinned at {TODO_PIN}: move the new one instead"
    assert len(todo) == TODO_PIN, f"{len(todo)} sites listed {TODO}: lower TODO_PIN to it"


def test_the_list_is_sorted_and_unique():
    lines = [ln for ln in LIST.read_text(encoding="utf-8").splitlines() if ln and not ln.startswith("#")]
    keys = [ln.split(" ")[0] for ln in lines]
    assert keys == sorted(set(keys))


@pytest.mark.parametrize("source,expect", [
    ("def test_a(tmp_path):\n    ms.connect(tmp_path / 's.db')\n", {"tests/t.py::test_a": 1}),
    ("def test_a():\n    ms.connect()\n", {}),
    ("@pytest.mark.sqlite_store\ndef test_a(tmp_path):\n    ms.connect(tmp_path / 's.db')\n", {}),
    ("pytestmark = pytest.mark.sqlite_store\ndef test_a(p):\n    ms.connect(p)\n", {}),
    ("class TestX:\n    def test_a(self, p):\n        memory_store.connect(path=p)\n", {"tests/t.py::TestX.test_a": 1}),
    ("def helper(p):\n    return ms.connect(p), ms.connect(p)\n", {"tests/t.py::helper": 2}),
])
def test_the_scan_finds_an_explicit_path_and_skips_a_sqlite_store_test(tmp_path, source, expect):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "t.py").write_text(source, encoding="utf-8")
    assert scan(tmp_path / "tests") == expect
