"""A gpu item held back only by the interactive server's pinned set runs in a window that releases it; never-fits counts the pins as releasable, and a re-run that still never fits is not queued again. #2100."""
import contextlib
import types

import pytest

from harness import admission, containers, interactive, memory, monitor, pressure, reverify, screen_window
from harness import job_state as js
from harness import workqueue as wq
from tests.test_reverify import NOW, check, conn, on, powered, queued, upgraded  # noqa: F401

MUSIC = ["uv", "run", "python", "-m", "evals.run", "--modality", "music", "--candidates", "acestep:acestep-v15-turbo",
         "--repeat", "1", "--split", "all"]
REAL_STANDING = memory.standing_gb
SMALL = ["uv", "run", "python", "-m", "evals.run", "--modality", "code", "--candidates", "llamacpp:Small-4B"]


@pytest.fixture
def studio(monkeypatch):
    """The live Studio on 2026-11-20: job 1798 needed 46.0 GiB, the measured peak of 20 stored rows there."""
    monkeypatch.setattr(admission, "admit", admission.admit.real)
    monkeypatch.setattr(memory, "standing_gb", REAL_STANDING)
    state = {"pinned": 32.8, "gb": {"acestep:acestep-v15-turbo": 46.0, "llamacpp:Small-4B": 4.0}, "opened": []}
    monkeypatch.setattr(memory, "available_gb", lambda: 200.0)
    monkeypatch.setattr(memory, "ceiling_gb", lambda: 77.76)
    monkeypatch.setattr(memory, "measured_reserve_gb", lambda conn=None: 18.0)
    monkeypatch.setattr(memory, "pinned_gb", lambda: state["pinned"])
    monkeypatch.setattr(interactive, "reserved_bytes", lambda *a, **k: int(state["pinned"] * 1024 ** 3))
    monkeypatch.setattr(containers, "vm_gb", lambda *a, **k: 3.8)
    monkeypatch.setattr(pressure, "sample", lambda: pressure.Pressure(level=pressure.NORMAL))
    monkeypatch.setattr(admission, "spec_gb", lambda spec: state["gb"].get(spec, state.get("default")))
    monkeypatch.setattr(admission, "_resident", lambda: [])

    @contextlib.contextmanager
    def opened(hold_s, why, **kw):
        state["opened"].append((hold_s, why))
        if state.get("refuse"):
            raise screen_window.Refused(state["refuse"])
        state["pinned"] = 0.0
        try:
            yield ["Ornith"]
        finally:
            state["pinned"] = 32.8
    monkeypatch.setattr(screen_window, "opened", opened)
    return state


@pytest.fixture
def alerts(monkeypatch):
    got = []
    monkeypatch.setattr(monitor, "alert", lambda kind, env, **k: got.append((kind, env["MONIT_DESCRIPTION"])))
    return got


def _ran():
    return wq.run_pending(popen=lambda *a, **k: types.SimpleNamespace(returncode=0))


def test_never_counts_the_pinned_set_as_released_so_the_music_need_is_not_refused_for_good(studio):
    assert memory.standing_gb() == pytest.approx(23.16)
    assert admission.never(admission.Need(46.0, priced=[("acestep:acestep-v15-turbo", 46.0)])) == ""


def test_a_need_over_the_ceiling_with_the_pins_released_is_still_never_and_says_what_would_admit_it(studio):
    why = admission.never(admission.Need(56.0, priced=[("x", 56.0)]))
    assert why.startswith("needs 56.0 GiB (x 56.0) but at most 56.0 GiB is ever admissible")
    assert "3.8 GiB given to the Docker VM" in why and "pinned models released" in why
    assert "another node" in why and "smaller quant" in why and "Docker VM stopped" in why
    assert "Docker VM stopped" not in admission.never(admission.Need(60.0, priced=[("x", 60.0)]))
    assert admission.never(admission.Need(55.9)) == ""


def test_the_music_reverify_runs_in_a_window_that_releases_the_pinned_set(studio, alerts):
    job = wq.add(MUSIC, title="reverify music: acestep:acestep-v15-turbo")
    assert [j["state"] for j in _ran()] == [wq.DONE]
    assert studio["opened"] == [(wq.ITEM_S, f"job {wq.label(job['id'])} (reverify music: acestep:acestep-v15-turbo)")]
    assert studio["pinned"] == 32.8 and alerts == []


def test_a_job_that_fits_beside_the_pins_opens_no_window(studio, alerts):
    wq.add(SMALL, title="small")
    assert [j["state"] for j in _ran()] == [wq.DONE]
    assert studio["opened"] == [] and alerts == []


def test_a_machine_with_nothing_pinned_opens_no_window_and_the_job_waits_for_memory(studio, alerts, monkeypatch):
    monkeypatch.setattr(interactive, "reserved_bytes", lambda *a, **k: 0)
    monkeypatch.setattr(memory, "available_gb", lambda: 40.0)
    job = wq.add(MUSIC, title="reverify music")
    assert _ran() == [] and studio["opened"] == []
    assert wq.get(job["id"])["note"].startswith("waits for memory: needs 46.0 GiB")


def test_a_window_that_will_not_open_leaves_the_job_pending_and_deferred_not_failed(studio, alerts):
    studio["refuse"] = "nothing is pinned here to release"
    job = wq.add(MUSIC, title="reverify music")
    assert _ran() == [] and _ran() == []
    got = wq.get(job["id"])
    assert got["state"] == wq.PENDING and got["note"] == "waits for a window: nothing is pinned here to release"
    assert got["not_before"] and len(studio["opened"]) == 1 and alerts == []


def test_a_reverify_that_still_never_fits_is_not_queued_again_until_it_would(upgraded, studio, alerts):
    c = upgraded
    check(c)
    [job] = queued(c)
    studio["default"] = 70.0
    wq._never_fits(c, job, admission.never(admission.Need(70.0, priced=[("q3-4b", 70.0)])))
    assert [s["outcome"] for s in check(c, now=NOW + 60)["settled"]] == [reverify.UNRUN]
    later = NOW + 60 * 86400.0
    assert check(c, now=later)["queued"] == []
    studio["default"] = 20.0
    assert len(check(c, now=later + 60)["queued"]) == 1
