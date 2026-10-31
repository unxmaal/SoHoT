"""A worktree reads the main checkout's private names, and the lint and the redactor share one reader. #1308."""
import re
import subprocess
from pathlib import Path

import pytest

from evals import decide_corpus, redact
from harness import privacy, repo

ROOT = Path(__file__).resolve().parent.parent
NAME = "Zorblax Quentaro"
OTHER = "Plimbo Varrak"


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True)


@pytest.fixture
def checkout(tmp_path, monkeypatch):
    """(main checkout holding the names file, a worktree made from it with `git worktree add`)."""
    monkeypatch.delenv("LH_PRIVATE_NAMES", raising=False)
    main, wt = tmp_path / "main", tmp_path / "wt"
    main.mkdir()
    _git(main, "init", "-q", "-b", "main")
    _git(main, "config", "user.email", "t@example.invalid")
    _git(main, "config", "user.name", "t")
    (main / "f").write_text("x\n", encoding="utf-8")
    _git(main, "add", "f")
    _git(main, "commit", "-q", "-m", "one")
    _git(main, "worktree", "add", "-q", "-b", "agent", str(wt))
    (main / privacy.NAMES_FILE).write_text(f"{NAME}\n", encoding="utf-8")
    return main, wt


def test_a_worktree_reads_the_main_checkouts_names(checkout):
    _, wt = checkout
    assert not (wt / privacy.NAMES_FILE).exists()
    assert privacy.names(wt) == [NAME]
    found = privacy.scan(f"{NAME} merged it", "t", privacy.name_pattern(wt))
    assert [f.name for f in found] == ["person-name"]


def test_the_main_checkout_reads_its_own_file_once(checkout):
    main, _ = checkout
    assert privacy.name_files(main) == [main / privacy.NAMES_FILE]
    assert privacy.names(main) == [NAME]


def test_a_worktrees_own_names_join_the_main_checkouts(checkout):
    _, wt = checkout
    (wt / privacy.NAMES_FILE).write_text(f"{OTHER}\n{NAME}\n", encoding="utf-8")
    assert privacy.names(wt) == [OTHER, NAME]


def test_outside_git_only_the_given_root_is_read(tmp_path, monkeypatch):
    monkeypatch.delenv("LH_PRIVATE_NAMES", raising=False)
    assert privacy.main_checkout(tmp_path) is None
    (tmp_path / privacy.NAMES_FILE).write_text(f"{NAME}\n", encoding="utf-8")
    assert privacy.names(tmp_path) == [NAME]


def test_the_redactor_takes_its_private_names_from_the_privacy_lint(monkeypatch):
    seen = []
    monkeypatch.setattr(privacy, "names", lambda root: seen.append(root) or [NAME])
    assert NAME in redact.known_here().names
    assert seen == [ROOT]


def _readers(pattern: str) -> list[str]:
    pat = re.compile(pattern)
    out = []
    for p in repo.publishable(ROOT):
        rel = p.relative_to(ROOT) if p.is_absolute() else p
        if rel.suffix in (".py", ".sh") and rel.parts[0] in ("harness", "evals", "scripts") \
                and pat.search((ROOT / rel).read_text(encoding="utf-8")):
            out.append(rel.as_posix())
    return sorted(out)


def test_one_module_finds_the_names_files_and_one_finds_the_main_checkout():
    """One question, two answers: a second reader of .privacy-names is how worktrees went blind. #1308."""
    assert _readers(r"\.privacy-names|(?<!HOME_)\bNAMES_FILE\b|git-common-dir") == ["harness/privacy.py"]
    assert _readers(r"commondir") == ["harness/repo.py"]


def test_a_generated_decide_case_ships_no_private_name(monkeypatch):
    monkeypatch.setenv("LH_PRIVATE_NAMES", NAME)
    case = {"id": "policy-x", "prompt": "Apply the policy.", "context": f"Ask {NAME} and Wood soonest.",
            "schema": {}, "answers": {}, "source": "civil_comments", "record": "x", "label": "y"}
    out = decide_corpus.case_yaml(case)
    assert NAME not in out
    assert f"Ask {decide_corpus.NAME_MASK} and Wood soonest." in out
