"""A cloud-only eval holds a cloud slot, never the GPU lock or the batch lease. #1135."""
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from evals import run
from harness import exclusive, knobs, models
from harness import watchdog as wd
from harness import workqueue as wq
from harness.commands import jobs as jobs_cmd
from tests.test_watchdog import NOON, Fake, P, ids, judged

REPO = Path(__file__).resolve().parent.parent

CONFIG = textwrap.dedent("""
    model_list:
      - model_name: cloud-opus
        litellm_params:
          model: anthropic/claude-opus-5-5
          api_key: os.environ/ANTHROPIC_API_KEY
      - model_name: eval-7b
        litellm_params:
          model: openai/Qwen2.5-7B-Instruct-Q4_K_M
          api_base: http://127.0.0.1:8082/v1
      - model_name: proxied-opus
        litellm_params:
          model: anthropic/claude-opus-5-5
          api_base: http://127.0.0.1:9000
""")


@pytest.fixture
def config(tmp_path):
    path = tmp_path / "gateway.yaml"
    path.write_text(CONFIG, encoding="utf-8")
    return path


def _locks_during_execute(monkeypatch, candidates, extra=()):
    seen = {}

    def execute(args):
        seen["gpu"] = exclusive._taken(exclusive.lock_path())
        seen["cloud"] = exclusive._taken(exclusive.cloud_lock_path(0))
        seen["held"] = [h["lock"] for h in exclusive.holders()]
        return 0

    monkeypatch.setattr(run, "_execute", execute)
    monkeypatch.setattr(run.env, "guard", lambda: None)
    run._main(run.parse_args(["--modality", "repo", "--candidates", candidates, *extra]))
    return seen


def test_a_claude_code_only_run_takes_a_cloud_slot_and_not_the_gpu_lock(monkeypatch):
    seen = _locks_during_execute(monkeypatch, "claude-code:claude-opus-5-5,context=skill:x,claude-code:claude-sonnet-5-5")
    assert seen == {"gpu": False, "cloud": True, "held": ["cloud"]}


def test_one_llamacpp_candidate_takes_the_gpu_lock(monkeypatch):
    seen = _locks_during_execute(monkeypatch, "claude-code:claude-opus-5-5,llamacpp:Qwen2.5-7B-Instruct-Q4_K_M")
    assert seen == {"gpu": True, "cloud": False, "held": ["gpu"]}


def test_a_hosted_gateway_entry_is_cloud_and_a_served_or_unknown_one_is_local(config):
    assert models.hosted("cloud-opus", config) and run.hosted("repair:cloud-opus,attempts=2", config)
    assert not models.hosted("eval-7b", config)
    assert not models.hosted("proxied-opus", config), "an api_base is a server someone runs, so it fails closed"
    assert not run.hosted("mlx-community/Qwen3-8B-4bit", config)
    assert not run.hosted("mflux:z-image-turbo", config)


def test_the_lock_kind_fails_closed(config):
    def kind(*argv):
        return run.lock_kind(run.parse_args(["--modality", "repo", *argv]), config)
    assert kind("--candidates", "cloud-opus,claude-code:claude-opus-5-5") == "cloud-eval"
    assert kind("--candidates", "cloud-opus,eval-7b") == "eval"
    assert kind("--from-winners") == "eval"
    assert kind("--candidates", "claude-code:claude-opus-5-5", "--adherence", "pickscore") == "eval"


HOLD = textwrap.dedent("""
    import sys, time
    sys.path.insert(0, {repo!r})
    from harness import exclusive
    exclusive.CLOUD_SLOTS = {slots}
    with exclusive.held("cloud-eval"):
        print("held", flush=True)
        time.sleep(60)
""")


def _hold(home, slots, job=""):
    env = {**os.environ, "LOCALHARNESS_HOME": str(home), wq.JOB_ENV: job}
    proc = subprocess.Popen([sys.executable, "-c", HOLD.format(repo=str(REPO), slots=slots)],
                            stdout=subprocess.PIPE, text=True, env=env)
    assert proc.stdout.readline().strip() == "held"
    return proc


