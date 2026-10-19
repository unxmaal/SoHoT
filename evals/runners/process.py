"""Runner for generators that are external processes.

Not image-specific: mflux, h3.c and any future audio engine are the same shape,
so they plug in as Engines rather than as new Runner classes.

There is no completion to parse here. What is measurable is the process itself:
exit status, wall time, peak memory, and whether the file it left behind is
real. All three come from harness.proc, which is also what the CLI uses, so the
eval measures the exact command the product runs.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from harness import proc, reasons
from harness.engines import Engine
from harness.hf_task import runtime_path

from evals.core import Case
from evals.runners.base import BaseRunner, RunnerError

#: Lines of a failed child's stderr kept beside its artifact.
STDERR_TAIL = 40


class ProcessRunner(BaseRunner):
    def __init__(self, engine: Engine, outdir: str | Path,
                 timeout: float | None = None, adherence: str | None = None):
        self.engine = engine
        # A run-level choice, so it travels with the runner rather than being
        # read from a global by the checker.
        self.adherence = adherence
        self.candidate = engine.name
        self.outdir = Path(outdir)
        self.outdir.mkdir(parents=True, exist_ok=True)
        self.timeout = timeout if timeout is not None else engine.timeout

    def score_kwargs(self) -> dict:
        return {"adherence": self.adherence} if self.adherence else {}

    def generate(self, case: Case):
        # Absolute: an engine with its own working directory would otherwise
        # write a relative path inside that directory rather than here.
        out = (self.outdir / self.artifact(
            case, self.engine.output_suffix)).resolve()
        if out.exists():
            out.unlink()
        Path(runtime_path(out)).unlink(missing_ok=True)
        sidecar(out).unlink(missing_ok=True)
        self.last_runtime = {}
        self.last_limit = ""

        try:
            # The material a decide engine scores travels with the params. #423.
            params = ({**case.params, "context": case.context} if case.context
                      else case.params)
            if case.input_file is not None:
                params = {**params, "input": str(Path(case.input_file).resolve())}
            argv = self.engine.argv(case.prompt, out, params)
        except ValueError as exc:
            raise RunnerError(str(exc), failure_class=reasons.HARNESS_ERROR) from exc

        try:
            r = proc.run(argv, timeout=self.timeout, stream=self.engine.stream,
                         cwd=self.engine.cwd)
        except subprocess.TimeoutExpired as exc:
            raise timed_out(case.modality, self.timeout) from exc
        except FileNotFoundError as exc:
            raise RunnerError(f"{argv[0]} not installed or not on PATH",
                              failure_class=reasons.HARNESS_ERROR) from exc
        except OSError as exc:
            raise RunnerError(f"could not launch: {exc}",
                              failure_class=reasons.HARNESS_ERROR) from exc

        if not r.ok:
            detail = f"exit {r.returncode}"
            tail = (r.stderr or "").strip().splitlines()
            if tail:
                # The why behind a one-line detail, kept in the run dir. #601.
                kept = self.outdir / self.artifact(case, ".stderr.txt")
                kept.write_text("\n".join(tail[-STDERR_TAIL:]) + "\n", encoding="utf-8")
            if tail:
                # An MPS abort is followed by interpreter warnings; the abort is the why. #604.
                detail += f": {reasons.backend_abort(tail) or tail[-1]}"
            raise RunnerError(detail, peak_kb=r.peak_kb)

        got = _runtime_of(out)
        self.last_limit = got.pop("limit", "")
        self.last_runtime = got
        return out, r.peak_kb

    def cut_off(self) -> str:
        """The limit an hf-task child says its reply filled, else "". #700."""
        return getattr(self, "last_limit", "")


def timed_out(lane: str, timeout: float, what: str = "") -> RunnerError:
    """An engine past the wall clock we chose: TIMEOUT, naming the engine_timeout knob for its lane. #693."""
    return RunnerError(f"{what}timed out after {timeout:g}s", failure_class=reasons.TIMEOUT,
                       limit=f"engine_timeout_s.{lane}>{timeout:g}")


def sidecar(out) -> Path:
    """The .json a media engine writes beside its artifact; a .json artifact has none. #691."""
    out = Path(out)
    return out.with_suffix(".json") if out.suffix != ".json" else out.with_name(out.name + ".sidecar")


def _runtime_of(out_path: Path) -> dict:
    """The device, attention, dtype and limit an hf-task child says answered (#604, #700, #1018), and the steps, guidance and dtype a media sidecar says it used (#691, #1013)."""
    import json
    out = {}
    for path, keys in ((Path(runtime_path(out_path)), ("device", "attn", "limit", "dtype")),
                       (sidecar(out_path), ("steps", "guidance", "dtype"))):
        try:
            got = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(got, dict):
            out.update({k: str(got[k]) for k in keys if got.get(k) is not None and got.get(k) != ""})
    return out
