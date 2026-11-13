"""A temp file whose writer died before its rename is removed by that writer's next write; a live writer's is kept. #1900."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from evals import repo
from harness import exclusive, heartbeat, identity, proc_identity, serve_lease, stale_temp, sweep_guard, unverified
from harness import deploy_switch

OLD = stale_temp.FLOOR_S + 5


def _dead_pid() -> int:
    for _ in range(5):
        p = subprocess.Popen([sys.executable, "-c", ""])
        p.wait()
        if proc_identity.same({"pid": p.pid}) is False:
            return p.pid
    pytest.skip("this platform cannot say a pid is gone")


@pytest.fixture
def live():
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    yield p.pid
    p.kill()
    p.wait()


def _plant(target: Path, form: str, pid: int, kind: str = "file", age: float = OLD) -> Path:
    p = target.with_name(form.format(name=target.name, pid=pid, thread=4242, hex="abcdef12"))
    if kind == "dir":
        p.mkdir(parents=True)
        (p / "half").write_text("x", encoding="utf-8")
    elif kind == "link":
        os.symlink(target.parent / "nowhere", p)
    else:
        p.write_text("half", encoding="utf-8")
    then = time.time() - age
    os.utime(p, (then, then), follow_symlinks=False)
    return p


def _there(p: Path) -> bool:
    return p.is_symlink() or p.exists()


def _git_source(root: Path) -> str:
    root.mkdir()
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@t"}
    for argv in (["init", "-q"], ["commit", "-q", "--allow-empty", "-m", "base"]):
        subprocess.run(["git", "-C", str(root), *argv], check=True, env=env, capture_output=True)
    return str(root)


def _prepare(tmp_path, monkeypatch):
    task = tmp_path / "task"
    task.mkdir()
    (task / "uv.lock").write_text("lock\n", encoding="utf-8")

    def fake(argv, **kw):
        Path(kw["env"]["UV_PROJECT_ENVIRONMENT"]).mkdir(parents=True)
        return SimpleNamespace(returncode=0, stderr="")
    monkeypatch.setattr(repo.subprocess, "run", fake)
    monkeypatch.setattr(repo, "interpreter", lambda task, uv, env: "/host/python")
    venv = repo.cache_root() / "envs" / repo.env_digest(task)
    venv.parent.mkdir(parents=True)
    return venv, lambda: repo.prepare(task), lambda: (venv / ".built").is_file()


def _beat(tmp_path, monkeypatch):
    monkeypatch.setenv(exclusive.HELD_ENV, "1")
    path = exclusive.holder_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"pid": 1, "kind": "eval"}), encoding="utf-8")
    return path, lambda: exclusive.beat(now=7.0), lambda: json.loads(path.read_text(encoding="utf-8"))["beat"] == 7.0


def _settle(tmp_path, monkeypatch):
    path = tmp_path / sweep_guard.HEARTBEAT
    path.write_text(json.dumps({"state": "running", "pid": 99999}), encoding="utf-8")
    return path, lambda: sweep_guard.settle_heartbeat(tmp_path, [{"pid": 99999}], alive=lambda pid: False), \
        lambda: json.loads(path.read_text(encoding="utf-8"))["state"] == "finished"


def _flip(tmp_path, monkeypatch):
    (tmp_path / "r2").mkdir()
    link = tmp_path / "current"
    return link, lambda: deploy_switch.flip(link, tmp_path / "r2"), lambda: os.readlink(link) == str(tmp_path / "r2")


def _mirror(tmp_path, monkeypatch):
    source = _git_source(tmp_path / "src")
    path = repo.mirror_path(source)
    path.parent.mkdir(parents=True)
    return path, lambda: repo.mirror(source), lambda: (path / "HEAD").is_file()


def _validation(tmp_path, monkeypatch):
    path = repo.validation_path("c1")
    path.parent.mkdir(parents=True)
    return path, lambda: repo.save_validation(SimpleNamespace(id="c1", prompt="p", params={}, assertions={}, modality="text"), {"verdict": "valid"}, "m", "c", 1.0), \
        lambda: json.loads(path.read_text(encoding="utf-8"))["m"]["verdict"] == "valid"


def _simple(target_of, write, check):
    def make(tmp_path, monkeypatch):
        target = target_of(tmp_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        return target, lambda: write(target), lambda: check(target)
    return make


def _json(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


WRITERS = {
    "unverified": ("{name}.{pid}", "file", _simple(lambda t: unverified._state_path(),
                                                   lambda t: unverified._remember("s", "t"),
                                                   lambda t: _json(t) == {"s": "t"})),
    "exclusive.mark": ("{name}.{pid}.{thread}", "file", _simple(lambda t: t / "refused",
                                                                lambda t: exclusive._mark(t, {"a": 1}, False),
                                                                lambda t: _json(t) == {"a": 1})),
    "exclusive.beat": ("{name}.{pid}.{thread}.tmp", "file", _beat),
    "deploy_switch.flip": (".{name}.{pid}", "link", _flip),
    "serve_lease": (".{name}.{pid}.{hex}", "file", _simple(lambda t: t / "lease.json",
                                                           lambda t: serve_lease._write(t, {"a": 1}),
                                                           lambda t: _json(t) == {"a": 1})),
    "heartbeat": ("{name}.{pid}.{thread}.tmp", "file", _simple(lambda t: heartbeat.path(),
                                                               lambda t: heartbeat._write({"a": 1}),
                                                               lambda t: _json(t) == {"a": 1})),
    "sweep_guard": ("{name}.{pid}.tmp", "file", _settle),
    "identity": ("{name}.{pid}.tmp", "file", _simple(lambda t: t / "cache" / "id.json",
                                                     lambda t: identity._save_cache(t, {"a": 1}),
                                                     lambda t: _json(t) == {"a": 1})),
    "repo.mirror": ("{name}.{pid}.{hex}", "dir", _mirror),
    "repo.prepare": ("{name}.{pid}-{hex}", "dir", _prepare),
    "repo.validation": ("{name}.{pid}", "file", _validation),
}


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks and pid proof are posix here")
@pytest.mark.parametrize("writer", sorted(WRITERS))
def test_the_next_write_removes_a_dead_writers_temp_and_keeps_a_live_ones(writer, tmp_path, monkeypatch, live):
    form, kind, setup = WRITERS[writer]
    target, write, landed = setup(tmp_path, monkeypatch)
    dead = _plant(target, form, _dead_pid(), kind)
    alive = _plant(target, form, live, kind)
    write()
    assert not _there(dead), f"{writer} left {dead.name}"
    assert _there(alive), f"{writer} removed a live writer's {alive.name}"
    assert landed()


def test_a_dead_writers_temp_younger_than_the_floor_is_kept(tmp_path):
    target = tmp_path / "t.json"
    young = _plant(target, "{name}.{pid}.tmp", _dead_pid(), age=1)
    old = _plant(target, "{name}.{pid}", _dead_pid())
    assert stale_temp.sweep(target, "{name}.{pid}.tmp") == []
    assert _there(young) and _there(old)


def test_a_pid_that_cannot_be_judged_keeps_its_temp(tmp_path, monkeypatch):
    target = tmp_path / "t.json"
    planted = _plant(target, "{name}.{pid}.tmp", _dead_pid())
    monkeypatch.setattr(stale_temp.proc_identity, "same", lambda rec: None)
    stale_temp.sweep(target, "{name}.{pid}.tmp")
    assert _there(planted)


def test_an_older_releases_temp_without_a_pid_is_kept(tmp_path):
    target = tmp_path / "lease.json"
    legacy = target.with_name(f".{target.name}.1a2b3c")
    legacy.write_text("half", encoding="utf-8")
    os.utime(legacy, (time.time() - OLD,) * 2)
    serve_lease._write(target, {"a": 1})
    assert _there(legacy)


def test_the_sweep_works_loaded_as_a_file_under_python_I_S(tmp_path):
    """sweep_guard runs as a file under python3 -I, where no harness package is importable. #1910."""
    target = tmp_path / "t.json"
    dead = _plant(target, "{name}.{pid}.tmp", _dead_pid())
    code = ("import importlib.util, sys; s = importlib.util.spec_from_file_location('stale_temp', sys.argv[1]); "
            "m = importlib.util.module_from_spec(s); s.loader.exec_module(m); "
            "print(len(m.sweep(sys.argv[2], '{name}.{pid}.tmp')))")
    got = subprocess.run([sys.executable, "-I", "-S", "-c", code, stale_temp.__file__, str(target)],
                         capture_output=True, text=True)
    assert got.returncode == 0, got.stderr
    assert got.stdout.strip() == "1" and not _there(dead)


@pytest.mark.gauntlet("a-closed-table-fronting-an-open-set", site="harness/stale_temp.py:_FIELDS")
@pytest.mark.parametrize("form", ["{name}.{pid}.{tid}.tmp", "{name}.{hex}", "{name}.{}"])
def test_a_form_with_an_unknown_field_or_no_pid_is_refused(form, tmp_path):
    with pytest.raises(ValueError, match="temp form"):
        stale_temp.temp(tmp_path / "t.json", form)


def test_a_digit_run_too_long_for_a_pid_is_kept_and_does_not_raise(tmp_path):
    target = tmp_path / "t.json"
    planted = _plant(target, "{name}.{pid}.tmp", 99999999999)
    assert stale_temp.sweep(target, "{name}.{pid}.tmp") == []
    assert _there(planted)
