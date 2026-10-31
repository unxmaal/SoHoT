"""An eval named into a directory whose checkpoint holds rows refuses without --resume, keeping them. #1441."""
from evals import watch
from tests.test_pause_813 import Ticking, _args, _run, clock, quiet  # noqa: F401


def test_a_run_without_resume_over_finished_rows_refuses_and_keeps_them(monkeypatch, tmp_path, quiet, clock, capsys):
    out = tmp_path / "run"
    first = Ticking(clock)
    assert _run(monkeypatch, first, _args(out, stop_at=clock.now + 45.0)) == watch.PAUSED
    before = (out / watch.CHECKPOINT).read_bytes()
    again = Ticking(clock)
    assert _run(monkeypatch, again, _args(out)) != 0
    assert again.ran == []
    assert (out / watch.CHECKPOINT).read_bytes() == before
    assert "--resume" in capsys.readouterr().err


def test_the_same_dir_with_resume_still_continues(monkeypatch, tmp_path, quiet, clock):
    out = tmp_path / "run"
    first = Ticking(clock)
    _run(monkeypatch, first, _args(out, stop_at=clock.now + 45.0))
    second = Ticking(clock)
    assert _run(monkeypatch, second, _args(out, resume=True)) == 0
    assert second.ran and not set(first.ran) & set(second.ran)


def test_a_checkpoint_with_only_its_header_starts_fresh(monkeypatch, tmp_path, quiet, clock):
    out = tmp_path / "run"
    out.mkdir()
    (out / watch.CHECKPOINT).write_text('{"identity": {"modality": "code"}}\n', encoding="utf-8")
    runner = Ticking(clock)
    assert _run(monkeypatch, runner, _args(out, stop_at=clock.now + 25.0)) == watch.PAUSED
    assert runner.ran
