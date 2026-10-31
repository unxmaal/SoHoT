"""Repo measurement stops when it has answered: the incumbent's full exam is reused, looks fall inside a paired run, and a full repo exam waits for a screen. #1353."""
import argparse
import json
import time
from pathlib import Path

import pytest

from evals import repo_screen, watch
from evals import run as R
from harness import adopt, holdout, identity, knobs, looks, paused, reuse, runs, workqueue
from harness import memory_store as ms
from harness.commands import adopt as adopt_cmd
from harness.commands import measure as measure_cmd
from harness.commands.measure import Launched
from tests.test_incumbent_reuse_1094 import INC as RINC
from tests.test_incumbent_reuse_1094 import _incumbent_only, pair, served  # noqa: F401
from tests.test_pause_813 import clock, quiet  # noqa: F401
from tests.test_resume_813 import CH, INC, Eval, _ns, _pauses, _rows, world  # noqa: F401

# --- the incumbent's stored exam is reused across a knob added after it ran -----------------


def _legacy(knob: str, out: Path) -> None:
    """Rewrite the stored run at `out` as if it ran before `knob` was recorded on identities."""
    conn = ms.connect()
    try:
        row = runs.at(conn, out)
        env = json.loads(row["environment"])
        ident = env["identities"][RINC]
        del ident["parts"]["settings"]["knobs"][knob]
        ident["digest"] = identity.digest_of(ident["parts"])
        conn.execute("UPDATE runs SET environment = ? WHERE id = ?", (json.dumps(env), row["id"]))
        conn.commit()
    finally:
        conn.close()


def _planned(lane="code"):
    """The incumbent cells a measure step takes from the store, as measure._with_reuse asks for them."""
    on = holdout.only(R.load_selected(R.parse_args(["--modality", lane])), "holdout")
    cells = [c.id for c in R.expand_cases(on, 1)]
    ident = R.content_identity(lane, RINC, R.run_budget(lane, None), (), {}, on)
    conn = ms.connect()
    try:
        return reuse.plan(conn, lane, ident["digest"], cells, cases=ident["cases"], parts=ident["parts"]), cells
    finally:
        conn.close()


def _unrecorded_knob(lane="code") -> str:
    now = knobs.settings(lane)
    got = sorted(k for k, v in now.items() if k in knobs.UNRECORDED and knobs.UNRECORDED[k] == v)
    assert got, f"no {lane} knob sits at its unrecorded value"
    return got[0]


def test_a_run_recorded_before_a_knob_at_its_unrecorded_value_is_the_incumbents_exam(tmp_path, quiet, pair):
    out = _incumbent_only(tmp_path)
    _legacy(_unrecorded_knob(), out)
    got, cells = _planned()
    assert got["reused"] == len(cells) and got["fresh"] == 0


def test_a_missing_knob_whose_unrecorded_value_is_not_todays_is_another_exam(tmp_path, quiet, pair, monkeypatch):
    out = _incumbent_only(tmp_path)
    knob = _unrecorded_knob()
    _legacy(knob, out)
    monkeypatch.setitem(knobs.UNRECORDED, knob, "something else")
    got, cells = _planned()
    assert got["reused"] == 0 and got["fresh"] == len(cells)


# --- looks inside one paired run --------------------------------------------------------------


class Slices(Eval):
    """evals.run paused at its --stop-at: each launch adds the next chunk of rows, as a run cut into look slices does."""

    def __init__(self, chunks):
        super().__init__(rows=[])
        self.chunks = list(chunks)

    def __call__(self, argv, **kw):
        if self.chunks:
            self.rows = self.chunks.pop(0)
        got = super().__call__(argv, **kw)
        out = Path(argv[argv.index("--out") + 1])
        p = json.loads((out / watch.PROGRESS).read_text(encoding="utf-8"))
        (out / watch.PROGRESS).write_text(json.dumps({**p, "why": "paused at its stop time, 9 case(s) left"}),
                                          encoding="utf-8")
        return got


def _measure(**kw):
    return measure_cmd._measure(_ns(**kw), {"name": CH, "lane": "code"}, [], None)


def _verdicts(conn):
    return [dict(r) for r in conn.execute("SELECT * FROM verdicts WHERE tier = ? ORDER BY id", (adopt.TIER,))]


