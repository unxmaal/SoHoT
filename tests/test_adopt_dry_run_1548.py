"""`soh adopt --dry-run` prints the plan on every path and runs and records nothing; a mode that cannot dry-run refuses. #1548."""
import sqlite3

import pytest

from harness import adopt, cli, paths
from harness import memory_store as ms
from harness.commands import measure as measure_cmd
from tests.test_lent_store_1426 import _counts
from tests.test_resume_813 import CH, INC


def _nothing_runs(*a, **k):
    raise AssertionError(f"a dry run launched {a[:1]}")


@pytest.fixture
def home(monkeypatch):
    ms.connect().close()
    monkeypatch.setattr(adopt, "default_for", lambda lane, fallback, conn=None: INC)
    monkeypatch.setattr(measure_cmd, "_launch", _nothing_runs)
    return ms.db_path()


def _connects(monkeypatch) -> list:
    opened, real = [], ms.connect
    monkeypatch.setattr(ms, "connect", lambda *a, **k: opened.append(a) or real(*a, **k))
    return opened


def test_a_paired_dry_run_prints_the_plan_and_runs_and_records_nothing(home, monkeypatch, capsys):
    before = _counts(home)
    opened = _connects(monkeypatch)
    assert cli.main(["adopt", "--lane", "code", "--challenger", CH, "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "power: repeat" in out and "-m evals.run --modality code" in out and f"{INC},{CH}" in out
    assert "dry run" in out
    assert not (paths.home() / "runs").exists() or not any((paths.home() / "runs").iterdir())
    assert _counts(home) == before
    assert len(opened) <= 1, opened


def test_a_paired_dry_run_reads_the_store_without_a_writable_connection(home, monkeypatch):
    """The lent connection is read-only, so a write anywhere on the path fails instead of landing."""
    seen = []
    real = ms.lend

    def spy(conn):
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("CREATE TABLE dry_run_probe (x)")
        seen.append(conn)
        return real(conn)

    monkeypatch.setattr(ms, "lend", spy)
    assert cli.main(["adopt", "--lane", "code", "--challenger", CH, "--dry-run"]) == 0
    assert seen


def test_a_dry_run_of_a_challenger_that_is_already_the_default_records_nothing(home, monkeypatch, capsys):
    before = _counts(home)
    assert cli.main(["adopt", "--lane", "code", "--challenger", INC, "--dry-run"]) == 0
    assert "already the code lane's default" in capsys.readouterr().out
    assert _counts(home) == before


def test_a_from_measurement_dry_run_still_records_nothing(home):
    before = _counts(home)
    assert cli.main(["adopt", "--lane", "code", "--from-measurement", "--dry-run"]) == 0
    assert _counts(home) == before


def test_a_power_dry_run_records_nothing(home):
    before = _counts(home)
    assert cli.main(["adopt", "--power", "--lane", "code", "--dry-run"]) == 0
    assert _counts(home) == before


def test_a_confirmation_cannot_dry_run_and_says_so(home, monkeypatch, capsys):
    monkeypatch.setattr(measure_cmd, "confirm_job", lambda v: pytest.fail("ran the confirmation"))
    assert cli.main(["adopt", "--confirm", "7", "--dry-run"]) != 0
    assert "--dry-run" in capsys.readouterr().err
