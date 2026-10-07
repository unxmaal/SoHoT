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


def test_the_gap_names_every_case_and_the_methods_it_takes(tmp_path, monkeypatch):
    monkeypatch.setattr(screen, "CASES", _cases(tmp_path / "cases", {
        "a": {"methods": ["llm"]}, "b": {"methods": ["llm", "agent"]}}), raising=False)
    assert screen.case_gap("svg", "omnisvg:8B") == (
        "no svg case fits the omnisvg method (a takes llm, b takes llm/agent)")


# ---- the store's card picks the engine and names the gap (#563, #601, #596) ----

def _carded(tmp_path, name, lane, **cols):
    conn = ms.connect(tmp_path / "s.db")
    ms.record(conn, ms.Seen(name=name, source="t", lane=lane, registry=ms.HUGGINGFACE,
                            resolved=name))
    conn.execute(f"UPDATE proposals SET {', '.join(f'{k} = ?' for k in cols)} WHERE name = ?",
                 (*cols.values(), name))
    conn.commit()
    return conn


def test_a_stored_card_picks_the_engine_its_task_names(tmp_path):
    conn = _carded(tmp_path, "org/emb", "retrieval", hf_task="feature-extraction")
    try:
        assert screen.candidate_for("retrieval", "org/emb", conn=conn) == "embed:org/emb"
        assert screen.candidate_for("retrieval", "org/emb") == "rerank:org/emb"
    finally:
        conn.close()


def test_a_stored_card_tagged_mlx_is_a_runner_gap(tmp_path):
    conn = _carded(tmp_path, "org/ocr-mlx", "ocr", card_tags='["mlx"]')
    try:
        assert screen.runner_gap("ocr", "org/ocr-mlx", conn=conn).startswith(
            "needs its own runner: its card is tagged mlx")
    finally:
        conn.close()


def test_the_first_engine_that_takes_the_model_wins():
    assert screen.no_runner("mflux:org/some-model")
    assert screen.candidate_for("image", "org/some-model") == "diffusers:org/some-model"


def test_a_method_or_a_gguf_stem_on_the_config_stays_off_the_upstream(tmp_path, monkeypatch):
    from harness import gguf
    cfg = tmp_path / "gateway.yaml"
    cfg.write_text(yaml.safe_dump({"model_list": [{"model_name": "org/listed", "litellm_params": {
        "model": "openai/x", "api_base": "http://127.0.0.1:8081/v1"}}]}), encoding="utf-8")
    monkeypatch.setattr(gguf, "fetched", lambda model, *a: None)
    monkeypatch.setattr(gguf, "hub_stem", lambda model: "stem" if model == "org/g" else None)
    assert screen.routed_gateway("best-of:3:org/listed", cfg) == ""
    assert screen.routed_gateway("org/g", cfg) == ""
    assert screen.routed_gateway("org/x", cfg) == "http://127.0.0.1:8081"
