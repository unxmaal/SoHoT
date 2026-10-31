"""Judging synthesized speech by whether it can be read back.

This is the suite's first quality axis. The objective checks elsewhere separate
working from broken and cannot order two candidates that both work; word error
rate can.

IT IS A JOINT MEASUREMENT of the TTS model and the STT model reading it, and it
cannot separate them. That is sound for the comparison it is used for -- hold
one side fixed, vary the other, and the ordering is real -- but a WER from here
is not an absolute score for either model on its own. Ranking STT models needs
reference audio with a human transcript (LibriSpeech test-clean), which this
machine does not have yet.
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import jiwer
from num2words import num2words

from harness import knobs, reasons
from harness.audio import AudioError, AudioTimeout

# A WAV header is 44 bytes. Anything near it holds no speech, and transcribing
# it would report the empty result as a terrible TTS model.
MIN_AUDIO_BYTES = 8000

_PUNCT = re.compile(r"[^\w\s]")
_DIGITS = re.compile(r"\d+")
_EN_NUMBER = re.compile(r"(\d+)(?:\.(\d+)|(st|nd|rd|th)\b)?")
_EN_GROUPING = re.compile(r"(?<=\d),(?=\d{3}\b)")
_SCALES = {"hundred", "thousand", "million", "billion"}
_SMALL = {"one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
          "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen",
          "seventeen", "eighteen", "nineteen", "twenty", "thirty", "forty", "fifty",
          "sixty", "seventy", "eighty", "ninety"}

#: The English WER normaliser's version; receipts carry it so WERs scored two ways are never compared. #1266.
NORMALISER = "2"
#: Lanes whose rows are scored by wer_counts, so whose receipts carry NORMALISER.
WER_LANES = ("music", "stt", "tts")

#: One spelling per English word where references and transcribers differ only in orthography: Whisper's map plus #701's. #1266.
_EN_SPELLING = {**json.loads((Path(__file__).with_name("english_spelling.json")).read_text(encoding="utf-8"))["spellings"],
                "mr": "mister", "mrs": "missus", "dr": "doctor", "o": "oh",
                **{f"en{s}": f"in{s}" for s in ("quire", "quired", "quires", "quiring", "quiry", "quiries")}}
#: Hesitations dropped on both sides, after the Open ASR leaderboard's patterns.
_FILLER = re.compile(r"a+h+m*|e+h+m*|e+r+m*|h+m+|m{2,}|m+h+m*|u+h+m*|u+m+h*")
#: Whisper's contractions, with 's expanded only after the leaderboard's pronouns and 'd only after a pronoun.
_PRONOUN = r"(i|you|he|she|it|we|they|who|what|that|there|here|how|when|where|why|this)"
_CONTRACTIONS = [(re.compile(p), r) for p, r in (
    (r"\bwon't\b", "will not"), (r"\bcan't\b", "can not"), (r"\blet's\b", "let us"), (r"\bma'am\b", "madam"),
    (r"\bwanna\b", "want to"), (r"\bgonna\b", "going to"), (r"\bgotta\b", "got to"),
    (r"'d been\b", " had been"), (r"'s been\b", " has been"), (r"'d gone\b", " had gone"), (r"'s gone\b", " has gone"),
    (r"'d done\b", " had done"), (r"'s got\b", " has got"),
    (r"n't\b", " not"), (r"'re\b", " are"), (rf"\b{_PRONOUN}'s\b", r"\1 is"), (rf"\b{_PRONOUN}'d\b", r"\1 would"),
    (r"(\w)'d\b", r"\1ed"), (r"'ll\b", " will"), (r"'ve\b", " have"), (r"'m\b", " am"),
    (r"(\d)\s*%", r"\1 percent"), (r"[$](\d[\d,]*)\b(?!\.\d)", r"\1 dollars"), (r"£(\d[\d,]*)\b(?!\.\d)", r"\1 pounds"))]
_BRACKETED = re.compile(r"[<\[][^>\]]*[>\]]|\([^)]*\)")
#: A reference word elided the old way (ceasd, smild): consonant then d, matching its -ed form.
_ELIDED = re.compile(r"[a-z]*[^aeiou\W\d]d")
#: A number in a hypothesis, held as one token until its reading is chosen.
_HELD = "zzheldnumber{}zz"
_HELD_TOKEN = re.compile(r"zzheldnumber(\d+)zz")


@dataclass
class SpeechResult:
    ok: bool
    reason: str = ""
    warnings: list[str] = field(default_factory=list)
    wer: float | None = None
    transcript: str = ""

    #: Errors and reference length, so the suite can aggregate a CORPUS rate.
    errors: int = 0
    words: int = 0
    failure_class: str = ""
    limit: str = ""

    @property
    def metrics(self) -> dict:
        """What the eval ranks on. Empty when nothing was measured, never 0.0:
        a zero error rate is the best possible score and would rank a candidate
        that never ran at the top.

        The counts travel with the rate so summarize() can total them. A mean
        of per-utterance rates lets a two-word clip weigh as much as a
        forty-word one, which is why ASR reports corpus wer instead.
        """
        if self.wer is None:
            return {}
        return {"wer": round(self.wer, 4),
                "wer_errors": self.errors, "wer_words": self.words}


def timed_out(exc: AudioTimeout) -> dict:
    """The class and limit a read-back past the audio timeout puts on a row. #693."""
    return {"failure_class": reasons.TIMEOUT, "limit": knobs.limit_text(exc.limit)}


