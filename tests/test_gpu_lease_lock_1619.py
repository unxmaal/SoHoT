"""The gpu lease is the machine lock: exclusive.held, delegate.busy, router release and the worker read one ledger. #1619."""
import os
import subprocess
import sys
import textwrap
import types
from pathlib import Path

import pytest

from harness import delegate, exclusive, item_lease, resources, router
from harness import memory_store as ms
from harness import workqueue as wq

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv(exclusive.HELD_ENV, raising=False)
    monkeypatch.delenv(wq.JOB_ENV, raising=False)


def _holder(kind: str, seconds: float = 30) -> subprocess.Popen:
    code = textwrap.dedent(f"""
        import sys, time
        sys.path.insert(0, {str(REPO)!r})
        from harness import exclusive
        with exclusive.held({kind!r}):
            print('held', flush=True)
            time.sleep({seconds})
    """)
    p = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True,
                         env={**os.environ, exclusive.HELD_ENV: ""})
    assert p.stdout.readline().strip() == "held"
    return p


def test_a_held_gpu_kind_holds_a_gpu_lease_and_frees_it():
    with exclusive.held("eval"):
        [h] = item_lease.live(ms.connect(), resources.GPU)
        assert (h["state"], h["pid"]) == ("eval", os.getpid())
        assert exclusive.gpu_holder()["kind"] == "eval"
    assert item_lease.live(ms.connect(), resources.GPU) == [] and exclusive.gpu_holder() == {}


def test_a_second_process_is_refused_while_the_first_holds_and_names_it():
    first = _holder("image")
    try:
        with exclusive.try_held("eval") as got:
            assert got is False
        assert exclusive.gpu_leases() == 1
        assert "image" in delegate.busy()
        first.terminate()
        first.wait()
        with exclusive.try_held("eval") as got:
            assert got is True, "a stopped holder's lease is released at the next take, not at its TTL"
    finally:
        first.kill()
        first.wait()


def test_a_killed_holder_frees_the_gpu_at_the_next_take():
    first = _holder("video", seconds=300)
    first.kill()
    first.wait()
    with exclusive.try_held("eval") as got:
        assert got is True


def test_a_queued_gpu_job_s_own_eval_reuses_the_job_s_lease(monkeypatch):
    seen = {}

    def popen(argv, cwd=None, stdout=None, stderr=None, env=None):
        monkeypatch.setenv(wq.JOB_ENV, env[wq.JOB_ENV])
        with exclusive.held("eval") as waited:
            seen["leases"] = item_lease.live(ms.connect(), resources.GPU)
            seen["waited"] = waited
            seen["busy"] = delegate.busy()
        return types.SimpleNamespace(returncode=0)

    job = wq.add([sys.executable, "-c", "pass"], title="gpu job")
    assert wq.run_pending(popen=popen)[0]["state"] == wq.DONE
    [h] = seen["leases"]
    assert h["job_id"] == int(job["id"]) and h["state"] == "eval" and seen["waited"] is False
    assert seen["busy"] == "", "a job's own eval is not busy to itself"


def test_a_gpu_lease_outside_the_queue_keeps_a_gpu_job_pending_without_a_claim_loop():
    outside = item_lease.take(ms.connect(), resources.GPU, "with-gpu-lock pid x", state="external")
    job = wq.add([sys.executable, "-c", "pass"], title="gpu job")
    calls = []
    real = wq._claim
    def claim(*a, **k):
        calls.append(1)
        if len(calls) > 3:
            raise RuntimeError("claimed and handed back in a loop")
        return real(*a, **k)
    wq._claim = claim
    try:
        assert wq.run_pending(popen=lambda *a, **k: pytest.fail("ran beside a held gpu")) == []
    finally:
        wq._claim = real
    assert calls == [] and wq.get(job["id"])["state"] == wq.PENDING
    item_lease.release(ms.connect(), outside["id"])


def test_a_router_release_waits_out_a_run_and_its_own_job_s_lease_is_its_own(monkeypatch):
    monkeypatch.setattr(router, "_get", lambda path: {"data": [{"id": "M", "status": {"value": "loaded"}}]})
    gone = []
    monkeypatch.setattr(router, "_post", lambda path, body: gone.append(body["model"]) or {})
    monkeypatch.setattr(router, "protected", lambda *a, **k: set())
    run = item_lease.take(ms.connect(), resources.GPU, "eval pid 1", state="eval")
    said = []
    assert router.release(["M"], "x", say=said.append) == [] and "in flight" in said[0]
    item_lease.release(ms.connect(), run["id"])
    job = wq.add([sys.executable, "-c", "pass"], title="measure")
    lease = item_lease.take(ms.connect(), resources.GPU, f"job {job['id']}", job_id=int(job["id"]))
    monkeypatch.setenv(wq.JOB_ENV, str(job["id"]))
    assert router.release(["M"], "measured", say=said.append) == ["M"]
    item_lease.release(ms.connect(), lease["id"])


def test_another_project_s_lockf_holds_the_gpu_and_a_held_kind_holds_the_flock_lockf_takes():
    fd = os.open(exclusive.lock_path(), os.O_RDWR | os.O_CREAT, 0o644)
    try:
        assert exclusive._take(fd), "lockf -k generation.lock, as infovore takes it (DECISION #210)"
        assert exclusive.gpu_leases() == 1 and "lockf" in delegate.busy()
        job = wq.add([sys.executable, "-c", "pass"], title="gpu job")
        assert wq.run_pending(popen=lambda *a, **k: pytest.fail("ran beside a lockf holder")) == []
        assert wq.get(job["id"])["state"] == wq.PENDING
        with exclusive.try_held("eval") as got:
            assert got is False
        assert item_lease.live(ms.connect(), resources.GPU) == [], "a refused take keeps no lease"
    finally:
        exclusive._release(fd)
        os.close(fd)
    with exclusive.held("eval"):
        assert exclusive._taken(exclusive.lock_path()), "a lockf user waits for a held kind"
