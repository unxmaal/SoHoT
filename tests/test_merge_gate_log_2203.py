"""The merge gate keeps each step's output in a log and a failing verdict names it, so a red test-postgres can be diagnosed. #2203."""
from __future__ import annotations

import sys
from pathlib import Path

from harness import merge_gate as mg
from harness import paths
from tests.test_merge_gate_2110 import Suite, _pass, world  # noqa: F401 - the fixture

SAY = "import sys; print('to ' + 'stdout'); print('to ' + 'stderr', file=sys.stderr); sys.exit(3)"


def test_a_step_writes_its_output_and_its_rc_to_the_log_and_the_next_step_appends(tmp_path):
    log = tmp_path / "x.log"
    rc, out = mg._run([sys.executable, "-c", SAY], tmp_path, {}, log=log)
    assert (rc, out) == (3, "")
    rc, out = mg._run([sys.executable, "-c", "print('list' + 'ed')"], tmp_path, {}, capture=True, log=log)
    assert (rc, out) == (0, "listed\n")
    text = log.read_text(encoding="utf-8")
    assert "to stdout" in text and "to stderr" in text and "-> rc 3" in text
    assert text.index("-> rc 3") < text.index("listed") and text.endswith("-> rc 0\n")


def test_a_step_without_a_log_writes_none(tmp_path, capfd):
    assert mg._run([sys.executable, "-c", "print('lou' + 'd')"], tmp_path, {}) == (0, "")
    assert "loud" in capfd.readouterr().out and list(tmp_path.iterdir()) == []


def test_a_timed_out_step_says_so_in_the_log(tmp_path, monkeypatch):
    monkeypatch.setattr(mg, "STEP_TIMEOUT_S", 0.5)
    log = tmp_path / "x.log"
    assert mg._run([sys.executable, "-c", "import time; time.sleep(30)"], tmp_path, {}, log=log)[0] == mg.TIMED_OUT
    assert "timed out" in log.read_text(encoding="utf-8")


def test_a_failing_pass_names_the_log_of_the_head_it_tested_and_the_log_holds_the_steps(world, monkeypatch):
    seen = []

    def step(argv, cwd, env, capture=False, log=None):
        seen.append(log)
        with open(log, "a", encoding="utf-8") as f:
            f.write("collected 3 items\nFAILED tests/test_x.py::test_y\n")
        return 1, ""
    monkeypatch.setattr(mg, "_run", step)
    monkeypatch.setattr(mg, "DESCRIPTION_MAX", 1000)
    head = world["pr"](7, {"x": "x\n"})
    rows = mg.run_pass(world["live"], gh=world["hub"], say=lambda m: None, only=7)
    log = mg.log_path(head)
    assert rows[0]["state"] == mg.FAILURE and seen == [log]
    assert log.parent == paths.home() / "merge-gate" and log.name == f"{head[:12]}.log"
    assert world["hub"].said(head)[-1][1].endswith(f"make check failed, log {mg.shown(log)}")
    assert "FAILED tests/test_x.py::test_y" in log.read_text(encoding="utf-8")


def test_a_second_pass_on_a_head_starts_its_log_afresh(world, monkeypatch):
    def step(argv, cwd, env, capture=False, log=None):
        Path(log).open("a", encoding="utf-8").write("one line\n")
        return 1, ""
    monkeypatch.setattr(mg, "_run", step)
    head = world["pr"](7, {"x": "x\n"})
    for _ in range(2):
        mg.run_pass(world["live"], gh=world["hub"], say=lambda m: None, only=7, again=True)
    assert mg.log_path(head).read_text(encoding="utf-8") == "one line\n"


def test_a_passing_pass_leaves_the_status_without_a_log_name(world):
    world["pr"](7, {"x": "x\n"})
    rows, _ = _pass(world, Suite(), only=7)
    assert world["hub"].said(rows[0]["head"])[-1][1].endswith(": passed")


def test_the_description_under_the_home_names_the_log_and_fits_what_github_keeps(tmp_path, monkeypatch):
    monkeypatch.setenv(paths.ENV_VAR, str(tmp_path / ("h" * 12)))
    head = "0123456789ab" + "0" * 28
    said = mg.shown(mg.log_path(head), tmp_path)
    text = f"tree {'f' * 40} on {'e' * 12}: make test-postgres failed, log {said}"
    assert said == f"~/{'h' * 12}/merge-gate/0123456789ab.log"
    assert len(text) <= mg.DESCRIPTION_MAX
