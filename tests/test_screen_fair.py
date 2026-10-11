"""A screen is not a terminal verdict from one case at harness-chosen sampler settings (#691)."""
import inspect
from argparse import Namespace
from pathlib import Path

from evals.core import Case, load_cases
from evals.run import screen_cases, screen_pool
from harness import image_diffusers, reasons, screen
from harness.memory_store import revisit

REPO = Path(__file__).resolve().parent.parent
#: The decide incumbent's per-case pass rate on the holdout, KB #376.
INCUMBENT_RATE = 61 / 137
#: The chance a model as good as the incumbent may fail the screen.
MISS = 0.05


def _decide():
    return [c for c in screen_pool(load_cases(REPO / "evals" / "cases" / "decide")) if c.modality == "decide"]


def test_a_decide_screen_draws_enough_cases_that_a_model_as_good_as_the_incumbent_rarely_fails_it():
    picked = screen_cases(_decide(), ["eval-imajev-4b"])
    assert len(picked) > 1, [c.id for c in picked]
    assert (1 - INCUMBENT_RATE) ** len(picked) < MISS, len(picked)


def test_the_case_count_comes_from_the_incumbent_rate():
    k = screen.cases_needed(INCUMBENT_RATE, MISS)
    assert (1 - INCUMBENT_RATE) ** k < MISS <= (1 - INCUMBENT_RATE) ** (k - 1)
    assert screen.cases_needed(1.0, MISS) == 1


def test_a_screen_spreads_its_cases_across_the_lane_s_families():
    picked = screen_cases(_decide(), ["eval-imajev-4b"])
    families = {c.id.split("-")[0] for c in picked}
    assert len(families) > 1, [c.id for c in picked]


def test_a_screen_that_passes_nothing_is_declined_with_the_limit_that_reopens_it():
    summary = {"o/x": {"total": 6, "passed": 0, "failures": ["check-squad2-1: wrong field"],
                       "failure_classes": {reasons.CONTENT_FAILED: 6}}}
    v = screen.outcome(0, summary, candidate="o/x")
    assert (v.outcome, v.reason) == ("declined", reasons.LIMIT), v
    assert v.until.startswith("limit:screen_cases>"), v.until
    k = int(v.until.rpartition(">")[2])
    assert revisit.until_met(v.until, {"limits": {"screen_cases": k + 1}})
    assert not revisit.until_met(v.until, {"limits": {"screen_cases": k}})


def test_a_media_screen_that_passes_nothing_waits_on_the_screen_size():
    summary = {"diffusers/x": {"total": 3, "passed": 0, "failures": ["fox-snow: noise"],
                               "failure_classes": {reasons.CONTENT_FAILED: 3}}}
    v = screen.outcome(0, summary, candidate="diffusers:o/x")
    assert v.outcome == "declined" and v.until.startswith("limit:screen_size>"), v


def _stub_engine(case: Case, min_steps: int, min_size: int) -> dict:
    """An engine that renders noise below its card's steps or size and a real artifact at them."""
    p = case.params
    ok = p.get("steps", min_steps) >= min_steps and p.get("width", min_size) >= min_size
    return {"total": 1, "passed": int(ok), "failures": [] if ok else [f"{case.id}: noise"],
            "failure_classes": {} if ok else {reasons.CONTENT_FAILED: 1}}


def test_a_video_engine_that_fails_at_two_steps_and_passes_at_its_card_minimum_is_not_broken():
    video = load_cases(REPO / "evals" / "cases" / "video")
    picked = screen_cases(video, ["diffusers-video:o/x"])
    card_steps = video[0].params["steps"]
    summary = {"diffusers-video/x": _stub_engine(picked[0], card_steps, 0)}
    v = screen.outcome(0, summary, candidate="diffusers-video:o/x", key="diffusers-video/x")
    assert v.outcome != "broken", v
    assert picked[0].params["steps"] == card_steps


def test_a_model_that_fails_below_its_card_size_is_never_recorded_broken():
    image = load_cases(REPO / "evals" / "cases" / "image")
    picked = screen_cases(image, ["diffusers:o/x"])
    summary = {"diffusers/x": _stub_engine(picked[0], 0, 512)}
    v = screen.outcome(0, summary, candidate="diffusers:o/x", key="diffusers/x")
    assert v.outcome != "broken", v


def test_a_turbo_model_that_is_not_sdxl_turbo_gets_its_own_family_s_steps():
    got = image_diffusers.sampling("Tongyi-MAI/Z-Image-Turbo", None, None)
    assert got.get("num_inference_steps") == 9, got


def test_a_turbo_name_the_table_does_not_know_gets_the_pipeline_s_own_defaults():
    assert image_diffusers.sampling("someone/foo-turbo-lora-merge", None, None) == {}


class _Pipe:
    def __call__(self, prompt, num_inference_steps=28, guidance_scale=3.5):
        raise AssertionError("not called")


def test_the_steps_a_generation_used_are_recorded_beside_the_image():
    args = Namespace(model="Tongyi-MAI/Z-Image-Turbo", prompt="p", steps=None, guidance=None,
                     width=512, height=512, seed=1)
    meta = image_diffusers.metadata(args, _Pipe(), "mps", "2.6.0")
    assert (meta["steps"], meta["guidance"]) == (9, 0.0), meta
    args.model = "o/unknown"
    meta = image_diffusers.metadata(args, _Pipe(), "mps", "2.6.0")
    assert (meta["steps"], meta["guidance"]) == (28, 3.5), meta
    assert "metadata" in inspect.getsource(image_diffusers.main)