def _stop(proc):
    proc.kill()
    proc.wait(timeout=10)


def test_a_cloud_eval_never_makes_a_gpu_run_wait(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALHARNESS_HOME", str(tmp_path))
    holder = _hold(tmp_path, 1)
    try:
        said = []
        with exclusive.held("eval", announce=said.append, poll=0.05) as waited:
            assert waited is False and said == []
    finally:
        _stop(holder)


def test_cloud_evals_past_the_slot_count_wait(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALHARNESS_HOME", str(tmp_path))
    monkeypatch.setattr(exclusive, "CLOUD_SLOTS", 2)
    first = _hold(tmp_path, 2)
    try:
        with exclusive.held("cloud-eval", poll=0.05) as waited:
            assert waited is False
        second = _hold(tmp_path, 2)
        try:
            saw = []

            def give_up(message):
                saw.append(message)
                raise TimeoutError

            with pytest.raises(TimeoutError):
                with exclusive.held("cloud-eval", announce=give_up, poll=0.05):
                    pass
            assert "waiting for one of 2 cloud evals" in saw[0]
        finally:
            _stop(second)
    finally:
        _stop(first)


def test_soh_jobs_names_the_lock_a_running_job_holds(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALHARNESS_HOME", str(tmp_path))
    holder = _hold(tmp_path, 2, job="137")
    try:
        held = exclusive.holders()
        assert [(h["lock"], h["job"]) for h in held] == [("cloud", "137")]
        listed = [{"id": "0137", "state": wq.RUNNING}, {"id": "0138", "state": wq.PENDING}]
        loose = jobs_cmd.held_locks(listed, held + [{"lock": "gpu", "kind": "eval", "pid": 9, "job": "138"}])
        assert listed[0]["lock"] == "cloud" and "lock" not in listed[1]
        assert [h["lock"] for h in loose] == ["gpu"], "a holder whose job is not running is shown, not dropped"
    finally:
        _stop(holder)


def test_the_watchdog_does_not_pause_a_cloud_job_for_daytime_gpu(tmp_path):
    class Cloudy(Fake):
        def __init__(self, *a, cloud=(), **kw):
            super().__init__(*a, **kw)
            self._cloud = set(cloud)

        def cloud(self):
            return self._cloud

    def job(cloud=(), lock=None):
        return Cloudy(tmp_path, procs=[P(500, 400, 500, wd.DAYTIME_GPU_S + 60, "uv run soh discover --loop"),
                                       P(510, 500, 510, wd.DAYTIME_GPU_S + 60, run_cmd)],
                      jobs={"0007": 500}, cloud=cloud, lock=lock)

    run_cmd = "uv run python -m evals.run --modality repo --candidates claude-code:claude-opus-5-5"
    assert ids(judged(job(), NOON)[1], "daytime_gpu") == ["job 0007"]
    assert ids(judged(job(cloud={510}), NOON)[1], "daytime_gpu") == []
    assert ids(judged(job(cloud={510}, lock={"kind": "eval", "pgid": 500}), NOON)[1], "daytime_gpu") == ["job 0007"]


def test_the_cloud_slot_count_is_a_registered_knob():
    knob = knobs.KNOBS["cloud_evals"]
    assert knob.default() == exclusive.CLOUD_SLOTS == 2
    assert knob.values == (1, 2, 3, 4)


def test_a_holder_record_names_its_job(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALHARNESS_HOME", str(tmp_path))
    monkeypatch.setenv(wq.JOB_ENV, "42")
    with exclusive.held("cloud-eval"):
        got = json.loads(exclusive.cloud_holder_path(0).read_text(encoding="utf-8"))
    assert got["job"] == "42" and got["kind"] == "cloud-eval"
