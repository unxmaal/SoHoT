"""#555: the screen gives a candidate a case its method can take, and a
candidate with no such case is a gap, never harness_error."""
import argparse
from types import SimpleNamespace

import pytest
import yaml

from evals import environment
from evals import run as R
from evals.core import Result
from evals.runners.base import BaseRunner
from harness import screen
from harness import memory_store as ms

SVG = {
    "chart-bars": {"methods": ["llm"]},
    "icon-gear": {},
    "logo-mark": {},
}


def _cases(root, table):
    d = root / "svg"
    d.mkdir(parents=True)
    for cid, extra in table.items():
        (d / f"{cid}.yaml").write_text(yaml.safe_dump(
            {"id": cid, "modality": "svg", "prompt": f"draw {cid}", **extra}),
            encoding="utf-8")
    return root


class Recorder(BaseRunner):
    def __init__(self, spec):
        self.candidate = self.spec = spec
        self.ran = []

    def run(self, case):
        self.ran.append(case)
        return Result(case.id, self.candidate, True, 0.1, 0, "")


@pytest.fixture
def quiet(monkeypatch):
    for name, value in (("accelerator_id", "unified:test"), ("where_id", "test"),
                        ("swap_used_mb", 0), ("instruments", {}), ("engines", {})):
        monkeypatch.setattr(R, name, lambda *a, _v=value, **k: _v)
    monkeypatch.setattr(ms.machines, "_THIS_MACHINE", None)
    monkeypatch.setattr(environment, "capture", lambda: {})
    monkeypatch.setattr(R, "warn_if_pressed", lambda *a, **k: SimpleNamespace(
        as_dict=lambda: {}))


def _screen(tmp_path, monkeypatch, spec):
    runner = Recorder(spec)
    monkeypatch.setattr(R, "build_runner", lambda *a, **k: runner)
    R._execute(argparse.Namespace(
        screen=True, repeat=1, adherence="",
        cases=str(_cases(tmp_path / "cases", SVG)), modality="svg",
        candidates=spec, from_winners=False, gateway="http://gw.test",
        out=str(tmp_path / "out")))
    return runner


def test_an_omnisvg_screen_runs_a_case_its_method_can_take(tmp_path, monkeypatch,
                                                          quiet):
    runner = _screen(tmp_path, monkeypatch, "omnisvg:8B")
    assert len(runner.ran) == 1
    case = runner.ran[0]
    assert not case.methods or "omnisvg" in case.methods
    assert case.id == "icon-gear"


def test_an_llm_screen_still_runs_one_case(tmp_path, monkeypatch, quiet):
    runner = _screen(tmp_path, monkeypatch, "local-large")
    assert [c.id for c in runner.ran] == ["chart-bars"]


def test_a_candidate_with_no_fitting_case_is_a_gap_not_a_harness_error(
        tmp_path, monkeypatch):
    root = _cases(tmp_path / "cases", {"chart-bars": {"methods": ["llm"]}})
    monkeypatch.setattr(screen, "CASES", root, raising=False)
    from evals.runners.omnisvg import MODELS
    repo = MODELS["8B"][1]
    gap = screen.runner_gap("svg", repo)
    assert "omnisvg" in gap and "chart-bars" in gap
    row = screen.plan([{"name": repo, "lane": "svg"}], missing=lambda n: [])[0]
    assert row["state"] == screen.NO_RUNNER
    assert row["why_not"] == gap


def test_a_lane_with_a_fitting_case_has_no_gap(tmp_path, monkeypatch):
    monkeypatch.setattr(screen, "CASES", _cases(tmp_path / "cases", SVG),
                        raising=False)
    from evals.runners.omnisvg import MODELS
    assert screen.runner_gap("svg", MODELS["8B"][1]) == ""
    assert screen.runner_gap("svg", "org/some-svg-llm") == ""
