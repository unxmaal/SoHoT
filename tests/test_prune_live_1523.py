"""Prune never removes a release a live process still runs from: cwd, executable, open or mapped file under it. #1523."""
from __future__ import annotations

import io
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from harness import cuts, deploy, holders, paths

live = pytest.mark.skipif(not (sys.platform == "darwin" or sys.platform.startswith("linux")),
                          reason="holders reads libproc on macOS and /proc on Linux")

OPEN = "import sys, time\nf = open(sys.argv[1], 'rb')\nprint('ready', flush=True)\ntime.sleep(600)\n"
# Python's mmap keeps a dup of the fd, so map through libc to leave the mapping as the only hold.
MAP = ("import ctypes, os, sys, time\nlibc = ctypes.CDLL(None, use_errno=True)\nlibc.mmap.restype = ctypes.c_void_p\n"
       "libc.mmap.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_long]\n"
       "fd = os.open(sys.argv[1], os.O_RDONLY)\naddr = libc.mmap(None, 4096, 1, 1, fd, 0)\n"
       "assert addr not in (None, ctypes.c_void_p(-1).value), ctypes.get_errno()\nos.close(fd)\n"
       "print('ready', flush=True)\ntime.sleep(600)\n")
WAIT = "import time\nprint('ready', flush=True)\ntime.sleep(600)\n"


@pytest.fixture
def runs():
    """Start a long run and wait until it is set up; every one is killed at the end."""
    started = []

    def start(argv, cwd):
        p = subprocess.Popen([str(a) for a in argv], cwd=str(cwd), stdout=subprocess.PIPE, text=True)
        started.append(p)
        if argv[0] == sys.executable:
            assert p.stdout.readline().strip() == "ready"
        return p

    yield start
    for p in started:
        p.kill()
        p.wait()


@pytest.fixture
def releases(monkeypatch):
    monkeypatch.setattr(deploy, "KEEP_RELEASES", 2)
    root = deploy.releases_dir()
    for name in ("adopted-aaa", "3-bbb", "7-ccc", "9-ddd"):
        (root / name / "scripts").mkdir(parents=True)
        (root / name / "scripts" / "serve-fetch.sh").write_text("sleep 600\n", encoding="utf-8")
    return root


@pytest.fixture
def cut(monkeypatch):
    said = []
    monkeypatch.setattr(cuts, "cut", lambda knob, what, **kw: said.append((knob, what, kw)))
    return said


def _names(root: Path) -> list[str]:
    return sorted(p.name for p in root.iterdir())


@live
def test_a_live_run_in_the_oldest_release_survives_two_prunes_and_goes_once_it_ends(releases, runs, cut, tmp_path):
    link = paths.home() / "deploy"
    os.symlink(releases / "adopted-aaa", link)
    fetch = runs([sys.executable, "-c", WAIT], link)
    os.unlink(link)
    os.symlink(releases / "9-ddd", link)
    log = io.StringIO()
    assert deploy.prune({releases / "7-ccc", link.resolve()}, tmp_path, room=1, log=log) == ["3-bbb"]
    assert f"kept release adopted-aaa past KEEP_RELEASES: 1 live process(es) run from it: pid {fetch.pid}" in log.getvalue()
    assert f"(cwd {os.path.realpath(releases / 'adopted-aaa')})" in log.getvalue()
    (releases / "11-eee").mkdir()
    assert deploy.prune({releases / "9-ddd", releases / "11-eee"}, tmp_path, room=1, log=log) == ["7-ccc"]
    assert _names(releases) == ["11-eee", "9-ddd", "adopted-aaa"]
    kept = [w for k, w, kw in cut if kw == {"kept": 1, "dropped": 0}]
    assert len(kept) == 2 and all(w.startswith("release adopted-aaa kept: 1 live process") for w in kept)
    fetch.kill()
    fetch.wait()
    assert deploy.prune({releases / "9-ddd", releases / "11-eee"}, tmp_path, room=1, log=log) == ["adopted-aaa"]
    assert _names(releases) == ["11-eee", "9-ddd"]


@live
@pytest.mark.parametrize("how", ["open fd", "mapped file", "executable"])
def test_a_run_whose_cwd_is_elsewhere_still_holds_the_release_it_runs_from(releases, runs, tmp_path, how):
    old, elsewhere = releases / "adopted-aaa", tmp_path / "elsewhere"
    elsewhere.mkdir()
    script = old / "scripts" / "serve-fetch.sh"
    if how == "executable":
        shutil.copy(shutil.which("sleep"), old / "sleep")
        if sys.platform == "darwin":
            # A copied platform binary is killed at exec unless it is signed again.
            subprocess.run(["codesign", "--force", "-s", "-", str(old / "sleep")], check=True, capture_output=True)
        p = runs([old / "sleep", "600"], elsewhere)
        assert p.poll() is None
    else:
        p = runs([sys.executable, "-c", OPEN if how == "open fd" else MAP, script], elsewhere)
    got = holders.holding([old, releases / "3-bbb"])
    assert list(got) == [old]
    assert [w for w in got[old] if w.startswith(f"pid {p.pid} ")][0].split(" (", 1)[1].startswith(how)


@live
def test_a_run_through_the_deploy_link_holds_the_release_it_resolved_to_and_no_sibling(releases, runs):
    link = paths.home() / "deploy"
    os.symlink(releases / "3-bbb", link)
    (releases / "3-bb").mkdir()
    p = runs([sys.executable, "-c", WAIT], link)
    got = holders.holding([releases / "3-bb", releases / "3-bbb", link])
    assert sorted(got) == sorted([releases / "3-bbb", link])
    assert all(any(w.startswith(f"pid {p.pid} ") for w in v) for v in got.values())


def test_prune_keeps_every_candidate_where_nobody_can_tell_who_runs_from_it(releases, cut, tmp_path):
    log = io.StringIO()
    assert deploy.prune({releases / "9-ddd"}, tmp_path, room=1, log=log, holding=lambda dirs: None) == []
    assert _names(releases) == ["3-bbb", "7-ccc", "9-ddd", "adopted-aaa"]
    assert log.getvalue().count("no way to tell on this platform") == 3
    assert len(cut) == 3


def test_holders_reads_the_platform_when_asked(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "win32")
    assert holders.holding([tmp_path]) is None
    assert holders.holding([]) == {}


def test_a_mac_without_libproc_cannot_tell_rather_than_finding_nobody(monkeypatch, tmp_path):
    def missing():
        raise OSError("dlopen(libproc.dylib): image not found")
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(holders, "_libproc", missing)
    assert holders.holding([tmp_path]) is None
