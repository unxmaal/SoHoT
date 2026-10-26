"""Knobs of the vision lane: shot scale of film frames against CineScale's labels (#1207)."""
from harness.knobs.base import _k

KNOBS = [
    _k("vision_align_max_offset", ["evals/vision.py:ALIGN_MAX_OFFSET_S"], [120, 300, 600, 900], limit="vision_align_max_offset", unit="s",
       note="seconds either way a copy may start against its labels; kubrick #2 found one longer edition 356 s off "
            "and partial copies at 4-12 s, so 600 covers both with room (#1207)"),
    _k("vision_align_min_marks", ["evals/vision.py:ALIGN_MIN_MARKS"], [20, 50, 100, 200], limit="vision_align_min_marks", unit="marks",
       note="label changes a whole-film fit needs inside the copy (halves need half); a 2 h film has ~1000, the "
            "noise test shows a fit on fewer is a lottery (kubrick #2) (#1207)"),
    _k("vision_align_min_z", ["evals/vision.py:ALIGN_MIN_Z"], [6.0, 8.0, 10.0, 12.0], limit="vision_align_min_z", unit="sd", grades=True,
       note="sd over shuffled change times a fit must reach; kubrick PR #9: accepted copies 12.9-27.1, mismatched "
            "pairs 4.0-6.1, so 8 sits between with the halves check behind it (NEGATIVE #34) (#1207)"),
    _k("vision_compare_draws", ["evals/vision.py:COMPARE_DRAWS"], [500, 1000, 2000, 5000],
       limit="vision_compare_draws", unit="draws",
       note="bootstrap draws behind compare's interval; at 2000 the 2.5% tail rests on 50 draws (#1282)"),
    _k("vision_compare_level", ["evals/vision.py:COMPARE_LEVEL"], [0.9, 0.95, 0.99], limit="vision_compare_level",
       unit="share",
       note="coverage of compare's interval on a kappa difference; 0.95 is 1 - adopt.ALPHA, the level adopt's paired tests use (#1282)"),
    _k("vision_control_draws", ["harness/checks/shot_scale.py:CONTROL_DRAWS"], [5, 10, 20, 50], limit="vision_control_draws", unit="draws",
       note="permutations of the true labels the control averages; at 500 frames a film one draw's kappa has sd "
            "~0.02, so 20 put the mean's sd under 0.01 (#1207)"),
    _k("vision_control_max_kappa", ["harness/checks/shot_scale.py:CONTROL_MAX_KAPPA"], [0.05, 0.1, 0.15, 0.2],
       limit="vision_control_max_kappa",
       unit="kappa", grades=True,
       note="largest |mean kappa| a shuffled-label control may reach before the run is discarded; kubrick's "
            "controls sat at <= 0.06 against real probes at 0.37-0.57 (#1207)"),
    _k("vision_fit_max_iter", ["evals/vision.py:FIT_MAX_ITER"], [100, 200, 500, 1000], limit="vision_fit_max_iter", unit="steps",
       note="L-BFGS iterations of the reference probe's fit; kubrick's scikit-learn row used 2000 lbfgs steps "
            "on CLS+mean features, L-BFGS with line search converges well inside 500 on 768 dims (#1207)"),
    _k("vision_frame_height", ["evals/vision.py:FRAME_HEIGHT"], [224, 448, 720], limit="vision_frame_height", unit="pixels",
       note="height a frame is extracted at; DINOv2 resizes to 224 and the Qwen-VL processors tile up to ~1000, "
            "so 448 feeds both without being the cost; part of the manifest (#1207)"),
    _k("vision_frames_per_film", ["evals/vision.py:FRAMES_PER_FILM"], [200, 500, 1000, 2000], limit="vision_frames_per_film", unit="frames",
       note="frames drawn per film; 4 films x 500 = 2000 frames keeps a 7B VLM's night run near an hour at "
            "~2 s a frame and the control's sd near 0.02 (#1207)"),
    _k("vision_half_offset_tolerance", ["evals/vision.py:HALF_OFFSET_TOLERANCE_S"], [1, 2, 4, 8], limit="vision_half_offset_tolerance", unit="s",
       note="seconds the two halves' offsets may differ by; exact NTSC/PAL ratios held kubrick's accepted copies "
            "within 2 s, while 25/24 drifted 3.6 s an hour (RULE #1061) (#1207)"),
    _k("vision_llamacpp_ctx", ["evals/vision.py:LLAMACPP_CTX"], [2048, 4096, 8192], limit="vision_llamacpp_ctx",
       unit="tokens",
       note="context a private llama-server starts with: a 448-pixel frame is a few hundred image tokens on the "
            "Qwen-VL and SmolVLM projectors, plus a ~120-token prompt and the reply budget (#1282)"),
    _k("vision_llamacpp_start_s", ["evals/vision.py:LLAMACPP_START_S"], [120, 300, 600, 1200],
       limit="vision_llamacpp_start_s", unit="s",
       note="seconds a private llama-server has to answer /health; gguf.READY_TIMEOUT_S gives the router 120 s for "
            "a warm restart, and a cold 7B load from the models volume plus Metal shader compile takes longer (#1282)"),
    _k("vision_min_private_name", ["harness/privacy.py:MIN_HOME_NAME"], [3, 4, 6], limit="vision_min_private_name", unit="chars",
       note="characters a registered private name needs; shorter ones are common words a title scan would flag "
            "everywhere (#1207)"),
    _k("vision_null_draws", ["evals/vision.py:NULL_DRAWS"], [100, 200, 500], limit="vision_null_draws", unit="draws",
       note="random change-time draws behind an alignment's z, kubrick #2's count (#1207)"),
    _k("vision_probe_c", ["evals/vision.py:PROBE_C"], [0.01, 0.1, 1.0], limit="vision_probe_c", unit="factor",
       note="L2 strength of the reference probe as scikit-learn's C; kubrick #2's linear row used 0.1 "
            "(0.37-0.51 leave-one-film-out) (#1207)"),
    _k("vision_probe_shuffles", ["evals/vision.py:PROBE_SHUFFLES"], [3, 5, 10], limit="vision_probe_shuffles", unit="draws",
       note="probes trained on labels shuffled within each film, the probe's own control (#1207)"),
    _k("vision_reply_max_tokens", ["evals/vision.py:REPLY_MAX_TOKENS"], [128, 256, 512, 1024],
       limit="vision_reply_max_tokens", unit="tokens",
       note="new tokens a labeller's reply may take, one budget for hf-vlm, mlx-vlm and llamacpp-vlm so engines "
            "compare on equal terms; 512 is hf-task's image-reply default (ocr_max_new_tokens), and an answer is "
            "one code, so only a model that reasons first comes near it; a cut reply is marked and counted (#1282)"),
    _k("vision_request_timeout_s", ["evals/vision.py:REQUEST_TIMEOUT_S"], [60, 300, 600, 1200],
       limit="vision_request_timeout_s", unit="s",
       note="seconds one frame's reply may take; a CPU-only 7B image encode plus a 512-token reply is minutes, "
            "the GPU path seconds (#1282)"),
    _k("vision_source_digest_bytes", ["evals/vision.py:SOURCE_DIGEST_BYTES"], [1 << 16, 1 << 20, 1 << 24],
       limit="vision_source_digest_bytes",
       unit="bytes", note="bytes hashed from each end of a copy for the manifest; a different edition or rip "
                          "changes its container header and tail, and a full hash of a 10 GB file costs a minute (#1207)"),
]

NOT_GATING = {
    **{f"evals/vision.py:STAND_IN_SHARE[{label}]": "share of a stand-in frame its drawn subject covers at that scale; "
                                                 "the fixture's picture, read back by size_label, decides no measurement"
       for label in ("ECU", "CU", "MCU", "MS", "MLS", "LS", "ELS")},
    "harness/llama_vlm.py:serve->_http.get(timeout)": "one health probe's wait inside the start window; "
                                                      "vision_llamacpp_start_s is the limit that gives up",
    "harness/llama_vlm.py:serve->proc.wait(timeout)": "grace for a stopped server to exit before it is killed; "
                                                      "every frame is already answered",
    "harness/mlx_vlm_label.py:load.ask->generate(temperature)": "greedy decoding, as hf-task's do_sample=False and "
                                                                "llamacpp-vlm's temperature 0: the exam's setting",
}