def _en_number(m: re.Match) -> str:
    whole, frac, suffix = m.groups()
    if suffix:
        return num2words(int(whole), lang="en", to="ordinal")
    words = num2words(int(whole), lang="en")
    if frac:
        words += " point " + " ".join(num2words(int(d), lang="en") for d in frac)
    return words


def drop_number_and(words: list[str]) -> list[str]:
    """One spoken form for English numbers: "hundred and five" and "a hundred" become "hundred five" and "one hundred"."""
    result = []
    for i, word in enumerate(words):
        if (word == "and" and i > 0 and words[i - 1] in _SCALES
                and i + 1 < len(words) and words[i + 1] in _SMALL):
            continue
        if word == "a" and i + 1 < len(words) and words[i + 1] in _SCALES:
            result.append("one")
        else:
            result.append(word)
    return result


def normalize(text: str, language: str = "en") -> str:
    """Strip everything that would measure transcription style, not speech.

    Parakeet emits no reliable punctuation and inconsistent casing, and it
    spells numbers out: "MLX 200" comes back as "mlx two hundred". Counting
    those as errors ranks models on how they write, not on what they heard.

    The expansion has to happen in the language being spoken. French 92 is
    "quatre-vingt-douze" -- four words for two digits -- so expanding it with
    the English table turns a correct reading into four errors and reports it
    as the TTS model failing.
    """
    if language == "en":
        return " ".join(_en_words(text))
    try:
        text = _DIGITS.sub(
            lambda m: num2words(int(m.group()), lang=language), text)
    except NotImplementedError as exc:
        # Silently leaving the digits alone would score a correct reading as
        # wrong, which is the failure this function exists to prevent.
        raise ValueError(
            f"cannot normalize numbers for language {language!r}: {exc}") from exc
    text = _PUNCT.sub(" ", text.lower())
    return " ".join(text.split())


def _plain(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if unicodedata.category(c) != "Mn")


def _en_words(text: str, held: list | None = None) -> list[str]:
    """One side's English words; with `held`, each number stays one token and its match is appended to `held`."""
    text = _BRACKETED.sub(" ", _plain(text).lower().replace("’", "'"))
    for pattern, replacement in _CONTRACTIONS:
        text = pattern.sub(replacement, text)
    text = _EN_GROUPING.sub("", text)
    if held is None:
        text = _EN_NUMBER.sub(_en_number, text)
    else:
        text = _EN_NUMBER.sub(lambda m: held.append(m) or f" {_HELD.format(len(held) - 1)} ", text)
    words = [w for w in _PUNCT.sub(" ", text).split() if not _FILLER.fullmatch(w)]
    return [_EN_SPELLING.get(w, w) for w in drop_number_and(words)]


def _spoken(text: str) -> list[str]:
    return drop_number_and(_PUNCT.sub(" ", text).split())


def _readings(m: re.Match) -> list[list[str]]:
    """How a hypothesis's digits may have been said: cardinal first, then ordinal and, for four digits, a year."""
    whole, frac, suffix = m.groups()
    if suffix or frac:
        return [_spoken(_en_number(m))]
    n = int(whole)
    out = [_spoken(num2words(n, lang="en")), _spoken(num2words(n, lang="en", to="ordinal"))]
    if len(whole) == 4:
        out.append(_spoken(num2words(n, lang="en", to="year")))
    return out


def _errors(ref: list[str], hyp: list[str]) -> int:
    if not ref or not hyp:
        return len(ref) + len(hyp)
    out = jiwer.process_words(" ".join(ref), " ".join(hyp))
    return out.substitutions + out.deletions + out.insertions


