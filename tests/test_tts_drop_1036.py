"""#1036: a tts stream the audio server drops is decided from the server's own traceback, cut from its log."""
import sys
from pathlib import Path

import httpx
import pytest
import respx

from evals.core import Case
from evals.runners.speech import SpeechRunner
from harness import audio, audio_log, paths, reasons, runner_gaps, screen

BASE = "http://127.0.0.1:8890/v1"
FIXTURES = Path(__file__).parent / "fixtures" / "audio_log"
#: ~/localharness/logs/tts.log lines 4447-4700: Kokoro's voice fetch timed out mid-stream (an older mlx-audio).
KOKORO = (FIXTURES / "kokoro-drop.log").read_text(encoding="utf-8")
#: tts.log lines 16404-16426: an stt failure mlx-audio 0.5.3 prints and answers in-band, no ASGI error.
STT = (FIXTURES / "stt-no-processor.log").read_text(encoding="utf-8")
#: mlx-audio 0.5.3 server, serve-tts.sh's live --with set (no soundfile), arktts ref_audio request on a scratch port.
ARKTTS = (FIXTURES / "arktts-soundfile-drop.log").read_text(encoding="utf-8")
ARK = "org/arktts-ref"
DROP = httpx.RemoteProtocolError("peer closed connection without sending complete message body (incomplete chunked read)")


def _log(name="tts.log") -> Path:
    path = paths.logs() / name
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _drop(log: Path, appended: str):
    def post(request):
        with open(log, "a", encoding="utf-8") as fh:
            fh.write(appended)
        raise DROP
    return post


def _row(tmp_path, ref=True):
    wav = tmp_path / "ref.wav"
    wav.write_bytes(b"RIFF")
    runner = SpeechRunner(model=ARK, voice="", outdir=tmp_path / "run", base_url=BASE,
                          ref_audio=wav if ref else None)
    runner.spec = f"tts:{ARK}"
    return runner.run(Case(id="pangram", modality="tts", prompt="the quick brown fox",
                           assertions={"max_wer": 0.2})), tmp_path / "run" / audio_log.FILE


def _lines(text):
    return text.splitlines(keepends=True)


def test_the_live_kokoro_drop_is_cut_from_uvicorns_line_to_the_last_exception_of_its_chain():
    ex = audio_log.cut(_lines(KOKORO), "tts.log", 4446)
    assert "Exception in ASGI application" in ex.lines[0]
    assert ex.lines[-1].startswith("requests.exceptions.ReadTimeout: HTTPSConnectionPool(host='raw.githubusercontent.com'")
    assert (ex.first, ex.last) == (4545, 4692)
    # The next request's line is not part of it, though stdout ran into it with no newline.
    assert not any("51134" in line for line in ex.lines)
    assert ex.errors[0].startswith("requests.exceptions.ReadTimeout")
    assert any(e.startswith("TimeoutError: [Errno 60]") for e in ex.errors)
    # A later drop in the same window ends nothing of this one.
    assert audio_log.cut(_lines(KOKORO + ARKTTS), "tts.log", 4446) == ex


def test_a_traceback_the_server_printed_and_answered_in_band_is_not_a_drop():
    assert audio_log.cut(_lines(STT)) is None


@respx.mock
@pytest.mark.parametrize("platform", ["darwin", "linux", "win32"])
def test_a_soundfile_traceback_beside_a_dropped_stream_waits_on_the_audio_servers_env(tmp_path, monkeypatch, platform):
    monkeypatch.setattr(sys, "platform", platform)
    log = _log()
    # An older drop before the request is not ours; an stt traceback beside ours is not a drop.
    log.write_text(KOKORO + STT, encoding="utf-8")
    respx.post(f"{BASE}/audio/speech").mock(side_effect=_drop(log, STT + ARKTTS))
    row, kept = _row(tmp_path)
    assert row.failure_class == reasons.MISSING_PACKAGE, row.detail
    assert "calibration clip failed while generating" in row.detail
    assert "No module named 'soundfile'" in row.detail
    before = len(_lines(KOKORO + STT + STT))
    ark = _lines(ARKTTS)
    first = before + next(i for i, s in enumerate(ark) if "Exception in ASGI application" in s) + 1
    last = before + max(i for i, s in enumerate(ark) if s.startswith("ModuleNotFoundError")) + 1
    assert kept.read_text(encoding="utf-8").splitlines()[0] == f"# tts.log lines {first}-{last}"
    assert "ReadTimeout" not in kept.read_text(encoding="utf-8")
    v = screen.decide_class(row.failure_class, row.detail, f"tts:{ARK}")
    assert (v.outcome, v.reason, v.until) == ("declined", reasons.RUNTIME, f"package:soundfile@{runner_gaps.AUDIO_ENV}")


