"""Judging synthesized speech: is it intelligible, and how intelligible.

This is the suite's first real quality axis. Everything else so far separates
working from broken; word error rate puts two working candidates in an order.

It is a JOINT measurement of a TTS model and the STT model reading it, and it
cannot separate them. That is fine for the comparison it is used for -- one
side is held fixed while the other varies -- and it is stated here so nobody
reads a WER as an absolute score for either model alone.
"""
import pytest

from harness.checks import speech


def test_identical_text_is_zero_error():
    assert speech.wer("the quick brown fox", "the quick brown fox") == 0.0


def test_one_wrong_word_in_four():
    assert speech.wer("the quick brown fox", "the quick brown box") == 0.25


def test_case_and_punctuation_are_normalized_away():
    """Parakeet emits no reliable punctuation and inconsistent casing. Counting
    that as an error would rank models on transcription style."""
    assert speech.wer("Hello, world!", "hello world") == 0.0


def test_a_totally_wrong_transcript_is_a_high_error_not_a_crash():
    assert speech.wer("the quick brown fox", "banana") >= 1.0


def test_an_empty_hypothesis_is_total_error_not_a_division_by_zero():
    assert speech.wer("the quick brown fox", "") == 1.0


def test_an_empty_reference_is_rejected_rather_than_scored():
    with pytest.raises(ValueError):
        speech.wer("", "anything")


def test_numbers_spoken_as_words_are_not_counted_as_errors():
    """"MLX 200" comes back as "mlx two hundred". Judging that as three errors
    measures the reference's spelling, not the speech."""
    assert speech.wer("mlx 200 is fast", "mlx two hundred is fast") == 0.0


# ---- the check ------------------------------------------------------------

def test_check_passes_when_the_transcript_matches(tmp_path):
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"x" * 9000)
    r = speech.check(wav, reference="the quick brown fox", max_wer=0.2,
                     transcriber=lambda p: "the quick brown fox")
    assert r.ok
    assert r.wer == 0.0


def test_check_fails_when_the_error_rate_is_over_the_limit(tmp_path):
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"x" * 9000)
    r = speech.check(wav, reference="the quick brown fox", max_wer=0.1,
                     transcriber=lambda p: "a slow green ox")
    assert not r.ok
    assert "0.1" in r.reason
    assert r.transcript == "a slow green ox"


def test_check_reports_the_transcript_so_a_failure_is_diagnosable(tmp_path):
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"x" * 9000)
    r = speech.check(wav, reference="hello", max_wer=0.0,
                     transcriber=lambda p: "yellow")
    assert "yellow" in r.reason


def test_missing_audio_is_a_failure_not_an_exception(tmp_path):
    r = speech.check(tmp_path / "nope.wav", reference="hello",
                     transcriber=lambda p: "hello")
    assert not r.ok and "no audio" in r.reason.lower()


def test_a_file_too_small_to_hold_speech_fails_before_transcribing(tmp_path):
    """A bare 44-byte WAV header passes `test -s` and transcribes to nothing,
    which would otherwise read as a bad TTS model rather than an empty file."""
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"RIFF" + b"\x00" * 40)
    called = []
    r = speech.check(wav, reference="hello",
                     transcriber=lambda p: called.append(p) or "hello")
    assert not r.ok
    assert not called


def test_with_no_limit_the_check_measures_without_judging(tmp_path):
    """Ranking needs the number even when there is no threshold to fail."""
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"x" * 9000)
    r = speech.check(wav, reference="hello", transcriber=lambda p: "yellow")
    assert r.ok
    assert r.wer == 1.0


def test_a_transcriber_that_fails_is_reported_as_such(tmp_path):
    """An STT outage must not be recorded as a TTS candidate scoring 100%
    error."""
    from harness.audio import AudioError
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"x" * 9000)

    def broken(p):
        raise AudioError("stt unreachable")

    r = speech.check(wav, reference="hello", transcriber=broken)
    assert not r.ok
    assert "stt unreachable" in r.reason
    assert r.wer is None


# ---- counts, so the suite can compute a corpus rate ------------------------
#
# Averaging per-utterance rates lets a two-word clip weigh as much as a
# forty-word one. Measured on LibriSpeech: "Ay me" heard as "I me" is one error
# in two words = 0.500, and it was the single worst row in a 40-utterance run
# whose mean was 0.023. Every ASR benchmark reports CORPUS wer -- total errors
# over total reference words -- and that needs the counts, not just the rate.

def test_wer_counts_reports_errors_and_reference_length():
    errors, words = speech.wer_counts("the quick brown fox", "the quick brown box")
    assert (errors, words) == (1, 4)


def test_wer_counts_agrees_with_the_rate():
    ref, hyp = "the quick brown fox jumps", "the quick brown box"
    errors, words = speech.wer_counts(ref, hyp)
    assert abs(errors / words - speech.wer(ref, hyp)) < 1e-9


def test_wer_counts_normalizes_like_the_rate_does():
    assert speech.wer_counts("MLX 200 is fast", "mlx two hundred is fast")[0] == 0


