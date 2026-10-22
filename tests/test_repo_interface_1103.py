"""The prompt states the names and signatures the hidden tests call, never the tests themselves. #1103."""
import subprocess

import pytest

from evals import interface, repo
from evals.importers import history

#: An account path a fix's default could carry, split so the privacy lint does not read this file as one.
HOME = "/Users/" + "alice/"
BASE = {"pkg/__init__.py": "", "pkg/mod.py": "def kept(x):\n    return x\n\n\ndef resigned(x):\n    return x\n\n\n"
        "class Box:\n    def old(self):\n        pass\n",
        "pkg/other.py": "def untouched():\n    pass\n", "tests/__init__.py": "", "tests/helpers.py": "def h():\n    pass\n"}
FIX = {"pkg/mod.py": "def kept(x):\n    return x\n\n\ndef resigned(x, *, strict: bool = False) -> int:\n    return x\n\n\n"
       "def new_fn(a, b):\n    return a + b\n\n\ndef _by_name():\n    pass\n\n\ndef _listed():\n    pass\n\n\n"
       f"def where(path='{HOME}data'):\n    pass\n\n\n"
       "class Box:\n    def old(self):\n        pass\n\n    def fresh(self, n: int) -> str:\n        return ''\n",
       "pkg/__init__.py": "from .mod import new_fn as reexported\n",
       "tests/helpers.py": "def h():\n    pass\n\n\ndef h2(n):\n    pass\n",
       "pkg/fresh.py": "LIMIT: int = 7\n\n\nclass Thing:\n    def __init__(self, size, colour='red'):\n        pass\n",
       "tests/test_new.py": (
           "import json\nimport pkg.mod as m\nfrom pkg import fresh, reexported\nfrom pkg.mod import new_fn, kept, Box\n"
           "from pkg.other import untouched\nfrom tests.helpers import h, h2\n\n\n"
           "def test_body_only_xyzzy():\n    assert new_fn(40, 2) == 42, 'SECRET_EXPECTED_xyzzy'\n"
           "    assert m.resigned(1, strict=True) == 1\n    assert Box().fresh(3) == '' and Box().old() is None\n"
           "    assert fresh.Thing(2) and fresh.LIMIT and reexported and kept and untouched and h and h2 and json\n"
           "    assert hasattr(m, '_by_name') and '_listed' in dir(m) and m.where()\n")}


def _git(cwd, *args):
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *args], cwd=cwd, check=True,
                   capture_output=True)


def _write(root, files):
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8")


def _fixture(tmp_path):
    _git(tmp_path, "init", "-q")
    _write(tmp_path, BASE)
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "base")
    _write(tmp_path, FIX)
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "fix")
    sha = lambda ref: subprocess.run(["git", "rev-parse", ref], cwd=tmp_path, capture_output=True,
                                     text=True, check=True).stdout.strip()
    return tmp_path / ".git", sha("HEAD^"), sha("HEAD")


WANT = ["class pkg.fresh.Thing(size, colour='red')",
        "pkg.fresh.LIMIT: int",
        "pkg.mod.Box.fresh(self, n: int) -> str",
        "pkg.mod._by_name()",
        "pkg.mod._listed()",
        "pkg.mod.new_fn(a, b)",
        "pkg.mod.resigned(x, *, strict: bool=False) -> int",
        f"pkg.mod.where(path='{HOME}data')",
        "pkg.reexported(a, b)"]
SHOWN = [line.replace(HOME, "~/") for line in WANT]


def test_the_interface_is_what_the_tests_use_that_the_fix_adds_or_resigns(tmp_path):
    mirror, base, fix = _fixture(tmp_path)
    assert interface.tests_call(mirror, base, fix) == WANT


def test_the_prompt_gains_the_signatures_and_nothing_from_the_test_body(tmp_path):
    mirror, base, fix = _fixture(tmp_path)
    got = history.refresh({"tasks": [{"base": base, "fix": fix, "context_files": ["pkg/mod.py"],
                                      "new_files": ["pkg/fresh.py"]}]}, mirror)["tasks"][0]
    row = {**got, "id": "fx-1", "issue": 1, "pr": 2, "date": "2026-10-22", "variant": "symptom",
           "prompts": {"spec": "# Add new_fn\n\nIt should add.", "symptom": "# Adding is missing"},
           "fail_to_pass": ["tests/test_new.py::test_body_only_xyzzy"], "pass_to_pass": []}
    case = history.convert(row).case
    assert case["prompt"].startswith("# Adding is missing\n\n" + interface.HEAD)
    assert "- `pkg.mod.new_fn(a, b)`" in case["prompt"]
    for leak in ("xyzzy", "42", "40, 2", "strict=True", "assert", "kept", "untouched", "tests.helpers", HOME):
        assert leak not in case["prompt"], leak
    assert case["params"]["interface"] == SHOWN
    repo.validate(case["id"], case["params"])
    with pytest.raises(ValueError, match="params.interface"):
        repo.validate(case["id"], {**case["params"], "interface": [1]})


def test_a_task_whose_tests_need_nothing_new_keeps_its_prompt(tmp_path):
    mirror, base, fix = _fixture(tmp_path)
    row = {"id": "fx-1", "issue": 1, "pr": 2, "date": "2026-10-22", "variant": "spec", "base": base, "fix": fix,
           "prompts": {"spec": "# Add new_fn"}, "context_files": ["pkg/mod.py"], "interface": [],
           "fail_to_pass": ["tests/test_new.py::test_body_only_xyzzy"], "pass_to_pass": []}
    case = history.convert(row).case
    assert case["prompt"] == "# Add new_fn" and "interface" not in case["params"]
    assert interface.block([]) == ""


def test_every_committed_history_case_shows_its_manifest_interface():
    for src in history.repos():
        for row in history.fetch(src=src):
            case = history.convert(row, src).case
            calls = row.get("interface")
            assert calls is not None, f"{case['id']}: manifest has no interface; run --refresh"
            assert (interface.block(calls) in case["prompt"]) if calls else interface.HEAD not in case["prompt"]
