"""Knobs of exploratory reads as quoted spans: `soh spans` (#1336)."""
from harness.knobs.base import _k

KNOBS = [
    _k("spans_anchor_chars", ["harness/spans.py:ANCHOR_CHARS"], [8, 12, 24],
       note="shortest quote of a span's first line that anchors it, unless it is the whole line (#1336)"),
    _k("spans_chunk_chars", ["harness/spans.py:CHUNK_CHARS"], [8000, 24_000, 48_000],
       note="characters of numbered file per spans call; a longer file is asked in parts (#1336)"),
    _k("spans_eval_gold_line_chars", ["evals/spans_recall.py:GOLD_LINE_CHARS"], [20, 30, 60],
       note="stripped length from which a file line a later input holds counts as gold (#1336)"),
    _k("spans_eval_min_gold", ["evals/spans_recall.py:MIN_GOLD"], [1, 2, 5],
       note="gold identifiers and lines a Read needs to be scored by `soh spans --eval` (#1336)"),
    _k("spans_eval_question_chars", ["evals/spans_recall.py:QUESTION_CHARS"], [200, 500, 1000],
       note="characters of the agent's words and of its task kept in an eval question (#1336)"),
    _k("spans_eval_recall_bar", ["evals/spans_recall.py:RECALL_BAR"], [0.8, 0.9, 0.95],
       note="span recall of later-used gold the eval needs to pass (#1336)"),
    _k("spans_max_share", ["harness/spans.py:MAX_SHARE"], [0.25, 0.5, 0.75],
       note="share of a file's characters past which its spans are dropped for the whole file (#1336)"),
    _k("spans_min_chars", ["harness/spans.py:MIN_CHARS"], [2000, 4000, 8000],
       note="characters under which a file is returned whole with no model call (#1336)"),
    _k("spans_redo_window", ["harness/spans.py:REDO_WINDOW"], [5, 10, 20],
       note="tool calls after a spans call within which a full Read of the path counts as a redo (#1336)"),
    _k("spans_reply_tokens", ["harness/spans.py:REPLY_TOKENS"], [600, 2048, 4096],
       note="reply budget of a spans call; a reply that reaches it returns the whole file (#1336)"),
]

NEVER_CUTS = {
    "evals/spans_recall.py:GOLD_LINE_CHARS": "which file lines count as gold; shorter lines still count through their identifiers (#1336)",
    "evals/spans_recall.py:RECALL_BAR": "the pass bar of the eval; every case is scored (#1336)",
    "harness/spans.py:REDO_WINDOW": "which later Reads count as a redo; every spans call is counted (#1336)",
}