def test_a_paired_run_is_cut_into_look_slices_inside_its_budget(monkeypatch, world):
    fake = Slices([_rows(6, gained=1, lost=1)])
    monkeypatch.setattr(measure_cmd, "_launch", fake)
    before = time.time()
    _measure()
    after = time.time()
    first = fake.argvs[0]
    stop = float(first[first.index("--stop-at") + 1])
    # --stop-at is whole seconds, stamped between before and after.
    assert before - 1 < stop <= after + looks.LOOK_INTERVAL_S + 1
    assert stop < after + 60 * 60 - 5


def test_a_decided_look_mid_run_stops_it_and_records_the_verdict(monkeypatch, world):
    n = len(holdout.for_lane("code").holdout)
    fake = Slices([_rows(6, gained=1, lost=1), _rows(n // 2, gained=n // 2)])
    monkeypatch.setattr(measure_cmd, "_launch", fake)
    assert _measure() == 0
    assert len(fake.argvs) == 2 and "--resume" in fake.argvs[1]
    assert fake.argvs[1][fake.argvs[1].index("--out") + 1] == fake.argvs[0][fake.argvs[0].index("--out") + 1]
    conn = world()
    try:
        (v,) = _verdicts(conn)
        (p,) = _pauses(conn)
    finally:
        conn.close()
    assert [x["decision"] for x in json.loads(p["looks"])] == ["continue"]
    assert p["state"] == "done" and p["sweeps"] == 1 and p["why"].endswith("stopped for success")


def test_a_hopeless_look_mid_run_stops_it_for_futility(monkeypatch, world):
    n = len(holdout.for_lane("code").holdout)
    fake = Slices([_rows(6, gained=1, lost=1), _rows(n - 5, lost=30)])
    monkeypatch.setattr(measure_cmd, "_launch", fake)
    _measure()
    assert len(fake.argvs) == 2
    conn = world()
    try:
        (v,) = _verdicts(conn)
        (p,) = _pauses(conn)
    finally:
        conn.close()
    assert v["outcome"] != "measured" and "futility" in v["detail"]
    assert p["state"] == "done"


def test_a_slice_that_ran_nothing_ends_the_run_with_its_pause_kept(monkeypatch, world):
    fake = Slices([_rows(6, gained=1, lost=1), _rows(6, gained=1, lost=1)])
    monkeypatch.setattr(measure_cmd, "_launch", fake)
    _measure()
    assert len(fake.argvs) == 2
    conn = world()
    try:
        (p,) = _pauses(conn)
        assert _verdicts(conn) == []
    finally:
        conn.close()
    assert p["state"] == "paused" and p["sweeps"] == 1 and len(json.loads(p["looks"])) == 2


def test_a_budget_under_one_look_interval_is_one_slice(monkeypatch, world):
    fake = Slices([_rows(6, gained=1, lost=1), _rows(12, gained=1, lost=1)])
    monkeypatch.setattr(measure_cmd, "_launch", fake)
    _measure(power_budget_min=looks.LOOK_INTERVAL_S / 60 / 2)
    assert len(fake.argvs) == 1


class Requested(Slices):
    """A slice that paused on request, with budget and rows left, as `soh pause` leaves it."""

    def __call__(self, argv, **kw):
        got = super().__call__(argv, **kw)
        out = Path(argv[argv.index("--out") + 1])
        p = json.loads((out / watch.PROGRESS).read_text(encoding="utf-8"))
        (out / watch.PROGRESS).write_text(json.dumps({**p, "why": "paused on request"}), encoding="utf-8")
        return got


def test_a_pause_on_request_is_never_resumed_inside_the_run(monkeypatch, world):
    fake = Requested([_rows(6, gained=1, lost=1), _rows(12, gained=1, lost=1)])
    monkeypatch.setattr(measure_cmd, "_launch", fake)
    _measure()
    assert len(fake.argvs) == 1


def test_a_pause_with_no_reason_is_never_resumed_inside_the_run(monkeypatch, world):
    fake = Eval(rows=_rows(6))
    monkeypatch.setattr(measure_cmd, "_launch", fake)
    _measure()
    assert len(fake.argvs) == 1


# --- a full repo exam waits for the candidate's screen ----------------------------------------

def _cases():
    return R.load_selected(R.parse_args(["--modality", "repo"]))


def _screen_run(conn, spec, passed: bool, path="screen", harness=None):
    ids = [c.id for c in repo_screen.pick(_cases())]
    receipt = {"modality": "repo", "tier": "measure", "split": "all", "case_ids": ids,
               **({"harness": harness} if harness else {})}
    rows = [{"candidate": spec, "case_id": c, "passed": passed, "seconds": 1.0} for c in ids]
    return runs.record(conn, path, {"generated": "2026-10-29T00:00:00", "receipt": receipt, "environment": {},
                                    "specs": {spec: spec}, "rows": rows}, at=time.time())


@pytest.fixture
def store(tmp_path, monkeypatch):
    real = ms.connect
    monkeypatch.setattr(ms, "connect", lambda *a, **k: real(tmp_path / "s.db"))
    return lambda: real(tmp_path / "s.db")


def test_a_candidate_with_no_screen_rows_is_refused_with_the_screen_to_run(store):
    conn = store()
    try:
        why = repo_screen.refusal(conn, ["llamacpp:New"], _cases())
    finally:
        conn.close()
    assert "no repo screen result" in why
    assert "evals.run --modality repo --repo-screen --candidates llamacpp:New" in why
    assert "--unscreened" in why


def test_a_screen_that_survived_lets_the_full_exam_run(store):
    conn = store()
    try:
        _screen_run(conn, "llamacpp:Good", True)
        assert repo_screen.refusal(conn, ["llamacpp:Good"], _cases()) == ""
    finally:
        conn.close()


def test_a_declined_screen_refuses_the_full_exam_and_says_so(store):
    conn = store()
    try:
        _screen_run(conn, "llamacpp:Bad", False)
        why = repo_screen.refusal(conn, ["llamacpp:Bad"], _cases())
    finally:
        conn.close()
    assert "llamacpp:Bad" in why and "declined" in why


def test_a_repair_harness_run_is_not_the_patch_screen(store):
    conn = store()
    try:
        _screen_run(conn, "llamacpp:Rep", True, harness="repair")
        assert "no repo screen result" in repo_screen.refusal(conn, ["llamacpp:Rep"], _cases())
    finally:
        conn.close()


def test_a_full_exam_covers_the_screen(store):
    conn = store()
    try:
        rows = [{"candidate": "llamacpp:Full", "case_id": c.id, "passed": True, "seconds": 1.0} for c in _cases()]
        runs.record(conn, "full", {"generated": "2026-10-29T00:00:00",
                                   "receipt": {"modality": "repo", "tier": "measure", "split": "all"},
                                   "environment": {}, "specs": {"llamacpp:Full": "llamacpp:Full"}, "rows": rows},
                    at=time.time())
        assert repo_screen.refusal(conn, ["llamacpp:Full"], _cases()) == ""
    finally:
        conn.close()


def test_the_screens_own_base_and_reference_need_no_screen(store):
    anchors = repo_screen.load_anchors()
    conn = store()
    try:
        for side in ("base", "reference"):
            assert repo_screen.refusal(conn, [anchors[side]["candidate"]], _cases()) == ""
    finally:
        conn.close()


def test_the_lanes_served_model_is_reverified_and_swept_without_a_screen(store, monkeypatch):
    monkeypatch.setattr(adopt, "default_for", lambda lane, fallback, conn=None: "llamacpp:Served")
    conn = store()
    try:
        assert repo_screen.refusal(conn, ["llamacpp:Served"], _cases()) == ""
        assert "no repo screen result" in repo_screen.refusal(conn, ["llamacpp:Other"], _cases())
    finally:
        conn.close()


def test_a_hosted_candidate_holds_no_gpu_so_needs_no_screen(store):
    args = R.parse_args(["--modality", "repo", "--candidates", "claude-code:claude-sonnet-5-5"])
    assert R.screen_refusal(args, ["claude-code:claude-sonnet-5-5"], R.expand_cases(_cases(), 1)) == ""
    mixed = ["claude-code:claude-sonnet-5-5", "llamacpp:New"]
    assert "llamacpp:New has no repo screen result" in R.screen_refusal(args, mixed, R.expand_cases(_cases(), 1))


def test_a_run_that_missed_screen_cases_is_no_screen_result(store):
    ids = [c.id for c in repo_screen.pick(_cases())]
    rows = [{"candidate": "llamacpp:Part", "case_id": c, "passed": True, "seconds": 1.0} for c in ids[:-1]]
    conn = store()
    try:
        runs.record(conn, "part", {"generated": "2026-10-29T00:00:00",
                                   "receipt": {"modality": "repo", "tier": "measure", "split": "all"},
                                   "environment": {}, "specs": {"llamacpp:Part": "llamacpp:Part"}, "rows": rows},
                    at=time.time())
        assert "no repo screen result" in repo_screen.refusal(conn, ["llamacpp:Part"], _cases())
    finally:
        conn.close()


def _argv(*extra):
    return ["uv", "run", "python", "-m", "evals.run", "--modality", "repo", "--candidates", "llamacpp:New",
            "--out", "/x", *extra]


def test_a_full_repo_exam_for_an_unscreened_candidate_is_refused_at_start_and_at_queue(store):
    with pytest.raises(SystemExit, match="no repo screen result"):
        R.screen_first(R.parse_args(_argv()[5:]), ["llamacpp:New"], R.expand_cases(_cases(), 1))
    assert "no repo screen result" in R.argv_screen_refusal(_argv())
    with pytest.raises(ValueError, match="not queued: .*no repo screen result"):
        workqueue.add(_argv(), title="full exam")


def test_a_knob_sweep_or_reverify_of_a_measured_model_is_queued_without_a_screen(store):
    for planner in workqueue.REMEASURES:
        assert workqueue.add(_argv(), title="sweep", requested_by=planner)["state"] == workqueue.PENDING


def test_the_screen_itself_a_small_subset_a_resume_and_unscreened_are_not_refused(store, tmp_path):
    assert R.argv_screen_refusal(_argv("--repo-screen")) == ""
    assert R.argv_screen_refusal(_argv("--unscreened")) == ""
    small = R.expand_cases(_cases()[:repo_screen.CASES], 3)
    R.screen_first(R.parse_args(_argv()[5:]), ["llamacpp:New"], small)
    out = tmp_path / "held"
    out.mkdir()
    watch.Checkpoint(out, {"x": 1})
    assert R.argv_screen_refusal([*_argv()[:-2], "--out", str(out), "--resume"]) == ""


def test_a_repo_adopt_for_an_unscreened_challenger_is_refused_before_any_run(monkeypatch, world):
    fake = Eval(rows=[])
    monkeypatch.setattr(measure_cmd, "_launch", fake)
    rc = measure_cmd._measure(_ns(), {"name": CH, "lane": "repo"}, [], None)
    assert rc == 1 and fake.argvs == []
    assert "no repo screen result" in adopt_cmd.argv_screen_refusal(
        ["uv", "run", "soh", "adopt", "--lane", "repo", "--challenger", CH])
    assert adopt_cmd.argv_screen_refusal(["uv", "run", "soh", "adopt", "--lane", "code", "--challenger", CH]) == ""


def test_unscreened_skips_the_measure_steps_screen_guard(monkeypatch, world):
    fake = Eval(rows=[])
    monkeypatch.setattr(measure_cmd, "_launch", fake)
    measure_cmd._measure(_ns(unscreened=True), {"name": CH, "lane": "repo"}, [], None)
    assert fake.argvs and "--unscreened" in fake.argvs[0]


def test_every_repo_pairing_the_measure_step_lets_run_carries_unscreened_to_evals_run(monkeypatch, world):
    fake = Eval(rows=[])
    monkeypatch.setattr(measure_cmd, "_launch", fake)
    monkeypatch.setattr(measure_cmd, "_screen_refusal", lambda a, lane, spec: "")
    measure_cmd._measure(_ns(), {"name": CH, "lane": "repo"}, [], None)
    measure_cmd._measure(_ns(), {"name": CH, "lane": "code"}, [], None)
    (repo, code) = fake.argvs
    assert "--unscreened" in repo and "--unscreened" not in code


def test_a_held_repo_pause_resumes_whatever_its_screen(monkeypatch, world):
    conn = world()
    try:
        paused.save(conn, lane="repo", inc_spec=INC, spec=CH, proposal=CH, out="/nonexistent",
                    ident={}, plan={}, done=1, total=2, looks=[])
    finally:
        conn.close()
    assert measure_cmd._screen_refusal(argparse.Namespace(), "repo", CH) == ""
