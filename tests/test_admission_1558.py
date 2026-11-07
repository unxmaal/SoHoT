"""A gpu job is admitted before it loads: resident, inside the memory budget beside the live leases and the pinned set, or unpriced and said so; never tried first. #1558."""
import sys
import types

import pytest

from harness import admission, item_lease, memory, pressure, resources
from harness import memory_store as ms
from harness import workqueue as wq

BIG = ["uv", "run", "python", "-m", "evals.run", "--modality", "code", "--candidates", "llamacpp:Big-30B"]
SMALL = ["uv", "run", "python", "-m", "evals.run", "--modality", "code", "--candidates", "llamacpp:Small-4B"]
SIZES = {"llamacpp:Big-30B": 30.0, "llamacpp:Small-4B": 4.0}


@pytest.fixture
def machine(monkeypatch):
    """A 60 GiB budget machine: ceiling 80, reserve 10, pinned 10, everything free, normal pressure."""
    monkeypatch.setattr(admission, "admit", admission.admit.real)
    state = {"available": 200.0, "level": pressure.NORMAL, "resident": []}
    monkeypatch.setattr(memory, "available_gb", lambda: state["available"])
    monkeypatch.setattr(memory, "ceiling_gb", lambda: 80.0)
    monkeypatch.setattr(memory, "measured_reserve_gb", lambda conn=None: 10.0)
    monkeypatch.setattr(memory, "pinned_gb", lambda: 10.0)
    monkeypatch.setattr(pressure, "sample", lambda: pressure.Pressure(level=state["level"]))
    monkeypatch.setattr(admission, "spec_gb", lambda spec: SIZES.get(spec))
    monkeypatch.setattr(admission, "_resident", lambda: state["resident"])
    return state


def _ran(argv):
    return wq.run_pending(popen=lambda *a, **k: types.SimpleNamespace(returncode=0))


def test_a_job_whose_model_does_not_fit_waits_with_the_numbers_and_starts_once_it_fits(machine):
    job = wq.add(BIG, title="big")
    machine["available"] = 35.0
    assert _ran(BIG) == []
    got = wq.get(job["id"])
    assert got["state"] == wq.PENDING
    assert "needs 30.0 GiB" in got["note"] and "25.0 GiB is admissible" in got["note"] and "harness limit" in got["note"]
    machine["available"] = 200.0
    assert [j["state"] for j in _ran(BIG)] == [wq.DONE]


def test_the_ledger_counts_what_live_leases_were_admitted_to_load(machine):
    item_lease.take(ms.connect(), resources.CPU, "a grader that loaded a model", mem_gb=35.0)
    ok, why = admission.admit(admission.need({"argv": BIG}), item_lease.live(ms.connect()))
    assert not ok and "35.0 GiB leased" in why
    assert admission.admit(admission.need({"argv": SMALL}), item_lease.live(ms.connect()))[0]


def test_a_resident_model_is_admitted_whatever_its_size(machine):
    machine["available"] = 12.0
    machine["resident"] = ["Big-30B"]
    ok, why = admission.admit(admission.need({"argv": BIG}), [])
    assert ok and "resident" in why


def test_an_unpriced_job_is_admitted_and_says_so(machine):
    ok, why = admission.admit(admission.need({"argv": [sys.executable, "-c", "pass"]}), [])
    assert ok and "unchecked" in why
    ok, why = admission.admit(admission.need({"argv": [*BIG[:-1], "llamacpp:Unknown-7B"]}), [])
    assert ok and "Unknown-7B has no size" in why


def test_memory_pressure_admits_nothing(machine):
    machine["level"] = pressure.WARN
    ok, why = admission.admit(admission.need({"argv": SMALL}), [])
    assert not ok and "pressure" in why


def test_an_admitted_job_records_what_it_was_admitted_to_load_on_its_lease(machine):
    seen = {}

    def popen(argv, **kw):
        seen["leases"] = item_lease.live(ms.connect())
        return types.SimpleNamespace(returncode=0)

    wq.add(SMALL, title="small")
    assert wq.run_pending(popen=popen)[0]["state"] == wq.DONE
    assert [round(x["mem_gb"], 1) for x in seen["leases"]] == [4.0]


def test_a_refused_gpu_job_does_not_hold_up_a_network_job(machine):
    machine["available"] = 35.0
    big = wq.add(BIG, title="big")
    net = wq.add(["uv", "run", "soh", "fetch", "--run"], title="fetch")
    ran = wq.run_pending(popen=lambda *a, **k: types.SimpleNamespace(returncode=0))
    assert [j["id"] for j in ran] == [net["id"]] and wq.get(big["id"])["state"] == wq.PENDING
