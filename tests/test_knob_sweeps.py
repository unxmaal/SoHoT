"""A binding knob queues a sweep across its range and records the cheapest value tied with the best (#636)."""
import argparse
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from evals import environment
from evals import run as R
from evals.runners.base import BaseRunner
from harness import knobs, reverify, runs, sweeps, workqueue as wq
from harness import memory_store as ms

DAY = 86400.0
NOW = 1_800_000_000.0
ROOT = Path(__file__).resolve().parents[1]
M = {"fingerprint": "Mac17,15/macOS/arm64", "hw_model": "Mac17,15", "os": "macOS-27.0.1-arm64-arm-64bit",
     "arch": "arm64", "memory_gb": 96.0, "accelerator": "unified 96GB", "runtimes": "cpu,mlx",
     "ceiling_gb": 66.0, "versions": {}}
ENV = {"hw_model": M["hw_model"], "os": M["os"], "arch": "arm64"}
_SEQ = iter(range(1, 10_000))


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(ms, "this_machine", lambda: dict(M))
    c = ms.connect(tmp_path / "d.db")
    ms.remember_machine(c, dict(M))
    yield c
    c.close()


@pytest.fixture
def serving(monkeypatch):
    def serve(spec="q3-4b", lane="code"):
        monkeypatch.setattr(reverify, "served", lambda conn: {lane: {
            "lane": lane, "spec": spec, "candidate_id": None, "incumbent": "", "incumbent_id": None}})
    serve()
    return serve


def record(conn, lane, passed, total, *, at=NOW - DAY, job_id=None, limit="", seconds=1.0, spec="q3-4b"):
    rows = [{"candidate": spec, "case_id": f"c{i}", "passed": i < passed, "seconds": seconds,
             "failure_class": "" if i < passed else ("token_budget_exhausted" if limit else "content_failed"),
             "limit": "" if i < passed else limit} for i in range(total)]
    rid = runs.record(conn, f"runs/r{next(_SEQ)}-{lane}",
                      {"receipt": {"modality": lane}, "environment": ENV, "specs": {spec: spec},
                       "rows": rows}, at=at)
    if job_id is not None:
        conn.execute("UPDATE runs SET job_id = ? WHERE id = ?", (int(job_id), rid))
        conn.commit()
    return rid


def binding_budget(conn):
    record(conn, "code", 5, 10, limit="max_tokens.code>32768")


def queued(conn):
    return [j for j in wq.jobs(conn=conn) if j["requested_by"] == sweeps.REQUESTED_BY]


def test_a_binding_knob_on_a_served_lane_is_planned_across_its_range(conn, serving):
    binding_budget(conn)
    plan = sweeps.plan(conn, now=NOW)
    assert [(p["knob"], p["lane"], p["spec"]) for p in plan] == [("reply_budget", "code", "q3-4b")]
    argvs = plan[0]["argv"]
    assert [a[a.index("--max-tokens") + 1] for a in argvs.values()] == [
        str(v) for v in knobs.KNOBS["reply_budget"].values]
    assert all(a[a.index("--modality") + 1] == "code" and "q3-4b" in a for a in argvs.values())


def test_a_timeout_sweep_sets_the_knob_by_name(conn, serving):
    record(conn, "code", 5, 10, limit="timeout_s>180")
    plan = sweeps.plan(conn, now=NOW)
    argv = plan[0]["argv"][600.0]
    assert argv[argv.index("--knob") + 1] == "request_timeout=600"


def test_a_knob_no_eval_can_set_is_not_swept(conn, serving):
    for i in range(4):
        ms.record(conn, ms.Seen(name=f"org/big-{i}", source="t", url="", why="", relevance=0,
                                kind="candidate", registry=ms.HUGGINGFACE, lane="code", resolved=f"org/big-{i}"))
        ms.decide(conn, f"org/big-{i}", "declined", tier="inspect", reason="machine",
                  detail="too-big", until="ceiling_gb:>66", at=NOW - DAY)
    assert sweeps.plan(conn, now=NOW) == []


