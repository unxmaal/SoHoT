"""The harness p-s limits record a limit_cuts row when they bind, and none when they do not (#1087)."""
from __future__ import annotations

import json
import subprocess

import httpx
import pytest

from harness import cuts, serving
from tests.test_resume_813 import Eval, _measure, _rows, world  # noqa: F401
from tests.test_slot_probe_1127 import fake  # noqa: F401

LLAMACPP_BUILD = serving.llamacpp_build


def _spooled() -> list[tuple]:
    path = cuts._spool_path()
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    return [(r["knob"], r["kept"], r["dropped"]) for r in map(json.loads, lines)]


def _knobs() -> list[str]:
    return [k for k, _, _ in _spooled()]


def _timeout(*a, **k):
    raise subprocess.TimeoutExpired(a[0] if a else "cmd", 1)


def test_a_papers_gap_past_max_days_is_a_cut_and_a_short_one_is_not(monkeypatch):
    from harness import papers
    monkeypatch.setattr(papers, "MAX_DAYS", 3)
    now = 30 * 86400.0
    assert len(papers.due_dates(now - 3 * 86400, now)) == 2
    assert _spooled() == []
    assert len(papers.due_dates(now - 10 * 86400, now)) == 3
    assert _spooled() == [("harness/papers.py:MAX_DAYS", 3, 6)]


def test_a_timed_out_deploy_lookup_is_one_cut_even_when_the_cut_asks_again(monkeypatch):
    from harness import paths
    calls = []
    monkeypatch.setattr(paths.sys, "platform", "darwin")
    monkeypatch.setattr(paths.subprocess, "run", lambda *a, **k: calls.append(a) or _timeout(*a))
    monkeypatch.setattr(paths, "is_live", lambda p: True)
    assert paths.deploy_checkout() is None
    assert len(calls) == 1
    assert _knobs() == ["harness/paths.py:deploy_checkout->subprocess.run(timeout)"]


def test_pressure_reads_that_time_out_are_cuts_and_answers_are_not(monkeypatch):
    from harness import pressure
    monkeypatch.setattr(pressure.subprocess, "run",
                        lambda *a, **k: subprocess.CompletedProcess(a[0], 0, "42\n", ""))
    assert pressure._sysctl("x") == "42" and pressure._vm_stat() == "42\n"
    assert _spooled() == []
    monkeypatch.setattr(pressure.subprocess, "run", _timeout)
    assert pressure._sysctl("x") == "" and pressure._vm_stat() == ""
    assert _knobs() == ["harness/pressure.py:_sysctl->subprocess.run(timeout)",
                        "harness/pressure.py:_vm_stat->subprocess.run(timeout)"]


def test_a_holdout_search_past_max_cases_is_a_cut(monkeypatch):
    from harness import power
    monkeypatch.setattr(power, "MAX_CASES", 12)
    assert power.cases_needed([0.5] * 10, 0.5, rho=0.0, alpha=0.05) is not None
    assert _spooled() == []
    assert power.cases_needed([0.5] * 10, 0.01, rho=1.0, alpha=0.05) is None
    assert _knobs() == ["harness/power.py:MAX_CASES"]


def test_a_plan_capped_at_its_repeat_cap_is_a_cut_and_an_enough_plan_is_not(monkeypatch):
    from harness import power
    monkeypatch.setattr(power, "PLATEAU", 2.0)
    assert power.plan([0.5] * 40, 0.5, cap=4, rho=0.0).enough
    assert "harness/power.py:CAP" not in _knobs()
    got = power.plan([0.5] * 4, 0.02, cap=4, rho=0.0)
    assert got.capped and not got.enough
    assert _knobs().count("harness/power.py:CAP") == 1


