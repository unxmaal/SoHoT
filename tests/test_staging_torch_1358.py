"""#1358: an image run with staging cases launches with the metrics group, and without torch staging is named, not a crash."""
import sys
from pathlib import Path

import pytest

from evals import core
from harness import holdout, paths, reasons, reverify, runner_gaps, screen, verify
from harness.checks import staging
from harness.commands import measure as measure_cmd

ROOT = Path(__file__).resolve().parents[1]
METRICS = ["uv", "run", "--group", "metrics", "python", "-m", "evals.run"]


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "home", lambda: tmp_path)
    monkeypatch.delenv("WHISPER_VENV", raising=False)
    return tmp_path


def _staged():
    return next(c for c in core.load_cases(ROOT / "evals" / "cases" / "image") if "staging" in c.assertions)


def test_a_staging_case_without_torch_is_a_named_missing_package_not_a_crash(tmp_path, monkeypatch):
    monkeypatch.delenv("SOH_STAGING_DEVICE", raising=False)
    monkeypatch.setitem(sys.modules, "torch", None)
    monkeypatch.setitem(sys.modules, "transformers", None)
    monkeypatch.setattr(staging, "_CACHE", {})
    from PIL import Image
    path = tmp_path / "out.png"
    Image.effect_noise((512, 512), 60).convert("RGB").save(path)
    r = core.CHECKERS["image"](path, _staged())
    assert not r.ok
    assert r.failure_class == reasons.MISSING_PACKAGE
    assert r.reason.startswith("staging not judged") and "torch" in r.reason and "--group metrics" in r.reason


def test_every_evals_run_launch_of_the_image_lane_carries_the_metrics_group(home):
    assert any("staging" in c.assertions for c in holdout.lane_cases("image"))
    assert runner_gaps.lane_groups("image") == ("metrics",)
    item = {"spec": "mflux:dev", "incumbent": "mflux:z-image-turbo", "lane": "image"}
    assert reverify.argv(item)[:7] == METRICS

    class Plan:
        repeat, side, budget_s, estimate = 1, "all", None, {}
    assert measure_cmd._argv("image", Plan(), home / "out", "mflux:dev", "mflux:z-image")[:7] == METRICS
    assert screen.argv({"candidate": "mflux:dev", "modality": "image"})[:7] == METRICS
    task, = verify.plan([{"lane": "image", "serves": "mflux:dev", "unverified": True, "stale": False}])
    assert task.argv[:7] == METRICS


def test_a_lane_with_no_staging_case_keeps_its_launcher(home):
    assert runner_gaps.lane_groups("svg") == ()
    item = {"spec": "svg:some/model", "incumbent": "", "lane": "svg"}
    assert reverify.argv(item)[:5] == ["uv", "run", "python", "-m", "evals.run"]
    assert screen.argv({"candidate": "svg:some/model", "modality": "svg"})[:3] == [sys.executable or "python",
                                                                                  "-m", "evals.run"]


def test_the_group_follows_the_cases_not_the_lane_name(tmp_path, monkeypatch):
    spec = core.load_case(_staged().source).source.read_text(encoding="utf-8")
    (tmp_path / "staged.yaml").write_text(spec, encoding="utf-8")
    monkeypatch.setattr(core, "local_root", lambda: tmp_path / "none")
    assert [c.modality for c in holdout.lane_cases("image", root=tmp_path)] == ["image"]
    assert runner_gaps.lane_groups("image", root=tmp_path) == ("metrics",)
    (tmp_path / "staged.yaml").unlink()
    (tmp_path / "plain.yaml").write_text("id: plain\nmodality: image\nprompt: a red fox\n", encoding="utf-8")
    assert runner_gaps.lane_groups("image", root=tmp_path) == ()