def test_a_knob_that_is_not_binding_is_not_swept(conn, serving):
    record(conn, "code", 99, 100, limit="max_tokens.code>32768")
    assert sweeps.plan(conn, now=NOW) == []


def test_check_queues_one_job_per_value_once(conn, serving):
    binding_budget(conn)
    got = sweeps.check(conn, now=NOW)
    assert len(got["queued"]) == 1
    assert len(queued(conn)) == len(knobs.KNOBS["reply_budget"].values)
    assert all(j["priority"] == sweeps.PRIORITY for j in queued(conn))
    again = sweeps.check(conn, now=NOW + 60)
    assert again["queued"] == [] and "already queued" in again["planned"][0]["skip"]
    assert len(queued(conn)) == len(knobs.KNOBS["reply_budget"].values)


def test_a_dry_run_queues_nothing(conn, serving):
    binding_budget(conn)
    got = sweeps.check(conn, now=NOW, dry_run=True)
    assert got["planned"] and not got["queued"] and queued(conn) == []


def _finish(conn, outcomes, state=wq.DONE):
    """outcomes: value -> (passed of 20, seconds per row), or None for a job that stored no run."""
    for job in queued(conn):
        wq._write({**job, "state": state, "rc": 0}, conn=conn)
    row = conn.execute("SELECT jobs FROM knob_sweeps ORDER BY id DESC").fetchone()
    for value, job_id in json.loads(row["jobs"]):
        got = outcomes.get(value)
        if got is not None:
            record(conn, "code", got[0], 20, at=NOW + 60, job_id=job_id, seconds=got[1])


def _settled(conn):
    return dict(conn.execute("SELECT * FROM knob_sweeps ORDER BY id DESC").fetchone())


def test_the_cheapest_value_tied_with_the_best_is_chosen_and_its_cost_recorded(conn, serving):
    binding_budget(conn)
    sweeps.check(conn, now=NOW)
    _finish(conn, {2000: (2, 0.5), 4000: (19, 1.0), 8000: (20, 2.0), 16384: (20, 4.0),
                   32768: (20, 8.0), 65536: (20, 16.0)})
    got = sweeps.check(conn, now=NOW + 120)
    row = _settled(conn)
    assert row["outcome"] == sweeps.CHOSEN
    assert json.loads(row["chosen"]) == 4000
    cost = json.loads(row["cost"])
    assert cost["4000"]["tied"] and not cost["2000"]["tied"]
    assert cost["8000"]["passed"] == 20 and cost["8000"]["seconds"] == 40.0
    assert "4000" in row["detail"] and "8000" in row["detail"]
    assert got["settled"][0]["chosen"] == 4000


def test_a_sweep_none_of_whose_jobs_stored_a_run_is_unrun(conn, serving):
    binding_budget(conn)
    sweeps.check(conn, now=NOW)
    _finish(conn, {}, state=wq.FAILED)
    sweeps.check(conn, now=NOW + 120)
    first = conn.execute("SELECT * FROM knob_sweeps ORDER BY id").fetchone()
    assert first["outcome"] == sweeps.UNRUN
    assert "retried after" in sweeps.check(conn, now=NOW + 240)["planned"][0]["skip"]
    assert len(sweeps.check(conn, now=NOW + 8 * DAY)["queued"]) == 1


def test_a_sweeps_own_runs_do_not_count_toward_binding(conn, serving):
    from harness import binding
    binding_budget(conn)
    sweeps.check(conn, now=NOW)
    _finish(conn, {v: (0, 1.0) for v in knobs.KNOBS["reply_budget"].values})
    got = next(r for r in binding.count(conn, now=NOW + 120) if r["knob"] == "reply_budget"
               and r["lane"] == "code")
    assert (got["hits"], got["of"]) == (5, 10)


def test_a_sweep_waits_while_any_of_its_jobs_is_pending(conn, serving):
    binding_budget(conn)
    sweeps.check(conn, now=NOW)
    assert sweeps.check(conn, now=NOW + 120)["settled"] == []
    assert _settled(conn)["outcome"] == ""


