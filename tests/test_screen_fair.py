"""A screen is not a terminal verdict from one case at harness-chosen sampler settings (#691)."""
import inspect
import json
from argparse import Namespace
from pathlib import Path

from evals.core import Case, load_cases
from evals.run import SCREEN_CASES, SCREEN_PARAMS, screen_cases, screen_counts, screen_pool, screen_until
from evals.runners import process
from harness import engines, image_diffusers, reasons, screen, video_cuda
from harness.memory_store import revisit

REPO = Path(__file__).resolve().parent.parent
#: The decide incumbent's per-case pass rate on the holdout, KB #376.
INCUMBENT_RATE = 61 / 137
#: The chance a model as good as the incumbent may fail the screen.
MISS = 0.05


def _decide():
    return [c for c in screen_pool(load_cases(REPO / "evals" / "cases" / "decide")) if c.modality == "decide"]


def _incumbent_rows(lane: str, ids, rate: float, draws: int = 20) -> list[dict]:
    """The lane incumbent's measure rows, passing each case `rate` of the time."""
    key = screen.incumbent_key(lane)
    hits = round(rate * draws)
    return [{"case_id": f"{c}#{k}", "candidate": key, "passed": k <= hits,
             "seconds": 1.0, "peak_kb": 0, "detail": ""}
            for c in ids for k in range(1, draws + 1)]


def test_a_decide_screen_draws_enough_cases_that_a_model_as_good_as_the_incumbent_rarely_fails_it(store_run):
    pool = _decide()
    store_run("20261011-000000-decide", "decide", rows=_incumbent_rows("decide", [c.id for c in pool], 0.45))
    picked = screen_cases(pool, ["eval-imajev-4b"])
    assert len(picked) > 1, [c.id for c in picked]
    assert (1 - INCUMBENT_RATE) ** len(picked) < MISS, len(picked)


def test_the_case_count_comes_from_the_incumbent_rate():
    k = screen.cases_needed(INCUMBENT_RATE, MISS)
    assert (1 - INCUMBENT_RATE) ** k < MISS <= (1 - INCUMBENT_RATE) ** (k - 1)
    assert screen.cases_needed(1.0, MISS) == 1


def test_a_lane_whose_incumbent_passes_most_cases_screens_on_few(store_run):
    pool = _decide()
    store_run("20261011-000000-decide", "decide", rows=_incumbent_rows("decide", [c.id for c in pool], 0.9))
    picked = screen_cases(pool, ["eval-imajev-4b"])
    assert len(picked) == screen.cases_needed(0.9, 1 - screen.SCREEN_CONFIDENCE) == 2, [c.id for c in picked]


def test_a_lane_whose_incumbent_rarely_passes_screens_up_to_the_case_cap_and_waits_on_it(store_run):
    pool = _decide()
    store_run("20261011-000000-decide", "decide", rows=_incumbent_rows("decide", [c.id for c in pool], 0.2))
    counts = screen_counts(pool)
    picked = screen_cases(pool, ["eval-imajev-4b"], counts)
    assert len(picked) == SCREEN_CASES < screen.cases_needed(0.2, 1 - screen.SCREEN_CONFIDENCE)
    assert screen_until(pool, picked, counts, pool) == f"limit:screen_cases>{SCREEN_CASES}"


def test_a_screen_the_cap_did_not_bind_waits_on_the_confidence(store_run):
    pool = _decide()
    store_run("20261011-000000-decide", "decide", rows=_incumbent_rows("decide", [c.id for c in pool], 0.9))
    counts = screen_counts(pool)
    until = screen_until(pool, screen_cases(pool, ["eval-imajev-4b"], counts), counts, pool)
    assert until == f"limit:screen_confidence>{screen.SCREEN_CONFIDENCE:g}", until
    assert revisit.until_met(until, {"limits": {"screen_confidence": 0.99}})
    assert not revisit.until_met(until, {"limits": {"screen_confidence": screen.SCREEN_CONFIDENCE}})


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


