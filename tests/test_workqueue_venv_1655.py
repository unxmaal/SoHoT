"""A queued job runs with the venv of the release its cwd is in, not the worker's. #1655."""
import json
import os
import sys

import pytest

from harness import exclusive, workqueue as wq


@pytest.fixture(autouse=True)
def _no_marker(monkeypatch):
    monkeypatch.delenv(exclusive.HELD_ENV, raising=False)


def _release(tmp_path, name, venv=True):
    rel = tmp_path / "releases" / name
    rel.mkdir(parents=True)
    (rel / "pyproject.toml").write_text("[project]\nname = 'x'\n", encoding="utf-8")
    if venv:
        wq._bin(rel / ".venv").mkdir(parents=True)
    return rel


def _dump(out):
    code = (f"import json, os; json.dump({{'venv': os.environ.get('VIRTUAL_ENV'), "
            f"'path': os.environ.get('PATH', '')}}, open({str(out)!r}, 'w'))")
    return [sys.executable, "-c", code]


def _worker_in(monkeypatch, rel):
    monkeypatch.setenv("VIRTUAL_ENV", str(rel / ".venv"))
    monkeypatch.setenv("PATH", os.pathsep.join([str(wq._bin(rel / ".venv")), os.path.dirname(sys.executable)]))


def test_a_step_queued_before_a_deploy_runs_with_its_own_releases_venv(tmp_path, monkeypatch):
    old, new = _release(tmp_path, "19-aaaa"), _release(tmp_path, "20-bbbb")
    out = tmp_path / "env.json"
    _worker_in(monkeypatch, old)
    wq.add(_dump(out), title="measure", cwd=str(old))
    _worker_in(monkeypatch, new)
    [got] = wq.run_pending()
    assert got["state"] == wq.DONE
    seen = json.loads(out.read_text(encoding="utf-8"))
    assert seen["venv"] == str((old / ".venv").resolve())
    parts = seen["path"].split(os.pathsep)
    assert parts[0] == str(wq._bin((old / ".venv").resolve()))
    assert str(wq._bin(new / ".venv")) not in parts


def test_a_job_in_a_subdirectory_finds_its_checkouts_venv(tmp_path):
    rel, other = _release(tmp_path, "19-aaaa"), _release(tmp_path, "20-bbbb")
    (rel / "evals").mkdir()
    env = wq.job_venv(rel / "evals", {"VIRTUAL_ENV": str(other / ".venv"), "PATH": str(wq._bin(other / ".venv"))})
    assert env["VIRTUAL_ENV"] == str((rel / ".venv").resolve())
    assert env["PATH"] == str(wq._bin((rel / ".venv").resolve()))


def test_a_checkout_with_no_venv_gets_none_and_loses_the_workers_bin(tmp_path):
    rel, other = _release(tmp_path, "19-aaaa", venv=False), _release(tmp_path, "20-bbbb")
    env = wq.job_venv(rel, {"VIRTUAL_ENV": str(other / ".venv"),
                            "PATH": os.pathsep.join([str(wq._bin(other / ".venv")), "/usr/bin"])})
    assert "VIRTUAL_ENV" not in env
    assert env["PATH"] == "/usr/bin"


def test_the_venv_is_the_checkouts_never_a_parent_directorys(tmp_path):
    rel, other = _release(tmp_path, "19-aaaa", venv=False), _release(tmp_path, "20-bbbb")
    (tmp_path / "releases" / ".venv").mkdir()
    env = wq.job_venv(rel, {"VIRTUAL_ENV": str(other / ".venv")})
    assert "VIRTUAL_ENV" not in env


def test_a_worker_with_no_venv_adds_none(tmp_path):
    rel = _release(tmp_path, "19-aaaa")
    assert wq.job_venv(rel, {"PATH": "/usr/bin", "X": "1"}) == {"PATH": "/usr/bin", "X": "1"}


def test_the_venv_bin_directory_is_read_at_call_time(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    assert wq._bin(tmp_path).name == "Scripts"
    monkeypatch.setattr(sys, "platform", "darwin")
    assert wq._bin(tmp_path).name == "bin"
