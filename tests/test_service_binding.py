"""Which address the services listen on.

Only the gateway binds 0.0.0.0 by default, and it demands a key (#482). The
text engines behind it take none, so they listen on loopback; MCP and audio
listen on loopback too and demand the gateway key when opened to the LAN
(#510). Either way the address is a PARAMETER: one variable per service.
"""
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SERVICES = {
    "scripts/serve-gateway.sh": "GATEWAY_HOST",
    "scripts/serve-mlx.sh": "MLX_HOST",
    "scripts/serve-tts.sh": "TTS_HOST",
    # The text lane's server on a machine with an NVIDIA card. Same rule: the
    # address is a parameter, and it listens everywhere by default because the
    # point is that the other machine can use this one's GPU.
    "scripts/serve-llamacpp.sh": "LLAMACPP_HOST",
    # The audio lanes on the same machine. mlx_audio serves these two
    # endpoints on the Mac; harness/audio_server.py serves them here.
    "scripts/serve-audio-cuda.sh": "AUDIO_HOST",
    "scripts/serve-mcp.sh": "MCP_HOST",
}


@pytest.mark.parametrize("script,var", SERVICES.items())
def test_the_listening_address_is_a_variable(script, var):
    """A hardcoded --host cannot be changed without editing the script."""
    text = (REPO / script).read_text(encoding="utf-8")
    assert f"${{{var}:-" in text, f"{script} should read its host from ${var}"
    assert not re.search(r'--host\s+["\']?127\.0\.0\.1["\']?\s', text), (
        f"{script} still hardcodes 127.0.0.1")


#: Loopback by default: keyless behind the gateway (#482), or keyed only when opened (#510).
LOOPBACK = {"scripts/serve-mlx.sh", "scripts/serve-llamacpp.sh", "scripts/serve-tts.sh",
            "scripts/serve-audio-cuda.sh", "scripts/serve-mcp.sh"}


@pytest.mark.parametrize("script,var", SERVICES.items())
def test_only_the_keyed_gateway_defaults_to_every_interface(script, var):
    text = (REPO / script).read_text(encoding="utf-8")
    want = r"127\.0\.0\.1" if script in LOOPBACK else r"0\.0\.0\.0"
    assert re.search(rf'\$\{{{var}:-{want}\}}', text), (
        f"{script} should default {var} to {want}")


def test_the_mac_tts_goes_through_the_key_guard():
    """mlx-audio has no key option, so its app is served by harness.lan_auth. #510."""
    text = (REPO / "scripts" / "serve-tts.sh").read_text(encoding="utf-8")
    assert "python -m harness.lan_auth mlx_audio.server:app" in text
    assert "python -m mlx_audio.server" not in text


@pytest.mark.parametrize("script", SERVICES)
def test_the_choice_is_argued_for_where_it_is_made(script):
    """The binding must not look accidental to whoever reads this next. It was
    0.0.0.0 by accident once already."""
    text = (REPO / script).read_text(encoding="utf-8").lower()
    assert ("lan" in text or "no auth" in text or "every interface" in text
            or "loopback" in text), (
        f"{script} binds every interface without saying why")


def test_smoke_can_be_pointed_at_another_host():
    """If the Studio serves and the Apple Silicon machine is a client, the smoke test has to be
    runnable against the Studio."""
    text = (REPO / "scripts" / "smoke.sh").read_text(encoding="utf-8")
    assert "${SMOKE_HOST:-" in text
    assert not re.search(r'="http://127\.0\.0\.1:', text)
