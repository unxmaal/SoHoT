"""Knobs of `soh ask` and local_complete with paths: what it reads and how it cuts it (#1335)."""
from harness.knobs.base import _k

KNOBS = [
    _k("ask_chunk_chars", ["harness/ask.py:CHUNK_CHARS"], [8000, 16000, 24000, 48000],
       note="characters of file per local call before a digest is asked part by part and merged (#1335)"),
    _k("ask_failure_lines", ["harness/ask.py:FAILURE_LINES"], [5, 20, 60],
       note="failure-shaped lines the deterministic scan adds to a digest about failures (#1335)"),
    _k("ask_line_chars", ["harness/ask.py:LINE_CHARS"], [120, 300, 1000],
       note="characters kept of one failure-shaped line, around its match (#1335)"),
    _k("ask_max_bytes", ["harness/ask.py:MAX_BYTES"], [262144, 1048576, 4194304],
       note="bytes a digest may read across its paths before it is refused (#1335)"),
    _k("ask_max_paths", ["harness/ask.py:MAX_PATHS"], [4, 16, 64],
       note="paths one digest may name (#1335)"),
    _k("ask_reply_tokens", ["harness/ask.py:REPLY_TOKENS"], [300, 600, 1200],
       note="reply budget of each digest call; the issue's digest is at most about 500 tokens (#1335)"),
]