def test_a_settled_sweep_is_not_run_again_until_the_model_or_machine_changes(conn, serving):
    binding_budget(conn)
    sweeps.check(conn, now=NOW)
    _finish(conn, {v: (20, 1.0) for v in knobs.KNOBS["reply_budget"].values})
    sweeps.check(conn, now=NOW + 120)
    before = len(queued(conn))
    again = sweeps.check(conn, now=NOW + 240)
    assert again["queued"] == [] and "swept" in again["planned"][0]["skip"]
    serving(spec="q3-8b")
    record(conn, "code", 5, 10, limit="max_tokens.code>32768", spec="q3-8b")
    assert len(sweeps.check(conn, now=NOW + 360)["queued"]) == 1
    assert len(queued(conn)) > before


def test_the_report_names_the_decision(conn, serving):
    binding_budget(conn)
    sweeps.check(conn, now=NOW)
    _finish(conn, {v: (20, 1.0) for v in knobs.KNOBS["reply_budget"].values})
    got = sweeps.check(conn, now=NOW + 120)
    text = sweeps.render(got)
    assert "reply_budget" in text and "chose 2000" in text


def test_the_loop_runs_the_sweep_check(monkeypatch, capsys):
    from harness.commands import loop
    seen = []
    monkeypatch.setattr(sweeps, "check", lambda conn, **kw: seen.append(kw) or
                        {"settled": [], "planned": [], "queued": [], "dry_run": False})
    loop._sweeps()
    assert seen and not seen[0].get("dry_run")


def test_a_knob_override_is_read_from_the_command_line():
    assert R.knob_overrides(["request_timeout=600"]) == {"request_timeout": 600.0}
    assert R.knob_overrides([]) == {}
    with pytest.raises(SystemExit):
        R.knob_overrides(["no_such=1"])
    with pytest.raises(SystemExit):
        R.knob_overrides(["request_timeout"])


@pytest.fixture
def quiet_receipt(monkeypatch):
    for name, value in (("accelerator_id", "unified:test"), ("where_id", "test"),
                        ("swap_used_mb", 0), ("instruments", {}), ("engines", {})):
        monkeypatch.setattr(R, name, lambda *a, _v=value, **k: _v)
    monkeypatch.setattr(ms.machines, "_THIS_MACHINE", None)
    monkeypatch.setattr(environment, "capture", lambda: {})
    monkeypatch.setattr(R, "warn_if_pressed", lambda *a, **k: SimpleNamespace(as_dict=lambda: {}))


class Answers(BaseRunner):
    def __init__(self):
        self.candidate = self.spec = "org/x"
        self.timeout, self.load_timeout = 180.0, 1800.0

    def generate(self, case):
        return "", 0


def test_a_run_at_an_overridden_knob_runs_and_records_it(tmp_path, monkeypatch, quiet_receipt):
    made = []
    monkeypatch.setattr(R, "build_runner", lambda *a, **k: made.append(Answers()) or made[-1])
    args = argparse.Namespace(
        screen=False, repeat=1, adherence="", cases=str(ROOT / "evals" / "cases"),
        modality="code", candidates="org/x", from_winners=False, gateway="http://gw.test",
        out=str(tmp_path / "out"), split="all", max_tokens=None, knob=["request_timeout=600"])
    R._execute(args)
    data = json.loads((tmp_path / "out" / "results.json").read_text(encoding="utf-8"))
    assert data["receipt"]["knobs"]["request_timeout"] == 600.0
    assert made[0].timeout == 600.0


def test_sensitivity_sweeps_is_a_dry_run(monkeypatch, capsys, tmp_path):
    from harness import cli
    monkeypatch.setattr(ms, "this_machine", lambda: dict(M))
    assert cli.main(["sensitivity", "--sweeps", "--json"]) == 0
    got = json.loads(capsys.readouterr().out)
    assert got == {"planned": [], "decided": []}
