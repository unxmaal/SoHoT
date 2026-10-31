"""A probe that fails once is not this machine's identity for the rest of the process. #747."""
import subprocess
import types

import pytest

from evals import environment
from harness import machine
from tests import conftest
from harness import memory_store as ms

FP = "Mac17,15/macOS/arm64/aaaaaaaaaaaa"
ENV = {"hw_model": "Mac17,15", "os": "macOS-27.0.1-arm64-arm-64bit", "arch": "arm64",
       "host": "aaaaaaaaaaaa", "memory_gb": 96, "accelerator": {}, "versions": {}}


def _fails_once(value):
    calls = []

    def probe(*a, **k):
        calls.append(1)
        if len(calls) == 1:
            raise OSError("probe timed out")
        return value
    return probe


@pytest.fixture
def uuid_cache(monkeypatch):
    # origin/main kept the answer in an lru_cache, not _UUID; clear both so the red run is honest.
    getattr(machine._platform_uuid, "cache_clear", lambda: None)()
    monkeypatch.setattr(machine, "_UUID", None)
    monkeypatch.setattr(machine, "_UUID_FAILED_AT", None, raising=False)
    yield
    getattr(machine._platform_uuid, "cache_clear", lambda: None)()


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


@pytest.fixture
def clock(monkeypatch):
    c = Clock()
    monkeypatch.setattr(machine, "_now", c, raising=False)
    monkeypatch.setattr(ms.machines, "_now", c, raising=False)
    return c


def _ioreg(answers):
    """subprocess.run where ioreg gives each answer in turn (an exception is raised) and the rest print nothing."""
    calls = []

    def run(args, *a, **k):
        if args and args[0] == "ioreg":
            calls.append(1)
            got = answers[min(len(calls), len(answers)) - 1]
            if isinstance(got, BaseException):
                raise got
            return types.SimpleNamespace(stdout=f'"IOPlatformUUID" = "{got}"', returncode=0, stderr="")
        return types.SimpleNamespace(stdout="", returncode=1, stderr="")
    run.calls = calls
    return run


TIMEOUT = subprocess.TimeoutExpired(cmd="ioreg", timeout=10)


def test_a_probe_that_fails_once_is_not_this_machine_for_the_rest_of_the_process(monkeypatch, clock):
    monkeypatch.setattr(ms.machines, "_THIS_MACHINE", None)
    monkeypatch.setattr(environment, "capture", _fails_once(dict(ENV)))
    ms.this_machine()
    clock.t += 3600
    got = ms.this_machine()
    assert got["memory_gb"] == 96 and got["fingerprint"] == FP


def test_a_failed_probe_keeps_the_identity_it_could_read(monkeypatch):
    monkeypatch.setattr(ms.machines, "_THIS_MACHINE", None)
    monkeypatch.setattr(environment, "capture", lambda: (_ for _ in ()).throw(OSError("no sysctl")))
    monkeypatch.setattr(environment, "identity", lambda: {
        "hw_model": "Mac17,15", "host": "aaaaaaaaaaaa", "fingerprint": FP,
        "os": ENV["os"], "arch": "arm64"})
    got = ms.this_machine()
    assert got["fingerprint"] == FP and got["hw_model"] == "Mac17,15"


def test_an_ioreg_that_times_out_once_is_asked_again(monkeypatch, uuid_cache, clock):
    monkeypatch.setattr(machine.sys, "platform", "darwin")
    calls = []

    def run(*a, **k):
        calls.append(1)
        if len(calls) == 1:
            raise subprocess.TimeoutExpired(cmd="ioreg", timeout=10)
        return types.SimpleNamespace(stdout='"IOPlatformUUID" = "UUID-1"')
    monkeypatch.setattr(subprocess, "run", run)
    assert machine._platform_uuid() == ""
    clock.t += 3600
    assert machine._platform_uuid() == "UUID-1"
    assert machine._platform_uuid() == "UUID-1" and len(calls) == 2


def _hashed(raw):
    import hashlib
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def test_a_host_whose_ioreg_timed_out_first_is_not_cached_under_a_fallback_host(monkeypatch, uuid_cache, clock):
    monkeypatch.setattr(machine.sys, "platform", "darwin")
    monkeypatch.setattr(ms.machines, "_THIS_MACHINE", None)
    monkeypatch.setattr(subprocess, "run", _ioreg([TIMEOUT, "UUID-1"]))
    ms.this_machine()
    clock.t += 3600
    assert ms.this_machine()["host"] == machine.host_id() == _hashed("UUID-1")


