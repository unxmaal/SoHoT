"""Knobs of the wall clock an engine subprocess runs a case under (#708)."""
from harness.knobs.base import _k

#: The lanes an eval runs through an engine process: ProcessRunner, ChainRunner (image) and TraceRunner (svg).
ENGINE_LANES = ("decide", "image", "music", "ocr", "pii", "retrieval", "shots", "svg", "video")

#: Each engine's own ceiling, the clock it runs at until enough of its cases are measured here.
CEILINGS = ["harness/engines.py:Engine.timeout", "evals/runners/chain.py:ChainRunner.__init__(timeout)",
            *(f"harness/engines.py:{b}->Engine(timeout)" for b in (
                "_acestep", "_bm25", "_decider", "_diffusers", "_hf_ocr", "_hf_pii", "_mflux", "_nimble", "_osocr",
                "_pii_regex", "_ranker.build", "_scenedetect", "_transnetv2"))]

KNOBS = [
    _k("engine_timeout", ["harness/engine_timeout.py:MARGIN", *CEILINGS], [2.0, 3.0, 5.0, 10.0],
       lanes=ENGINE_LANES, limit="engine_timeout_s.{lane}", unit="s", derived="harness/engine_timeout.py:derive",
       receipt="knobs", unrecorded=3.0,
       note="an engine's clock per case is this many times its slowest finished case on this machine. Store "
            "2026-10-25, 2,329 finished engine cases: a clock set from the cases before each one would have cut 3 "
            "at 1.5, 1 at 2 (mflux on the M2 Pro), none at 3, 5 or 10; no stored row ever hit an engine clock, and "
            "each is at most a third of the clock it now gets, so receipts before it ran at 3 (#708). Counting only "
            "the 2,301 cases the engine generated (#1256): 1 cut at 2, none at 3, 5 or 10"),
    _k("engine_timeout_floor", ["harness/engine_timeout.py:FLOOR_S"], [10.0, 30.0, 60.0, 120.0],
       binds_via="engine_timeout",
       note="seconds no derived engine clock goes below: pii-regex and bm25 finish in under 0.1 s, and a process "
            "start on a loaded machine is not their measurement (#708)"),
    _k("engine_timeout_min_cases", ["harness/engine_timeout.py:MIN_CASES"], [5, 10, 20, 50],
       binds_via="engine_timeout",
       note="finished cases an engine needs on this machine before its slowest replaces its ceiling; store "
            "2026-10-25: h3 has 6 on the Studio (slowest 439.6 s, ceiling 6 h), diffusers-video 1 (#708)"),
    _k("engine_timeout_reruns", ["harness/engine_timeout.py:RERUNS"], [0, 1, 2, 3],
       binds_via="engine_timeout",
       note="cases per candidate per run that, cut under a derived clock, are rerun once at the engine's ceiling; "
            "0 is #708's cut. Store 2026-10-25: a correct heavier model of an engine runs 6-20x the lighter ones "
            "(diffusers prxpixel-t2i 63-74 s graded vs 2-5 s, nimble 9B-v2 79.8 s vs 12.9 s), and no engine row was "
            "ever a TIMEOUT, so one rerun costs a wedged candidate one ceiling and never changed a stored row (#1256)"),
    _k("h3_steps", ["harness/engines.py:H3_STEPS"], [4, 8, 20],
       note="denoising passes h3 runs when neither the spec nor the case names them; it moved off fox-run.yaml, where "
            "it read as part of the task. h3.c's own default is 20; the Studio ran fox-run (256x256x22) at 4 in "
            "439.6 s, so 20 would cost the video exam about 5x (#735)"),
]

NOT_GATING: dict = {}

NEVER_CUTS = {
    "harness/engines.py:H3_STEPS": "a sampler setting h3 is passed when nothing names one; it stops nothing (#735)",
}
