"""Each wait has a deadline, an owner told when it ends and a named end state: serving yields, serving cuts, reverify jobs. #1765."""
import os
import types

import pytest

from evals import run as R
from evals import watch
from harness import completion, cuts, monitor, reverify, serve_lease
from harness import job_state as js
from harness import memory_store as ms
from harness import runs
from harness import workqueue as wq
from tests.test_pause_813 import clock  # noqa: F401
from tests.test_reverify import NOW, _latest, check, conn, on, powered, queued, upgraded  # noqa: F401
from tests.test_serving_lease_1556 import polls  # noqa: F401

WT = "a-wait-with-no-deadline-owner-or-end-state"
EVAL = ["uv", "run", "python", "-m", "evals.run", "--modality", "pii", "--candidates", "pii-regex"]


def _cuts(knob: str) -> list[dict]:
    conn = ms.connect()
    try:
        cuts.flush(conn)
        return [dict(r) for r in conn.execute("SELECT knob, what, dropped FROM limit_cuts WHERE knob = ?", (knob,))]
    finally:
        conn.close()


@pytest.fixture
def alerts(monkeypatch):
    got = []
    monkeypatch.setattr(monitor, "alert", lambda kind, env, **k: got.append((kind, env["MONIT_DESCRIPTION"])))
    return got


@pytest.mark.gauntlet(WT, site="evals/watch.py:Watch._serve")
def test_a_yield_to_serving_that_never_ends_pauses_the_run_for_serving_at_the_knob(monkeypatch, clock, polls):
    monkeypatch.setattr(serve_lease, "YIELD_WAIT_S", 5.0)
    eye = watch.Watch(yielder=serve_lease.Yielder(""), planned={"k": 1.0}, left={"k": 4})
    serve_lease.Lease("code", "a code delegation")
    start = clock.now

    def stuck(n):
        if n > 200:
            pytest.fail(f"still yielded after {clock.now - start:.0f}s, past serve_yield_wait")
    polls["on"] = stuck
    with pytest.raises(watch.Deferred) as got:
        eye.before("k", "c1")
    assert got.value.reason == serve_lease.SERVING_PAUSE
    assert serve_lease.YIELD_WAIT_S <= clock.now - start < serve_lease.YIELD_WAIT_S + serve_lease.POLL_S
    assert "past serve_yield_wait" in got.value.why and "4 case(s) left" in got.value.why
    assert eye.yields == 1 and eye.yielding_since is None
    assert [(c["knob"], c["dropped"]) for c in _cuts("serve_yield_wait")] == [("serve_yield_wait", 4)]


def test_a_yield_shorter_than_the_knob_resumes_the_run(monkeypatch, clock, polls):
    monkeypatch.setattr(serve_lease, "YIELD_WAIT_S", 5.0)
    eye = watch.Watch(yielder=serve_lease.Yielder(""))
    lease = serve_lease.Lease("code", "a code delegation")
    polls["on"] = lambda n: n == 4 and lease.drop()
    assert eye.before("k", "c1") is True
    assert _cuts("serve_yield_wait") == []


def _always_cut(eye: watch.Watch, case: str):
    """One try of `case` under _attempt while a delegation asks every try to cut it."""
    serve_lease.ask_cut([{"state": serve_lease.CASE, "pid": os.getpid(), "case": case, "candidate": "k"}],
                        "a code delegation")

    def run_case():
        when = completion._CUT_WHEN.get()
        if when is not None and when():
            raise completion.ServingCut("cut to serve")
        return types.SimpleNamespace(metrics={}, warnings=[])
    return R._attempt(eye, "k", case, run_case)


def test_a_case_cut_on_every_try_pauses_the_run_for_serving_at_the_knob(monkeypatch):
    eye = watch.Watch(yielder=serve_lease.Yielder(""), left={"k": 2})
    tries = 0
    with pytest.raises(watch.Deferred) as got:
        while tries < 2 * serve_lease.CUT_TRIES:
            tries += 1
            assert _always_cut(eye, "c1") is None
    assert tries == serve_lease.CUT_TRIES
    assert got.value.reason == serve_lease.SERVING_PAUSE and f"cut {serve_lease.CUT_TRIES} times" in got.value.why
    assert [c["dropped"] for c in _cuts("serving_cut_tries")] == [2]


