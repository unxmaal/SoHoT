"""Knobs of reply budget and request timeouts of the text lanes (#751)."""
from harness.knobs.base import REQUEST_LANES, TEXT_LANES, _k

KNOBS = [
    _k("load_timeout", ["harness/completion.py:LOAD_TIMEOUT_S"],
       [600.0, 1200.0, 1800.0, 3600.0], lanes=REQUEST_LANES, limit="load_timeout_s", receipt="knobs", runner_attr="load_timeout",
       note="seconds the untimed first request may spend loading weights"),
    _k("reply_budget", ["harness/completion.py:BUDGET", "harness/completion.py:MAX_TOKENS"],
       [2000, 4000, 8000, 16384, 32768, 65536], lanes=TEXT_LANES,
       lane_values={"claims": (200, 400, 800, 1600)}, limit="max_tokens.{lane}",
       receipt="max_tokens", note="the reply budget an eval asks every text reply at (#628)"),
    _k("request_timeout", ["harness/completion.py:TIMEOUT_S", "harness/completion.py:MIN_DECODE_TOK_S"],
       [60.0, 120.0, 180.0, 300.0, 600.0], lanes=REQUEST_LANES, limit="timeout_s", receipt="knobs", runner_attr="timeout",
       note="seconds one request may take; a big budget stretches it at the slowest decode"),
]

NOT_GATING = {
    "evals/core.py:Receipt.max_tokens": "what a receipt records a run asked for; the budget itself is reply_budget (#706)",
}
