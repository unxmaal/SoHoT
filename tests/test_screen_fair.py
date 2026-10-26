"""A screen is not a terminal verdict from one case at harness-chosen sampler settings (#691)."""
import inspect
import json
import sys
from argparse import Namespace
from pathlib import Path

from evals.core import Case, load_cases
from evals.run import (SCREEN_CASES, SCREEN_PARAMS, screen_caveat, screen_cases, screen_counts, screen_pool,
                       screen_rates, screen_until)
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


#: The receipt key the live store's decide measure rows carry: the served model's pre-#670 name.
STORED_KEY = "eval-imajev-4b"


def _incumbent_rows(lane: str, ids, rate: float, draws: int = 20, key: str = STORED_KEY) -> list[dict]:
    """The lane incumbent's measure rows, under the key measure stored them, passing each case `rate` of the time."""
    hits = round(rate * draws)
    return [{"case_id": f"{c}#{k}", "candidate": key, "passed": k <= hits,
             "seconds": 1.0, "peak_kb": 0, "detail": ""}
            for c in ids for k in range(1, draws + 1)]


def test_a_decide_screen_draws_enough_cases_that_a_model_as_good_as_the_incumbent_rarely_fails_it(store_run):
    pool = _decide()
    store_run("20261011-000000-decide", "decide", specs={STORED_KEY: STORED_KEY}, rows=_incumbent_rows("decide", [c.id for c in pool], 0.45))
    picked = screen_cases(pool, ["eval-imajev-4b"])
    assert len(picked) > 1, [c.id for c in picked]
    assert (1 - INCUMBENT_RATE) ** len(picked) < MISS, len(picked)


def test_the_case_count_comes_from_the_incumbent_rate():
    k = screen.cases_needed(INCUMBENT_RATE, MISS)
    assert (1 - INCUMBENT_RATE) ** k < MISS <= (1 - INCUMBENT_RATE) ** (k - 1)
    assert screen.cases_needed(1.0, MISS) == 1


def test_a_lane_whose_incumbent_passes_most_cases_screens_on_few(store_run):
    pool = _decide()
    store_run("20261011-000000-decide", "decide", specs={STORED_KEY: STORED_KEY}, rows=_incumbent_rows("decide", [c.id for c in pool], 0.9))
    picked = screen_cases(pool, ["eval-imajev-4b"])
    assert len(picked) == screen.cases_needed(0.9, 1 - screen.SCREEN_CONFIDENCE) == 2, [c.id for c in picked]


def test_a_lane_whose_incumbent_rarely_passes_screens_up_to_the_case_cap_and_waits_on_it(store_run):
    pool = _decide()
    store_run("20261011-000000-decide", "decide", specs={STORED_KEY: STORED_KEY}, rows=_incumbent_rows("decide", [c.id for c in pool], 0.2))
    counts = screen_counts(pool)
    picked = screen_cases(pool, ["eval-imajev-4b"], counts)
    assert len(picked) == SCREEN_CASES < screen.cases_needed(0.2, 1 - screen.SCREEN_CONFIDENCE)
    assert screen_until(pool, picked, counts, pool) == f"limit:screen_cases>{SCREEN_CASES}"


def test_a_screen_the_cap_did_not_bind_waits_on_the_confidence(store_run):
    pool = _decide()
    store_run("20261011-000000-decide", "decide", specs={STORED_KEY: STORED_KEY}, rows=_incumbent_rows("decide", [c.id for c in pool], 0.9))
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
    params = {**fox.params, "steps": 4}
    argv = engines.resolve("diffusers-video:Lightricks/LTX-Video").argv(fox.prompt, Path("o.mp4"), params)
    assert "--steps" not in argv, argv
    argv = engines.resolve("diffusers-video:Lightricks/LTX-Video,steps=30").argv(fox.prompt, Path("o.mp4"), params)
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


def test_the_incumbent_rate_comes_from_the_rows_measure_stored_under_the_served_model_s_old_name(store_run):
    pool = _decide()
    store_run("20261011-000000-decide", "decide", specs={STORED_KEY: STORED_KEY},
              rows=_incumbent_rows("decide", [c.id for c in pool], 0.45))
    assert screen.incumbent_rate("decide", [c.id for c in pool]) == 0.45
    counts = screen_counts(pool)
    assert set(counts.values()) == {screen.cases_needed(0.45, MISS)} == {6}, counts


def test_an_incumbent_with_no_stored_rows_is_said_out_loud_and_on_the_run(store_run, capsys):
    pool = _decide()
    store_run("20261011-000000-decide", "decide", specs={"someone-else": "someone-else"},
              rows=_incumbent_rows("decide", [c.id for c in pool], 0.9, key="someone-else"))
    rates = screen_rates(pool)
    assert all(not measured for _, measured in rates.values()), rates
    assert "unmeasured" in capsys.readouterr().err
    caveat = screen_caveat(rates)
    assert "unmeasured" in caveat and "decide" in caveat, caveat
    summary = {"o/x": {"total": 5, "passed": 0, "failures": ["check-squad2-1: wrong field"],
                       "failure_classes": {reasons.CONTENT_FAILED: 5}, "screen_caveat": caveat}}
    v = screen.outcome(0, summary, candidate="o/x")
    assert v.outcome == "declined" and "unmeasured" in v.detail, v


