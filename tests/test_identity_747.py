"""A probe that fails once is not this machine's identity for the rest of the process. #747."""
import subprocess
import types

import pytest

from evals import environment
from harness import machine
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
def uuid_cache():
    machine._UUID = None
    yield
    machine._UUID = None


def test_a_probe_that_fails_once_is_not_this_machine_for_the_rest_of_the_process(monkeypatch):
    monkeypatch.setattr(ms.machines, "_THIS_MACHINE", None)
    monkeypatch.setattr(environment, "capture", _fails_once(dict(ENV)))
    ms.this_machine()
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


def test_an_ioreg_that_times_out_once_is_asked_again(monkeypatch, uuid_cache):
    monkeypatch.setattr(machine.sys, "platform", "darwin")
    calls = []

    def run(*a, **k):
        calls.append(1)
        if len(calls) == 1:
            raise subprocess.TimeoutExpired(cmd="ioreg", timeout=10)
        return types.SimpleNamespace(stdout='"IOPlatformUUID" = "UUID-1"')
    monkeypatch.setattr(subprocess, "run", run)
    assert machine._platform_uuid() == ""
    assert machine._platform_uuid() == "UUID-1"
    assert machine._platform_uuid() == "UUID-1" and len(calls) == 2
