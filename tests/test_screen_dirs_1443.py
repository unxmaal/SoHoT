"""Two screens named in the same second get two run dirs, so the second cannot overwrite the first. #1443."""
from harness import paths


def test_runs_named_in_the_same_second_get_their_own_dirs(tmp_path, monkeypatch):
    monkeypatch.setenv(paths.ENV_VAR, str(tmp_path))
    got = [paths.unused_run("screen-1793452737", "-code") for _ in range(3)]
    assert [p.name for p in got] == ["screen-1793452737-code", "screen-1793452737.2-code", "screen-1793452737.3-code"]
    assert all(p.is_dir() and p.parent == paths.runs() for p in got)


def test_an_existing_dir_is_never_handed_out_again(tmp_path, monkeypatch):
    monkeypatch.setenv(paths.ENV_VAR, str(tmp_path))
    held = paths.runs() / "chaos-screen-1"
    held.mkdir(parents=True)
    (held / "checkpoint.jsonl").write_text("kept\n", encoding="utf-8")
    assert paths.unused_run("chaos-screen-1") != held
    assert (held / "checkpoint.jsonl").read_text(encoding="utf-8") == "kept\n"
