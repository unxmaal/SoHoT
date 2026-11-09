"""A paired run's --gateway follows the challenger's built spec, not its name: a nimble: challenger sends no gateway request. #1660."""
import argparse
import subprocess

import pytest

from harness import adopt, candidates, cli, screen
from harness import memory_store as ms
from harness.commands import measure as measure_cmd

MLX = "http://127.0.0.1:8081"
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


class _Done:
    returncode, stdout, stderr = 0, "", ""


@pytest.fixture
def cfg(monkeypatch, tmp_path):
    path = tmp_path / "g.yaml"
    path.write_text(CFG, encoding="utf-8")
    monkeypatch.setenv("GATEWAY_CONFIG", str(path))
    real = ms.connect
    monkeypatch.setattr(ms, "connect", lambda *a, **k: real(tmp_path / "d.db"))
    return path


def _decide(monkeypatch, spec, dry=False):
    seen = {}
    monkeypatch.setattr(measure_cmd, "_launch", lambda argv, **kw: subprocess.run(argv, **kw))
    monkeypatch.setattr(subprocess, "run", lambda argv, **kw: (seen.update(argv=argv), _Done())[1])
    monkeypatch.setattr(adopt, "default_for", lambda lane, fallback, conn=None: "imajev-4b-Q8_0")
    monkeypatch.setattr(candidates, "for_proposal", lambda store, lane, name, attaches="": spec)
    monkeypatch.setattr(screen, "candidate_for", lambda lane, name, attaches="", conn=None: spec if name == "org/x" else name)
    monkeypatch.setattr(measure_cmd, "_receipt_at", lambda out: None)
    monkeypatch.setattr(measure_cmd, "_screen_refusal", lambda a, lane, spec: "")
    cli._measure_and_adopt(argparse.Namespace(repeat=3, power_budget_min=1e9, dry_run=dry), {"name": "org/x", "lane": "decide"})
    return seen.get("argv", [])


@pytest.mark.parametrize("engine", ["nimble", "decider"])
def test_a_process_engine_challenger_adds_no_gateway_and_keeps_the_incumbent_alias(monkeypatch, cfg, engine):
    """Job 1616: Bespoke-Nimble-9B's repo id sent the run to :8081, and the incumbent with it."""
    argv = _decide(monkeypatch, f"{engine}:org/x")
    assert argv, "evals.run was never launched"
    assert "--gateway" not in argv, argv
    assert argv[argv.index("--candidates") + 1] == f"imajev-4b-Q8_0,{engine}:org/x"


def test_a_repo_id_challenger_still_routes_to_mlx_and_takes_the_incumbent_along(monkeypatch, cfg):
    argv = _decide(monkeypatch, "org/x")
    assert argv[argv.index("--gateway") + 1] == MLX, argv
    up = screen.upstream_of("imajev-4b-Q8_0")
    assert argv[argv.index("--candidates") + 1] == f"{up},org/x"


def test_the_dry_run_prints_the_same_route(monkeypatch, cfg, capsys):
    _decide(monkeypatch, "nimble:org/x", dry=True)
    out = capsys.readouterr().out
    assert "--candidates imajev-4b-Q8_0,nimble:org/x" in out, out
    assert "--gateway" not in out


def test_the_route_is_read_from_the_spec(cfg):
    assert screen.routed_gateway("org/x", cfg) == MLX
    assert screen.routed_gateway("nimble:org/x", cfg) == ""
    assert screen.routed_gateway("decider:org/x", cfg) == ""
    assert screen.routed_gateway("vllm:org/x", cfg) == ""
    assert screen.routed_gateway("best-of:3:org/x", cfg) == MLX
    assert screen.routed_gateway("repair:org/x", cfg) == MLX
    assert screen.routed_gateway("imajev-4b-Q8_0", cfg) == ""


def test_the_screen_routes_by_the_candidate_it_runs(cfg):
    argv = screen.argv({"name": "org/x", "candidate": "nimble:org/x", "modality": "decide"})
    assert "--gateway" not in argv, argv
    assert "--gateway" in screen.argv({"name": "org/x", "candidate": "org/x", "modality": "decide"})
