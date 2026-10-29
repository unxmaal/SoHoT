"""A test that runs too long prints every stack and then ends its process, from a thread no test can patch. #1351."""
import os
import subprocess
import sys
import threading
from pathlib import Path

from tests import conftest

ROOT = Path(__file__).resolve().parents[1]
CHILD_TIMEOUT_S = 60


def _check(now, running):
    out, left = [], []
    conftest._hang_check(running, now, out.append, left.append)
    return "".join(out), left


def test_nothing_happens_between_tests_or_before_the_dump_limit():
    assert _check(10_000.0, {}) == ("", [])
    running = {"test": {"nodeid": "t::slow", "began": 0.0, "dumped": False}}
    assert _check(conftest.HANG_DUMP_S - 1, running) == ("", [])


def test_past_the_dump_limit_every_thread_stack_is_printed_once():
    running = {"test": {"nodeid": "t::slow", "began": 0.0, "dumped": False}}
    text, left = _check(conftest.HANG_DUMP_S + 1, running)
    assert "t::slow has run" in text and "test_past_the_dump_limit_every_thread_stack_is_printed_once" in text
    assert f"Thread {threading.current_thread().name}" in text and left == []
    assert _check(conftest.HANG_DUMP_S + 2, running) == ("", [])


def test_past_the_exit_limit_the_process_leaves_naming_the_test():
    running = {"test": {"nodeid": "t::hung", "began": 0.0, "dumped": True}}
    text, left = _check(conftest.HANG_EXIT_S, running)
    assert "t::hung ran" in text and left == [70]


def test_the_dump_reaches_the_terminal_past_pytests_own_capture(tmp_path):
    (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    (tmp_path / "test_slow.py").write_text(
        "import time\nfrom tests import conftest\n\n\n"
        "def test_slow():\n    conftest.HANG_DUMP_S = 0.5\n    time.sleep(3)\n", encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k != "PYTEST_ADDOPTS"}
    env["PYTHONPATH"] = str(ROOT)
    got = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "tests.conftest", "-p", "no:xdist",
                          "-p", "no:randomly", "-p", "no:cacheprovider", "test_slow.py"],
                         cwd=tmp_path, env=env, capture_output=True, text=True, timeout=CHILD_TIMEOUT_S)
    assert got.returncode == 0, got.stdout + got.stderr
    assert "test_slow.py::test_slow has run" in got.stdout + got.stderr


def test_a_hung_test_is_dumped_and_ended_even_when_it_freezes_the_clock():
    code = (
        "import time\n"
        "from tests import conftest as c\n"
        "c.HANG_DUMP_S, c.HANG_EXIT_S = 0.5, 2.5\n"
        "c._hang_watch()\n"
        "c._running['test'] = {'nodeid': 'x::hangs', 'began': c._running['clock'](), 'dumped': False}\n"
        "time.monotonic = lambda: 0.0\n"
        "time.sleep(CHILD)\n".replace("CHILD", str(CHILD_TIMEOUT_S)))
    got = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True,
                         timeout=CHILD_TIMEOUT_S)
    assert got.returncode == 70, got.stderr
    assert "x::hangs has run" in got.stderr and "line 7, in <module>" in got.stderr and "x::hangs ran" in got.stderr
