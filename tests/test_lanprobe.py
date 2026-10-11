"""The launchd-context LAN probe: macOS Local Network privacy, told apart from a node that is down. #739."""
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from harness import lanprobe, nodes
from tests.shells import BASH

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "lan-probe.sh"


# --- classification -----------------------------------------------------------

def test_an_instant_errno_65_is_the_privacy_block():
    assert lanprobe.classify("65 3")[0] == lanprobe.PRIVACY


def test_a_slow_errno_65_is_a_real_missing_route():
    assert lanprobe.classify(f"65 {lanprobe.INSTANT_MS + 2000}")[0] == lanprobe.DOWN


@pytest.mark.parametrize("line", ["61 2", "timeout 3001", "60 3000", "64 900", "dns 12"])
def test_refused_or_timed_out_means_down(line):
    assert lanprobe.classify(line)[0] == lanprobe.DOWN


@pytest.mark.parametrize("line", ["", "Traceback (most recent call last):", "65", "ok x"])
def test_anything_else_is_unknown(line):
    assert lanprobe.classify(line)[0] == lanprobe.UNKNOWN


def test_a_privacy_block_fails_and_names_the_settings_path(tmp_path):
    passed, text = lanprobe.verdict("pc", "node-host:18082", "65 4", sys.executable)
    assert not passed
    assert "System Settings > Privacy & Security > Local Network" in text and "Python" in text
    assert os.path.realpath(sys.executable) in text
    assert "restart gateway" in text


def test_a_down_node_passes_and_says_it_is_down():
    passed, text = lanprobe.verdict("pc", "node-host:18082", "61 1", "")
    assert passed and "down, not blocked" in text and "Local Network" not in text


def test_a_probe_that_never_ran_fails():
    passed, text = lanprobe.verdict("pc", "node-host:18082", "", "")
    assert not passed and "no launchd probe result" in text


def test_the_verdict_reads_the_first_line_a_kept_alive_job_wrote(tmp_path, capsys):
    out = tmp_path / "out"
    out.write_text("\n65 2\nok 1\n", encoding="utf-8")
    assert lanprobe.main(["verdict", "pc", "h:1", str(out)]) == 1
    assert "Local Network" in capsys.readouterr().out


def _closed_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_connect_reports_ok_against_a_listener():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        line = lanprobe.connect("127.0.0.1", s.getsockname()[1], 2.0)
    assert lanprobe.classify(line)[0] == lanprobe.OK


def test_connect_reports_a_refusal_as_down():
    line = lanprobe.connect("127.0.0.1", _closed_port(), 2.0)
    assert lanprobe.classify(line)[0] == lanprobe.DOWN, line


def test_targets_come_from_nodes_yaml():
    node = nodes.Node("pc", "http://node-host:18082/v1", "llama-server", ("m",), connect_timeout=3)
    assert lanprobe.targets([node]) == ["pc node-host 18082 3 1"]


# --- the shell around launchctl -------------------------------------------------

FAKE_LAUNCHCTL = r"""#!/usr/bin/env bash
echo "$*" >> "$FAKE_LOG"
[ "$1" = submit ] || exit 0
shift
while [ "$1" != -- ]; do case "$1" in -o) out="$2"; shift 2 ;; *) shift ;; esac; done
shift
if [ -n "${FAKE_PROBE_LINE+set}" ]; then printf '%s' "$FAKE_PROBE_LINE" >> "$out"; else "$@" >> "$out" 2>&1; fi
"""


@pytest.fixture
def probe(tmp_path):
    if not BASH or sys.platform == "win32":
        pytest.skip("needs a POSIX bash")
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    (bin_ / "launchctl").write_text(FAKE_LAUNCHCTL, encoding="utf-8")
    (bin_ / "uname").write_text("#!/bin/sh\necho Darwin\n", encoding="utf-8")
    for f in bin_.iterdir():
        f.chmod(0o755)
    log = tmp_path / "launchctl.log"

    def run(port, line=None):
        (tmp_path / "nodes.yaml").write_text(
            f"nodes:\n  - name: pc\n    api_base: http://127.0.0.1:{port}/v1\n"
            f"    engine: llama-server\n    models: [m]\n    connect_timeout: 2\n", encoding="utf-8")
        env = {**os.environ, "PATH": f"{bin_}{os.pathsep}{os.environ['PATH']}",
               "LOCALHARNESS_HOME": str(tmp_path), "SOHOT_NODES": str(tmp_path / "nodes.yaml"),
               "LAN_PROBE_PYTHON": sys.executable, "LAN_PROBE_WAIT_EXTRA_S": "2",
               "FAKE_LOG": str(log)}
        env.pop("FAKE_PROBE_LINE", None)
        if line is not None:
            env["FAKE_PROBE_LINE"] = line
        got = subprocess.run([BASH, str(SCRIPT)], cwd=REPO, env=env, capture_output=True,
                             text=True, timeout=120)
        return got, log.read_text(encoding="utf-8") if log.exists() else ""
    return run


def test_the_shell_submits_removes_and_fails_on_a_privacy_block(probe):
    got, calls = probe(18082, line="65 3")
    assert got.returncode == 1, got.stdout + got.stderr
    assert "Privacy & Security > Local Network" in got.stdout
    submits = [c for c in calls.splitlines() if c.startswith("submit")]
    assert len(submits) == 1 and "lanprobe.py connect 127.0.0.1 18082 2 1" in submits[0]
    assert sys.executable in submits[0]
    label = submits[0].split("-l ", 1)[1].split()[0]
    assert calls.splitlines()[-1] == f"remove {label}" and calls.splitlines()[0].startswith("submit")


def test_the_shell_runs_the_real_connect_and_reports_a_down_node(probe):
    got, _ = probe(_closed_port())
    assert got.returncode == 0, got.stdout + got.stderr
    assert "DOWN  node pc" in got.stdout


def test_the_shell_passes_a_reachable_node(probe):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen(4)
        got, _ = probe(s.getsockname()[1])
    assert got.returncode == 0 and "PASS  launchd can reach node pc" in got.stdout, got.stdout + got.stderr


def test_the_shell_fails_when_the_job_never_writes(probe):
    got, _ = probe(18082, line="")
    assert got.returncode == 1 and "no launchd probe result" in got.stdout


# --- wired into install and smoke -----------------------------------------------

def _install_body() -> str:
    text = (REPO / "scripts" / "launchd.sh").read_text(encoding="utf-8")
    return text.split("install_units() {", 1)[1].split("\n}\n", 1)[0]


def test_install_probes_the_lan_after_the_gateway_is_reloaded():
    body = _install_body()
    assert "scripts/lan-probe.sh" in body
    assert body.index("scripts/lan-probe.sh") > body.index("launchctl bootstrap")


def test_install_fails_when_the_lan_probe_fails():
    body = _install_body()
    after = body[body.index("scripts/lan-probe.sh"):]
    assert "blocked=1" in after and '[ "$blocked" -eq 0 ] || return 1' in after


def test_smoke_probes_the_lan_before_the_node_checks():
    text = (REPO / "scripts" / "smoke.sh").read_text(encoding="utf-8")
    assert "scripts/lan-probe.sh || FAIL=1" in text
    assert text.index("scripts/lan-probe.sh") < text.index("harness.nodes smoke")
