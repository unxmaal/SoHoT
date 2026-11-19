from __future__ import annotations

import os
import plistlib
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from harness import monitor

PROBE_C = '#include <signal.h>\n#include <stdio.h>\n#include <errno.h>\n#include <string.h>\n' \
          'int main(void){int r=kill(-1,0);printf("rc=%d errno=%d\\n",r,r?errno:0);return 0;}\n'
darwin = pytest.mark.skipif(sys.platform != "darwin" or not shutil.which("cc") or not shutil.which("monit"),
                            reason="the guard is a macOS dylib built with cc and loaded into monit")


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True,
                          text=True).stdout.strip()[:1] not in ("", "Z")


def _refuses_broadcast(lib: Path, d: Path) -> subprocess.CompletedProcess:
    (d / "probe.c").write_text(PROBE_C, encoding="utf-8")
    subprocess.run(["cc", "-o", str(d / "probe"), str(d / "probe.c")], check=True, capture_output=True, timeout=120)
    return subprocess.run(monitor.guarded([str(d / "probe")], lib), capture_output=True, text=True, timeout=30)


def test_the_unit_loads_the_guard_into_monit(tmp_path):
    unit = plistlib.loads(monitor.plist("/x/monit", tmp_path))
    lib = monitor.guard_path(tmp_path)
    assert unit["ProgramArguments"] == ["/usr/bin/env", f"DYLD_INSERT_LIBRARIES={lib}", "/x/monit", "-I", "-c",
                                        str(monitor.rc_path(tmp_path))]


def test_install_loads_no_monit_when_the_guard_cannot_be_proven(monkeypatch, tmp_path):
    monkeypatch.setattr(monitor, "live_home", lambda home=None: True)
    monkeypatch.setattr(monitor, "plist_path", lambda: tmp_path / "monit.plist")
    monkeypatch.setattr(monitor, "spec_here", lambda run=None: {"models": "", "data": "/", "services": []})
    monkeypatch.setattr(monitor, "render", lambda s: "check program p with path /usr/bin/true\n")
    monkeypatch.setattr(monitor, "syntax", lambda monit, rc, run=None: "")
    monkeypatch.setattr(monitor, "rc_path", lambda home=None: tmp_path / "monit" / "monitrc")
    calls = []

    def run(argv, **kw):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, "", "")
    with pytest.raises(monitor.InstallError, match="dyld did not load"):
        monitor.install(run=run, which=lambda n: "/x/monit", platform="darwin", sleep=lambda s: None)
    assert not (tmp_path / "monit.plist").exists()
    assert not [c for c in calls if c[0] == "launchctl"]


@darwin
def test_the_guard_refuses_a_broadcast_signal(tmp_path):
    lib = monitor.guard(shutil.which("monit"), tmp_path)
    got = _refuses_broadcast(lib, tmp_path)
    assert got.stdout.strip() == "rc=-1 errno=1", got.stdout + got.stderr
    assert "monit-guard: refused kill(-1, 0)" in got.stderr


@darwin
def test_monit_that_cannot_fork_leaves_every_process_outside_its_tree_alone(tmp_path):
    monit = shutil.which("monit")
    d = Path(monitor.__file__).resolve().parents[1] / "tmp"
    d.mkdir(exist_ok=True)
    d = Path(__import__("tempfile").mkdtemp(prefix="m2072", dir=d))
    lib = monitor.guard(monit, d)
    got = _refuses_broadcast(lib, d)
    if got.stdout.strip() != "rc=-1 errno=1":
        pytest.fail(f"the guard does not refuse kill(-1), so monit is not started: {got.stdout}{got.stderr}")
    sentinel = subprocess.Popen(["/bin/sleep", "120"], start_new_session=True)
    rc = d / "rc"
    rc.write_text(f"set daemon 1 with start delay 4\nset log {d}/monit.log\nset pidfile {d}/monit.pid\n"
                  f"set idfile {d}/monit.id\nset statefile {d}/monit.state\n"
                  'check program p with path "/bin/sleep 0" with timeout 2 seconds\n'
                  '    if status != 0 then exec "/usr/bin/true"\n', encoding="utf-8")
    rc.chmod(0o600)
    probe, err = d / "probe.pid", d / "stderr"

    def no_forks():
        import resource
        resource.setrlimit(resource.RLIMIT_NPROC, (1, resource.getrlimit(resource.RLIMIT_NPROC)[1]))
    with err.open("w") as fh:
        daemon = subprocess.Popen(monitor.guarded([monit, "-I", "-c", str(rc)], lib, MONIT_GUARD_PROBE=str(probe)),
                                  stdout=fh, stderr=fh, start_new_session=True, preexec_fn=no_forks)
    try:
        assert os.getpgid(sentinel.pid) == sentinel.pid != os.getpgid(0)
        deadline = time.monotonic() + 3
        while not probe.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        if not probe.exists() or probe.read_text(encoding="utf-8").strip() != str(daemon.pid):
            os.killpg(daemon.pid, signal.SIGKILL)
            pytest.fail("the guard was not loaded into the scratch monit before its first cycle")
        log = d / "monit.log"
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline and "refused kill(-1, 9)" not in err.read_text(encoding="utf-8"):
            time.sleep(0.2)
        said = (log.read_text(encoding="utf-8") if log.exists() else "")[-400:]
        assert "refused kill(-1, 9)" in err.read_text(encoding="utf-8"), said
        assert "failed to execute" in said
        assert _alive(sentinel.pid) and daemon.poll() is None
    finally:
        if daemon.poll() is None:
            os.killpg(daemon.pid, signal.SIGKILL)
        daemon.wait(10)
        os.killpg(sentinel.pid, signal.SIGKILL)
        sentinel.wait(10)
        shutil.rmtree(d, ignore_errors=True)