def test_cuts_of_different_cases_do_not_add_up_to_the_knob():
    eye = watch.Watch(yielder=serve_lease.Yielder(""))
    for i in range(serve_lease.CUT_TRIES + 1):
        assert _always_cut(eye, f"c{i}") is None
    assert _cuts("serving_cut_tries") == []


def test_a_run_paused_for_serving_waits_again_behind_the_gates_where_it_stopped(tmp_path, monkeypatch):
    where = tmp_path / "runs" / "x"
    where.mkdir(parents=True)
    monkeypatch.setattr(runs, "for_job", lambda c, i: {"path": str(where)})
    job = wq.add(EVAL, title="batch")

    def popen(argv, cwd=None, stdout=None, stderr=None, env=None):
        watch.ask_pause(where, serve_lease.SERVING_PAUSE)
        return types.SimpleNamespace(returncode=watch.PAUSED)
    wq.run_one(wq.get(job["id"]), popen=popen)
    got = wq.get(job["id"])
    assert (got["state"], got["reason"]) == (wq.PENDING, js.CONTENTION_PAUSE)
    assert got["argv"] == [*EVAL, "--out", str(where), "--resume"]


def test_a_reverify_job_pending_past_the_knob_is_cancelled_and_settled_unrun_with_one_alert(upgraded, alerts):
    conn = upgraded
    check(conn)
    [job] = queued(conn)
    conn.execute("UPDATE jobs SET note = ? WHERE id = ?", ("waits for memory: needs 46.0 GiB", int(job["id"])))
    conn.commit()
    assert check(conn, now=NOW + reverify.PENDING_EXPIRY_S - 1)["settled"] == []
    assert _latest(conn)["outcome"] == "" and alerts == []
    dry = check(conn, now=NOW + reverify.PENDING_EXPIRY_S, dry_run=True)["settled"]
    assert [s["outcome"] for s in dry] == [reverify.UNRUN] and wq.get(job["id"])["state"] == wq.PENDING
    settled = check(conn, now=NOW + reverify.PENDING_EXPIRY_S)
    assert [s["outcome"] for s in settled["settled"]] == [reverify.UNRUN] and settled["queued"] == []
    rv = _latest(conn)
    assert rv["outcome"] == reverify.UNRUN and "waits for memory: needs 46.0 GiB" in rv["detail"]
    got = wq.get(job["id"])
    assert (got["state"], got["reason"]) == (wq.CANCELLED, js.EXPIRED)
    assert len(alerts) == 1 and f"job {job['id']}" in alerts[0][1] and "waits for memory" in alerts[0][1]
    assert [c["knob"] for c in _cuts("reverify_pending_expiry")] == ["reverify_pending_expiry"]
    again = check(conn, now=NOW + reverify.PENDING_EXPIRY_S + 3600)
    assert again["settled"] == [] and again["queued"] == [] and len(alerts) == 1


def test_a_reverify_job_that_started_is_never_expired_pending(upgraded, alerts):
    conn = upgraded
    check(conn)
    [job] = queued(conn)
    conn.execute("UPDATE jobs SET state = ?, started_at = ? WHERE id = ?", (wq.RUNNING, NOW + 60, int(job["id"])))
    conn.commit()
    assert check(conn, now=NOW + 2 * reverify.PENDING_EXPIRY_S, dry_run=True)["settled"] == []
    assert check(conn, now=NOW + 2 * reverify.PENDING_EXPIRY_S)["settled"] == [] and alerts == []
    assert _latest(conn)["outcome"] == ""


def test_an_expired_pending_rerun_is_not_queued_again_for_new_code_before_its_days(upgraded, alerts, monkeypatch):
    conn = upgraded
    check(conn)
    check(conn, now=NOW + reverify.PENDING_EXPIRY_S)
    monkeypatch.setattr(reverify, "_committed_at", lambda: NOW + reverify.PENDING_EXPIRY_S + 60)
    assert check(conn, now=NOW + reverify.PENDING_EXPIRY_S + 3600)["queued"] == []
