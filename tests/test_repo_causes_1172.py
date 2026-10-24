"""A diff against a file missing at base is its own cause, not unclassed. #1172."""
from evals.analysis import repo_failures as F
from tests.test_repo_causes_1128 import RANGED, _run

MISSING = "git apply: error: harness/memory_store/migrations/v71.py: No such file or directory"


def test_a_diff_against_a_missing_file_is_missing_file(tmp_path):
    run = F.load_run(_run(tmp_path, "r", {"m": ("invalid_patch", MISSING, RANGED, RANGED, 10, 20),
                                           "c": ("invalid_patch", "git apply: error: patch failed: x.py:1",
                                                 RANGED, RANGED, 10, 20)}))
    rows = F.causes(run, {})
    assert [r["cause"] for r in rows] == ["missing_file", "context_mismatch"]
    assert "| missing_file | 1 | 1 |" in F.cause_table(rows)
