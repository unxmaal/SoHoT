"""A sampler setting one engine reads lives on that engine, not in the case. #735."""
from pathlib import Path

import yaml

from harness import engines

CASES = Path(__file__).resolve().parents[1] / "evals" / "cases"
#: Settings only an engine's sampler reads; a case that sets one is tuned to that engine.
SAMPLER = {"steps", "guidance"}


def _argv(spec, **params):
    eng = engines.resolve(spec)
    return eng.argv("a red fox", Path("/out.mp4"), params)


def test_h3_runs_at_its_own_steps_when_the_case_names_none():
    a = _argv("h3", frames=22, width=256, height=256, seed=42)
    assert a[a.index("--steps") + 1] == str(engines.H3_STEPS) == "4"
    assert a.count("--steps") == 1


def test_a_spec_option_still_sets_h3_steps():
    a = _argv("h3,steps=8", frames=22)
    assert a[a.index("--steps") + 1] == "8"
    a = _argv("h3", frames=22, steps=6)
    assert a[a.index("--steps") + 1] == "6"


def test_no_case_sets_an_engine_sampler_setting():
    found = []
    for path in sorted(CASES.rglob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for case in data if isinstance(data, list) else [data]:
            if isinstance(case, dict):
                found += [f"{path.relative_to(CASES).as_posix()}: {k}" for k in sorted(SAMPLER & set(case.get("params") or {}))]
    assert not found, found


def test_diffusers_video_still_runs_at_its_pipelines_own_steps():
    a = _argv("diffusers-video:org/model", frames=22, steps=4)
    assert "--steps" not in a
    a = _argv("diffusers-video:org/model,steps=30", frames=22)
    assert a[a.index("--steps") + 1] == "30"
