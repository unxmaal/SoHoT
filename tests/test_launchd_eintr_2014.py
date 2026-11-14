"""The units' weights env survives a SIGCHLD that lands while its write to a pipe waits: bash 3.2's printf fails EINTR. #2014."""
from __future__ import annotations

import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from tests import shells

LAUNCHD = Path(__file__).resolve().parents[1] / "scripts" / "launchd.sh"
pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="SIGCHLD and process groups are POSIX")
#: macOS's /bin/bash is 3.2, whose SIGCHLD handler restarts nothing; a newer bash on PATH does not show it.
BASHES = sorted({b for b in (shells.BASH, "/bin/bash") if b and Path(b).exists()})


def _function(name: str) -> str:
    text = LAUNCHD.read_text(encoding="utf-8")
    m = re.search(rf"^{name}\(\) \{{\n.*?^\}}\n", text, re.M | re.S)
    assert m, f"launchd.sh defines no {name}()"
    return m.group(0)


def _full_pipe() -> tuple[int, int]:
    import fcntl
    r, w = os.pipe()
    flags = fcntl.fcntl(w, fcntl.F_GETFL)
    fcntl.fcntl(w, fcntl.F_SETFL, flags | os.O_NONBLOCK)
    while True:
        try:
            os.write(w, b"." * 4096)
        except BlockingIOError:
            break
    fcntl.fcntl(w, fcntl.F_SETFL, flags)
    return r, w


def _drain(r: int) -> bytes:
    out = b""
    while chunk := os.read(r, 65536):
        out += chunk
    os.close(r)
    return out


@pytest.mark.parametrize("bash", BASHES)
def test_hf_env_writes_whole_through_a_sigchld_during_a_blocked_write(bash, tmp_path):
    marker = tmp_path / "pairs-read"
    script = (f"_hf_pairs() {{ printf 'HF_ROOT=/w/root\\nHF_HOME=/w/home\\n'; : > {marker}; }}\n"
              f"{_function('_hf_env')}_hf_env\n")
    r, w = _full_pipe()
    proc = subprocess.Popen([bash, "-c", script], stdout=w, stderr=subprocess.PIPE, start_new_session=True)
    os.close(w)
    try:
        end = time.monotonic() + 30
        while not marker.exists() and proc.poll() is None and time.monotonic() < end:
            time.sleep(0.01)
        assert marker.exists(), "the stand-in _hf_pairs never ran"
        sent = 0
        while sent < 25 and proc.poll() is None:
            os.killpg(proc.pid, signal.SIGCHLD)
            sent += 1
            time.sleep(0.02)
        assert sent, "the write did not wait on the full pipe, so no signal met it"
        out = _drain(r)
        rc = proc.wait(timeout=30)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
    err = proc.stderr.read().decode()
    assert rc == 0 and err == "", err
    assert out.lstrip(b".").decode() == ("    <key>HF_ROOT</key><string>/w/root</string>\n"
                                         "    <key>HF_HOME</key><string>/w/home</string>\n")


@pytest.mark.parametrize("bash", BASHES)
def test_hf_env_with_no_pairs_writes_nothing(bash):
    got = subprocess.run([bash, "-c", f"_hf_pairs() {{ :; }}\n{_function('_hf_env')}_hf_env\n"],
                         capture_output=True, text=True, timeout=30)
    assert (got.returncode, got.stdout, got.stderr) == (0, "", "")
