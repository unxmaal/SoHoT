"""Every committed repo case shows only files its base commit has, and names as new only files it lacks. #913."""
import os
import subprocess
from pathlib import Path

import pytest

from evals.core import load_cases
from evals.importers import history

ROOT = Path(__file__).resolve().parents[1]
CASES = [c for c in load_cases(ROOT / "evals" / "cases" / "repo")
         if c.params["source_repo"] == history.REPO_URL]


def _missing(objects) -> set:
    """The `rev:path` names this checkout's object store does not hold."""
    got = subprocess.run(["git", "-C", str(ROOT), "cat-file", "--batch-check"], check=True,
                         input="".join(f"{o}\n" for o in objects), capture_output=True, text=True)
    return {line.rsplit(" ", 1)[0] for line in got.stdout.splitlines() if line.endswith(" missing")}


def test_the_repo_lane_has_cases_from_this_repository():
    assert len(CASES) >= 40


def test_every_case_base_commit_is_in_this_checkout():
    gone = _missing(f"{c.params['base']}^{{commit}}" for c in CASES)
    if gone and not os.environ.get("CI"):
        pytest.skip(f"a shallow checkout lacks {len(gone)} base commits; CI fetches full history")
    assert not gone, "fetch the full history (actions/checkout fetch-depth: 0)"


def test_every_context_file_exists_at_base_and_no_new_file_does():
    if _missing(f"{c.params['base']}^{{commit}}" for c in CASES):
        pytest.skip("base commits not in this checkout")
    shown = [(c.id, f"{c.params['base']}:{p}") for c in CASES for p in c.params["context_files"]]
    new = [(c.id, f"{c.params['base']}:{p}") for c in CASES for p in c.params.get("new_files") or []]
    absent = _missing(o for _, o in shown)
    assert not absent, [f"{i}: {o.split(':', 1)[1]}" for i, o in shown if o in absent]
    gone = _missing(o for _, o in new)
    assert not [o for _, o in new if o not in gone], \
        [f"{i}: {o.split(':', 1)[1]} already exists" for i, o in new if o not in gone]
