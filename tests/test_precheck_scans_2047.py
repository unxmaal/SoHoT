"""make precheck runs every whole-tree scan test over the files the branch changes, and scope always selects them. #2047."""
import shutil
from pathlib import Path

from tests import tree_cache
from tests.gauntlet import precheck, scope
from tests.test_knob_merge import git

REPO = Path(__file__).resolve().parents[1]
KILL = "import os\n\n\ndef stop(pid):\n    os.killpg(pid, 15)\n"


def _repo(tmp_path):
    root = tmp_path / "repo"
    for rel in ("tests/tree_cache.py", "tests/test_portability.py"):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO / rel, root / rel)
    (root / "harness").mkdir()
    (root / "harness/__init__.py").write_text("", encoding="utf-8")
    (root / "harness/old.py").write_text(KILL, encoding="utf-8")
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "base")
    git(root, "update-ref", "refs/remotes/origin/main", "HEAD")
    return root


def test_a_killpg_in_a_changed_file_fails_precheck_and_one_in_an_unchanged_file_is_never_read(tmp_path, monkeypatch):
    monkeypatch.delenv(tree_cache.ENV, raising=False)
    root = _repo(tmp_path)
    assert precheck.tree_scans(root) == [], "nothing changed since the base"
    (root / "harness/new.py").write_text(KILL, encoding="utf-8")
    got = precheck.tree_scans(root)
    assert [p.subject for p in got] == [
        "tests/test_portability.py::test_no_posix_only_primitive_is_used_without_a_platform_guard"]
    text = "\n".join(got[0].fix)
    assert "harness/new.py:5: os.killpg" in text and "harness/old.py" not in text


def test_a_scan_only_run_reads_and_scans_only_the_listed_files(tmp_path, monkeypatch):
    for rel in ("a.py", "b.py"):
        (tmp_path / rel).write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setenv(tree_cache.ONLY_ENV, "b.py")
    seen = []
    tree_cache.each(lambda text, rel: seen.append(rel) or [], [("x = 1\n", "a.py"), ("x = 1\n", "b.py")])
    listed = [rel for _, rel in tree_cache.listed(tmp_path, lambda p: True, lister=lambda r: sorted(Path(r).glob("*.py")))]
    assert seen == ["b.py"] and listed == ["b.py"]


def test_every_tree_scan_test_is_found_and_always_selected():
    texts = {"harness/x.py": "X = 1\n", "tests/test_x.py": "from harness import x\n",
             "tests/test_walks.py": "from tests import tree_cache\n\ndef test_w():\n"
                                    "    assert tree_cache.each(f, items) == []\n\ndef test_unit():\n    pass\n"}
    assert tree_cache.scanning(texts) == {"tests/test_walks.py": ["test_w"]}
    chosen, _ = scope.select(["harness/x.py"], texts, {"tests/test_x.py", "tests/test_walks.py"})
    assert chosen == ["tests/test_walks.py", "tests/test_x.py"]
    found = tree_cache.scanning({p.relative_to(REPO).as_posix(): p.read_text(encoding="utf-8")
                                 for p in (REPO / "tests").glob("test_*.py")})
    assert {"tests/test_portability.py", "tests/test_gauntlet_scanners.py", "tests/test_mcp_import_guard_1221.py",
            "tests/test_no_drop_column.py"} <= set(found)