def test_a_failed_uuid_probe_reads_back_the_host_this_machine_last_answered(monkeypatch, uuid_cache, clock, tmp_path):
    monkeypatch.setattr(machine.sys, "platform", "darwin")
    monkeypatch.setattr(subprocess, "run", _ioreg(["UUID-1"]))
    real = machine.host_id(home=tmp_path)
    monkeypatch.setattr(machine, "_UUID", None)
    monkeypatch.setattr(subprocess, "run", _ioreg([TIMEOUT]))
    assert machine.host_id(home=tmp_path) == real == _hashed("UUID-1")


def test_a_fallback_host_from_an_earlier_failure_gives_way_to_the_real_one(monkeypatch, uuid_cache, clock, tmp_path):
    monkeypatch.setattr(machine.sys, "platform", "darwin")
    (tmp_path / machine.HOST_FILE).write_text("deadbeef0000\n", encoding="utf-8")
    monkeypatch.setattr(subprocess, "run", _ioreg(["UUID-1"]))
    machine.host_id(home=tmp_path)
    monkeypatch.setattr(machine, "_UUID", None)
    monkeypatch.setattr(subprocess, "run", _ioreg([TIMEOUT]))
    assert machine.host_id(home=tmp_path) == _hashed("UUID-1")


def test_a_failed_uuid_probe_never_mints_a_host_id_for_later_processes(monkeypatch, uuid_cache, clock, tmp_path):
    monkeypatch.setattr(machine.sys, "platform", "darwin")
    monkeypatch.setattr(subprocess, "run", _ioreg([TIMEOUT]))
    assert machine.host_id(home=tmp_path) == ""
    assert not (tmp_path / machine.HOST_FILE).exists()


def test_a_probe_that_keeps_failing_is_asked_at_most_once_a_minute(monkeypatch, uuid_cache, clock):
    monkeypatch.setattr(machine.sys, "platform", "darwin")
    run = _ioreg([TIMEOUT])
    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(ms.machines, "_THIS_MACHINE", None)
    captures = []
    real = environment.capture
    monkeypatch.setattr(environment, "capture", lambda: captures.append(1) or real())
    for _ in range(5):
        ms.this_machine()
    assert len(run.calls) == 1 and len(captures) == 1
    clock.t += getattr(machine, "RETRY_S", 60) + 1
    ms.this_machine()
    assert len(run.calls) == 2 and len(captures) == 2


POISONED = '''
from harness import memory_store as ms


def test_a_leaks_an_identity():
    ms.machines._THIS_MACHINE = {"fingerprint": "poison", "hw_model": "", "os": "", "arch": "", "host": ""}


def test_b_starts_from_this_machine():
    assert ms.this_machine()["fingerprint"] != "poison"
'''


def test_an_identity_one_test_leaves_behind_is_not_the_next_tests(tmp_path):
    """The live-audit flake hypothesis: identity depended on earlier tests on the same worker."""
    import sys
    from pathlib import Path
    real = Path(__file__).with_name("conftest.py")
    (tmp_path / "conftest.py").write_text(
        f"exec(compile(open({str(real)!r}).read(), {str(real)!r}, 'exec'))\n", encoding="utf-8")
    (tmp_path / "test_order.py").write_text(POISONED, encoding="utf-8")
    got = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:xdist", "-p", "no:randomly",
                          "-p", "no:cacheprovider", "-o", "addopts=", str(tmp_path / "test_order.py")],
                         capture_output=True, text=True, cwd=Path(__file__).parents[1], timeout=conftest.HANG_DUMP_S)
    assert got.returncode == 0, got.stdout[-2000:]


def test_a_failed_capture_never_blanks_the_real_machines_row(monkeypatch, tmp_path, clock):
    conn = ms.connect(tmp_path / "s.db")
    monkeypatch.setattr(ms.machines, "_THIS_MACHINE", None)
    full = {**ENV, "accelerator": {"kind": "metal", "total_gb": 96},
            "versions": {"mlx": "0.30.0"}}
    monkeypatch.setattr(environment, "capture", lambda: dict(full))
    monkeypatch.setattr(machine, "uuid_failed", lambda: False)
    first = ms.remember_machine(conn)
    before = dict(conn.execute("SELECT * FROM machines WHERE id = ?", (first,)).fetchone())
    monkeypatch.setattr(ms.machines, "_THIS_MACHINE", None)
    monkeypatch.setattr(environment, "capture", lambda: (_ for _ in ()).throw(OSError("no sysctl")))
    monkeypatch.setattr(environment, "identity", lambda: {
        "hw_model": "Mac17,15", "host": "aaaaaaaaaaaa", "os": ENV["os"], "arch": "arm64"})
    assert ms.remember_machine(conn) == first
    after = dict(conn.execute("SELECT * FROM machines WHERE id = ?", (first,)).fetchone())
    keep = ("memory_gb", "ceiling_gb", "accelerator", "runtimes", "versions", "os")
    assert {k: after[k] for k in keep} == {k: before[k] for k in keep}
    assert before["memory_gb"] == 96 and before["versions"] != "{}"
