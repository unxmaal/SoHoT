"""A pending gpu job whose models can never be admitted here is refused by name with one alert; one that may fit later waits. #1926."""
import types

import pytest

from harness import admission, containers, memory, monitor, pressure, reverify
from harness import job_state as js
from harness import workqueue as wq
from tests.test_reverify import NOW, _latest, check, conn, on, powered, queued, upgraded  # noqa: F401

HUGE = ["uv", "run", "python", "-m", "evals.run", "--modality", "music", "--candidates", "llamacpp:Huge-46B"]
BIG = ["uv", "run", "python", "-m", "evals.run", "--modality", "code", "--candidates", "llamacpp:Big-20B"]
SMALL = ["uv", "run", "python", "-m", "evals.run", "--modality", "code", "--candidates", "llamacpp:Small-4B"]
SIZES = {"llamacpp:Huge-46B": 46.0, "llamacpp:Big-20B": 20.0, "llamacpp:Small-4B": 4.0}


@pytest.fixture
def machine(monkeypatch):
    """The live Studio's admission numbers when job 1624 waited, set below."""
    monkeypatch.setattr(admission, "admit", admission.admit.real)
    state = {"available": 200.0}
    monkeypatch.setattr(memory, "available_gb", lambda: state["available"])
    monkeypatch.setattr(memory, "ceiling_gb", lambda: 77.8)
    monkeypatch.setattr(memory, "measured_reserve_gb", lambda conn=None: 18.0)
    monkeypatch.setattr(memory, "pinned_gb", lambda: 28.6)
    monkeypatch.setattr(containers, "vm_gb", lambda *a, **k: 8.0)
    monkeypatch.setattr(pressure, "sample", lambda: pressure.Pressure(level=pressure.NORMAL))
    monkeypatch.setattr(admission, "spec_gb", lambda spec: SIZES.get(spec))
    monkeypatch.setattr(admission, "_resident", lambda: [])
    return state


@pytest.fixture
def alerts(monkeypatch):
    got = []
    monkeypatch.setattr(monitor, "alert", lambda kind, env, **k: got.append((kind, env["MONIT_DESCRIPTION"])))
    return got


def _ran():
    return wq.run_pending(popen=lambda *a, **k: types.SimpleNamespace(returncode=0))


def test_a_job_that_can_never_fit_is_refused_by_name_with_one_alert_and_how_to_run_it(machine, alerts):
    job = wq.add(HUGE, title="reverify music: Huge-46B")
    small = wq.add(SMALL, title="small")
    assert [j["id"] for j in _ran()] == [small["id"]]
    got = wq.get(job["id"])
    assert (got["state"], got["reason"]) == (wq.FAILED, js.NEVER_FITS)
    assert not got["started"] and got["rc"] is None and got["finished"]
    note = got["note"]
    assert note.startswith("refused: needs 46.0 GiB (llamacpp:Huge-46B 46.0)")
    assert "at most 23.2 GiB is ever admissible" in note and "36.6 GiB held" in note and "18.0 GiB reserve" in note
    assert "another node" in note and "smaller quant" in note
    assert len(alerts) == 1 and f"job {wq.label(job['id'])}" in alerts[0][1] and "never started" in alerts[0][1]
    assert "at most 23.2 GiB" in alerts[0][1]
    assert _ran() == [] and len(alerts) == 1 and wq.get(job["id"])["state"] == wq.FAILED


def test_a_job_that_can_fit_later_keeps_waiting_and_starts_once_it_fits(machine, alerts):
    job = wq.add(BIG, title="big")
    machine["available"] = 30.0
    for _ in range(3):
        assert _ran() == []
    got = wq.get(job["id"])
    assert (got["state"], got["reason"]) == (wq.PENDING, js.ADDED)
    assert got["note"].startswith("waits for memory: needs 20.0 GiB") and "12.0 GiB is admissible" in got["note"]
    assert alerts == []
    machine["available"] = 200.0
    assert [j["state"] for j in _ran()] == [wq.DONE] and alerts == []


def test_never_is_silent_for_a_need_that_fits_the_ceiling_or_is_not_priced(machine, monkeypatch):
    assert admission.never(admission.Need(23.2)) == ""
    assert admission.never(admission.Need(23.3, priced=[("x", 23.3)])).startswith("needs 23.3 GiB (x 23.3)")
    assert admission.never(admission.Need(None)) == "" and admission.never(admission.Need(0.0)) == ""
    monkeypatch.setattr(memory, "ceiling_gb", lambda: 0.0)
    assert admission.never(admission.Need(500.0)) == ""


def test_a_reverify_job_refused_as_never_fitting_settles_unrun_naming_why_and_is_not_requeued_for_new_code(
        upgraded, alerts, monkeypatch):
    c = upgraded
    check(c)
    [job] = queued(c)
    wq._never_fits(c, job, "needs 46.0 GiB but at most 23.2 GiB is ever admissible here")
    assert len(alerts) == 1
    got = check(c, now=NOW + 60)
    assert [s["outcome"] for s in got["settled"]] == [reverify.UNRUN]
    assert "at most 23.2 GiB is ever admissible" in _latest(c)["detail"]
    monkeypatch.setattr(reverify, "_committed_at", lambda: NOW + 120)
    assert check(c, now=NOW + 3600)["queued"] == []
