"""The disk sweep prunes uv's cache, never forced; every Mac `uv run --with` resolves through a lock. #2049."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

from harness import disk, uv_cache

REPO = Path(__file__).resolve().parents[1]
UV = shutil.which("uv")
needs_uv = pytest.mark.skipif(not UV, reason="no uv on PATH")
#: Runs on the CUDA node, not the Mac whose disk #2049 filled.
NOT_MAC = ("scripts/serve-audio-cuda.sh",)


def _wheel(where: Path) -> Path:
    path = where / "tinykeep-1.0-py3-none-any.whl"
    info = "tinykeep-1.0.dist-info"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("tinykeep.py", "X = 1\n")
        z.writestr(f"{info}/METADATA", "Metadata-Version: 2.1\nName: tinykeep\nVersion: 1.0\n")
        z.writestr(f"{info}/WHEEL", "Wheel-Version: 1.0\nGenerator: t\nRoot-Is-Purelib: true\nTag: py3-none-any\n")
        z.writestr(f"{info}/RECORD", "")
    return path


@pytest.fixture
def planted(tmp_path):
    """A scratch uv cache holding one archive entry an installed wheel references and one nothing does."""
    cache = tmp_path / "cache"
    env = {**os.environ, "UV_CACHE_DIR": str(cache), "UV_OFFLINE": "1", "VIRTUAL_ENV": ""}
    venv = tmp_path / "v"
    for argv in ([UV, "venv", "-q", "--python", sys.executable, str(venv)],
                 [UV, "pip", "install", "-q", "--python", str(venv), str(_wheel(tmp_path))]):
        subprocess.run(argv, env=env, check=True, capture_output=True, timeout=120)
    archive = cache / "archive-v0"
    (kept,) = [p for p in archive.iterdir() if (p / "tinykeep.py").exists()]
    orphan = archive / "ORPHANentry00000"
    orphan.mkdir()
    (orphan / "blob").write_bytes(b"x" * 300_000)
    return cache, kept, orphan


@needs_uv
def test_the_prune_removes_an_unreferenced_entry_and_keeps_a_referenced_one(planted):
    cache, kept, orphan = planted
    got = uv_cache.prune_at(cache)
    assert "skipped" not in got, got
    assert not orphan.exists()
    assert (kept / "tinykeep.py").exists()
    assert got["bytes"] >= 300_000


@needs_uv
@pytest.mark.skipif(sys.platform == "win32", reason="the lock probe is flock")
def test_a_held_cache_lock_skips_the_prune_and_removes_nothing(planted, monkeypatch):
    import fcntl
    cache, kept, orphan = planted
    monkeypatch.setattr(uv_cache, "PRUNE_TIMEOUT_S", 20.0)
    fd = os.open(cache / ".lock", os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_SH)
        got = uv_cache.prune_at(cache)
    finally:
        os.close(fd)
    assert got == {"skipped": uv_cache.HELD}
    assert orphan.exists() and kept.exists()


@needs_uv
@pytest.mark.skipif(sys.platform == "win32", reason="the lock probe is flock")
def test_a_lock_taken_after_the_probe_is_seen_in_uvs_first_line_and_not_waited_on(planted, monkeypatch):
    import fcntl
    cache, kept, orphan = planted
    monkeypatch.setattr(uv_cache, "held", lambda c: False)
    monkeypatch.setattr(uv_cache, "PRUNE_TIMEOUT_S", 20.0)
    fd = os.open(cache / ".lock", os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_SH)
        got = uv_cache.prune_at(cache)
    finally:
        os.close(fd)
    assert got == {"skipped": uv_cache.HELD}
    assert orphan.exists()


def test_no_cache_is_skipped_with_its_path(tmp_path):
    assert uv_cache.prune_at(tmp_path / "none")["skipped"].startswith("no uv cache at")


@pytest.mark.parametrize("text,want", [("Pruning cache at: c\nRemoved 3 files (8.0KiB)\n", 8192),
                                       ("Removed 12 files (1.5GiB)", round(1.5 * 1024 ** 3)),
                                       ("Pruning cache at: c\nNo unused entries found\n", 0)])
def test_bytes_freed_are_read_from_uvs_summary(text, want):
    assert uv_cache.removed_bytes(text) == want


def test_the_sweep_reports_bytes_freed_and_a_volume_still_under_the_alert(monkeypatch):
    lines = []
    monkeypatch.setattr(uv_cache, "prune", lambda: {"bytes": 3 * 1024 ** 3, "free": 10 * 1024 ** 3})
    disk.uv_prune(lines.append)
    assert lines[0] == "  uv cache: freed 3.0 GiB"
    assert "10.0 GiB free, under monit's" in lines[1]
    lines.clear()
    monkeypatch.setattr(uv_cache, "prune", lambda: {"bytes": 0, "free": 900 * 1024 ** 3})
    disk.uv_prune(lines.append)
    assert lines == ["  uv cache: freed 0.0 GiB"]


def test_the_sweep_says_why_the_prune_was_skipped(monkeypatch):
    lines = []
    monkeypatch.setattr(uv_cache, "prune", lambda: {"skipped": uv_cache.HELD})
    assert disk.uv_prune(lines.append) == {"skipped": uv_cache.HELD}
    assert lines == [f"  uv cache prune skipped: {uv_cache.HELD}"]


def _pins() -> dict:
    text = (REPO / "scripts" / "versions.sh").read_text(encoding="utf-8")
    return dict(re.findall(r'^([A-Z0-9_]+)="([^"]*)"', text, re.M))


def _uv_runs() -> list[tuple[str, str]]:
    """Each `uv run` command in the Mac's scripts and the Makefile that takes a --with, continuation lines joined."""
    out = []
    for path in sorted([*REPO.glob("scripts/*.sh"), REPO / "Makefile"]):
        rel = path.relative_to(REPO).as_posix()
        if rel in NOT_MAC:
            continue
        text = re.sub(r"\\\n", " ", path.read_text(encoding="utf-8"))
        for line in text.splitlines():
            if line.lstrip().startswith("#"):
                continue
            for cmd in re.findall(r"uv run .*", line):
                if re.search(r"--with\s", cmd):
                    out.append((rel, cmd))
    return out


