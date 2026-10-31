"""Knobs of reply budget and request timeouts of the text lanes (#751)."""
from harness.knobs.base import REQUEST_LANES, TEXT_LANES, _k

KNOBS = [
    _k("delegate_chars_per_token", ["harness/delegate.py:CHARS_PER_TOKEN"], [1, 2, 3, 4],
       note="prompt size estimate for delegate.cap and the ladder, used only where the served tokenizer cannot be asked (#692)"),
    _k("load_timeout", ["harness/completion.py:LOAD_TIMEOUT_S"],
       [600.0, 1200.0, 1800.0, 3600.0], lanes=REQUEST_LANES, limit="load_timeout_s", unit="s", receipt="knobs", runner_attr="load_timeout",
       note="seconds the untimed first request may spend loading weights"),
    _k("pool_full_retries", ["harness/completion.py:POOL_FULL_RETRIES"], [0, 1, 2], limit="pool_full_retries", unit="calls",
       note="times a request is sent again after llama-server 0.5.0 failed every task in flight on a full --kv-unified "
            "pool (#748 probe: 3 x 2500-word prompts over -c 8192 all got HTTP 500 'Context size has been exceeded.' "
            "after 4 s); retries hold one lock per gateway, so each runs with the pool free. Store 2026-10-25: no "
            "pool_full among 29,700 results rows, so 1 costs nothing until a pool fills (#755)"),
    _k("reply_budget", ["harness/completion.py:BUDGET", "harness/completion.py:MAX_TOKENS"],
       [2000, 4000, 8000, 16384, 32768, 65536], lanes=TEXT_LANES,
       lane_values={"claims": (200, 400, 800, 1600)}, limit="max_tokens.{lane}", unit="tokens",
       receipt="max_tokens", note="the reply budget an eval asks every text reply at unless its model's stored runs "
                                  "derive a smaller cap, harness/reply_cap.py (#628, #1352)"),
    _k("reply_cap_margin", ["harness/reply_cap.py:MARGIN"], [0.1, 0.25, 0.5], unit="share", binds_via="reply_budget",
       note="room a token-derived reply cap leaves above the quantile reply's completion tokens before rounding up to "
            "a whole 4096. Store 2026-10-29, 0.95 quantile: repo Qwen3.6-27B 9757 tokens -> 12288 at 0.1 and 0.25, "
            "16384 at 0.5 (#1352)"),
    _k("reply_cap_min_passes", ["harness/reply_cap.py:MIN_PASSES"], [5, 8, 10, 20], unit="draws", binds_via="reply_budget",
       note="passes a model needs at the lane's whole budget (or a sweep's best budget) before they set its cap; "
            "fewer and it runs at the lane's budget, so its first exam is the evidence. Store 2026-10-29: the "
            "Qwopus3.6-27B repo sweep's best budget passed 9 (runs 576-579) (#1352)"),
    _k("reply_cap_min_saved", ["harness/reply_cap.py:MIN_SAVED"], [0.0, 0.05, 0.1, 0.2], unit="share", binds_via="reply_budget",
       note="the share of a model's stored seconds its cap must save before its runs ask at it, since a capped "
            "receipt no longer pairs with older ones at the lane's budget. Store 2026-10-29: agent Ornith 4096 saves 0% "
            "and repo Opus 12288 0% (kept at the budget); repo Qwopus3.6 8000 saves 31%, repo Qwen3.6-27B 12288 24% (#1352)"),
    _k("reply_cap_noise_z", ["harness/reply_cap.py:NOISE_Z"], [1.64, 1.96, 2.58], unit="sd", binds_via="reply_budget",
       note="a swept budget, or a token-derived cap against the model's own passes, sets the cap when the cases only "
            "the larger budget passes outnumber those only it passes by no more than this many sd of their sum (a "
            "paired sign test). Store 2026-10-29: Qwopus3.6-27B repo 8000 9, 16384 9, 32768 6 of 108 -> 8000 at every "
            "value; code Ornith's 24576 would lose 21 of 869 passes, over 1.96 x sqrt(21), so it keeps 32768 (#1352)"),
    _k("reply_cap_quantile", ["harness/reply_cap.py:QUANTILE"], [0.9, 0.95, 0.99, 1.0], unit="share", binds_via="reply_budget",
       note="the share of a model's passing replies, ranked by completion tokens, its cap lets finish. Store "
            "2026-10-29, on each model's rows at the whole budget: 0.95 gives repo Qwen3.6-27B 12288 (1 of 35 "
            "passes lost, 24% of 4.1 GPU-h saved), code Ornith 24576 (21 of 869 lost: refused by reply_cap_noise_z); "
            "0.99 gives both 32768, no cap (#1352)"),
    _k("request_timeout", ["harness/completion.py:TIMEOUT_S", "harness/completion.py:MIN_DECODE_TOK_S"],
       [60.0, 120.0, 180.0, 300.0, 600.0], lanes=REQUEST_LANES, limit="timeout_s", unit="s", receipt="knobs", runner_attr="timeout",
       note="seconds one request may take; a big budget stretches it at the slowest decode"),
    _k("yield_stop_explore", ["harness/yield_stop.py:EXPLORE_SHARE"], [0.0, 0.05, 0.1, 0.2],
       note="share of a measured run's tasks, drawn by case id and run, let past the yield stop point to the budget so "
            "the curve can move up; 0 freezes it. 2026-10-22 store: repo Ornith 71 of 170 rows ran past the 18160-token "
            "stop and 1 of them passed, so at 0.1 a 128-case run explores about 5 tail tasks and gives back about a tenth "
            "of the 41% saving; code Ornith 159 of 1000 ran past 21164 and 31 passed (#1127)"),
    _k("yield_stop_ratio", ["harness/yield_stop.py:STOP_RATIO"], [0.1, 0.25, 0.5],
       limit="yield_stop", unit="tokens", derived="harness/yield_stop.py:point",
       note="a measured reply stops once tasks still running at its generated-token count pass below this share of "
            "its lane-model's base pass rate. 2026-10-22 store, Ornith: repo 0.1 stops at 21969 tokens (0 of 15 passes "
            "lost, 32% of 8.0 GPU-h saved), 0.25 at 18160 (1 lost, 41%), 0.5 at 9821 (3 lost, 64%); code 0.1 at 28873 "
            "(11 of 783 lost, 14% of 18.6 h), 0.25 at 21164 (32 lost, 27%), 0.5 at 11541 (88 lost, 50%) (#1127)"),
]

