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
       receipt="max_tokens", note="the reply budget an eval asks every text reply at (#628)"),
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
    "evals/core.py:Receipt.max_tokens": "what a receipt records a run asked for; the budget itself is reply_budget (#706)",
    "evals/core.py:GRADED_FAILURE[repo][resolved]": "what the repo grader records on a failed reply, given to a cut one; a fact, not a setting (#1113)",
    "evals/core.py:GRADED_FAILURE[repo][patch_applied]": "what the repo grader records on an empty diff, given to a cut reply; a fact, not a setting (#1113)",
}
