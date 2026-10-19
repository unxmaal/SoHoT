"""#1030: the audio server's env is a runner env, so a package its model reads waits on the server's own pins."""
import json
import shutil
import sys
from pathlib import Path

import httpx
import pytest

from harness import audio, live_audit, paths, reasons, runner_gaps, screen
from harness import memory_store as ms
from harness.memory_store import revisit
from tests.test_whisper_group_1024 import _decline

GRANITE = "ibm-granite/granite-speech-4.1-2b-nar"
#: mlx-audio 0.5.3 server._stream_inference_results: an stt failure after the 200 is one in-band ndjson line.
IN_BAND = json.dumps({"error": {"message": "No module named 'soundfile'", "type": "ModuleNotFoundError"}}) + "\n"


@pytest.fixture
def store(tmp_path):
    conn = ms.connect(tmp_path / "s.db")
    yield conn
    conn.close()


def _server_error(monkeypatch):
    def post(url, **kw):
        return httpx.Response(200, text=IN_BAND, request=httpx.Request("POST", url))
    monkeypatch.setattr(httpx, "post", post)


def _evidence(tmp_path, monkeypatch) -> str:
    _server_error(monkeypatch)
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"RIFF")
    with pytest.raises(audio.AudioError) as e:
        audio.transcribe(wav, model=GRANITE, base_url="http://127.0.0.1:1/v1")
    return f"it ran and passed nothing: 1089-134686-0001: {e.value}"


@pytest.mark.parametrize("platform", ["darwin", "linux", "win32"])
def test_a_soundfile_the_audio_server_lacks_waits_on_the_servers_env_and_the_deploy_ends_it(
        tmp_path, monkeypatch, platform):
    monkeypatch.setattr(sys, "platform", platform)
    why = _evidence(tmp_path, monkeypatch)
    assert "No module named 'soundfile'" in why
    cls = reasons.classify(why, reasons.RUNNER, f"stt:{GRANITE}")
    assert cls == reasons.MISSING_PACKAGE
    v = screen.decide_class(cls, why, f"stt:{GRANITE}")
    assert (v.outcome, v.reason, v.until) == ("declined", reasons.RUNTIME, f"package:soundfile@{runner_gaps.AUDIO_ENV}")
    # uv builds the env when the service starts, so the deploy's pin is what ends the wait.
    assert revisit.until_met(v.until, {})


def test_the_wait_holds_while_the_servers_script_does_not_pin_it(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    (tmp_path / "scripts").mkdir()
    shutil.copy(paths.REPO / "pyproject.toml", tmp_path)
    shutil.copy(paths.REPO / "scripts" / "versions.sh", tmp_path / "scripts")
    text = (paths.REPO / "scripts" / "serve-tts.sh").read_text(encoding="utf-8")
    (tmp_path / "scripts" / "serve-tts.sh").write_text(text.replace('--with "$SOUNDFILE_PIN"', ""), encoding="utf-8")
    assert not runner_gaps.provides("soundfile", runner_gaps.AUDIO_ENV, tmp_path)
    assert runner_gaps.provides("mlx-audio", runner_gaps.AUDIO_ENV, tmp_path)


def test_each_platforms_audio_server_script_is_read_when_asked(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    mac = runner_gaps.installs(runner_gaps.AUDIO_ENV)
    assert {"mlx-audio", "misaki", "fastapi", "setuptools", "soundfile"} <= mac
    assert "faster-whisper" not in mac
    # uv layers the --with pins over the checkout's .venv, so the project's own dependencies are there too.
    assert runner_gaps.installs("") <= mac
    monkeypatch.setattr(sys, "platform", "linux")
    cuda = runner_gaps.installs(runner_gaps.AUDIO_ENV)
    assert {"faster-whisper", "kokoro-onnx", "soundfile", "nvidia-cublas-cu12"} <= cuda
    assert "mlx-audio" not in cuda


def test_the_audio_heads_map_to_the_servers_env_unless_another_runner_reads_the_audio():
    env = runner_gaps.AUDIO_ENV
    assert runner_gaps.venv_of(f"stt:{GRANITE}") == env
    assert runner_gaps.venv_of("tts:mlx-community/Kokoro-82M-bf16,voice=af_sky") == env
    assert runner_gaps.venv_of(f"stt:{GRANITE},backend=server") == env
    assert runner_gaps.venv_of(f"stt:{GRANITE},backend=whisper") == runner_gaps.WHISPER_VENV
    assert runner_gaps.venv_of("tts:mlx-community/Kokoro-82M-bf16,ear=whisper:fr") == runner_gaps.WHISPER_VENV
    assert runner_gaps.venv_of("stt:FluidInference/parakeet,backend=fluidaudio") == ""
    assert runner_gaps.venv_of("hf-ocr:microsoft/trocr-small-printed") == "hf-task"


def test_the_servers_env_is_never_an_evals_run_interpreter(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "home", lambda: tmp_path)
    assert runner_gaps.launcher([f"stt:{GRANITE}"], ["x"]) == ["x"]
    assert not runner_gaps.has_package("soundfile", runner_gaps.AUDIO_ENV)


def test_a_held_soundfile_on_the_servers_env_is_reachable(store, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    _decline(store, GRANITE, f"package:soundfile@{runner_gaps.AUDIO_ENV}", reasons.MISSING_PACKAGE, "x",
             f"stt:{GRANITE}")
    assert live_audit.unreachable_packages(store) == []
    assert "soundfile" not in runner_gaps.uninstalled_runner_packages()


def test_serve_tts_pins_soundfile_from_versions_sh():
    text = (Path(paths.REPO) / "scripts" / "serve-tts.sh").read_text(encoding="utf-8")
    assert '--with "$SOUNDFILE_PIN"' in text