@respx.mock
def test_a_drop_with_nothing_in_the_log_is_the_harness_queued(tmp_path):
    log = _log()
    log.write_text(KOKORO, encoding="utf-8")
    respx.post(f"{BASE}/audio/speech").mock(side_effect=_drop(log, "INFO:     127.0.0.1:1 - \"POST /v1/audio/speech HTTP/1.1\" 200 OK\n"))
    row, kept = _row(tmp_path, ref=False)
    assert row.failure_class == reasons.HARNESS_ERROR, row.detail
    assert reasons.CLASSES[row.failure_class] == ("queued", reasons.HARNESS)
    assert not kept.exists()


@respx.mock
def test_a_drop_from_another_machines_server_reads_no_local_log(tmp_path):
    log = _log()
    log.write_text("", encoding="utf-8")
    respx.post("http://studio.example:8890/v1/audio/speech").mock(side_effect=_drop(log, ARKTTS))
    with pytest.raises(audio.StreamDropped) as e:
        audio.speak("hi", out=tmp_path / "a.wav", base_url="http://studio.example:8890/v1")
    assert e.value.excerpt is None
    assert reasons.classify(str(e.value), reasons.RUNNER, "tts:x/y") == reasons.HARNESS_ERROR


@respx.mock
def test_a_log_rotated_during_the_request_is_read_from_its_start(tmp_path):
    log = _log()
    log.write_text(KOKORO + KOKORO, encoding="utf-8")

    def post(request):
        log.write_text(ARKTTS, encoding="utf-8")
        raise DROP
    respx.post(f"{BASE}/audio/speech").mock(side_effect=post)
    with pytest.raises(audio.StreamDropped) as e:
        audio.speak("hi", out=tmp_path / "a.wav", base_url=BASE)
    assert e.value.excerpt.errors == ["ModuleNotFoundError: No module named 'soundfile'"]


@respx.mock
def test_services_sh_stderr_file_is_read_when_launchd_has_no_tts_log(tmp_path):
    log = _log("audio.err.log")
    respx.post(f"{BASE}/audio/speech").mock(side_effect=_drop(log, ARKTTS))
    with pytest.raises(audio.StreamDropped) as e:
        audio.speak("hi", out=tmp_path / "a.wav", base_url=BASE)
    assert "audio.err.log lines" in str(e.value)
    assert reasons.classify(str(e.value), reasons.RUNNER, "tts:x/y") == reasons.MISSING_PACKAGE


def test_an_exception_group_uvicorn_logs_is_read_through_its_bars():
    import traceback
    try:
        try:
            import soundfile_absent_1036  # noqa: F401
        except ModuleNotFoundError as inner:
            raise ExceptionGroup("unhandled errors in a TaskGroup", [ModuleNotFoundError("No module named 'soundfile'")]) from inner
    except ExceptionGroup as eg:
        text = "ERROR:    Exception in ASGI application\n" + "".join(traceback.format_exception(eg))
    ex = audio_log.cut(_lines(text + STT))
    assert "ModuleNotFoundError: No module named 'soundfile'" in ex.errors
    assert reasons.classify(" ".join(ex.errors), reasons.RUNNER, f"tts:{ARK}") == reasons.MISSING_PACKAGE


def test_an_isolated_home_reads_the_serving_homes_audio_log(tmp_path, monkeypatch):
    from harness import load_log
    monkeypatch.setenv(load_log.SERVING_ENV, str(tmp_path / "serving"))
    assert audio_log.logs()[0] == tmp_path / "serving" / "logs" / "tts.log"


@respx.mock
def test_the_live_drop_a_voice_fetch_timed_out_on_is_the_network_queued_not_the_model(tmp_path):
    log = _log()
    respx.post(f"{BASE}/audio/speech").mock(side_effect=_drop(log, KOKORO))
    row, kept = _row(tmp_path, ref=False)
    assert "Read timed out" in row.detail
    assert row.failure_class == reasons.HARNESS_ERROR, row.detail
    assert kept.is_file()
    plain = "requests.exceptions.ConnectionError: HTTPConnectionPool(host='mirror', port=80): Max retries exceeded"
    assert reasons.classify(plain, reasons.RUNNER, f"tts:{ARK}") == reasons.HARNESS_ERROR
