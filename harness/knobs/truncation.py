"""Knobs of generations and scans that end at our own cap (#751)."""
from harness.knobs.base import _k

KNOBS = [
    _k("contamination_clean_share", ["harness/contamination.py:CLEAN_SHARE"], [0.9, 0.95, 0.99], unit="share",
       note="share of known-clean passages a calibrated contamination_hit must leave below it (#727)"),
    _k("contamination_hit", ["harness/contamination.py:HIT"], [0.125, 0.25, 0.5, 0.75, 1.0], unit="share", grades=True,
       note="leading-word overlap counted as reproducing a source (#700); calibrated on evals/contamination/probes.jsonl "
            "(job 0166): the smallest value no more than 5% of known-clean passages reach for any of sohot-decide, "
            "-extract, -code (clean hits at 0.25: 0/40, 0/33, 0/40; at 0.125: 7/40); canon sensitivity at 0.25 is "
            "0.03-0.26, so a miss is weak evidence (#727)"),
    _k("contamination_max_tokens", ["harness/contamination.py:MAX_TOKENS"], [256, 1024, 4096],
       limit="contamination_max_tokens", unit="tokens", note="reply budget of a contamination probe; a probe that ends there is an error naming it, never a miss (#700)"),
    _k("contamination_min_passages", ["harness/contamination.py:MIN_PASSAGES"], [5, 10, 30], unit="cases",
       note="probed passages each calibration set needs before a model's HIT derivation counts (#727)"),
    _k("contamination_probe_words", ["harness/contamination.py:PREFIX_WORDS", "harness/contamination.py:TARGET_WORDS"],
       [16, 32, 64], note="leading words of a source item a contamination probe sends, then the words its reply is scored "
                          "against for contamination_hit; a shorter item is skipped (#491)"),
    _k("degenerate_entropy", ["harness/degenerate.py:ENTROPY_BITS"], [2.5, 3.412, 4.0],
       note="bits per non-space character at or under which a budget-cut reply's tail is degenerate; code lane only, fitted on evals/degenerate (#955)"),
    _k("degenerate_min_chars", ["harness/degenerate.py:MIN_CHARS"], [256, 512, 1024, 2048],
       note="visible characters under which a budget-cut reply is never measured and stays a limit (#955)"),
    _k("degenerate_repeat", ["harness/degenerate.py:REPEAT_SHARE"], [0.55, 0.677, 0.8, 0.9],
       note="share of a budget-cut reply's tail repeating an earlier 64-char span that makes it degenerate, not a limit; code lane only, fitted on evals/degenerate (#955)"),
    _k("degenerate_tail_chars", ["harness/degenerate.py:TAIL_CHARS"], [2000, 4000, 8000],
       note="characters at the end of a budget-cut reply the degenerate measure reads; fitted with degenerate_repeat on evals/degenerate (#955)"),
    _k("max_mentions", ["harness/judge.py:MAX_MENTIONS"], [6, 12, 24],
       note="names kept from one mention reply; a thread is read in MENTION_CHUNK_CHARS pieces (#700)"),
    _k("mention_chunk_chars", ["harness/judge.py:MENTION_CHUNK_CHARS"], [2000, 4000, 8000],
       note="characters of a thread asked about in one mention call; the whole thread is read, one call per piece (#700)"),
    _k("ocr_max_new_tokens", ["harness/hf_task.py:MAX_NEW_TOKENS"], [256, 512, 1024, 2048, 4096],
       lanes=("ocr",), limit="hf_max_new_tokens", unit="tokens", receipt="knobs",
       note="new tokens an hf-task ocr reply may take (#700)", unrecorded=512),
]

NOT_GATING = {
    "evals/contamination_passages.py:WORDS": "words kept per calibration passage; the probe reads its 48 and "
                                             "split_prefix refuses a shorter one (#727)",
    "evals/contamination_passages.py:_http->httpx.Client(timeout)": "how long a fixture build waits on Wikipedia or "
                                                                     "Gutenberg; a timeout raises, it never shortens a passage (#727)",
}

NEVER_CUTS = {
    "harness/contamination.py:CLEAN_SHARE": "the clean quantile a HIT is read at; every probe is reported (#727)",
    "harness/contamination.py:MIN_PASSAGES": "when a model's derivation counts; every probe is reported (#727)",
}