def test_a_lane_with_exactly_the_cap_of_cases_and_needing_more_waits_on_the_lane_gaining_one():
    pool = _decide()[:SCREEN_CASES]
    group = (pool[0].modality, pool[0].language)
    counts = {group: SCREEN_CASES + 1}
    picked = screen_cases(pool, ["eval-imajev-4b"], counts)
    until = screen_until(pool, picked, counts, pool)
    assert until == f"cases:decide>{SCREEN_CASES}", until


def _screen_run(monkeypatch, tmp_path, modality: str, candidate: str) -> dict:
    """evals.run --screen with every case failing, and the results.json it wrote."""
    import contextlib

    from evals import run
    from evals.core import Result

    def fail_all(args, cand, runner, mine, results, outdir, evicted=None, ladder=(), *rest):
        results += [Result(candidate=runner.candidate, case_id=c.id, passed=False, seconds=1.0, peak_kb=0,
                           detail="noise", failure_class=reasons.CONTENT_FAILED) for c in mine]
    monkeypatch.setattr(run, "_run_candidate", fail_all)
    monkeypatch.setattr(run, "_servable", lambda c: None)
    monkeypatch.setattr(run, "_served", lambda c: contextlib.nullcontext({}))
    out = tmp_path / "run"
    run._execute(run.parse_args(["--modality", modality, "--screen", "--candidates", candidate,
                                 "--out", str(out)]))
    return json.loads((out / "results.json").read_text(encoding="utf-8"))


def test_the_screen_run_writes_the_until_its_zero_pass_waits_on_into_results_json(monkeypatch, tmp_path):
    video = load_cases(REPO / "evals" / "cases" / "video")
    got = _screen_run(monkeypatch, tmp_path, "video", "diffusers-video:o/x")
    (entry,) = got["summary"].values()
    assert entry["screen_until"] == f"cases:video>{len(video)}", entry
    v = screen.outcome(0, got["summary"], candidate="diffusers-video:o/x", key=next(iter(got["summary"])))
    assert v.until == entry["screen_until"], v


def test_a_screen_run_whose_incumbent_rate_is_unmeasured_says_so_in_results_json(monkeypatch, tmp_path):
    got = _screen_run(monkeypatch, tmp_path, "decide", "o/x")
    (entry,) = got["summary"].values()
    assert "unmeasured" in entry.get("screen_caveat", ""), entry


def test_a_stale_sidecar_from_an_earlier_run_never_reaches_this_run_s_row(tmp_path):
    from evals.runners.process import ProcessRunner, sidecar
    from harness.engines import Engine
    write = ("import sys;from PIL import Image;import random;im=Image.new('RGB',(64,64));"
             "im.putdata([(random.randint(0,255),)*3 for _ in range(64*64)]);im.save(sys.argv[1])")
    engine = Engine(name="fake", spec="fake:1", modality="image", output_suffix=".png", timeout=60.0,
                    argv=lambda p, out, params: [sys.executable, "-c", write, str(out)])
    runner = ProcessRunner(engine, tmp_path)
    case = Case(id="fox", modality="image", prompt="a fox", params={"width": 64, "height": 64})
    stale = sidecar(tmp_path / runner.artifact(case, ".png"))
    stale.write_text(json.dumps({"steps": 99, "guidance": 7.0}), encoding="utf-8")
    runner.run(case)
    assert "steps" not in runner.last_runtime, runner.last_runtime


def test_the_unseen_rate_knob_sets_both_an_unmeasured_screen_count_and_an_unmeasured_adopt_plan(monkeypatch):
    from harness import knobs, power
    assert "harness/power.py:UNSEEN" in knobs.KNOBS["unseen_rate"].sites
    ids = [c.id for c in _decide()]
    for value in knobs.KNOBS["unseen_rate"].values:
        monkeypatch.setattr(power, "UNSEEN", value)
        monkeypatch.setattr(screen, "incumbent_draws", lambda lane, conn: {})
        rate, measured = screen.incumbent_measure("decide", ids, conn=object())
        assert (rate, measured) == (value, False)
        rates, observed = power.rates_from({}, ids)
        assert rates == {i: value for i in ids}
        assert power.plan(rates.values(), observed=observed).unmeasured


def test_a_child_s_limit_and_a_sidecar_s_steps_both_reach_the_row(tmp_path):
    from harness import hf_task
    out = tmp_path / "fox-snow.png"
    out.write_bytes(b"png")
    Path(hf_task.runtime_path(out)).write_text(json.dumps({"device": "mps", "limit": "hf_max_new_tokens>512"}),
                                               encoding="utf-8")
    process.sidecar(out).write_text(json.dumps({"steps": 9, "guidance": 0.0}), encoding="utf-8")
    got = process._runtime_of(out)
    assert got == {"device": "mps", "limit": "hf_max_new_tokens>512", "steps": "9", "guidance": "0.0"}
