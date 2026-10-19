"""#1021: a llama-server load failure on a bare GGUF repo id and mlx-audio's whisper gap are runtime, not the candidate; a sighting of a queued name writes no verdict."""
import argparse
import subprocess
import sys
from pathlib import Path

import pytest

from evals.core import Result, summarize
from harness import candidates, cli, coherence, load_log, memory, paths, reasons, runner_gaps, screen
from harness import memory_store as ms
from harness.commands import measure as measure_cmd
from harness.commands import screen as screen_cmd
from harness.memory_store import revisit, transitions

FIXTURES = Path(__file__).parent / "fixtures" / "load_log"
#: eval.log lines 1090950-1091012: the Qwengram load that failed on llama.cpp 11146.
QWENGRAM = (FIXTURES / "qwengram-wrong-tensor-count.log").read_text(encoding="utf-8").splitlines(keepends=True)
REPO, ALIAS = "Ninnix96/Qwengram-0.8B", "QwenGram-0.8B-Q4_K_M"
#: The spec the 2026-10-19 day loop screened it as: the GGUF-only repo id the router serves (#583).
BARE = f"{REPO},temperature=0"
WARMUP = ('warm-up: gateway returned HTTP 500: {"error":{"code":500,"message":'
          f'"model name={ALIAS} failed to load","type":"server_error"}}}}')
WHISPER = "mlx-community/whisper-large-v3-mlx"
# Verdict 12798's detail, as the day loop wrote it.
NO_PROCESSOR = ("it ran and passed nothing: 1089-134686-0001: stt response had no 'text': {'error': {'message': "
                "'Processor not found. Make sure the model was loaded with a HuggingFace processor.', "
                "'type': 'ValueError'}}")


@pytest.fixture
def llama(monkeypatch):
    monkeypatch.setattr(screen, "_installed", lambda pkg: "11146")


def test_a_bare_gguf_repo_ids_load_failure_waits_on_its_load_log():
    assert reasons.classify(WARMUP, reasons.RUNNER, BARE) == reasons.LOAD_LOG_UNREAD
    assert reasons.classify(WARMUP, reasons.RUNNER, f"llamacpp:{ALIAS}") == reasons.LOAD_LOG_UNREAD
    # mlx-audio's own wording is not llama-server's.
    assert reasons.classify("HTTP 500: failed to load model", reasons.RUNNER, "org/m") == reasons.CRASHED


def test_the_load_log_decides_a_bare_spec_with_the_llama_cpp_until(llama):
    ex = load_log.cut(QWENGRAM, ALIAS)
    v = load_log.decided(WARMUP, ex, BARE, REPO, None, "here")
    assert (v.outcome, v.reason, v.until, v.failure_class) == (
        "declined", reasons.RUNTIME, "version:llama.cpp>11146", reasons.LOAD_FAILED_RUNTIME)
    assert "wrong number of tensors; expected 346, got 335" in v.detail


class _Done:
    returncode = 0
    stderr = ""


def _latest(conn, name):
    return conn.execute("SELECT v.* FROM verdicts v JOIN proposals p ON p.state_verdict_id = v.id "
                        "WHERE p.name = ?", (name,)).fetchone()


