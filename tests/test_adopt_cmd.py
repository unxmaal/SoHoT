"""soh adopt: a named challenger goes through the loop's measure-and-adopt. #464."""
from harness.commands import measure as measure_cmd
from harness import cli


def test_adopt_hands_the_challenger_to_the_paired_measure(monkeypatch):
    seen = []
    monkeypatch.setattr(measure_cmd, "_measure_and_adopt", lambda a, row: seen.append((a.repeat, row)) or 0)
    assert cli.main(["adopt", "--lane", "svg", "--challenger", "q3-30b", "--repeat", "3"]) == 0
    assert seen == [(3, {"name": "q3-30b", "lane": "svg"})]


def test_an_unknown_lane_is_refused_before_anything_runs(monkeypatch):
    monkeypatch.setattr(measure_cmd, "_measure_and_adopt", lambda a, row: (_ for _ in ()).throw(AssertionError("ran")))
    assert cli.main(["adopt", "--lane", "nope", "--challenger", "x"]) == 1


def test_a_nested_run_is_named_by_posix_path(windows_relative_paths):
    """#1079: the judge's run label for runs/a/b is a/b on Windows too."""
    from harness import paths
    from harness.commands import adopt
    assert adopt._run_name(paths.home() / "runs" / "a" / "b") == "a/b"
