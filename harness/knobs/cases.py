"""Knobs of the pass thresholds an importer writes into each case and of which cases it draws (#751, #734)."""
from harness.knobs.base import _k

KNOBS = [
    _k("benchmark_page_chars", ["evals/benchmark_import.py:PAGE_CHARS"], [500, 1500, 4000],
       note="characters a labelled page may have and still go into a benchmark case; longer ones are skipped, unmeasured (#491)"),
    _k("decide_check_cases", ["evals/decide_corpus.py:CHECK_CASES"], [6],
       note="SQuAD check cases the corpus builder draws; the SQuAD importer supplies the rest (#671)"),
    _k("decide_check_questions", ["evals/decide_corpus.py:QUESTIONS"], [3, 5, 8],
       note="SQuAD questions of one paragraph a decide check case holds; it is kept only with both answerable and not (#423)"),
    _k("decide_per_family", ["evals/decide_corpus.py:PER_FAMILY"], [6, 30, 60, 90],
       note="decide cases the corpus builder draws per route, policy and rate family; 60 holds SQuAD to half the holdout (#423, #671)"),
    _k("ocr_max_cer", ["evals/importers/ocr_synth.py:MAX_CER", "evals/ocr_corpus.py:MAX_CER"], [0.0, 0.05, 0.1, 0.25],
       unit="share", grades=True,
       note="CER an ocr case passes at, written into each case (#701); noise floor of Vision (macOS 27.0.1) on 464 "
            "clean renders, 440 of them planted plain (job 0159): 0.0 (1-15 chars), 0.08 (16-30), 0.043 (31+), so 0.1 "
            "is the derived value; same-config rerun (job 0164) changed 0 of 464 (`soh floors`, #730)"),
    _k("pii_no_pii_share", ["evals/importers/pii_synth.py:NO_PII_SHARE"], [0.1, 0.2, 0.3],
       note="share of generated pii cases holding no PII, the control a redactor must leave unchanged (#610)"),
    _k("squad2_cases", ["evals/importers/squad2_check.py:N", "evals/importers/squad2_extract.py:N"], [220, 440, 880],
       note="SQuAD 2.0 cases the check and extract importers draw; unmeasured against a smaller holdout (#603)"),
    _k("squad2_check_questions", ["evals/importers/squad2_check.py:QUESTIONS"], [3, 5, 8],
       note="questions of one paragraph a SQuAD check case asks (#603)"),
    _k("squad2_retrieval_cases", ["evals/importers/squad2_retrieval.py:N"], [290, 580, 1160],
       note="SQuAD 2.0 cases the retrieval importer draws (#603)"),
    _k("stt_max_wer", ["evals/importers/librispeech.py:MAX_WER"], [0.0, 0.05, 0.1, 0.2],
       unit="share", grades=True,
       note="per-utterance WER a LibriSpeech case passes at, written into each case (#701); noise floor of whisper-large-v3 "
            "on all 480 clips (job 0155) under normaliser 2 (#1266): 0.167 (1-10 words), 0.125 (11-17), 0.111 (18+), "
            "so 0.2 is the derived value; normaliser 1 gave 0.25; same-config rerun (job 0162) changed 0 of 480 "
            "(`soh floors`, #730)"),
    _k("tts_max_wer", ["evals/importers/tts_synth.py:MAX_WER"], [0.1, 0.2, 0.3],
       unit="share", grades=True,
       note="read-back WER a generated tts case passes at, joint with the ear (#701); noise floor of Kokoro bm_george "
            "through the parakeet-v2 ear (mlx-audio 0.5.3) on 222 sentences without a 4-digit count (job 0157): 0.125 "
            "(1-17 words), 0.111 (18+), so 0.2 is the derived value; same-config rerun (job 0163) changed 1 of 222 by "
            "one word (tts-synth-0419) (`soh floors`, #730)"),
]

NOT_GATING = {
    "evals/importers/svg_synth.py:ATTEMPTS": "redraws of one row before the generator refuses a kind too small "
                                             "for its share; it raises, it never changes a case (#1050)",
    "evals/importers/geneval.py:PARAMS[width]": "the picture size every staging case asks for, as the hand cases "
                                                "do; exam content, not a threshold (#603)",
    "evals/importers/geneval.py:PARAMS[height]": "the picture size every staging case asks for, as the hand cases "
                                                 "do; exam content, not a threshold (#603)",
    "evals/importers/geneval.py:PARAMS[seed]": "the generation seed every staging case asks for, as the hand cases "
                                               "do; exam content, not a threshold (#603)",
    "evals/importers/geneval.py:download->urllib.request.urlopen(timeout)": "network timeout of a by-hand refresh "
                                                                           "of the recorded copy; it raises, it never "
                                                                           "changes a case (#603)",
    "evals/importers/web_synth.py:ATTEMPTS": "redraws of one row before the generator refuses a kind too small "
                                             "for its share; it raises, it never changes a case (#603)",
}

NEVER_CUTS = {
    "evals/importers/pii_synth.py:NO_PII_SHARE": "the mix of generated pii cases; every case drawn is written (#610)",
    "evals/decide_corpus.py:THRESHOLD": "the rater fraction that labels a policy answer true or false; every picked "
                                        "comment is written (#491)",
    "evals/ocr_corpus.py:MAX_CER": "the pass mark written into each generated OCR case; every case is written (#603)",
}
