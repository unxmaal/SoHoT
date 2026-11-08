"""Every queued job needs one resource class: one gpu job at a time, network, disk and cpu jobs beside it up to their capacity; a job runs under an executor. #1508."""
import sys
import threading
import time
import types

import pytest

from harness import cli, executors, exclusive, resources
from harness import memory_store as ms
from harness import workqueue as wq

ORNITH = ["uv", "run", "python", "-m", "evals.run", "--modality", "repo", "--candidates",
          "llamacpp:Ornith-1.5-35B-Q4_K_M", "--out", "runs/ornith"]
OPUS = ["uv", "run", "python", "-m", "evals.run", "--modality", "repo", "--candidates",
        "claude-code:claude-opus-5-5", "--out", "runs/opus"]
FETCH = ["uv", "run", "soh", "fetch", "--run"]


class Fake:
    """A popen whose jobs block until released, recording each start by its title-bearing argv."""

    def __init__(self):
        self.gates, self.started, self.lock = {}, [], threading.Lock()

    def hold(self, argv):
        self.gates[tuple(argv)] = threading.Event()

    def __call__(self, argv, cwd=None, stdout=None, stderr=None, env=None):
        with self.lock:
            self.started.append(tuple(argv))
        gate = self.gates.get(tuple(argv))
        if gate is not None:
            gate.wait()
        return types.SimpleNamespace(returncode=0)


@pytest.fixture
def fake():
    got = Fake()
    yield got
    for gate in got.gates.values():
        gate.set()


def _until(cond, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


def _worker(fake):
    t = threading.Thread(target=wq.run_pending, kwargs={"popen": fake, "watch": 0.02}, daemon=True)
    t.start()
    return t


@pytest.mark.parametrize("argv,kind,want", [
    (ORNITH, "command", resources.GPU),
    (OPUS, "command", resources.NETWORK),
    (FETCH, "command", resources.NETWORK),
    (["soh", "discover", "--loop"], "command", resources.GPU),
    (["true"], wq.DEPLOY, resources.DEPLOY),
    (["python", "-m", "evals.run", "--no-such-flag"], "command", resources.GPU),
])
def test_a_job_that_declares_nothing_is_classed_by_its_command(argv, kind, want):
    assert resources.classify(argv, kind) == want == wq.needs({"argv": argv, "kind": kind})


def test_a_declared_class_wins_over_the_command_and_an_unknown_one_is_refused():
    job = wq.add(ORNITH, title="ornith", resource=resources.DISK)
    assert wq.get(job["id"])["resource"] == resources.DISK and wq.needs(wq.get(job["id"])) == resources.DISK
    with pytest.raises(ValueError, match="resource"):
        wq.add(["true"], title="x", resource="tpu")


def test_a_gpu_job_and_a_network_job_run_together_and_two_gpu_jobs_never_do(fake):
    fake.hold(ORNITH)
    gpu = wq.add(ORNITH, title="ornith")
    worker = _worker(fake)
    assert _until(lambda: tuple(ORNITH) in fake.started)
    second = wq.add([*ORNITH[:-1], "runs/ornith-2"], title="ornith again")
    net = wq.add(FETCH, title="fetch")
    assert _until(lambda: wq.get(net["id"])["state"] == wq.DONE), "the download ran beside the GPU job"
    assert wq.get(gpu["id"])["state"] == wq.RUNNING and wq.get(second["id"])["state"] == wq.PENDING
    fake.gates[tuple(ORNITH)].set()
    worker.join(20)
    assert wq.get(second["id"])["state"] == wq.DONE
    assert fake.started.index(tuple(FETCH)) < fake.started.index(tuple([*ORNITH[:-1], "runs/ornith-2"]))


def test_a_class_at_capacity_waits_while_another_class_starts(fake):
    disk_a = [sys.executable, "-c", "pass", "a"]
    disk_b = [sys.executable, "-c", "pass", "b"]
    cpu = [sys.executable, "-c", "pass", "cpu"]
    fake.hold(disk_a)
    wq.add(disk_a, title="copy a", resource=resources.DISK)
    second = wq.add(disk_b, title="copy b", resource=resources.DISK)
    other = wq.add(cpu, title="grade", resource=resources.CPU)
    worker = _worker(fake)
    assert _until(lambda: wq.get(other["id"])["state"] == wq.DONE)
    assert wq.get(second["id"])["state"] == wq.PENDING, "disk holds one job at a time"
    fake.gates[tuple(disk_a)].set()
    worker.join(20)
    assert wq.get(second["id"])["state"] == wq.DONE


def test_the_network_capacity_is_the_cloud_slots_knob_not_a_copy(monkeypatch):
    monkeypatch.setattr(exclusive, "CLOUD_SLOTS", 3)
    assert resources.capacity(resources.NETWORK) == 3
    assert resources.capacity(resources.GPU) == 1


def test_soh_jobs_add_declares_a_class_and_the_list_shows_each(capsys):
    assert cli.main(["jobs", "add", "--resource", "network", "--", sys.executable, "-c", "pass"]) == 0
    assert cli.main(["jobs", "add", "--", *ORNITH]) == 0
    capsys.readouterr()
    assert cli.main(["jobs", "list"]) == 0
    lines = [x for x in capsys.readouterr().out.splitlines() if x.startswith("  0")]
    assert len(lines) == 2 and "network" in lines[0] and "gpu" in lines[1]


def test_a_job_runs_under_its_executor_which_cancel_also_stops(monkeypatch, tmp_path):
    seen = []

    class Recording(executors.Host):
        def run(self, job, argv, cwd=None, stdout=None, env=None):
            seen.append(("run", job["id"]))
            return super().run(job, argv, cwd=cwd, stdout=stdout, env=env)

        def stop(self, pid, grace=None):
            seen.append(("stop", pid))
            return super().stop(pid, grace)

    monkeypatch.setitem(executors.EXECUTORS, executors.HOST, Recording())
    job = wq.add([sys.executable, "-c", "pass"], title="plain")
    assert wq.run_pending()[0]["state"] == wq.DONE
    assert seen[0] == ("run", job["id"]) and seen[1][0] == "stop"


def test_a_job_that_declares_nothing_stores_no_class_and_is_classed_when_read(monkeypatch):
    job = wq.add(OPUS, title="opus")
    assert wq.get(job["id"])["resource"] == ""
    monkeypatch.setattr(resources, "classify", lambda argv, kind="command": resources.CPU)
    assert wq.needs(wq.get(job["id"])) == resources.CPU
