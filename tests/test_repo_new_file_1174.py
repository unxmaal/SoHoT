"""A file headed `--- a/P` whose hunks are all -0,0 is created when P is absent at base. #1174."""
import re
import subprocess
from pathlib import Path

import pytest

from evals import repo
from evals.analysis.demand import replay
from evals.core import load_cases

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "repo_new_file_1174"

CREATE = "--- a/n/new.py\n+++ b/n/new.py\n@@ -0,0 +1,2 @@\n+one\n+two\n"
CHANGE = "--- a/x\n+++ b/x\n@@ -1,3 +1,3 @@\n a\n-b\n+B\n c\n"


def _repo(path: Path, files: dict) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    for rel, text in files.items():
        (path / rel).parent.mkdir(parents=True, exist_ok=True)
        (path / rel).write_bytes(text.encode("utf-8"))
    run = lambda *a: subprocess.run(["git", *a], cwd=path, check=True, capture_output=True)  # noqa: E731
    run("init", "-q")
    run("add", "-A")
    run("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "base", "--allow-empty")
    return path


def _text(p: Path) -> str:
    return p.read_text(encoding="utf-8")


@pytest.mark.parametrize("order", ["create_first", "create_last"])
def test_an_absent_path_with_an_empty_old_side_applies_as_a_new_file(order, tmp_path):
    task = _repo(tmp_path, {"x": "a\nb\nc\n"})
    diff = CREATE + CHANGE if order == "create_first" else CHANGE + CREATE
    assert repo.apply(task, diff) == (True, "")
    assert (_text(task / "n" / "new.py"), _text(task / "x")) == ("one\ntwo\n", "a\nB\nc\n")


def test_the_rewrite_names_dev_null_and_a_new_file_mode():
    out = repo.with_git_headers(CREATE, lambda p: False)
    assert out.splitlines()[:3] == ["diff --git a/n/new.py b/n/new.py", "new file mode 100644", "--- /dev/null"]
    crlf = repo.with_git_headers(CREATE.replace("\n", "\r\n"), lambda p: False)
    assert "--- /dev/null\r\n" in crlf


def test_a_path_present_at_base_keeps_its_header(tmp_path):
    asked = []
    out = repo.with_git_headers(CREATE, lambda p: asked.append(p) or True)
    assert asked == ["n/new.py"]
    assert "--- a/n/new.py\n" in out and "/dev/null" not in out and "new file mode" not in out
    task = _repo(tmp_path, {"n/new.py": "zero\n"})
    applied, why = repo.apply(task, CREATE)
    assert (applied, "patch failed" in why, "already exists" in why) == (False, True, False)
    assert _text(task / "n" / "new.py") == "zero\n"


def test_a_hunk_with_an_old_side_keeps_the_header_on_an_absent_path():
    mixed = CREATE + "@@ -3,1 +5,1 @@\n-q\n+Q\n"
    assert "/dev/null" not in repo.with_git_headers(mixed, lambda p: False)


def test_without_a_base_nothing_is_turned_into_a_creation():
    assert "/dev/null" not in repo.with_git_headers(CREATE + CHANGE)


def test_a_creation_survives_a_skipped_doc_hunk(tmp_path):
    task = _repo(tmp_path, {"x": "a\nb\nc\n", "README.md": "r\ns\nt\n"})
    doc = "--- a/README.md\n+++ b/README.md\n@@ -1,3 +1,3 @@\n r\n-nope\n+S\n t\n"
    applied, why, skipped = repo.apply_docs_aside(task, doc + CREATE + CHANGE, lambda p: False)
    assert (applied, why, [s["path"] for s in skipped]) == (True, "", ["README.md"])
    assert _text(task / "n" / "new.py") == "one\ntwo\n"


def test_the_replay_check_applies_a_creation_headed_a():
    after = replay._apply({"x": {"base": "a\nb\nc\n", "post": "a\nB\nc\n"}}, CREATE + CHANGE)
    assert after == {"x": "a\nB\nc\n"}


def test_opus_858_spec_applies_to_its_base(tmp_path):
    params = next(c.params for c in load_cases(ROOT / "evals" / "cases" / "repo") if c.id == "sohot-858-spec")
    diff = (FIXTURES / "sohot-858-spec.diff").read_text(encoding="utf-8")
    got = subprocess.run(["git", "-C", str(ROOT), "cat-file", "-e", f"{params['base']}^{{commit}}"],
                         capture_output=True)
    if got.returncode:
        pytest.skip("a shallow checkout lacks the base commit; CI fetches full history")
    paths = sorted(set(re.findall(r"^\+\+\+ b/(\S+)", diff, re.M)))
    files = {}
    for p in paths:
        blob = subprocess.run(["git", "-C", str(ROOT), "show", f"{params['base']}:{p}"], capture_output=True)
        if not blob.returncode:
            files[p] = blob.stdout.decode("utf-8")
    assert "harness/memory_store/migrations/v71.py" not in files and "/dev/null" not in diff
    task = _repo(tmp_path / "task", files)
    assert repo.apply(task, diff) == (True, "")
    assert (task / "harness" / "memory_store" / "migrations" / "v71.py").is_file()