def test_the_live_screen_of_a_bare_gguf_repo_keeps_the_load_log_and_declines_it(monkeypatch, tmp_path, llama):
    real = ms.connect
    monkeypatch.setattr(ms, "connect", lambda *a, **k: real(tmp_path / "d.db"))
    conn = ms.connect()
    ms.record(conn, ms.Seen(name=REPO, source="t", kind="weights", lane="code", why="seeded"))
    conn.close()
    plan = [{"name": REPO, "state": screen.READY, "candidate": BARE, "modality": "code", "why_not": ""}]
    monkeypatch.setattr(screen_cmd, "_screen_plan", lambda want: plan)
    monkeypatch.setattr(screen_cmd, "snapshot_gap", lambda r, c: "")
    monkeypatch.setattr(memory, "check_model", lambda *a, **k: (True, ""))
    monkeypatch.setattr(screen, "argv", lambda r, **k: ["screen", r["name"]])
    monkeypatch.setattr(subprocess, "run", lambda argv, **kw: _Done())
    key = candidates.key_of(BARE)
    rows = [Result(case, key, False, 0.0, 0, WARMUP, failure_class=reasons.classify(WARMUP, reasons.RUNNER, BARE))
            for case in ("chunk-bytes", "evaluate-expr")]
    monkeypatch.setattr(measure_cmd, "_receipt_at", lambda out: {"summary": summarize(rows)})
    paths.logs().mkdir(parents=True, exist_ok=True)
    (paths.logs() / "eval.log").write_text("".join(QWENGRAM), encoding="utf-8")
    cli._report_screen(argparse.Namespace(lane="", top=5, limit=5, run=True, json=False))
    outdir = next(paths.runs().glob("screen-*"))
    assert "[50345]" in (outdir / load_log.FILE).read_text(encoding="utf-8")
    conn = ms.connect()
    try:
        v = _latest(conn, REPO)
        assert (v["outcome"], v["reason"], v["until"], v["failure_class"]) == (
            "declined", reasons.RUNTIME, "version:llama.cpp>11146", reasons.LOAD_FAILED_RUNTIME)
    finally:
        conn.close()


def test_mlx_audios_missing_processor_on_whisper_is_a_runner_gap(monkeypatch):
    monkeypatch.setattr(runner_gaps, "has_package", lambda dist, venv="": False)
    spec = f"stt:{WHISPER}"
    cls = reasons.classify(NO_PROCESSOR, reasons.RUNNER, spec)
    assert cls == reasons.LOAD_FAILED_LAYOUT
    v = screen.decide_class(cls, NO_PROCESSOR.removeprefix("it ran and passed nothing: "), spec)
    assert (v.outcome, v.reason, v.until) == ("declined", reasons.RUNTIME, "package:mlx-whisper@whisper")
    assert not transitions.incoherent(v.outcome, v.reason, v.until)
    # Another stt repo without a processor waits on a runner for its layout, still not the candidate.
    other = screen.decide_class(cls, NO_PROCESSOR, "stt:org/some-asr")
    assert other.reason == reasons.RUNTIME and other.until.startswith("runner:stt/")
    # The phrase is mlx-audio's stt server's; a text model saying it is still its own crash.
    assert reasons.classify(NO_PROCESSOR, reasons.RUNNER, "org/m") == reasons.CRASHED


def test_the_whisper_until_is_met_once_mlx_whisper_is_installed():
    assert revisit.until_met("package:mlx-whisper@whisper", {"packages": {"whisper": {"mlx-whisper"}}})
    assert not revisit.until_met("package:mlx-whisper@whisper", {"packages": {"whisper": set()}})