def test_a_repeat_over_its_time_budget_is_a_cut_and_one_within_it_is_not():
    from harness import power
    chosen = power.plan([0.5] * 20, 0.3, repeat=3, rho=0.0)
    power.within_budget(chosen, [0.5] * 20, cases_run=20, median_s=1.0, budget_s=10_000.0)
    assert _spooled() == []
    got = power.within_budget(chosen, [0.5] * 20, cases_run=20, median_s=1.0, budget_s=100.0)
    assert got.repeat == 2
    assert _spooled() == [("harness/power.py:BUDGET_MIN", 2, 1)]


def test_seconds_per_call_capped_at_the_whole_budget_estimate_is_a_decode_rate_cut(monkeypatch):
    from harness import power
    monkeypatch.setattr(power, "_served_rows", lambda *a, **k: ({}, [{"receipt": "{}", "seconds": 1.0}]))
    monkeypatch.setattr(power, "reply_settings", lambda receipt, lane: (100, ()))
    monkeypatch.setattr(power, "draws_from", lambda got, key, lane="": ({}, 50.0))
    monkeypatch.setattr(power, "decode_tok_s", lambda hw_model=None: 10.0)
    monkeypatch.setattr(power, "estimated_seconds", lambda lane, tok_s=None: 80.0)
    assert power.served_bound(None, "code", "x", (100,), None)[0] == 50.0
    assert _spooled() == []
    monkeypatch.setattr(power, "estimated_seconds", lambda lane, tok_s=None: 20.0)
    assert power.served_bound(None, "code", "x", (100,), None)[0] == 20.0
    assert _spooled() == [("decode_tok_s", None, None)]


@pytest.fixture
def conn(tmp_path, monkeypatch):
    from harness import memory_store as ms
    from tests.test_min_effect_1320 import FAKE_MACHINE
    monkeypatch.setattr(ms.machines, "_THIS_MACHINE", FAKE_MACHINE)
    c = ms.connect(tmp_path / "d.db")
    yield c
    c.close()


def _cut_rows(conn) -> list[tuple]:
    cuts.flush(conn)
    return [(r["knob"], r["kept"], r["dropped"]) for r in conn.execute("SELECT knob, kept, dropped FROM limit_cuts")]


def test_a_null_declined_only_because_the_lane_noise_is_above_the_floor_records_the_lane_effect(conn, monkeypatch):
    from harness import adopt, power
    from tests.test_min_effect_1320 import _null_on
    monkeypatch.setattr(power, "EFFECT", {"decide": 0.2})
    inside = _null_on("decide", 0.15)
    assert inside.failure_class == "" and inside.evidence == {"lane_effect": {"noise": 0.2, "seen": 0.15}}
    assert not _null_on("decide", 0.08).evidence
    adopt.record(conn, adopt.Verdict("decide", "inc", "q3-8b", False, "no gain"))
    assert _cut_rows(conn) == []
    adopt.record(conn, adopt.Verdict("decide", "inc", "q3-30b", False, inside.why, evidence=inside.evidence))
    assert _cut_rows(conn) == [("adopt_effect", 0, 1)]


def test_decide_carries_the_lane_effect_evidence_from_its_null(monkeypatch):
    from harness import adopt
    from tests.test_min_effect_1320 import _plan
    null = adopt.Verdict("decide", "inc", "ch", False, "null", evidence={"lane_effect": {"seen": 0.15}})
    monkeypatch.setattr(adopt, "_null", lambda *a, **k: null)
    monkeypatch.setattr(adopt, "_lane_too_small", lambda *a, **k: None)
    monkeypatch.setattr(adopt, "_worse", lambda *a, **k: "")
    monkeypatch.setattr(adopt, "_gates", lambda lane, i, c, *a, **k: adopt.Verdict(lane, i, c, False, "null"))
    rows = [{"candidate": "inc", "case_id": "a", "passed": True}, {"candidate": "ch", "case_id": "a", "passed": True}]
    got = adopt.decide("decide", {"candidate": "inc"}, {"candidate": "ch"}, rows, plan=_plan(0.2, 0.15))
    assert got.evidence["lane_effect"] == {"seen": 0.15}


