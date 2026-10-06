"""Suite-wide isolation.

A test that writes to the developer's real LOCALHARNESS_HOME is invisible on
CI, where that directory does not exist, and visible only as junk accumulating
on the one machine nobody re-clones. Issue #188 found two such keys, `s` and
`blocked`, sitting in a real discovery-state.json for ten days.
"""
import pytest

from harness import paths


@pytest.fixture(autouse=True)
def _home(tmp_path_factory, monkeypatch):
    """Every test gets its own LOCALHARNESS_HOME.

    Autouse and unconditional: an opt-in guard protects the tests that
    remembered, which are never the ones that leak.
    """
    home = tmp_path_factory.mktemp("lh-home")
    monkeypatch.setenv(paths.ENV_VAR, str(home))
    return home


@pytest.fixture(autouse=True)
def _no_real_services(monkeypatch):
    """No test restarts a launchd service. One did on 2026-10-04: a fetch test
    called the real refresh_router, the temporary home gave it a different
    lock, and it restarted the eval server under a live measurement. #319."""
    from harness import gguf
    restarts = []
    monkeypatch.setattr(gguf, "refresh_router", lambda: restarts.append(True))
    return restarts


@pytest.fixture(autouse=True)
def _no_real_disk_sweep(monkeypatch):
    """No test deletes from the real weights cache. #373."""
    from harness import disk
    calls = []
    monkeypatch.setattr(disk, "sweep", lambda *a, **k: calls.append((a, k)) or {})
    return calls
