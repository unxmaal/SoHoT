"""#771: the loop's fetch step beats from the bytes a download writes, so a long download is not stalled."""
import os
import threading
import time
import types

import pytest

from harness import downloads, fetching, gguf
from harness import heartbeat as hb
from harness import sweep_check as sc
from tests.test_sweep_check_1062 import START, unit

REPO = "org/Big-Model"
MIB = 1024 * 1024
HALF_HOUR = 1800


@pytest.fixture
def clock(monkeypatch):
    now = {"t": START + 5}
    monkeypatch.setattr(hb, "clock", lambda: now["t"])
    hb.start(lane="", total=10)
    hb.beat("fetch", step=8)
    return now


def _write(path, n=MIB):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "ab") as f:
        f.write(os.urandom(n))


def _verdicts(now):
    b = hb.read()
    return hb.status(b, alive=lambda pid: True), sc.verdict(unit("running"), b, now, START,
                                                             alive=lambda pid: True)["verdict"]


def test_a_download_that_keeps_writing_for_four_hours_reads_running(clock):
    blob = downloads.hub_dir(REPO) / "blobs" / "abc.1234.incomplete"
    with downloads.landing(downloads.hub_dir(REPO), what=REPO) as watch:
        for _ in range(8):
            clock["t"] += HALF_HOUR
            _write(blob)
            assert watch.tick()
            assert _verdicts(clock["t"]) == ("running", sc.RUNNING)
    b = hb.read()
    assert b["landed"] >= 8 * MIB and b["candidate"] == REPO and "MiB landed" in hb._where(b)


def test_a_download_that_writes_nothing_reads_stalled(clock):
    start = clock["t"]
    with downloads.landing(downloads.hub_dir(REPO), what=REPO) as watch:
        clock["t"] = start + sc.STALL_S + 1
        assert not watch.tick()
        assert _verdicts(clock["t"])[1] == sc.STALLED
        clock["t"] = start + hb.STALL_S + 1
        assert not watch.tick()
        assert _verdicts(clock["t"])[0] == "stalled"


def test_a_preallocated_file_is_not_progress(clock, monkeypatch):
    blob = downloads.hub_dir(REPO) / "blobs" / "sparse.incomplete"
    real = os.lstat

    def lstat(path):
        st = real(path)
        if str(path) != str(blob):
            return st
        return types.SimpleNamespace(st_mode=st.st_mode, st_size=4096 * MIB, st_blocks=0)

    with downloads.landing(downloads.hub_dir(REPO), what=REPO) as watch:
        blob.parent.mkdir(parents=True)
        blob.touch()
        monkeypatch.setattr(downloads.os, "lstat", lstat)
        clock["t"] += sc.STALL_S + 1
        assert not watch.tick()
        assert _verdicts(clock["t"])[1] == sc.STALLED


def _until_beat(before, ready):
    """Wait for the watcher thread's beat after `before`, then let the fake download return."""
    end = time.monotonic() + 60  # a deadline only a hung watcher reaches; a loaded make check took over 5 s. #1303.
    while time.monotonic() < end:
        b = hb.read()
        if b.get("updated", 0) > before and b.get("landed"):
            ready.set()
            return b
        threading.Event().wait(0.01)
    ready.set()
    return hb.read()


def test_the_real_download_path_beats_from_its_bytes(clock, monkeypatch):
    monkeypatch.setattr(downloads, "PROGRESS_POLL_S", 0.01)
    clock["t"] += HALF_HOUR
    seen = {}

    def snapshot(repo_id, allow_patterns=None):
        d = downloads.hub_dir(repo_id)
        _write(d / "blobs" / "w.incomplete")
        seen["beat"] = _until_beat(START + 5, threading.Event())
        (d / "snapshots" / "0").mkdir(parents=True)
        (d / "snapshots" / "0" / "config.json").write_text("{}", encoding="utf-8")
        return d / "snapshots" / "0"

    fetching.download(REPO, snapshot=snapshot, text=False)
    assert seen["beat"]["updated"] == clock["t"] and seen["beat"]["landed"] >= MIB
    assert seen["beat"]["candidate"] == REPO


def test_the_gguf_download_path_beats_from_its_bytes(clock, monkeypatch):
    monkeypatch.setattr(downloads, "PROGRESS_POLL_S", 0.01)
    clock["t"] += HALF_HOUR
    seen = {}

    def hf_download(repo, filename, local_dir):
        _write(gguf.models_dir() / ".cache" / "huggingface" / "download" / f"{filename}.x.incomplete")
        seen["beat"] = _until_beat(START + 5, threading.Event())
        _write(gguf.models_dir() / filename)
        return str(gguf.models_dir() / filename)

    gguf.download(REPO, "Big-Q4_K_M.gguf", hf_download=hf_download, refresh=lambda: None)
    assert seen["beat"]["updated"] == clock["t"] and seen["beat"]["landed"] >= MIB


def test_a_fetch_outside_the_loop_writes_no_heartbeat(monkeypatch):
    monkeypatch.setattr(downloads, "PROGRESS_POLL_S", 0.01)

    def snapshot(repo_id, allow_patterns=None):
        d = downloads.hub_dir(repo_id)
        _write(d / "blobs" / "w.incomplete")
        threading.Event().wait(0.1)
        (d / "snapshots" / "0").mkdir(parents=True)
        return d / "snapshots" / "0"

    fetching.download(REPO, snapshot=snapshot, text=False)
    assert hb.read() is None


def test_bytes_landed_outside_the_loop_leave_another_process_s_heartbeat_alone(clock):
    theirs = {**hb.read(), "pid": os.getpid() + 1}
    hb._write(theirs)
    hb.landed(5 * MIB, REPO)
    assert hb.read() == theirs