def test_a_paired_run_killed_at_its_deadline_is_a_deadline_grace_cut(monkeypatch, world):  # noqa: F811
    from harness.commands import measure as measure_cmd
    monkeypatch.setattr(measure_cmd, "_launch", Eval(rows=_rows(5)))
    _measure()
    assert "deadline_grace" not in _knobs()
    monkeypatch.setattr(measure_cmd, "_launch", Eval(rows=_rows(5), timed_out=True))
    _measure()
    assert _knobs().count("deadline_grace") == 1


def test_an_offline_probe_client_names_its_own_budget_site(tmp_path):
    from harness import github, probes
    with pytest.raises(github.BudgetError):
        probes.offline(tmp_path).get("repos/a/b")
    assert _knobs() == ["harness/probes.py:offline->github.Client(budget)"]
    with pytest.raises(github.BudgetError):
        github.Client(cache=tmp_path, budget=0).get("repos/a/b")
    assert _knobs()[-1] == "harness/github.py:Client.budget"


def _ramp(free):
    from types import SimpleNamespace
    from harness import ramp
    seen = iter(free)
    return ramp.run(step_gb=1.0, settle_s=0, floor_pct=10, cap_gb=3.0, allocate=lambda gb: None,
                    release=lambda: None, sleep=lambda s: None, available=lambda: 10.0, beat=lambda: None,
                    sample=lambda: SimpleNamespace(free_pct=next(seen), level=1, swapouts=0, wired_gb=0.0))


def test_a_ramp_stopped_at_the_free_floor_is_a_cut_and_one_stopped_at_its_cap_is_not():
    assert _ramp([50, 40, 30, 20])["stopped"] == "cap"
    assert _spooled() == []
    assert _ramp([50, 40, 5])["stopped"] == "free below floor"
    assert _knobs() == ["harness/ramp.py:run(floor_pct)"]


def test_a_repo_gate_short_of_valid_tasks_is_a_cut(monkeypatch, tmp_path):
    from evals import repo
    from harness import repo_gate
    sandbox = tmp_path / "sandbox-exec"
    sandbox.write_text("", encoding="utf-8")
    monkeypatch.setattr(repo_gate.sys, "platform", "darwin")
    monkeypatch.setattr(repo, "SANDBOX_EXEC", str(sandbox))
    monkeypatch.setattr(repo_gate, "valid_tasks", lambda machine=None: set(range(repo_gate.MIN_TASKS)))
    assert repo_gate.active()
    assert _spooled() == []
    monkeypatch.setattr(repo_gate, "valid_tasks", lambda machine=None: {1, 2})
    assert not repo_gate.active()
    assert _spooled() == [("repo_gate_min_tasks", 2, None)]


def test_a_full_judgeable_page_is_a_cut(monkeypatch):
    from harness import memory_store as ms, report
    monkeypatch.setattr(ms, "judgeable", lambda conn, limit: [{}] * 3)
    assert len(report.ms_judgeable(None)) == 3
    assert _spooled() == []
    monkeypatch.setattr(ms, "judgeable", lambda conn, limit: [{}] * limit)
    report.ms_judgeable(None)
    assert _spooled() == [("harness/report.py:ms_judgeable->ms.judgeable(limit)", 1_000_000, None)]


def test_incumbent_cells_short_of_the_draws_reuse_needs_are_one_cut(monkeypatch):
    from harness import reuse
    stored = {("a", 1): [(1.0, 7, "a", "inc", 1.0, None, "")] * 2, ("b", 1): [(1.0, 7, "b", "inc", 1.0, None, "")],
              ("c", 1): [(1.0, 7, "c", "inc", 1.0, None, "")]}
    monkeypatch.setattr(reuse, "draws", lambda *a, **k: stored)
    assert len(reuse.plan(None, "code", "d", ["a", "b", "c", "e"], min_draws=1)["cells"]) == 3
    assert _spooled() == []
    assert len(reuse.plan(None, "code", "d", ["a", "b", "c", "e"], min_draws=2)["cells"]) == 1
    assert _spooled() == [("incumbent_reuse_min_draws", 1, 2)]


