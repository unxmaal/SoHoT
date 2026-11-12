"""A kill mid-append leaves a torn checkpoint line; the resume drops it and no later row is hidden. #1757."""
import json

import pytest

from evals import watch
from evals.analysis import repo_failures
from tests.test_pause_813 import Ticking, _args, _run, clock, quiet  # noqa: F401

TORN = '{"row": {"case_id": "half'


def _tear(path, torn=TORN):
    with path.open("a", encoding="utf-8") as f:
        f.write(torn)


@pytest.mark.parametrize("torn", [TORN, '{"row": {"case_id": "half", "wall_s": 9.0}}'])
def test_an_append_after_a_torn_line_starts_its_own_line_and_both_rows_read(tmp_path, torn):
    ck = watch.Checkpoint(tmp_path, {"a": 1})
    ck.add({"case_id": "x"}, 1.0)
    _tear(ck.path, torn)
    again = watch.Checkpoint(tmp_path, {"a": 1}, keep=True)
    again.add({"case_id": "y"}, 2.0)
    again.add({"case_id": "z"}, 3.0)
    text = ck.path.read_text(encoding="utf-8")
    assert text.endswith("\n") and "half" not in text
    assert all(json.loads(line) for line in text.splitlines())
    assert [r["case_id"] for r in watch.read(tmp_path)[1]] == ["x", "y", "z"]


def test_a_checkpoint_already_glued_by_an_older_resume_still_reads_the_rows_after_the_glue(tmp_path):
    ck = watch.Checkpoint(tmp_path, {"a": 1})
    ck.add({"case_id": "x"}, 1.0)
    _tear(ck.path)
    ck.add({"case_id": "lost"}, 2.0)
    ck.add({"case_id": "y"}, 3.0)
    assert [r["case_id"] for r in watch.read(tmp_path)[1]] == ["x", "y"]


def test_a_resume_after_a_kill_mid_append_never_reruns_what_it_finished(monkeypatch, tmp_path, quiet, clock):
    out = tmp_path / "run"
    first = Ticking(clock)
    assert _run(monkeypatch, first, _args(out, stop_at=clock.now + 45.0)) == watch.PAUSED
    _tear(out / watch.CHECKPOINT)
    second = Ticking(clock)
    assert _run(monkeypatch, second, _args(out, resume=True, stop_at=clock.now + 45.0)) == watch.PAUSED
    assert [r["case_id"] for r in watch.read(out)[1]] == first.ran + second.ran
    third = Ticking(clock)
    assert _run(monkeypatch, third, _args(out, resume=True)) == 0
    assert not set(third.ran) & (set(first.ran) | set(second.ran))


def test_the_repo_failure_report_reads_a_paused_checkpoint_with_a_torn_last_line(tmp_path):
    ck = watch.Checkpoint(tmp_path, {"a": 1})
    ck.add({"case_id": "x"}, 1.0)
    _tear(ck.path)
    got = repo_failures.load_run(tmp_path)
    assert got.receipt == {"a": 1} and [r["case_id"] for r in got.rows] == ["x"]
