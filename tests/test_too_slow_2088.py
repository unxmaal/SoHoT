"""An over-plan run that still finishes cases is re-planned from its observed rate; only one that stopped finishing is an overrun. #2088."""
import contextlib
import json
from dataclasses import dataclass, field

from evals import run as R
from evals import watch
from harness import exclusive, overrun
from harness import watchdog as wd
from harness.commands import measure as measure_cmd
from tests.test_resume_813 import Eval, _measure, _rows, world  # noqa: F401
from tests.test_watchdog import NIGHT, ids, judged, owned_eval

INC, CH = "llamacpp:Ornith-1.5-35B-Q4_K_M", "daksh-neo/acervo-extractor-qwen3.5-9b-GGUF"


def _run(last_s=39.0, ceiling_s=3 * 3600.0, left=None, now=NIGHT):
    """The adopt-code run of #2088 as the watchdog read it: the challenger far over its planned seconds per case."""
    got = {"state": "running", "pid": 511, "done": 23, "total": 135, "specs": {INC: INC, CH: CH},
           "planned_s_per_case": {INC: 49.05, CH: 12.72}, "observed_s_per_case": {INC: None, CH: 44.172427882318914},
           "started_at": now - 1062.0, "last_progress_at": now - last_s,
           "left": {INC: 67, CH: 45} if left is None else left}
    if ceiling_s is not None:
        got["ceiling_at"] = now + ceiling_s
    return got


def _found(tmp_path, **kw):
    return judged(owned_eval(tmp_path, progress=[_run(**kw)]))[1]


def test_a_slow_challenger_still_finishing_cases_that_fits_its_ceiling_runs_on(tmp_path):
    found = _found(tmp_path)
    assert ids(found, "overrun") == [] and ids(found, "too_slow") == []


def test_a_run_with_no_ceiling_still_finishing_cases_runs_on(tmp_path):
    found = _found(tmp_path, ceiling_s=None)
    assert ids(found, "overrun") == [] and ids(found, "too_slow") == []


def test_a_slow_challenger_that_cannot_fit_its_ceiling_is_too_slow_with_its_observed_rate(tmp_path):
    found = _found(tmp_path, ceiling_s=1800.0)
    assert ids(found, "overrun") == []
    (f,) = [f for f in found if f.criterion == "too_slow"]
    assert f.evidence["candidate"] == CH and f.evidence["observed_s_per_case"] == 44.17
    assert f.evidence["planned_s_per_case"] == 12.72
    assert f.evidence["projected_s"] == round(67 * 49.05 + 45 * 44.172427882318914)
    assert f.evidence["ceiling_left_s"] == 1800


def test_without_counts_per_candidate_the_rest_is_priced_at_the_slowest_rate(tmp_path):
    (f,) = [f for f in _found(tmp_path, ceiling_s=1800.0, left={}) if f.criterion == "too_slow"]
    assert f.evidence["projected_s"] == round(112 * 49.05)


def test_an_over_plan_run_that_stopped_finishing_cases_is_still_an_overrun(tmp_path):
    found = _found(tmp_path, last_s=max(wd.STALL_S, wd.STALL_CASES * 49.05) + 60)
    assert ids(found, "overrun") == ["eval pgid 510"] and ids(found, "too_slow") == []


def test_too_slow_stops_after_notes_and_reads_registered_knobs():
    c = wd.BY_ID[wd.TOO_SLOW]
    assert (c.action, c.escalation) == (wd.NOTE, wd.STOP)


def test_progress_records_the_ceiling_and_the_cases_left(tmp_path, monkeypatch):
    monkeypatch.setattr(watch, "clock", lambda: NIGHT)
    eye = watch.Watch(planned={CH: 12.72}, stop_at=NIGHT + 600, ceiling_at=NIGHT + 7200, left={CH: 45})
    eye.yield_s = 30.0
    got = watch.Progress(tmp_path, eye, {CH: CH}, 135, 23).write()
    assert got["ceiling_at"] == NIGHT + 7230 and got["left"] == {CH: 45}
    assert json.loads((tmp_path / watch.PROGRESS).read_text(encoding="utf-8"))["ceiling_at"] == NIGHT + 7230


def test_a_look_slice_does_not_shrink_the_ceiling(tmp_path, monkeypatch):
    monkeypatch.setattr(watch, "clock", lambda: NIGHT)
    monkeypatch.setattr(R.env, "guard", lambda: None)

    @contextlib.contextmanager
    def held(kind, announce=None, deadline_s=None, **kw):
        yield True

    monkeypatch.setattr(exclusive, "held", held)
    seen = []
    monkeypatch.setattr(R, "_execute", lambda args: seen.append((args.stop_at, args.ceiling_at)) or 0)
    R._main(R.parse_args(["--modality", "code", "--candidates", f"{INC},{CH}", "--out", str(tmp_path),
                          "--stop-at", f"{NIGHT + 7200:.0f}", "--stop-after", "1800"]))
    assert seen == [(NIGHT + 1800, float(f"{NIGHT + 7200:.0f}"))]


@dataclass(frozen=True)
class _Plan:
    estimate: dict = field(default_factory=dict)


def _plan():
    return _Plan({"incumbent_s": 49.05, "incumbent_calls": 1, "challenger_s": 6.36, "challenger_calls": 2})


def test_a_resume_after_a_too_slow_stop_prices_each_side_at_the_rate_its_run_observed(tmp_path):
    (tmp_path / watch.PROGRESS).write_text(json.dumps(_run()), encoding="utf-8")
    assert overrun.observed_plan(_plan(), tmp_path, INC, CH) == _plan()
    watch.mark_stop(tmp_path, wd.TOO_SLOW)
    got = overrun.observed_plan(_plan(), tmp_path, INC, CH)
    inc, ch = measure_cmd._case_s(got)
    assert inc == 49.05 and round(ch, 2) == 44.17


def test_a_resume_with_too_few_cases_keeps_the_fresh_price(tmp_path):
    (tmp_path / watch.PROGRESS).write_text(json.dumps({**_run(), "done": wd.OVERRUN_MIN_CASES - 1}), encoding="utf-8")
    watch.mark_stop(tmp_path, wd.TOO_SLOW)
    assert measure_cmd._case_s(overrun.observed_plan(_plan(), tmp_path, INC, CH)) == [49.05, 12.72]


class _StoppedSlow(Eval):
    """evals.run the watchdog stopped as too slow on its first launch."""

    def __call__(self, argv, **kw):
        got = super().__call__(argv, **kw)
        if len(self.argvs) == 1:
            watch.mark_stop(argv[argv.index("--out") + 1], wd.TOO_SLOW)
        return got


def test_the_measure_step_resumes_a_too_slow_run_at_its_observed_rate(monkeypatch, world):  # noqa: F811
    fake = _StoppedSlow(rc=-15, rows=_rows(10))
    monkeypatch.setattr(measure_cmd, "_launch", fake)
    _measure()
    _measure()
    first, second = fake.argvs
    assert "--resume" in second
    plan_s = lambda argv: [argv[i + 1] for i, a in enumerate(argv) if a == "--plan-s"]  # noqa: E731
    assert plan_s(second) == ["1.50", "2.50"] != plan_s(first)
