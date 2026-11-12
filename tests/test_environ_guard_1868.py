"""A test that leaves os.environ changed fails, and in-process queue jobs never leave a job id behind. #1868."""
import os
import subprocess
import sys
import threading
from pathlib import Path

from harness import paths, store
from harness import workqueue as wq
from tests import conftest, inproc

INNER = '''
import os


def test_leaks():
    os.environ["SOHOT_LEAK_1868"] = "x"


def test_after_a_leak_the_variable_is_gone():
    assert "SOHOT_LEAK_1868" not in os.environ


def test_drops():
    del os.environ["SOHOT_KEEP_1868"]


def test_after_a_drop_the_variable_is_back():
    assert os.environ["SOHOT_KEEP_1868"] == "k"


def test_monkeypatched(monkeypatch):
    monkeypatch.setenv("SOHOT_LEAK_1868", "y")
    monkeypatch.delenv("SOHOT_KEEP_1868")
'''


def test_a_test_that_changes_os_environ_errors_at_teardown_and_the_next_test_starts_clean(tmp_path):
    real = Path(conftest.__file__)
    (tmp_path / "conftest.py").write_text(
        f"exec(compile(open({str(real)!r}).read(), {str(real)!r}, 'exec'))\n", encoding="utf-8")
    (tmp_path / "test_inner.py").write_text(INNER, encoding="utf-8")
    clean = {k: v for k, v in os.environ.items()
             if k not in (store.BACKEND_ENV, paths.ENV_VAR, "PYTEST_ADDOPTS") and not k.startswith("PG")}
    got = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:xdist", "-p", "no:randomly",
                          "-p", "no:cacheprovider", "-o", "addopts=", str(tmp_path / "test_inner.py")],
                         capture_output=True, text=True, cwd=paths.REPO,
                         env={**clean, "SOHOT_KEEP_1868": "k"}, timeout=conftest.HANG_DUMP_S)
    assert "5 passed, 2 errors" in got.stdout, got.stdout[-3000:]
    assert "ERROR at teardown of test_leaks" in got.stdout and "SOHOT_LEAK_1868: None -> 'x'" in got.stdout
    assert "ERROR at teardown of test_drops" in got.stdout and "SOHOT_KEEP_1868: 'k' -> None" in got.stdout
    assert "ERROR at teardown of test_monkeypatched" not in got.stdout


def test_env_left_names_each_changed_key_and_ignores_pytests_own():
    before = {"A": "1", "B": "2", "PYTEST_CURRENT_TEST": "x (setup)"}
    assert conftest.env_left(before, dict(before)) == []
    assert conftest.env_left(before, {"A": "1", "B": "3", "C": "4"}) == ["B: '2' -> '3'", "C: None -> '4'"]
    assert conftest.env_left(before, {"B": "2"}) == ["A: '1' -> None"]


def test_two_in_process_jobs_at_once_each_see_their_own_id_and_leave_none(monkeypatch):
    monkeypatch.delenv(wq.JOB_ENV, raising=False)
    began = {"7": threading.Event(), "8": threading.Event()}
    done7, seen = threading.Event(), {}

    def main(words):
        me = words[-1]
        began[me].set()
        if me == "7":
            began["8"].wait(0.5)
        else:
            done7.wait(0.5)
        seen[me] = os.environ.get(wq.JOB_ENV)
        return 0

    monkeypatch.setattr(inproc.cli, "main", main)

    def job(i, after=None):
        inproc.popen(["python", "-m", "harness.cli", i], env={wq.JOB_ENV: i})
        if after:
            after.set()

    a = threading.Thread(target=job, args=("7", done7))
    a.start()
    began["7"].wait(5)
    b = threading.Thread(target=job, args=("8",))
    b.start()
    a.join(5)
    b.join(5)
    assert seen == {"7": "7", "8": "8"}
    assert wq.JOB_ENV not in os.environ
