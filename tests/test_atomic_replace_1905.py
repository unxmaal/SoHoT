"""A replace onto a file another writer is replacing or a reader holds open lands on Windows, and every writer goes through it. #1905."""
import ast
import os
import sys
from pathlib import Path

import pytest

from harness import atomic_file
from harness import heartbeat as hb

REPO = Path(__file__).resolve().parents[1]
#: Runs as a bare `python -I harness/lane_probe.py` and writes its result under its own flock.
EXEMPT = {"harness/atomic_file.py", "harness/lane_probe.py"}


def _refusing(times: int, calls: list):
    real = os.replace

    def replace(src, dst):
        calls.append(dst)
        if len(calls) <= times:
            raise PermissionError(13, "Access is denied")
        return real(src, dst)
    return replace


@pytest.fixture
def windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(atomic_file, "sleep", lambda s: None)


def test_a_replace_windows_refuses_a_few_times_lands(tmp_path, monkeypatch, windows):
    calls = []
    monkeypatch.setattr(os, "replace", _refusing(3, calls))
    src, dst = tmp_path / "a.tmp", tmp_path / "a"
    src.write_text("new", encoding="utf-8")
    dst.write_text("old", encoding="utf-8")
    atomic_file.replace(src, dst)
    assert len(calls) == 4 and dst.read_text(encoding="utf-8") == "new" and not src.exists()


def test_a_heartbeat_write_lands_through_a_windows_refusal(monkeypatch, windows):
    calls = []
    monkeypatch.setattr(os, "replace", _refusing(2, calls))
    hb._write({"writer": 7})
    assert len(calls) == 3 and hb.read() == {"writer": 7}


@pytest.mark.gauntlet("a-wait-with-no-deadline-owner-or-end-state", site="harness/atomic_file.py:replace")
def test_a_refusal_that_outlasts_the_bound_raises(tmp_path, monkeypatch, windows):
    now = [0.0]
    monkeypatch.setattr(atomic_file, "clock", lambda: now[0])
    monkeypatch.setattr(atomic_file, "sleep", lambda s: now.__setitem__(0, now[0] + s))
    calls = []
    monkeypatch.setattr(os, "replace", _refusing(10 ** 6, calls))
    with pytest.raises(PermissionError):
        atomic_file.replace(tmp_path / "a.tmp", tmp_path / "a")
    assert now[0] >= atomic_file.REPLACE_TIMEOUT_S and len(calls) < 100


def test_off_windows_a_permission_error_is_not_retried(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    calls = []
    monkeypatch.setattr(os, "replace", _refusing(1, calls))
    with pytest.raises(PermissionError):
        atomic_file.replace(tmp_path / "a.tmp", tmp_path / "a")
    assert len(calls) == 1


def _bare_replaces(text: str, rel: str) -> list[str]:
    got = []
    for node in ast.walk(ast.parse(text)):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "replace"):
            continue
        on_os = isinstance(node.func.value, ast.Name) and node.func.value.id == "os"
        path_like = len(node.args) == 1 and not node.keywords and not isinstance(node.args[0], ast.Constant)
        if on_os or path_like:
            got.append(f"{rel}:{node.lineno}")
    return got


def test_bare_replaces_finds_os_and_path_replace_but_not_str_or_dataclass_replace():
    src = "os.replace(a, b)\np.replace(q)\ns.replace('a', 'b')\ndataclasses.replace(x, y=1)\nd.replace(tzinfo=z)\n"
    assert _bare_replaces(src, "f.py") == ["f.py:1", "f.py:2"]


def test_no_source_replaces_a_file_except_through_atomic_file():
    offenders = []
    for package in ("harness", "evals"):
        for path in sorted((REPO / package).rglob("*.py")):
            rel = path.relative_to(REPO).as_posix()
            if rel not in EXEMPT:
                offenders += _bare_replaces(path.read_text(encoding="utf-8"), rel)
    assert not offenders, "use atomic_file.replace, which Windows cannot refuse mid-write:\n  " + "\n  ".join(offenders)
