"""Resolving a lane's model looks this machine's row up by its cheap fingerprint, never by the runtime-version probe. #1427."""
import subprocess
import sys

from evals import environment
from harness import delegate, machine, paths, runs
from harness import memory_store as ms


def _fresh_process(monkeypatch):
    """This worker's identity forgotten, as a new process starts; returns the version and identity probe counts."""
    monkeypatch.setattr(ms.machines, "_THIS_MACHINE", None)
    monkeypatch.setattr(ms.machines, "_THIS_FINGERPRINT", None)
    monkeypatch.setattr(ms.machines, "_PROVISIONAL", None)
    versions, identities = [], []
    real_identity = environment.identity
    monkeypatch.setattr(machine, "versions", lambda: versions.append(1) or {})
    monkeypatch.setattr(environment, "identity", lambda: identities.append(1) or real_identity())
    return versions, identities


def test_resolving_a_lane_model_makes_no_runtime_version_probe(monkeypatch):
    with ms.connect() as c:
        mid = ms.remember_machine(c)
    versions, _ = _fresh_process(monkeypatch)
    delegate.route("decide")
    with ms.connect() as c:
        assert runs.here(c) == [mid]
    assert versions == []


def test_the_identity_probe_runs_at_most_once_per_process(monkeypatch):
    versions, identities = _fresh_process(monkeypatch)
    first = ms.this_fingerprint()
    assert ms.this_fingerprint() == first
    with ms.connect() as c:
        ms.machine_row(c)
    assert identities == [1] and versions == []


def test_the_cheap_fingerprint_is_the_one_the_full_probe_records(monkeypatch):
    versions, _ = _fresh_process(monkeypatch)
    cheap = ms.this_fingerprint()
    assert ms.this_machine()["fingerprint"] == cheap
    assert versions == [1]


def test_once_the_full_facts_are_known_no_identity_probe_runs(monkeypatch):
    _, identities = _fresh_process(monkeypatch)
    full = ms.this_machine()["fingerprint"]
    identities.clear()
    assert ms.this_fingerprint() == full and identities == []


def test_a_failed_uuid_probe_is_not_cached_as_this_machine(monkeypatch):
    _, identities = _fresh_process(monkeypatch)
    monkeypatch.setattr(machine, "uuid_failed", lambda: True)
    ms.this_fingerprint()
    assert ms.machines._THIS_FINGERPRINT is None


def test_a_stand_in_capture_names_the_row_on_any_real_board(monkeypatch):
    real = environment.identity
    monkeypatch.setattr(environment, "identity", lambda: {
        **real(), "hw_model": "Other,1", "fingerprint": "Other,1/macOS/arm64/cccccccccccc"})
    fake = {"hw_model": "Mac17,15", "os": "macOS-27", "arch": "arm64", "host": "aaaaaaaaaaaa",
            "memory_gb": 96, "accelerator": {}, "versions": {}}
    monkeypatch.setattr(environment, "capture", lambda: dict(fake))
    monkeypatch.setattr(ms.machines, "_THIS_MACHINE", None)
    monkeypatch.setattr(ms.machines, "_THIS_FINGERPRINT", None)
    with ms.connect() as c:
        mid = ms.remember_machine(c)
        monkeypatch.setattr(ms.machines, "_THIS_MACHINE", None)
        assert ms.machine_row(c) == mid


def test_importing_ds4_reads_no_case_file():
    code = ("import pathlib, sys\n"
            "read = []\n"
            "real = pathlib.Path.read_text\n"
            "pathlib.Path.read_text = lambda self, *a, **k: read.append(self) or real(self, *a, **k)\n"
            "from harness import ds4\n"
            "assert not [p for p in read if ds4.CASES in p.parents], read[:3]\n"
            "assert ds4.Spec('x').ctx == ds4.DEFAULT_CTX == ds4.default_ctx() > ds4.PROMPT_ROOM\n")
    got = subprocess.run([sys.executable, "-c", code], cwd=paths.REPO, capture_output=True,
                         text=True, timeout=120)
    assert got.returncode == 0, got.stderr[-2000:]
