"""Knobs of the pass thresholds an importer writes into each case (#751)."""
from harness.knobs.base import _k

KNOBS = [
    _k("ocr_max_cer", ["evals/importers/ocr_synth.py:MAX_CER", "evals/ocr_corpus.py:MAX_CER"], [0.0, 0.05, 0.1, 0.25],
       note="CER an ocr case passes at; written into each case, required since #701"),
    _k("stt_max_wer", ["evals/importers/librispeech.py:MAX_WER"], [0.0, 0.05, 0.1, 0.2],
       note="per-utterance WER a LibriSpeech case passes at; written into each case, so the cases digest carries it; floor unmeasured (#701)"),
    _k("tts_max_wer", ["evals/importers/tts_synth.py:MAX_WER"], [0.1, 0.2, 0.3],
       note="read-back WER a generated tts case passes at, joint with the ear; floor unmeasured (#701)"),
]

NOT_GATING = {
    "evals/importers/svg_synth.py:ATTEMPTS": "redraws of one row before the generator refuses a kind too small "
                                             "for its share; it raises, it never changes a case (#1050)",
}