def test_an_empty_hypothesis_counts_every_word_as_an_error():
    assert speech.wer_counts("one two three", "") == (3, 3)


def test_the_check_publishes_the_counts_for_aggregation(tmp_path):
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"x" * 9000)
    r = speech.check(wav, reference="the quick brown fox",
                     transcriber=lambda p: "the quick brown box")
    assert r.metrics["wer_errors"] == 1
    assert r.metrics["wer_words"] == 4


# ---- normalizing a language that is not English ----------------------------
# The digit expansion exists so "200" scored against "two hundred" is not an
# error. In French 92 is "quatre-vingt-douze" -- four words for two digits --
# so expanding with the English table turns a correct reading into four errors
# and reports it as the TTS model failing.

def test_digits_expand_in_the_language_being_spoken():
    # The hyphen goes the way every other punctuation mark does, and it goes
    # from both sides: the transcriber writes "quatre-vingt-douze" too.
    assert speech.normalize("42 jetons", language="fr") == "quarante deux jetons"
    assert speech.normalize("42 tokens") == "forty two tokens"


def test_a_correct_french_number_reading_is_not_an_error():
    assert speech.wer("Le modèle a produit 92 jetons.",
                      "Le modèle a produit quatre-vingt-douze jetons.",
                      language="fr") == 0.0


def test_scoring_french_with_the_english_table_would_have_been_wrong():
    """The bug this guards: same pair, default language, several errors."""
    assert speech.wer("Le modèle a produit 92 jetons.",
                      "Le modèle a produit quatre-vingt-douze jetons.") > 0.0


def test_wer_counts_uses_the_same_language(tmp_path):
    errors, words = speech.wer_counts(
        "92 jetons", "quatre-vingt-douze jetons", language="fr")
    assert errors == 0


def test_an_unsupported_language_says_so_rather_than_scoring_nonsense():
    with pytest.raises(ValueError) as e:
        speech.normalize("42", language="xx")
    assert "xx" in str(e.value)


def test_check_passes_the_language_through(tmp_path):
    clip = tmp_path / "a.wav"
    clip.write_bytes(b"x" * 9000)
    r = speech.check(clip, reference="92 jetons", language="fr",
                     transcriber=lambda p: "quatre-vingt-douze jetons")
    assert r.ok and r.wer == 0.0


# ---- one canonical spoken form for English numbers (#606) -------------------
# num2words says "one hundred and five"; a voice may say "one hundred five".
# Both sides are reduced to the same form, so either correct reading scores 0
# and a wrong number still costs a word.

@pytest.mark.parametrize("reference, heard", [
    ("He spent 105 nights there.", "he spent one hundred five nights there"),
    ("He spent 105 nights there.", "he spent one hundred and five nights there"),
    ("Rhiannon spent 125 nights.", "rhiannon spent one hundred twenty five nights"),
    ("It cost 2026 dollars.", "it cost two thousand twenty six dollars"),
    ("We shipped 9999 crates.", "we shipped nine thousand nine hundred ninety nine crates"),
    ("We shipped 6319 crates.", "we shipped six thousand three hundred nineteen crates"),
    ("About 1,250 people came.", "about one thousand two hundred fifty people came"),
    ("About 100 people came.", "about a hundred people came"),
    ("Take the 21st exit.", "take the twenty first exit"),
    ("She was 3rd in line.", "she was third in line"),
    ("It took 3.5 seconds.", "it took three point five seconds"),
    ("It took 2.05 seconds.", "it took two point zero five seconds"),
])
def test_a_correct_english_number_reading_is_not_an_error(reference, heard):
    assert speech.wer(reference, heard) == 0.0


@pytest.mark.parametrize("reference, heard", [
    ("He spent 105 nights there.", "he spent one hundred fifteen nights there"),
    ("He spent 105 nights there.", "he spent one hundred and fifteen nights there"),
    ("We shipped 6319 crates.", "we shipped sixty three nineteen crates"),
    ("He walked 1019 miles.", "he walked ten nineteen miles"),
    ("Take the 21st exit.", "take the twenty second exit"),
    ("It took 3.5 seconds.", "it took thirty five seconds"),
    ("About 1,250 people came.", "about one thousand two hundred people came"),
])
def test_a_wrong_number_is_still_an_error(reference, heard):
    assert speech.wer(reference, heard) > 0.0


def test_an_and_between_words_that_are_not_a_number_still_counts():
    assert speech.wer("salt and pepper", "salt pepper") > 0.0
    assert speech.wer("100 apples and 5 pears", "one hundred apples five pears") > 0.0


def test_the_canonical_form_drops_the_conjunction_on_both_sides():
    assert speech.normalize("105") == "one hundred five"
    assert speech.normalize("one hundred and five") == "one hundred five"
    assert speech.normalize("2026") == "two thousand twenty six"


def test_wer_counts_charge_nothing_for_a_correct_reading_over_99():
    assert speech.wer_counts("105 nights", "one hundred five nights") == (0, 4)
