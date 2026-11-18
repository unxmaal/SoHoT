import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler
from pathlib import Path

import pytest

from harness import audio, loopback, monitor
from tests import shells

REPO = Path(__file__).resolve().parents[1]
BASH = shells.resolve("bash")
needs_bash = pytest.mark.skipif(sys.platform == "win32" or BASH is None, reason="runs scripts/smoke.sh lines in bash")


def _audio_lines() -> str:
    """smoke.sh's audio section, as smoke runs it."""
    lines = (REPO / "scripts" / "smoke.sh").read_text(encoding="utf-8").splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.startswith("# ---- audio"))
    end = next(i for i, ln in enumerate(lines) if ln.startswith("# Machine monitoring"))
    return "\n".join(lines[start:end])


@pytest.fixture
def broken_tts():
    """A speech server that answers every request 500, as the serving release's did offline."""
    class Broken(BaseHTTPRequestHandler):
        def do_POST(self):
            self.send_response(500)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *a):
            return None

    srv = loopback.ThreadingHTTPServer(("127.0.0.1", 0), Broken)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv.server_address[1]
    srv.shutdown()


def _smoke(port, speech=None):
    script = "FAIL=0\nok(){ printf 'PASS  %s\\n' \"$1\"; }\nno(){ printf 'FAIL  %s\\n' \"$1\"; FAIL=1; }\n" \
             + "H=127.0.0.1\n" + _audio_lines() + "\nexit $FAIL\n"
    env = {k: v for k, v in os.environ.items() if k != audio.SPEECH_ENV}
    env.update(TTS_PORT=str(port), SMOKE_TTS_MODEL="t", SMOKE_STT_MODEL="s", SMOKE_G2P_CHECK="false")
    if speech is not None:
        env[audio.SPEECH_ENV] = speech
    return subprocess.run([BASH, "-c", script], cwd=REPO, env=env, capture_output=True, text=True,
                          encoding="utf-8", timeout=120)


@needs_bash
def test_a_broken_speech_server_does_not_fail_smoke_while_speech_is_paused(broken_tts):
    got = _smoke(broken_tts)
    assert got.returncode == 0, got.stdout + got.stderr
    assert "SKIP  speech checks" in got.stdout and "speech is paused" in got.stdout
    assert "FAIL" not in got.stdout


@needs_bash
def test_with_speech_on_the_same_broken_server_fails_smoke(broken_tts):
    got = _smoke(broken_tts, speech="1")
    assert got.returncode == 1, got.stdout + got.stderr
    assert "FAIL  tts speech" in got.stdout and "FAIL  stt transcription round trip" in got.stdout
    assert "SKIP  speech checks" not in got.stdout


@needs_bash
@pytest.mark.parametrize("value", ["", "0", "no", "off", "1", "true", "YES", "On", " on "])
def test_smoke_and_the_harness_read_the_switch_alike(broken_tts, value):
    got = _smoke(broken_tts, speech=value)
    assert (got.returncode == 1) is audio.speech_enabled({audio.SPEECH_ENV: value}), (value, got.stdout)


def test_speech_is_paused_by_default(monkeypatch):
    monkeypatch.delenv(audio.SPEECH_ENV, raising=False)
    assert not audio.speech_enabled()
    monkeypatch.setenv(audio.SPEECH_ENV, "1")
    assert audio.speech_enabled()


def _units(tmp_path):
    for unit in ("gateway", "tts"):
        (tmp_path / f"com.unxmaal.localharness.{unit}.plist").write_text("x", encoding="utf-8")


def test_monit_does_not_watch_tts_while_speech_is_paused(tmp_path, monkeypatch):
    _units(tmp_path)
    monkeypatch.delenv(audio.SPEECH_ENV, raising=False)
    monkeypatch.delenv("GATEWAY_PORT", raising=False)
    assert monitor.watched_services(tmp_path) == [("gateway", 4000)]


def test_monit_watches_tts_with_speech_on(tmp_path, monkeypatch):
    _units(tmp_path)
    monkeypatch.setenv(audio.SPEECH_ENV, "1")
    monkeypatch.delenv("GATEWAY_PORT", raising=False)
    monkeypatch.delenv("TTS_PORT", raising=False)
    assert monitor.watched_services(tmp_path) == [("gateway", 4000), ("tts", 8890)]