NOT_GATING = {
    "harness/completion.py:POOL_FULL_POLL_S": "how often a pool-full retry asks for the retry lock; the request's own "
                                              "timeout bounds the wait, never a result (#755)",
    "harness/reply_cap.py:STEP": "the rounding a token-derived cap moves in, so a little new evidence does not change "
                                 "a run's budget and its receipts stay comparable; the cap's size is reply_cap_quantile (#1352)",
    "evals/core.py:Receipt.max_tokens":"what a receipt records a run asked for; the budget itself is reply_budget (#706)",
    "evals/core.py:GRADED_FAILURE[repo][resolved]": "what the repo grader records on a failed reply, given to a cut one; a fact, not a setting (#1113)",
    "evals/core.py:GRADED_FAILURE[repo][patch_applied]": "what the repo grader records on an empty diff, given to a cut reply; a fact, not a setting (#1113)",
}

NEVER_CUTS = {
    "evals/runners/text.py:CompletionRunner.__init__(max_tokens)": "0 asks at the lane's reply_budget, which records "
                                                                   "its own binding as max_tokens.<lane> (#628)",
    "evals/runners/text.py:CompletionRunner.warm->completion.complete_with_usage(max_tokens)":
        "the warm-up's reply budget; a reply cut there counts as answered (#406)",
}