def test_the_until_the_screen_run_wrote_is_the_one_the_verdict_waits_on():
    summary = {"diffusers-video/x": {"total": 1, "passed": 0, "failures": ["fox-run: noise"],
                                     "failure_classes": {reasons.CONTENT_FAILED: 1},
                                     "screen_until": "cases:video>1"}}
    v = screen.outcome(0, summary, candidate="diffusers-video:o/x", key="diffusers-video/x")
    assert (v.outcome, v.until) == ("declined", "cases:video>1"), v


def test_a_media_screen_that_passes_nothing_waits_on_the_screen_size():
    summary = {"diffusers/x": {"total": 3, "passed": 0, "failures": ["fox-snow: noise"],
                               "failure_classes": {reasons.CONTENT_FAILED: 3}}}
    v = screen.outcome(0, summary, candidate="diffusers:o/x")
    assert v.outcome == "declined" and v.until.startswith("limit:screen_size>"), v


def test_an_image_screen_shrunk_below_its_cases_waits_on_the_screen_size():
    image = load_cases(REPO / "evals" / "cases" / "image")
    counts = screen_counts(image)
    picked = screen_cases(image, ["diffusers:o/x"], counts)
    assert screen_until(image, picked, counts, image) == f"limit:screen_size>{SCREEN_PARAMS['width']}"


def test_a_video_screen_short_of_cases_waits_on_the_lane_gaining_one():
    video = load_cases(REPO / "evals" / "cases" / "video")
    counts = screen_counts(video)
    picked = screen_cases(video, ["diffusers-video:o/x"], counts)
    until = screen_until(video, picked, counts, video)
    assert until == f"cases:video>{len(video)}", until
    assert revisit.until_met(until, {"cases": {"video": len(video) + 1}})
    assert not revisit.until_met(until, {"cases": {"video": len(video)}})
    assert not revisit.until_met(until, {"limits": {"screen_size": 1024}})


def _stub_engine(case: Case, min_steps: int, min_size: int) -> dict:
    """An engine that renders noise below its card's steps or size and a real artifact at them."""
    p = case.params
    ok = p.get("steps", min_steps) >= min_steps and p.get("width", min_size) >= min_size
    return {"total": 1, "passed": int(ok), "failures": [] if ok else [f"{case.id}: noise"],
            "failure_classes": {} if ok else {reasons.CONTENT_FAILED: 1}}


def test_a_model_that_fails_below_its_card_size_is_never_recorded_broken():
    image = load_cases(REPO / "evals" / "cases" / "image")
    picked = screen_cases(image, ["diffusers:o/x"])
    summary = {"diffusers/x": _stub_engine(picked[0], 0, 512)}
    v = screen.outcome(0, summary, candidate="diffusers:o/x", key="diffusers/x")
    assert v.outcome != "broken", v


def test_a_diffusers_video_model_runs_at_its_own_steps_not_the_case_s():
    fox = load_cases(REPO / "evals" / "cases" / "video")[0]
    assert fox.params.get("steps") == 4
    argv = engines.resolve("diffusers-video:Lightricks/LTX-Video").argv(fox.prompt, Path("o.mp4"), fox.params)
    assert "--steps" not in argv, argv
    argv = engines.resolve("diffusers-video:Lightricks/LTX-Video,steps=30").argv(fox.prompt, Path("o.mp4"), fox.params)
    assert argv[argv.index("--steps") + 1] == "30", argv


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


def test_video_diffusers_leaves_steps_and_guidance_to_the_pipeline_and_records_what_it_used():
    args = video_cuda.parse_args(["--model", "o/x", "--prompt", "p", "--output", "o.mp4"])
    assert (args.steps, args.guidance) == (None, None)
    meta = video_cuda.metadata(args, _Pipe(), "cuda", "2.6.0")
    assert (meta["steps"], meta["guidance"]) == (28, 3.5), meta
    assert "metadata" in inspect.getsource(video_cuda.main)


def test_the_steps_a_media_engine_used_reach_the_receipt_row(tmp_path):
    out = tmp_path / "fox-snow.png"
    out.write_bytes(b"png")
    out.with_suffix(".json").write_text(json.dumps({"steps": 9, "guidance": 0.0, "model": "m"}),
                                        encoding="utf-8")
    got = process._runtime_of(out)
    assert (got.get("steps"), got.get("guidance")) == ("9", "0.0"), got
