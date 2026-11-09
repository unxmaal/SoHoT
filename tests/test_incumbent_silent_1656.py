"""A paired run stops when its incumbent answers nothing; a router-served alias travels to the router. #1656."""
import argparse
import json
import subprocess

from evals import run as R
from evals import watch
from evals.core import Result
from evals.runners.base import RunnerError
from harness import adopt, cli, reasons, screen
from harness import memory_store as ms
from harness.commands import measure as measure_cmd
from tests.test_interleave_816 import Named
from tests.test_pause_813 import _args, clock, quiet  # noqa: F401

INC, CH = "org/inc", "org/ch"
#: The warm-up detail of every incumbent row in runs/20261108-232512-adopt-decide.
SNAPSHOT_404 = ('warm-up: gateway returned HTTP 404: {"error": "Cannot find an appropriate cached snapshot folder '
                'for the specified revision on the local disk and outgoing traffic has been disabled."}')


class Refused(Named):
    """An incumbent whose warm-up the server refuses, as mlx_lm.server refused a router stem."""

    def warm(self):
        self.warms += 1
        raise RunnerError(SNAPSHOT_404, failure_class=reasons.HARNESS_ERROR)


def _pair(monkeypatch, clock, inc_cls=Refused, block=1):
    log = []
    runners = {INC: inc_cls(INC, clock, log), CH: Named(CH, clock, log)}
    monkeypatch.setattr(R, "build_runner", lambda candidate, *a, **k: runners[candidate])
    monkeypatch.setattr(R, "pair_block", lambda candidates, gateway: block)
    return runners, log


def _row(key, failure_class=reasons.HARNESS_ERROR):
    return Result(case_id="c", candidate=key, passed=False, seconds=0.0, peak_kb=0, detail=SNAPSHOT_404,
                  failure_class=failure_class)


def test_five_harness_errors_from_the_incumbent_stop_the_run_naming_it():
    why = R.incumbent_silent([_row(INC) for _ in range(5)] + [_row(CH, "")], INC)
    assert INC in why and "harness_error" in why and "cached snapshot folder" in why


def test_fewer_than_five_do_not_stop_it():
    assert R.incumbent_silent([_row(INC) for _ in range(4)], INC) == ""


def test_one_answered_case_means_the_incumbent_is_not_silent():
    rows = [_row(INC) for _ in range(5)] + [_row(INC, reasons.CONTENT_FAILED)]
    assert R.incumbent_silent(rows, INC) == ""


def test_rows_restored_from_the_checkpoint_are_not_counted():
    assert R.incumbent_silent([_row(INC) for _ in range(5)], INC, since=5) == ""


def test_a_paired_run_whose_incumbent_answers_nothing_stops_early_and_says_why(
        monkeypatch, tmp_path, quiet, clock, capsys):
    out = tmp_path / "run"
    runners, log = _pair(monkeypatch, clock)
    rc = R._execute(_args(out, candidates=f"{INC},{CH}"))
    assert rc == watch.SILENT
    _, rows = watch.read(out)
    mine = [r for r in rows if r["candidate"] == INC]
    assert len(mine) == R.SILENT_CASES and all(r["failure_class"] == reasons.HARNESS_ERROR for r in mine)
    assert len(runners[CH].ran) < R.SILENT_CASES
    assert watch.stop_reason(out) == watch.INCUMBENT_SILENT
    progress = json.loads((out / watch.PROGRESS).read_text(encoding="utf-8"))
    assert progress["state"] == "stopped" and INC in progress["why"]
    assert INC in capsys.readouterr().err.strip().splitlines()[-1]


def test_a_candidate_major_run_stops_before_the_challenger_runs(monkeypatch, tmp_path, quiet, clock):
    out = tmp_path / "run"
    runners, _ = _pair(monkeypatch, clock, block=None)
    assert R._execute(_args(out, candidates=f"{INC},{CH}")) == watch.SILENT
    assert not runners[CH].ran


def test_an_incumbent_that_answers_runs_to_the_end(monkeypatch, tmp_path, quiet, clock):
    out = tmp_path / "run"
    runners, _ = _pair(monkeypatch, clock, inc_cls=Named)
    assert R._execute(_args(out, candidates=f"{INC},{CH}")) == 0
    assert runners[INC].ran == runners[CH].ran and len(runners[CH].ran) > R.SILENT_CASES


# --- the route: an alias the router serves goes to the router ----------------

CFG = """model_list:
  - model_name: imajev-4b-Q8_0
    litellm_params:
      model: openai/imajev-4b-Q8_0
      api_base: http://127.0.0.1:8082/v1
      api_key: not-needed
  - model_name: q3-4b
    litellm_params:
      model: openai/mlx-community/Qwen3-4B-Instruct-2507-4bit
      api_base: http://127.0.0.1:8081/v1
"""


def test_an_alias_the_router_serves_resolves_to_its_router_spec(tmp_path):
    cfg = tmp_path / "g.yaml"
    cfg.write_text(CFG, encoding="utf-8")
    assert screen.upstream_of("imajev-4b-Q8_0", cfg) == "llamacpp:imajev-4b-Q8_0"
    assert screen.upstream_of("q3-4b", cfg) == "mlx-community/Qwen3-4B-Instruct-2507-4bit"


def test_the_decide_incumbent_goes_to_the_router_when_the_challenger_goes_to_mlx(monkeypatch, tmp_path):
    """Job 1616: --gateway :8081 for a repo-id challenger sent the bare stem to mlx_lm.server, which 404'd."""
    cfg = tmp_path / "g.yaml"
    cfg.write_text(CFG, encoding="utf-8")
    monkeypatch.setenv("GATEWAY_CONFIG", str(cfg))
    seen = {}

    class _Done:
        returncode, stderr = 0, ""
    monkeypatch.setattr(measure_cmd, "_launch", lambda argv, **kw: subprocess.run(argv, **kw))
    monkeypatch.setattr(subprocess, "run", lambda argv, **kw: (seen.update(argv=argv), _Done())[1])
    monkeypatch.setattr(adopt, "default_for", lambda lane, fallback, conn=None: "imajev-4b-Q8_0")
    monkeypatch.setattr("harness.screen.routed_gateway", lambda model, config=None: "http://127.0.0.1:8081")
    monkeypatch.setattr(measure_cmd, "_receipt_at", lambda out: None)
    real = ms.connect
    monkeypatch.setattr(ms, "connect", lambda *a, **k: real(tmp_path / "d.db"))
    cli._measure_and_adopt(argparse.Namespace(repeat=3, power_budget_min=1e9),
                           {"name": "org/challenger", "lane": "code"})
    cands = seen["argv"][seen["argv"].index("--candidates") + 1]
    assert cands.split(",")[0] == "llamacpp:imajev-4b-Q8_0", cands
