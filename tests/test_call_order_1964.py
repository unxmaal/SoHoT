"""Gauntlet OR-8 rest (#1964): the speech defaults follow the platform and WHISPER_MODEL of the moment."""
import sys

import httpx
import respx

from evals.runners.transcription import TranscriptionRunner
from harness import audio

BASE = "http://audio.test/v1"


def _windows(monkeypatch, whisper="Systran/faster-whisper-small.en"):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("WHISPER_MODEL", whisper)
    return whisper


def test_the_stt_default_is_the_whisper_model_set_after_import(monkeypatch):
    whisper = _windows(monkeypatch)
    assert audio.default_stt_model() == whisper
    monkeypatch.setenv("WHISPER_MODEL", "Systran/faster-whisper-tiny.en")
    assert audio.default_stt_model() == "Systran/faster-whisper-tiny.en"


def test_the_tts_default_follows_the_platform_of_the_moment(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    assert audio.default_tts_model() == audio.SPEECH_DEFAULTS["tts"]["win32"]
    monkeypatch.setattr(sys, "platform", "darwin")
    assert audio.default_tts_model() == audio.SPEECH_DEFAULTS["tts"]["other"]
    assert audio.default_stt_model() == audio.SPEECH_DEFAULTS["stt"]["other"]


def test_the_transcription_runner_takes_the_default_of_the_moment(monkeypatch):
    whisper = _windows(monkeypatch)
    runner = TranscriptionRunner(base_url=BASE)
    assert runner.model == whisper
    assert runner.candidate == whisper.split("/")[-1]


@respx.mock
def test_lh_hear_sends_the_whisper_model_set_after_import(monkeypatch, tmp_path):
    from tests.test_harness_audio import wav_bytes
    clip = tmp_path / "c.wav"
    clip.write_bytes(wav_bytes())
    route = respx.post(f"{BASE}/audio/transcriptions").mock(
        return_value=httpx.Response(200, json={"text": "x"}))
    whisper = _windows(monkeypatch)
    audio.transcribe(clip, base_url=BASE)
    assert whisper in route.calls[0].request.read().decode("utf-8", "replace")
