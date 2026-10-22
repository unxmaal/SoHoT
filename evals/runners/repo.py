"""The repo lane's runner: one completion asked for a diff, graded in the runner before the checkout goes. #887."""
from __future__ import annotations

import dataclasses
import json
import time

from evals import repo
from evals.core import Case
from evals.runners.base import RunnerError
from evals.runners.claude_code import ClaudeCodeRunner
from evals.runners.text import CompletionRunner
from harness import reasons


class RepoGrading:
    """Restore, ask the next runner in the MRO once, grade the diff; mixed into a text or claude-code runner."""
    #: (params) -> repo.Attempt; tests hand in a fixture's.
    attempt = staticmethod(repo.Attempt.open)

    def generate(self, case: Case):
        self.last_metrics, self.last_grade = {}, {}
        try:
            attempt = self.attempt(case.params)
        except repo.RepoEnvError as exc:
            raise RunnerError(f"environment: {exc}", failure_class=reasons.ENVIRONMENT_ERROR) from exc
        try:
            started = time.perf_counter()
            asked = dataclasses.replace(case, prompt=attempt.prompt(case.prompt), context="")
            reply, _ = super().generate(asked)
            spent = dict(self.last_metrics)
            diff = repo.extract_diff(reply)
            got = attempt.submit(diff)
            wall = round(time.perf_counter() - started, 3)
        except repo.RepoEnvError as exc:
            raise RunnerError(f"environment: {exc}", failure_class=reasons.ENVIRONMENT_ERROR) from exc
        finally:
            attempt.close()
        metrics = {"resolved": int(got.resolved), "patch_applied": int(got.patch_applied),
                   "wall_s": wall, "test_s": got.test_s}
        self.last_metrics = spent
        self.last_grade = metrics
        return json.dumps({"case": case.id, "diff": diff, "reply": reply,
                           "grade": {"resolved": got.resolved, "patch_applied": got.patch_applied,
                                     "detail": got.detail, "failed": got.failed, "limit": got.limit,
                                     "skipped": got.skipped},
                           "metrics": metrics}), 0

    def run(self, case: Case):
        row = super().run(case)
        if "wall_s" in (row.metrics or {}):
            # The checkout and its environment are the harness's to build, not the model's to pay for.
            row.seconds = row.metrics["wall_s"]
        return row


class RepoRunner(RepoGrading, CompletionRunner):
    pass


class ClaudeRepoRunner(RepoGrading, ClaudeCodeRunner):
    """The patch-only call through `claude -p`, built-in tools off, so Opus answers the same one prompt. #905."""
