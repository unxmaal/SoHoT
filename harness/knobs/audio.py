"""Knobs of tts and stt limits (#751)."""
from harness.knobs.base import _k

KNOBS = [
    _k("audio_timeout", ["harness/audio.py:TIMEOUT_S"], [60.0, 120.0, 300.0, 600.0],
       lanes=("tts", "stt"), limit="audio_timeout_s", unit="s", receipt="knobs", note="seconds one tts or stt request may take (#693)", unrecorded=120.0),
    _k("runaway_rate", ["harness/audio.py:SECONDS_PER_WORD_CEILING", "harness/audio.py:RUNAWAY_MIN_WORDS"],
       [0.6, 0.8, 0.95, 1.2, 2.0], lanes=("tts",), limit="seconds_per_word", unit="s/word", receipt="knobs",
       note="seconds of speech per word above which tts ran away (#91)"),
    _k("tts_calibration_tokens", ["harness/audio.py:CALIBRATION_TOKENS"], [50, 100, 200],
       note="cap on the clip that measures an unlisted cloning model's codec rate; the clip must end at it (#700)"),
    _k("tts_cap_fill", ["harness/audio.py:TOKEN_CAP_FILL"], [0.9, 0.95, 0.99],
       lanes=("tts",), binds_via="tts_token_floor", receipt="knobs",
       note="share of the token budget's seconds a cloning clip must reach to be TOKEN_BUDGET_EXHAUSTED (#700, #752)"),
    _k("tts_token_floor", ["harness/audio.py:TOKEN_BUDGET_MIN_S", "harness/audio.py:TOKEN_BUDGET_MARGIN",
                           "harness/audio.py:CODEC_HZ[chatterbox]"], [4.0, 8.0, 16.0, 30.0],
       lanes=("tts",), limit="tts_budget_s", unit="s", receipt="knobs",
       note="fewest seconds a cloning request may speak; the budget is that or the text at the runaway rate, at the codec's rate (#700)", unrecorded=8.0),
]