def test_a_rubric_reply_that_times_out_is_a_cut():
    from harness import rubric_eval
    r = rubric_eval.Rubric("r", 1, "judge", {"type": "object", "properties": {"x": {"enum": ["a"]}}}, "x")

    def slow(*a, **k):
        raise httpx.ReadTimeout("slow")

    def refused(*a, **k):
        raise httpx.ConnectError("no")
    assert not rubric_eval.evaluate(r, "t", "m", "http://127.0.0.1:1", post=refused).ok
    assert _spooled() == []
    assert not rubric_eval.evaluate(r, "t", "m", "http://127.0.0.1:1", post=slow).ok
    assert _knobs() == ["harness/rubric_eval.py:evaluate(timeout)"]


def test_a_small_weight_listing_read_as_loose_by_the_floor_is_a_cut():
    from harness import screen
    big = [{"rfilename": "model.safetensors", "size": screen.ADAPTER_FLOOR_BYTES * 2}]
    small = [{"rfilename": "model.safetensors", "size": 1024}]
    assert screen.listing_kind(big) == screen.BULK
    assert screen.listing_kind(small + [{"rfilename": "config.json", "size": 10}]) == screen.LOOSE
    assert _spooled() == []
    assert screen.listing_kind(small) == screen.LOOSE
    assert _knobs() == ["adapter_floor"]


def test_a_transcript_over_the_screen_wer_is_a_cut():
    from harness import screen
    heard = {"k": {"metrics": {"wer": 0.3}, "metric_n": {"wer": 4}}}
    garbled = {"k": {"metrics": {"wer": 0.9}, "metric_n": {"wer": 4}}}
    assert screen.plausible_wer(heard, "stt") == 0.3
    assert _spooled() == []
    assert screen.plausible_wer(garbled, "stt") is None
    assert _knobs() == ["stt_screen_max_wer"]


def test_mlx_parallel_names_the_knob_that_bound_it(monkeypatch):
    from harness import memory, serving
    gib = 1024 ** 3
    monkeypatch.setattr(memory, "mlx_kv_bytes_per_token", lambda repo: gib // serving.MLX_REQUEST_CTX)
    monkeypatch.setattr(memory, "cache_path", lambda repo: "x")
    monkeypatch.setattr(memory, "size_gb", lambda path: 0.0)
    monkeypatch.setattr(memory, "measured_reserve_gb", lambda: 0.0)
    monkeypatch.setattr(serving, "_router_gb", lambda: 0.0)
    for room, want in ((serving.MLX_MAX_PARALLEL, []), (1000.0, ["mlx_max_parallel"]),
                       (3.0, ["mlx_max_parallel", "mlx_request_ctx"])):
        monkeypatch.setattr(memory, "ceiling_gb", lambda r=room: r)
        serving.mlx_parallel("m")
        assert _knobs() == want
    assert serving.mlx_parallel("m") == 3


def test_a_llama_server_version_that_times_out_is_a_cut(monkeypatch):
    monkeypatch.setattr(serving, "llamacpp_build", LLAMACPP_BUILD)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a[0], 0, "build 42", ""))
    assert serving.llamacpp_build("x") == "42"
    assert _spooled() == []
    monkeypatch.setattr(subprocess, "run", _timeout)
    assert serving.llamacpp_build("x") == ""
    assert _knobs() == ["harness/serving.py:llamacpp_build->subprocess.run(timeout)"]


