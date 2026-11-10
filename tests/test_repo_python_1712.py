"""#1712: a repo env is built with an interpreter this host can run, never uv's newest across architectures."""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from evals import repo

LOCK = 'version = 1\nrevision = 3\nrequires-python = ">=3.10"\n\n[[package]]\nname = "toy"\nversion = "0"\nsource = { virtual = "." }\n'
PROJECT = '[project]\nname = "toy"\nversion = "0"\nrequires-python = ">=3.10"\ndependencies = []\n'
MANAGED = "/data/uv/python"


def _entry(version, os_, arch, path, libc="none"):
    major, minor, patch = (int(p) for p in version.split("."))
    return {"key": f"cpython-{version}-{os_}-{arch}-{libc}", "version": version, "path": path, "os": os_,
            "arch": arch, "libc": libc, "implementation": "cpython", "variant": "default",
            "version_parts": {"major": major, "minor": minor, "patch": patch}}


def _task(tmp_path, pin="3.14"):
    task = tmp_path / "task"
    task.mkdir()
    (task / "uv.lock").write_text(LOCK, encoding="utf-8")
    (task / "pyproject.toml").write_text(PROJECT, encoding="utf-8")
    if pin is not None:
        (task / ".python-version").write_text(f"{pin}\n", encoding="utf-8")
    return task


class _Uv:
    """subprocess.run standing in for uv: lists `installed`, names MANAGED, records every argv."""

    def __init__(self, installed):
        self.installed, self.calls = installed, []

    def __call__(self, argv, **kw):
        argv = [str(a) for a in argv]
        self.calls.append(argv)
        if argv[1:3] == ["python", "list"]:
            return subprocess.CompletedProcess(argv, 0, json.dumps(self.installed), "")
        if argv[1:3] == ["python", "dir"]:
            return subprocess.CompletedProcess(argv, 0, MANAGED + "\n", "")
        Path(kw["env"]["UV_PROJECT_ENVIRONMENT"]).mkdir(parents=True)
        return subprocess.CompletedProcess(argv, 0, "", "")

    def synced_with(self):
        sync = next(c for c in self.calls if c[1] == "sync")
        return sync[sync.index("--python") + 1]


def _host(monkeypatch, plat, machine, libc=("glibc", "2.39")):
    monkeypatch.setattr(sys, "platform", plat)
    monkeypatch.setattr(platform, "machine", lambda: machine)
    monkeypatch.setattr(platform, "libc_ver", lambda *a, **k: libc)


def _build(tmp_path, monkeypatch, installed, pin="3.14"):
    uv = _Uv(installed)
    monkeypatch.setattr(repo, "cache_root", lambda: tmp_path / "cache")
    monkeypatch.setattr(repo.subprocess, "run", uv)
    monkeypatch.setattr(repo.shutil, "which", lambda name: name)
    repo.prepare(_task(tmp_path, pin))
    return uv


def test_an_arm64_mac_never_builds_with_the_newer_x86_64_install(tmp_path, monkeypatch):
    _host(monkeypatch, "darwin", "arm64")
    uv = _build(tmp_path, monkeypatch, [
        _entry("3.14.10", "macos", "x86_64", f"{MANAGED}/cpython-3.14-macos-x86_64-none/bin/python3.14"),
        _entry("3.14.8", "macos", "aarch64", f"{MANAGED}/cpython-3.14-macos-aarch64-none/bin/python3.14")])
    assert uv.synced_with() == f"{MANAGED}/cpython-3.14-macos-aarch64-none/bin/python3.14"
    assert uv.calls[0][1:4] == ["python", "list", "3.14"]


def test_linux_takes_its_own_arch_and_libc(tmp_path, monkeypatch):
    _host(monkeypatch, "linux", "x86_64")
    uv = _build(tmp_path, monkeypatch, [
        _entry("3.14.10", "linux", "aarch64", f"{MANAGED}/a/bin/python3.14", "gnu"),
        _entry("3.14.9", "linux", "x86_64", f"{MANAGED}/m/bin/python3.14", "musl"),
        _entry("3.14.8", "linux", "x86_64", f"{MANAGED}/g/bin/python3.14", "gnu")])
    assert uv.synced_with() == f"{MANAGED}/g/bin/python3.14"


def test_windows_amd64_takes_the_x86_64_build(tmp_path, monkeypatch):
    _host(monkeypatch, "win32", "AMD64")
    uv = _build(tmp_path, monkeypatch, [
        _entry("3.14.10", "windows", "aarch64", "/c/uv/arm/python.exe"),
        _entry("3.14.8", "windows", "x86_64", "/c/uv/x64/python.exe")])
    assert uv.synced_with() == "/c/uv/x64/python.exe"


