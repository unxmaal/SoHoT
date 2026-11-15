"""A test that walks the repo's own tree is selected on every pull request, so a new site cannot pass the PR and fail main. #2053."""
import pytest

from tests.gauntlet import scope

NEW = "tests/test_new_2053.py"
NEW_TEXT = ("from harness import memory_store as ms\n\n"
            "def test_x(tmp_path):\n    ms.connect(tmp_path / 'x.db').close()\n")


def test_a_branch_adding_only_a_test_with_an_explicit_store_path_selects_the_store_path_scanner():
    files = scope.tracked() + [NEW]
    texts = {**scope.sources(files), NEW: NEW_TEXT}
    tests = {p for p in files if scope.is_test(p)}
    chosen, _ = scope.select([NEW], texts, tests, files)
    assert chosen is not None and NEW in chosen
    assert "tests/test_explicit_store_paths_1631.py" in chosen


@pytest.mark.parametrize("source,walks", [
    ("from pathlib import Path\nTESTS = Path(__file__).parent\ndef test_a():\n    list(TESTS.rglob('*.py'))\n", True),
    ("from pathlib import Path\nT = Path(__file__).parent\ndef scan(root=T):\n    return root.rglob('*.py')\n", True),
    ("from tests.gauntlet.mutation import REPO\ndef test_a():\n    list((REPO / 'harness').glob('**/*.py'))\n", True),
    ("import os\nfrom pathlib import Path\nR = Path(__file__).parents[1]\ndef test_a():\n    os.walk(R / 'evals')\n", True),
    ("def test_a(tmp_path):\n    list(tmp_path.rglob('*.py'))\n", False),
    ("from pathlib import Path\nG = Path(__file__).parent / 'golden'\ndef test_a():\n    list(G.rglob('*'))\n", False),
    ("from pathlib import Path\nF = Path(__file__).parent\ndef test_a():\n    list(F.glob('*.json'))\n", False),
])
def test_a_walk_counts_only_when_it_is_anchored_at_the_repo_and_not_a_data_tree(source, walks):
    assert (scope.walking({"tests/test_t.py": source}) == {"tests/test_t.py"}) is walks
    assert scope.walking({"harness/t.py": source}) == set()
