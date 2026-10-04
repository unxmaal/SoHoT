"""One lock for every model-loading run, shared with other projects. #314."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

from harness import exclusive

REPO = Path(__file__).resolve().parents[1]
HELPER = REPO / "scripts" / "with-gpu-lock"


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALHARNESS_HOME", str(tmp_path))
    monkeypatch.delenv(exclusive.HELD_ENV, raising=False)
    return tmp_path


def _free() -> bool:
    """Can someone else take the lock right now?"""
    fd = os.open(exclusive.lock_path(), os.O_RDWR | os.O_CREAT, 0o644)
    try:
        got = exclusive._take(fd)
        if got:
            exclusive._release(fd)
        return got
    finally:
        os.close(fd)


@pytest.mark.parametrize("kind", ["eval", "ramp", "external"])
def test_batch_model_runs_hold_the_machine(kind):
    with exclusive.held(kind):
        assert not _free()
    assert _free()


def test_a_nested_holder_does_not_deadlock_against_its_parent():
    with exclusive.held("external"):
        with exclusive.held("eval") as waited:
            assert waited is False


def test_children_know_the_lock_is_held():
    with exclusive.held("eval"):
        out = subprocess.run([sys.executable, "-c",
                              f"import os; print(os.environ.get('{exclusive.HELD_ENV}'))"],
                             capture_output=True, text=True).stdout.strip()
    assert out == "1"
    assert exclusive.HELD_ENV not in os.environ


@pytest.mark.skipif(sys.platform == "win32", reason="a POSIX script")
def test_the_helper_holds_the_lock_for_the_command_and_passes_its_exit():
    probe = (f"import sys; sys.path.insert(0, {str(REPO)!r}); "
             "import os; from harness import exclusive as e; "
             "fd = os.open(e.lock_path(), os.O_RDWR | os.O_CREAT); "
             "sys.exit(3 if e._take(fd) else 7)")
    # The probe clears the marker so it asks the OS, not the environment.
    got = subprocess.run([str(HELPER), "env", "-u", exclusive.HELD_ENV,
                          sys.executable, "-c", probe])
    assert got.returncode == 7, "the lock was free while the helper ran"
    assert _free()


def test_evals_run_holds_the_lock_while_it_runs(monkeypatch):
    from evals import run
    seen = {}
    monkeypatch.setattr(run.env, "guard", lambda: None)
    monkeypatch.setattr(run, "_execute",
                        lambda args: seen.setdefault("free", _free()) and 0)
    run.main(["--modality", "code", "--candidates", "q3-4b"])
    assert seen["free"] is False


def test_the_ramp_holds_the_lock(monkeypatch):
    from harness import cli, ramp
    seen = {}

    def fake(**kw):
        seen["free"] = _free()
        return {"steps": [], "stopped": "cap"}
    monkeypatch.setattr(ramp, "run", fake)
    cli.main(["memory", "ramp"])
    assert seen["free"] is False


def test_launchd_install_restarts_services_under_the_lock():
    text = (REPO / "scripts" / "launchd.sh").read_text(encoding="utf-8")
    assert "with-gpu-lock" in text
    assert exclusive.HELD_ENV in text
