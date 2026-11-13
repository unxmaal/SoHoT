"""A job and its pass through the hold, and a run and its rows, commit together or not at all. #1950, #1951."""
import sys

import pytest

from harness import cli, hold, paths, runs
from harness import memory_store as ms
from harness import workqueue as wq


class _Death(BaseException):
    """The process dying between two writes: nothing after it runs, nothing uncommitted survives."""


def test_a_despite_hold_job_that_dies_before_its_pass_commits_leaves_no_job(monkeypatch):
    def let(conn, job_id):
        conn.execute("UPDATE jobs SET despite_hold = 1 WHERE id = ?", (int(job_id),))
        raise _Death

    monkeypatch.setattr(hold, "let", let)
    with pytest.raises(_Death):
        cli.main(["jobs", "add", "--despite-hold", "--", sys.executable, "-c", "pass", "-m", "evals.run"])
    assert wq.pending() == []


def test_a_despite_hold_job_is_queued_already_let_through(capsys):
    assert cli.main(["jobs", "add", "--despite-hold", "--", sys.executable, "-c", "pass", "-m", "evals.run"]) == 0
    capsys.readouterr()
    (job,) = wq.pending()
    conn = ms.connect()
    try:
        assert conn.execute("SELECT despite_hold FROM jobs WHERE id = ?", (int(job["id"]),)).fetchone()[0] == 1
    finally:
        conn.close()


def _receipt(key="fake/key"):
    return {"generated": "2026-11-13T00:00:00", "environment": ms.this_machine(),
            "receipt": {"modality": "svg", "tier": "measure"}, "specs": {key: key},
            "rows": [{"case_id": c, "candidate": key, "passed": True, "seconds": 1.0, "peak_kb": 1, "detail": ""}
                     for c in ("a", "b")]}


def _rows(path):
    conn = ms.connect()
    try:
        return conn.execute("SELECT COUNT(*) FROM results r JOIN runs u ON u.id = r.run_id WHERE u.path = ?",
                            (runs.path_key(path),)).fetchone()[0]
    finally:
        conn.close()


def test_a_rerecord_that_dies_after_its_first_row_keeps_the_rows_it_had(monkeypatch):
    path = paths.runs() / "20261113-000000-000-0000-svg"
    path.mkdir(parents=True)
    conn = ms.connect()
    runs.record(conn, path, _receipt())
    conn.close()
    assert _rows(path) == 2
    real, seen = runs.row_fields, []

    def row_fields(*a, **k):
        seen.append(a)
        if len(seen) == 2:
            raise _Death
        return real(*a, **k)

    monkeypatch.setattr(runs, "row_fields", row_fields)
    conn = ms.connect()
    with pytest.raises(_Death):
        runs.record(conn, path, _receipt())
    conn.close()
    assert _rows(path) == 2
