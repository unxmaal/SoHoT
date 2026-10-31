"""The shared runner spine.

A runner's only real job is `generate`: turn a case into an artifact and say
what it cost. Everything after that -- timing, scoring, building the row -- is
identical for every modality, and must stay identical or the comparison is
between two rulers rather than two candidates.

That is not hypothetical. Timing, failure handling and Result construction were
copied between the text and process runners, and the copies drifted: the
process runner called the image checker directly and so lost every shared
assertion for image cases.
"""
from __future__ import annotations

import time
from pathlib import Path

from evals import core
from evals.core import Case, Result, artifact_name
from harness import completion, degenerate, reasons


def _waited(waits) -> dict:
    """{"busy_wait_s", "pool_full_wait_s"} when a request of the row waited, else {}. #776, #1235."""
    from harness import completion
    return completion.waited(waits)


class RunnerError(RuntimeError):
    """A generation that failed for a reason worth putting in a row.

    Anything NOT raised as a RunnerError propagates: a bug in a runner must
    surface as a traceback, not as a quiet FAIL row that reads like the
    candidate's fault.
    """

    def __init__(self, detail: str, peak_kb: int = 0, failure_class: str = "",
                 limit: str = ""):
        super().__init__(detail)
        self.detail = detail
        # A crash after the model loaded is exactly when peak memory matters.
        self.peak_kb = peak_kb
        # Set where the cause is known; "" is read once by reasons.classify.
        self.failure_class = failure_class
        self.limit = limit


class BaseRunner:
    def extra_metrics(self) -> dict:
        """Numbers the RUNNER measured, merged into the row alongside the
        checker's. Empty for runners that measure nothing extra."""
        return {}

    #: Name this runner reports in every row. Set by the subclass.
    candidate: str = ""
    #: The spec it was built from, which the error adapter reads. #408.
    spec: str = ""
    #: A screen asks whether it runs at all, so a runner may warm and retry. #406.
    screening: bool = False

    def artifact(self, case: Case, suffix: str) -> str:
        """The one file name every runner writes a case's artifact under. #429."""
        return artifact_name(self.candidate, case.id, suffix)

    def cut_off(self) -> str:
        """The `limit:` body when the last reply stopped at the token budget, else "". #628."""
        return ""

    def stopped_by(self) -> tuple[str, str]:
        """(failure class, limit body) a failing row is put down to: a budget or cap we chose, else ("", ""). #695."""
        cut = self.cut_off()
        return (reasons.TOKEN_BUDGET_EXHAUSTED, cut) if cut else ("", "")

    def warm(self) -> None:
        """Load the model untimed, so no timed case pays for it. #406."""

    def failed(self, case: Case, exc: RunnerError, seconds: float = 0.0) -> Result:
        """The row for a failure, classed at the one place errors are caught."""
        cls = exc.failure_class or reasons.classify(
            exc.detail, reasons.RUNNER, self.spec or self.candidate)
        return Result(case.id, self.candidate, False, round(seconds, 3),
                      exc.peak_kb, exc.detail, failure_class=cls,
                      limit=exc.limit)

    def generate(self, case: Case):
        """Return (artifact, peak_kb). Raise RunnerError on a real failure.

        `artifact` is completion text for a text modality and the path to the
        produced file for a binary one; score() dispatches on the modality.
        """
        raise NotImplementedError(
            f"{type(self).__name__} must implement generate()")

    def score_kwargs(self) -> dict:
        """Extra arguments for the checker.

        A checker for a binary artifact may need a model of its own -- speech
        needs a transcriber -- and it should use the same server the runner
        was pointed at rather than a module default.
        """
        return {}

    def run(self, case: Case) -> Result:
        # perf_counter, not monotonic: `monotonic` is GetTickCount64 on
        # Windows and quantises to 15.6ms, which measured a 0.15s run as
        # 0.14 in 75 of 200 tries. This number is reported as a result and
        # divided into token counts, so its resolution is the measurement.
        started = time.perf_counter()
        # A wait for another batch on the serving machine is not the candidate's time. #776.
        with completion.measuring() as waits:
            try:
                artifact, peak_kb = self.generate(case)
            except RunnerError as exc:
                row = self.failed(case, exc, completion.since(started))
                row.metrics = core.as_graded(case.modality, row.failure_class,
                                             {**(row.metrics or {}), **_waited(waits)})
                self.graded(case, row)
                return row
            elapsed = completion.since(started)

        row = core.score(case, artifact, **self.score_kwargs())
        row.candidate = self.candidate
        cls, limit = self.stopped_by()
        tail: dict = {}
        if not row.passed and cls:
            # A reply our budget or cap stopped failed on our limit, not on its answer. #628, #695.
            row.failure_class, row.limit = cls, limit
            if cls == reasons.TOKEN_BUDGET_EXHAUSTED and case.modality in degenerate.LANES:
                tail, looped = degenerate.judged(artifact if isinstance(artifact, str) else "")
                if looped:
                    # A loop or a collapse would fill any budget, so the cut is not what failed it. #955.
                    row.failure_class, row.limit = reasons.DEGENERATE, ""
        if not row.passed and not row.failure_class:
            row.failure_class = reasons.CONTENT_FAILED
        row.seconds = round(elapsed, 3)
        # A runner may have measured something the checker cannot see,
        # such as tokens/sec from the server's usage block.
        row.metrics = core.as_graded(case.modality, row.failure_class,
                                     {**row.metrics, **self.extra_metrics(), **tail, **_waited(waits)})
        row.peak_kb = peak_kb
        if isinstance(artifact, str):
            row.output = artifact
        elif Path(artifact).is_file():
            row.artifact_path = str(artifact)
        t = self.timing()
        row.ttft_s = t.get("ttft_s")
        row.first_reasoning_s = t.get("first_reasoning_s")
        row.prefill_s = t.get("prefill_s")
        row.cold = t.get("cold")
        row.runtime = dict(getattr(self, "last_runtime", None) or {})
        self.graded(case, row)
        return row

    def graded(self, case: Case, row: Result) -> None:
        """Called with each scored row; a runner whose server learns from verdicts reports it here. #1338."""

    def timing(self) -> dict:
        """First-token timings of the last generate(); {} where unmeasured. #468."""
        return getattr(self, "last_timing", None) or {}