def test_slot_probe_cuts_name_the_wait_that_ended_it(fake):  # noqa: F811
    from harness import slot_probe
    f = fake(frees=True)
    assert slot_probe.probe(f.url, f.url, "tiny", max_tokens=2000, settle_s=3.0)[0]
    assert _spooled() == []
    g = fake(frees=False)
    assert not slot_probe.probe(g.url, g.url, "tiny", max_tokens=2000, settle_s=0.5)[0]
    assert _knobs() == ["slot_probe_settle"]
    h = fake(frees=True, invisible=True)
    assert not slot_probe.probe(h.url, h.url, "tiny", max_tokens=2000, settle_s=1.0, busy_wait_s=0.5)[0]
    assert _knobs() == ["slot_probe_settle", "slot_probe_busy_wait", "slot_probe_max_tokens"]


def _check(beat, now=100_000.0, start=90_000.0):
    from harness import sweep_check
    unit = {"loaded": True, "state": "running", "pid": 1, "rc": None}
    return sweep_check.verdict(unit, beat, now, start, alive=lambda pid: True)["verdict"]


def test_sweep_check_verdicts_cut_by_a_threshold_are_cuts():
    from harness import heartbeat, sweep_check
    assert _check({"started": 91_000.0, "updated": 99_000.0, "pid": 1}) == sweep_check.RUNNING
    assert _check({"started": 50_000.0, "finished": 99_000.0, "state": heartbeat.FINISHED, "rc": 0,
                   "step": 3, "total": 3}) == sweep_check.STALLED
    assert _knobs() == ["sweep_check_start_slack"]
    assert _check({"started": 91_000.0, "finished": 91_100.0, "state": heartbeat.FINISHED, "rc": 0,
                   "step": 3, "total": 3}) == sweep_check.EARLY
    assert _knobs()[-1] == "sweep_check_early"
    assert _check({"started": 91_000.0, "updated": 91_000.0, "pid": 1}, now=99_000.0) == sweep_check.STALLED
    assert _knobs()[-1] == "sweep_check_stall"
    assert _check({"started": 91_000.0, "updated": 91_000.0, "pid": 1, "deadline_s": 5000.0},
                  now=99_000.0) == sweep_check.STALLED
    assert _knobs().count("sweep_check_stall") == 1


def test_thin_lane_evidence_is_a_cut_and_none_is_not():
    from harness import sweeps
    assert sweeps.lane_evidence({"cuts": 0, "where": []}, "m") is None
    assert sweeps.lane_evidence({"cuts": 5, "converted": 1, "where": []}, "m") is None
    assert _spooled() == []
    assert sweeps.lane_evidence({"cuts": 5, "where": []}, "m") is None
    assert _spooled() == [("lane_min_cuts", 5, None)]


class _Rows:
    def __init__(self, rows):
        self.rows = rows

    def execute(self, sql, params=()):
        if sql.lstrip().upper().startswith("INSERT"):
            raise RuntimeError("read only")
        return self

    def fetchall(self):
        return self.rows


def test_a_newer_small_run_passed_over_for_a_full_one_is_a_cut(monkeypatch):
    from harness import reverify, sweeps
    monkeypatch.setattr(reverify, "_flagged_runs", lambda conn: set())
    monkeypatch.setattr(sweeps, "_working", lambda *a: False)
    monkeypatch.setattr(sweeps, "_bound", lambda rows, lane: {})

    def run(rid, n, cid):
        return [{"run_id": rid, "candidate_id": cid, "candidate": "m", "spec": "m", "passed": 1, "metrics": "{}",
                 "failure_class": ""}] * n
    full = sweeps.FALLBACK_MIN_CASES
    got = sweeps.passing(_Rows(run(9, full, 1) + run(8, 2, 1)), "code", None)
    assert got[1]["run_id"] == 9 and _spooled() == []
    got = sweeps.passing(_Rows(run(9, 2, 1) + run(8, full, 1) + run(7, 2, 2)), "code", None)
    assert got[1]["run_id"] == 8 and got[2]["run_id"] == 7
    assert _spooled() == [("fallback_min_cases", None, 1)]