def _read(ref: list[str], hyp: list[str], held: list) -> list[str]:
    """The hypothesis with each held number in the reading that leaves the fewest errors; a tie keeps the cardinal."""
    options = [_readings(m) for m in held]
    pick = [0] * len(options)

    def spell(choice):
        out = []
        for w in hyp:
            got = _HELD_TOKEN.fullmatch(w)
            out.extend(options[int(got.group(1))][choice[int(got.group(1))]] if got else [w])
        return out
    for i, readings in enumerate(options):
        pick[i] = min(range(len(readings)), key=lambda r: (_errors(ref, spell(pick[:i] + [r] + pick[i + 1:])), r))
    return spell(pick)


def _variants(side: list[str], other: list[str], score) -> list[str]:
    """`side` with adjacent words joined, or an elided -d spelled -ed, where `other` writes it so and errors fall."""
    vocab = set(other)
    i = 0
    while i < len(side):
        trials = []
        if i + 1 < len(side) and side[i] + side[i + 1] in vocab:
            trials.append(side[:i] + [side[i] + side[i + 1]] + side[i + 2:])
        if side[i] not in vocab and _ELIDED.fullmatch(side[i]) and side[i][:-1] + "ed" in vocab:
            trials.append(side[:i] + [side[i][:-1] + "ed"] + side[i + 1:])
        better = [t for t in trials if score(t) < score(side)]
        if better:
            side = better[0]
            continue
        i += 1
    return side


def pair(reference: str, hypothesis: str, language: str = "en") -> tuple[list[str], list[str]]:
    """Reference and hypothesis words as scored: each side normalised, then read against the other. #1266."""
    if language != "en":
        ref, hyp = normalize(reference, language).split(), normalize(hypothesis, language).split()
    else:
        held: list = []
        ref, hyp = _en_words(reference), _en_words(hypothesis, held)
        if ref:
            hyp = _read(ref, hyp, held)
            ref = _variants(ref, hyp, lambda r: _errors(r, hyp))
            hyp = _variants(hyp, ref, lambda h: _errors(ref, h))
    if not ref:
        raise ValueError("cannot score against an empty reference")
    return ref, hyp


def wer(reference: str, hypothesis: str, language: str = "en") -> float:
    """Word error rate, after normalization. 0.0 is perfect."""
    errors, words = wer_counts(reference, hypothesis, language)
    return errors / words


def wer_counts(reference: str, hypothesis: str,
               language: str = "en") -> tuple[int, int]:
    """(errors, reference words) after the same normalization wer() uses.

    Needed for a corpus rate: total errors over total words, rather than a mean
    of per-utterance rates in which a two-word clip outweighs a long one.
    """
    ref, hyp = pair(reference, hypothesis, language)
    if not hyp:
        return len(ref), len(ref)
    return _errors(ref, hyp), len(ref)


def check(path: str | Path, reference: str, max_wer: float | None = None,
          transcriber=None, language: str = "en") -> SpeechResult:
    """Transcribe the audio at `path` and compare it to `reference`.

    `max_wer` is optional: with no limit the check measures without judging,
    which is what ranking needs.
    """
    from harness import audio  # imported here so tests can inject a stub

    transcriber = transcriber or audio.transcribe
    path = Path(path)
    if not path.exists():
        return SpeechResult(False, f"no audio file at {path}")
    size = path.stat().st_size
    if size < MIN_AUDIO_BYTES:
        from harness import cuts
        cuts.cut("harness/checks/speech.py:MIN_AUDIO_BYTES", f"speech {path.name}: {size} bytes")
        return SpeechResult(
            False, f"audio is {size} bytes, too small to hold speech")

    try:
        transcript = transcriber(path)
    except AudioTimeout as exc:
        return SpeechResult(False, f"could not transcribe: {exc}", **timed_out(exc))
    except AudioError as exc:
        # An STT outage must not be recorded as this candidate scoring 100%
        # error: that is a broken instrument, not a bad model.
        return SpeechResult(False, f"could not transcribe: {exc}")

    rate = wer(reference, transcript, language)
    errors, words = wer_counts(reference, transcript, language)
    if max_wer is not None and rate > max_wer:
        return SpeechResult(
            False,
            f"word error rate {rate:.2f} over the limit of {max_wer}; "
            f"heard {transcript!r}",
            wer=rate, transcript=transcript, errors=errors, words=words)
    return SpeechResult(True, "", wer=rate, transcript=transcript,
                        errors=errors, words=words)
