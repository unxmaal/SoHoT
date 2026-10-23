"""The worker starts a cloud-only eval beside a running GPU job, by evals.run's own lock rule. #1153."""
import os
import threading
import time
import types

import pytest

from evals import run
from harness import exclusive, slot_probe
from harness import workqueue as wq

ORNITH = ["uv", "run", "python", "-m", "evals.run", "--modality", "repo", "--candidates",
          "llamacpp:Ornith-1.5-35B-Q4_K_M", "--repeat", "1", "--split", "all", "--out", "runs/ornith"]
OPUS = ["uv", "run", "python", "-m", "evals.run", "--modality", "repo", "--candidates",
        "claude-code:claude-opus-5-5", "--repeat", "1", "--split", "all", "--out", "runs/opus"]
SONNET = [*OPUS[:8], "claude-code:claude-sonnet-5-5", *OPUS[9:]]


class Fake:
    """A popen whose jobs block until released, recording when each starts and ends."""

    def __init__(self):
        self.gates, self.events, self.lock, self.workers = {}, [], threading.Lock(), []

    def hold(self, argv):
        self.gates[tuple(argv)] = threading.Event()

    def release(self, argv):
        self.gates[tuple(argv)].set()

    def __call__(self, argv, cwd=None, stdout=None, stderr=None, env=None):
        with self.lock:
            self.events.append(("start", argv[8]))
        gate = self.gates.get(tuple(argv))
        if gate is not None:
            assert gate.wait(10), f"{argv[8]} never released"
        with self.lock:
            self.events.append(("end", argv[8]))
        return types.SimpleNamespace(returncode=0)

    def started(self):
        with self.lock:
            return [n for e, n in self.events if e == "start"]


def _until(cond, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


@pytest.fixture
def fake():
    got = Fake()
    yield got
    for gate in got.gates.values():
        gate.set()
    for t in got.workers:
        t.join(10)


def _worker(fake):
    t = threading.Thread(target=wq.run_pending, kwargs={"popen": fake, "watch": 0.02}, daemon=True)
    fake.workers.append(t)
    t.start()
    return t


def _state(job_id):
    return wq.get(job_id)["state"]


@pytest.mark.parametrize("argv,want", [
    (OPUS, wq.CLOUD),
    (ORNITH, wq.GPU),
    (["uv", "run", "python", "-m", "evals.run", "--modality", "repo", "--candidates",
      "claude-code:claude-opus-5-5,llamacpp:Ornith-1.5-35B-Q4_K_M"], wq.GPU),
    (["python", "evals/run.py", "--modality", "repo", "--candidates", "claude-code:claude-opus-5-5"], wq.CLOUD),
    (["python", "-m", "evals.run", "--compare", "a,b"], wq.GPU),
    (["python", "-m", "evals.run", "--no-such-flag"], wq.GPU),
    (["soh", "discover", "--loop"], wq.GPU),
])
def test_a_job_needs_the_lock_evals_run_would_take(argv, want):
    assert wq.needs({"argv": argv}) == want


def test_the_class_is_read_from_evals_run_lock_kind_not_a_copy(monkeypatch):
    monkeypatch.setattr(run, "lock_kind", lambda args, config=None: "cloud-eval")
    assert wq.needs({"argv": ORNITH}) == wq.CLOUD


def test_with_a_gpu_job_running_a_cloud_job_starts_and_a_gpu_job_does_not(fake):
    fake.hold(ORNITH)
    gpu = wq.add(ORNITH, title="ornith")
    worker = _worker(fake)
    assert _until(lambda: fake.started() == ["llamacpp:Ornith-1.5-35B-Q4_K_M"])
    second = wq.add([*ORNITH[:-1], "runs/ornith-2"], title="ornith again")
    cloud = wq.add(OPUS, title="opus")
    assert _until(lambda: _state(cloud["id"]) == wq.DONE)
    assert _state(gpu["id"]) == wq.RUNNING
    assert _state(second["id"]) == wq.PENDING
    fake.release(ORNITH)
    worker.join(10)
    assert not worker.is_alive()
    assert _state(second["id"]) == wq.DONE
    assert fake.started() == ["llamacpp:Ornith-1.5-35B-Q4_K_M", "claude-code:claude-opus-5-5",
                              "llamacpp:Ornith-1.5-35B-Q4_K_M"]


def test_cloud_jobs_fill_the_free_slots_in_priority_order(monkeypatch, fake):
    monkeypatch.setattr(exclusive, "CLOUD_SLOTS", 1)
    fake.hold(ORNITH)
    fake.hold(OPUS)
    wq.add(ORNITH, title="ornith")
    low = wq.add(SONNET, title="sonnet")
    high = wq.add(OPUS, title="opus", priority=5)
    worker = _worker(fake)
    assert _until(lambda: len(fake.started()) == 2)
    assert sorted(fake.started()) == ["claude-code:claude-opus-5-5", "llamacpp:Ornith-1.5-35B-Q4_K_M"]
    time.sleep(0.1)
    assert _state(low["id"]) == wq.PENDING
    fake.release(OPUS)
    assert _until(lambda: _state(low["id"]) == wq.DONE)
    assert _state(high["id"]) == wq.DONE
    fake.release(ORNITH)
    worker.join(10)
    assert not worker.is_alive()


def test_a_cloud_slot_held_outside_the_queue_keeps_a_cloud_job_waiting(monkeypatch, fake):
    monkeypatch.setattr(exclusive, "CLOUD_SLOTS", 1)
    fd = os.open(exclusive.cloud_lock_path(0), os.O_RDWR | os.O_CREAT, 0o644)
    assert exclusive._take(fd)
    cloud = wq.add(OPUS, title="opus")
    worker = _worker(fake)
    try:
        time.sleep(0.2)
        assert _state(cloud["id"]) == wq.PENDING
        assert worker.is_alive() is False
    finally:
        exclusive._release(fd)
        os.close(fd)
    assert wq.run_pending(popen=fake, watch=0.02)[0]["state"] == wq.DONE


def test_current_is_the_gpu_job_and_the_probe_spares_every_running_jobs_models(fake):
    fake.hold(ORNITH)
    fake.hold(OPUS)
    wq.add(ORNITH, title="ornith")
    worker = _worker(fake)
    assert _until(lambda: len(fake.started()) == 1)
    wq.add(OPUS, title="opus")
    assert _until(lambda: len(fake.started()) == 2)
    try:
        assert wq.current()["title"] == "ornith"
        busy = slot_probe.busy_text()
        assert "Ornith-1.5-35B-Q4_K_M" in busy and "claude-opus-5-5" in busy
    finally:
        fake.release(OPUS)
        fake.release(ORNITH)
        worker.join(10)
    assert not worker.is_alive()


def test_a_job_that_breaks_the_worker_is_raised_after_the_jobs_beside_it_finish(fake):
    fake.hold(ORNITH)

    def popen(argv, **kw):
        if argv == OPUS:
            raise RuntimeError("store gone")
        return fake(argv, **kw)

    wq.add(ORNITH, title="ornith")
    wq.add(OPUS, title="opus")
    threading.Timer(0.3, fake.release, (ORNITH,)).start()
    with pytest.raises(RuntimeError, match="store gone"):
        wq.run_pending(popen=popen, watch=0.02)
    assert fake.started() == ["llamacpp:Ornith-1.5-35B-Q4_K_M"]
    assert ("end", "llamacpp:Ornith-1.5-35B-Q4_K_M") in fake.events