def _lock(name: str) -> dict:
    out = {}
    for line in (REPO / "scripts" / "locks" / f"{name}.txt").read_text(encoding="utf-8").splitlines():
        spec = line.split(";")[0].strip()
        if spec and not spec.startswith("#"):
            req = Requirement(spec)
            out[canonicalize_name(req.name)] = req.url or str(req.specifier).removeprefix("==")
    return out


def test_every_mac_uv_run_with_resolves_through_a_lock_that_holds_its_pins():
    """`--with X==1` alone takes the newest of X's dependencies each run: a fresh cached environment."""
    runs = _uv_runs()
    assert {rel for rel, _ in runs} >= {"Makefile", "scripts/serve-gateway.sh", "scripts/serve-tts.sh"}
    pins = _pins()
    for rel, cmd in runs:
        lock = re.search(r"--with-requirements scripts/locks/([a-z0-9-]+)\.txt", cmd)
        assert lock, f"{rel}: `{cmd[:80]}` takes --with without --with-requirements scripts/locks/NAME.txt"
        held = _lock(lock.group(1))
        for word in re.findall(r"--with\s+(\"[^\"]+\"|'[^']+'|\S+)", cmd):
            word = word.strip("\"'")
            ref = re.fullmatch(r"\$\$?\{?([A-Z0-9_]+)\}?", word)
            req = Requirement(pins[ref.group(1)] if ref else word)
            got = held.get(canonicalize_name(req.name))
            assert got, f"{rel}: {req} is not in scripts/locks/{lock.group(1)}.txt; run scripts/lock-with.sh"
            if req.url:
                assert got == req.url, f"{rel}: {req.name} is {got} in the lock, {req.url} pinned"
            else:
                assert req.specifier.contains(got, prereleases=True), (
                    f"{rel}: the lock has {req.name}=={got}, versions.sh pins {req}; run scripts/lock-with.sh")