def test_a_managed_install_comes_before_a_newer_system_one(tmp_path, monkeypatch):
    _host(monkeypatch, "darwin", "arm64")
    uv = _build(tmp_path, monkeypatch, [
        _entry("3.14.10", "macos", "aarch64", "/opt/homebrew/bin/python3.14"),
        _entry("3.14.8", "macos", "aarch64", f"{MANAGED}/cpython-3.14-macos-aarch64-none/bin/python3.14"),
        _entry("3.14.7", "macos", "aarch64", f"{MANAGED}/cpython-3.14.7-macos-aarch64-none/bin/python3.14")])
    assert uv.synced_with() == f"{MANAGED}/cpython-3.14-macos-aarch64-none/bin/python3.14"


def test_a_path_uv_prints_relative_to_the_checkout_reaches_sync_absolute(tmp_path, monkeypatch):
    _host(monkeypatch, "darwin", "arm64")
    uv = _build(tmp_path, monkeypatch, [_entry("3.14.8", "macos", "aarch64", "py/bin/python3.14")])
    assert uv.synced_with() == str(tmp_path / "task" / "py" / "bin" / "python3.14")


def test_with_no_pin_the_request_is_requires_python(tmp_path, monkeypatch):
    _host(monkeypatch, "darwin", "arm64")
    uv = _build(tmp_path, monkeypatch, [_entry("3.12.15", "macos", "aarch64", "/opt/homebrew/bin/python3.12")], pin=None)
    assert uv.calls[0][1:4] == ["python", "list", ">=3.10"]


def test_no_host_arch_interpreter_fails_naming_what_is_missing(tmp_path, monkeypatch):
    _host(monkeypatch, "darwin", "arm64")
    with pytest.raises(repo.RepoEnvError) as err:
        _build(tmp_path, monkeypatch, [
            _entry("3.14.10", "macos", "x86_64", f"{MANAGED}/cpython-3.14-macos-x86_64-none/bin/python3.14")])
    msg = str(err.value)
    assert "no macos-aarch64 Python 3.14 is installed" in msg
    assert "cpython-3.14.10-macos-x86_64-none" in msg
    assert "uv python install cpython-3.14-macos-aarch64" in msg
    assert not (tmp_path / "cache" / "envs").exists() or not any((tmp_path / "cache" / "envs").iterdir())


def _foreign_binary(path: Path) -> bool:
    """A thin x86_64 Mach-O at path, True when this host refuses to run it (an arm64 Mac without Rosetta)."""
    if sys.platform != "darwin" or platform.machine() != "arm64" or not shutil.which("lipo"):
        return False
    path.parent.mkdir(parents=True)
    subprocess.run(["lipo", "-thin", "x86_64", "/usr/bin/true", "-output", str(path)], check=True, timeout=60)
    try:
        subprocess.run([str(path)], timeout=60)
    except OSError:
        return True
    return False


def test_real_uv_builds_past_an_unrunnable_newer_install(tmp_path, monkeypatch):
    uv = shutil.which("uv")
    minor = f"{sys.version_info.major}.{sys.version_info.minor}"
    inst = tmp_path / "uv-python"
    if not uv or not _foreign_binary(inst / f"cpython-{minor}.99-macos-x86_64-none" / "bin" / f"python{minor}"):
        pytest.skip("needs uv on an arm64 Mac that cannot run x86_64")
    host = inst / f"cpython-{platform.python_version()}-macos-aarch64-none" / "bin" / f"python{minor}"
    host.parent.mkdir(parents=True)
    host.symlink_to(Path(sys.base_prefix) / "bin" / f"python{minor}")
    monkeypatch.setenv("UV_PYTHON_INSTALL_DIR", str(inst))
    monkeypatch.setenv("UV_OFFLINE", "1")
    monkeypatch.setattr(repo, "cache_root", lambda: tmp_path / "cache")
    task = _task(tmp_path, minor)
    venv = repo.prepare(task)
    out = subprocess.run([str(repo.python_of(venv)), "-c", "import platform; print(platform.machine())"],
                         capture_output=True, text=True, timeout=60, env={**os.environ, "PYTHONNOUSERSITE": "1"})
    assert out.stdout.strip() == "arm64"
    assert repo.interpreter(task, uv, {**os.environ}) == str(host)


@pytest.mark.gauntlet("a-closed-table-fronting-an-open-set", site="evals/repo.py:UV_ARCH")
@pytest.mark.gauntlet("a-closed-table-fronting-an-open-set", site="evals/repo.py:UV_OS")
def test_an_unmapped_host_matches_uv_by_its_own_name_or_fails_naming_it(tmp_path, monkeypatch):
    _host(monkeypatch, "freebsd14", "riscv64")
    assert repo.host_platform() == ("freebsd14", "riscv64", "none")
    with pytest.raises(repo.RepoEnvError, match="no freebsd14-riscv64 Python 3.14"):
        _build(tmp_path, monkeypatch, [_entry("3.14.8", "linux", "riscv64", "/r/bin/python3.14", "gnu")])
    _host(monkeypatch, "linux", "riscv64")
    (tmp_path / "again").mkdir()
    uv = _build(tmp_path / "again", monkeypatch, [_entry("3.14.8", "linux", "riscv64", "/r/bin/python3.14", "gnu")])
    assert uv.synced_with() == "/r/bin/python3.14"