def test_a_whisper_repo_screens_through_mlx_whisper_when_its_group_installs_it(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    assert screen.candidate_for("stt", WHISPER) == f"stt:{WHISPER}"
    monkeypatch.setattr(sys, "platform", "darwin")
    assert screen.candidate_for("stt", WHISPER) == f"stt:{WHISPER},backend=whisper"
    # openai's own repo is a PyTorch checkpoint mlx-whisper does not read; parakeet is no whisper.
    assert screen.candidate_for("stt", "openai/whisper-large-v3") == "stt:openai/whisper-large-v3"
    assert screen.candidate_for("stt", "mlx-community/parakeet-tdt-0.6b-v2") == \
        "stt:mlx-community/parakeet-tdt-0.6b-v2"


def _broken(conn, name, detail, spec, run_dir=""):
    ms.record(conn, ms.Seen(name=name, source="t", registry=ms.HUGGINGFACE, lane="code", resolved=name))
    pid = conn.execute("SELECT id FROM proposals WHERE name = ?", (name,)).fetchone()[0]
    cid = candidates.ensure(conn, spec, proposal=name, lane="code")
    run_id = None
    if run_dir:
        run_id = conn.execute("INSERT INTO runs (path, tier, recorded_at) VALUES (?, 'screen', 0)", (run_dir,)).lastrowid
    transitions._write(conn, pid, name, {"outcome": "broken", "tier": "screen", "detail": detail,
                                         "decided_at": 1792410700.0, "until": "", "reason": "candidate",
                                         "failure_class": reasons.CRASHED, "candidate_id": cid,
                                         "run_id": run_id})
    conn.commit()


def test_coherence_re_decides_both_live_verdicts(tmp_path, monkeypatch, llama):
    monkeypatch.setattr(runner_gaps, "has_package", lambda dist, venv="": False)
    conn = ms.connect(tmp_path / "s.db")
    run = tmp_path / "runs" / "screen-1792410689-code"
    run.mkdir(parents=True)
    log = tmp_path / "eval.log"
    log.write_text("".join(QWENGRAM), encoding="utf-8")
    try:
        _broken(conn, REPO, f"it ran and passed nothing: chunk-bytes: {WARMUP}", REPO, str(run))
        _broken(conn, WHISPER, NO_PROCESSOR, f"stt:{WHISPER}")
        found = {c["name"]: c for c in coherence.changes(conn, logs=[log])}
        assert found[REPO]["now"] == ["declined", "screen", reasons.RUNTIME, "version:llama.cpp>11146"]
        assert found[WHISPER]["now"] == ["declined", "screen", reasons.RUNTIME, "package:mlx-whisper@whisper"]
        coherence.apply(conn, list(found.values()))
        assert (run / load_log.FILE).is_file()
        for name, cls in ((REPO, reasons.LOAD_FAILED_RUNTIME), (WHISPER, reasons.LOAD_FAILED_LAYOUT)):
            v = _latest(conn, name)
            assert (v["outcome"], v["failure_class"]) == ("declined", cls)
        assert coherence.changes(conn, logs=[log]) == []
    finally:
        conn.close()


def test_two_parents_naming_one_queued_weight_write_one_verdict(tmp_path, monkeypatch):
    from harness import github
    from harness import inspect as ins
    from tests.test_harness_registry import _no_model
    monkeypatch.setattr(paths, "home", lambda: tmp_path)
    monkeypatch.setenv(paths.ENV_VAR, str(tmp_path))
    weight = "mlx-community/whisper-tiny"
    parents = ("cubist38/mlx-openai-server", "ml-explore/mlx-examples")
    conn = ms.connect()
    for p in parents:
        ms.record(conn, ms.Seen(name=p, source="t", registry=ms.GITHUB, resolved=p))
    conn.close()

    class Client:
        stale: list = []
        spent = 0

        def __init__(self, **kw):
            pass

        def repo(self, name):
            return {"size": 10, "description": "a tool"}

    monkeypatch.setattr(github, "Client", Client)
    monkeypatch.setattr(ins, "ceiling_bytes", lambda *a, **k: 66 * 2**30)
    monkeypatch.setattr(ins, "inspect", lambda repo, work, meta=None, **kw: ins.Fit(
        repo=repo, registry=ms.GITHUB, verdict="fits", weights={weight: 2**26},
        headline=[weight], lanes={weight: "stt"}))
    monkeypatch.setattr(ins, "hf_model", _no_model)
    args = type("A", (), {"repos": list(parents), "from_store": False, "top": 10, "budget": 10,
                          "shard": "", "judge": False, "json": False})()
    assert cli._report_inspect(args) == 0
    assert cli._report_inspect(args) == 0
    conn = ms.connect()
    try:
        rows = conn.execute("SELECT v.outcome, v.tier FROM verdicts v JOIN proposals p ON p.id = v.proposal_id "
                            "WHERE p.name = ?", (weight,)).fetchall()
        assert [tuple(r) for r in rows] == [("queued", ms.INSPECT)]
        assert sorted(ms.parents(conn, weight)) == sorted(parents)
    finally:
        conn.close()
