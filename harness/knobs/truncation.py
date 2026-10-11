"""Knobs of generations and scans that end at our own cap (#751)."""
from harness.knobs.base import _k

KNOBS = [
    _k("contamination_hit", ["harness/contamination.py:HIT"], [0.25, 0.5, 0.75, 1.0],
       note="leading-word overlap counted as reproducing a source; not calibrated on known-clean text (#700)"),
    _k("contamination_max_tokens", ["harness/contamination.py:MAX_TOKENS"], [256, 1024, 4096],
       note="reply budget of a contamination probe; a probe that ends there is an error naming it, never a miss (#700)"),
    _k("max_mentions", ["harness/judge.py:MAX_MENTIONS"], [6, 12, 24],
       note="names kept from one mention reply; a thread is read in MENTION_CHUNK_CHARS pieces (#700)"),
    _k("mention_chunk_chars", ["harness/judge.py:MENTION_CHUNK_CHARS"], [2000, 4000, 8000],
       note="characters of a thread asked about in one mention call; the whole thread is read, one call per piece (#700)"),
    _k("ocr_max_new_tokens", ["harness/hf_task.py:MAX_NEW_TOKENS"], [256, 512, 1024, 2048, 4096],
       lanes=("ocr",), limit="hf_max_new_tokens", receipt="knobs",
       note="new tokens an hf-task ocr reply may take (#700)", unrecorded=512),
]
