"""The case tree and the production listing are walked once per change, not once per call (#1590)."""
import os
import shutil
import subprocess
import sys
from types import SimpleNamespace

import pytest
import yaml

from evals import core
from harness import holdout, knob_backlog, knobs, limit_trace, repo


@pytest.fixture(params=["cached", "fresh"])
def way(request, monkeypatch):
    if request.param == "fresh":
        monkeypatch.setattr(core, "sys", SimpleNamespace(platform="win32"))
    return request.param


def _rglob(root):
    return sorted((str(p), p.stat().st_mtime_ns, p.stat().st_size) for p in root.rglob("*") if p.is_file())


def _tree(tmp_path):
    root = tmp_path / "cases"
    (root / "a" / "b").mkdir(parents=True)
    (root / "a" / "one.yaml").write_text("x: 1\n", encoding="utf-8")
    (root / "a" / "b" / "two.txt").write_text("two\n", encoding="utf-8")
    (root / ".hidden").write_text("h\n", encoding="utf-8")
    return root


def test_files_lists_what_rglob_and_is_file_list(tmp_path, way):
    root = _tree(tmp_path)
    assert core.files(root) == _rglob(root)
    assert core.files(tmp_path / "absent") == []


def test_a_file_added_edited_or_removed_after_a_listing_is_seen(tmp_path, way):
    root = _tree(tmp_path)
    core.files(root)
    (root / "a" / "b" / "three.yaml").write_text("x: 3\n", encoding="utf-8")
    (root / "a" / "one.yaml").write_text("x: 1000\n", encoding="utf-8")
    (root / ".hidden").unlink()
    (root / "a" / "b" / "two.txt").rename(root / "a" / "moved.txt")
    assert core.files(root) == _rglob(root)
    assert sorted(os.path.basename(p) for p, _, _ in core.files(root)) == ["moved.txt", "one.yaml", "three.yaml"]


def test_an_edit_that_keeps_the_size_is_seen_by_its_mtime(tmp_path, way):
    root = _tree(tmp_path)
    before = dict((p, m) for p, m, _ in core.files(root))
    f = root / "a" / "one.yaml"
    f.write_text("x: 2\n", encoding="utf-8")
    st = f.stat()
    os.utime(f, ns=(st.st_atime_ns, st.st_mtime_ns + 10**9))
    assert dict((p, m) for p, m, _ in core.files(root))[str(f)] != before[str(f)]


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges on Windows")
def test_a_symlinked_directory_is_not_entered_and_a_symlinked_file_is_listed(tmp_path, way):
    root = _tree(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "far.yaml").write_text("x: 9\n", encoding="utf-8")
    (root / "linked").symlink_to(outside, target_is_directory=True)
    (root / "a" / "alias.txt").symlink_to(root / "a" / "b" / "two.txt")
    (root / "a" / "dangling.txt").symlink_to(tmp_path / "nowhere")
    assert core.files(root) == _rglob(root)
    assert not any("far.yaml" in p for p, _, _ in core.files(root))


def _case(root, cid, prompt="say hi"):
    (root / f"{cid}.yaml").write_text(yaml.safe_dump({
        "id": cid, "modality": "svg", "prompt": prompt, "methods": ["llm"],
        "assert": {"min_shapes": 1}}), encoding="utf-8")


def test_a_case_added_to_a_root_after_its_split_is_drawn(tmp_path):
    root = tmp_path / "cases"
    root.mkdir()
    for i in range(8):
        _case(root, f"c{i}")
    first = holdout.splits(root)["svg"]
    _case(root, "c8")
    again = holdout.splits(root)["svg"]
    assert "c8" not in first.dev + first.holdout
    assert "c8" in again.dev + again.holdout
    assert [c.id for c in core.load_cases(root)] == [f"c{i}" for i in range(9)]


def test_an_agent_bundle_edited_in_place_gets_a_new_digest(tmp_path):
    case = next(c for c in core.load_cases(core.SHIPPED / "agent") if c.params.get("repo_digest"))
    src = core.Path(case.source).parent
    copy = tmp_path / "agent"
    shutil.copytree(src / str(case.params["repo"]), copy / str(case.params["repo"]))
    yml = copy / core.Path(case.source).name
    shutil.copyfile(case.source, yml)
    bundle = copy / str(case.params["repo"]) / "repo"
    before = core.load_case(yml).params["repo_digest"]
    target = sorted(p for p in bundle.rglob("*") if p.is_file())[0]
    target.write_bytes(target.read_bytes() + b"\nedited\n")
    assert core.load_case(yml).params["repo_digest"] != before


def _git_tree(tmp_path):
    subprocess.run(("git", "init", "-q", str(tmp_path)), check=True)
    for rel, text in {"harness/a.py": "LIMIT = 3\n", "evals/cases/x/c.py": "MAX_X = 9\n",
                      "evals/runner.py": "MAX_RUN = 4\n", "scripts/s.sh": 'N="${N:-5}"\n',
                      "tests/test_t.py": "MAX_T = 1\n"}.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text, encoding="utf-8")
    subprocess.run(("git", "-C", str(tmp_path), "add", "."), check=True)
    (tmp_path / "evals" / "fresh").mkdir()
    (tmp_path / "evals" / "fresh" / "new.py").write_text("MAX_NEW = 2\n", encoding="utf-8")
    (tmp_path / "evals" / "loose.py").write_text("MAX_LOOSE = 6\n", encoding="utf-8")
    return tmp_path


def test_the_production_listing_is_publishable_filtered_and_sees_an_untracked_module(tmp_path):
    root = _git_tree(tmp_path)
    everything = repo.names(root)
    want = sorted(r for r in everything if knobs._production(r))
    assert sorted(r for r in repo.names(root, *knobs.production(root)) if knobs._production(r)) == want
    assert {"evals/fresh/new.py", "evals/loose.py", "evals/runner.py", "harness/a.py"} == set(want)
    assert [p.relative_to(root).as_posix() for p in repo.publishable(root)] == everything


def test_the_scanners_read_every_production_module_and_script(tmp_path):
    root = _git_tree(tmp_path)
    assert {s.split(":")[0] for s in knobs.inventory(root)} == {
        "harness/a.py", "evals/runner.py", "evals/fresh/new.py", "evals/loose.py", "scripts/s.sh"}
    assert {rel for rel, _ in limit_trace._modules(root)} == {
        "harness/a.py", "evals/runner.py", "evals/fresh/new.py", "evals/loose.py"}
    assert [rel for rel, _ in limit_trace._scripts(root)] == ["scripts/s.sh"]
    (root / "evals" / "fresh" / "q.py").write_text('x = f"over {MAX_NEW}"\n', encoding="utf-8")
    assert "evals/fresh/q.py" in {q.rel for q in knob_backlog.all_quotes(root)}
