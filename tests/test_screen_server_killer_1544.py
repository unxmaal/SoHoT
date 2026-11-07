"""A candidate whose screens keep killing the shared server is declined until the runtime moves; a restarted server is no failed sweep. #1544."""
import argparse
import json
import subprocess
import time

from harness.commands import measure as measure_cmd
from harness.commands import screen as screen_cmd
from harness import cli, knobs, memory, mlx_server, reasons, screen
from harness import memory_store as ms


class _Done:
    returncode = 0
    stderr = ""


def _setup(monkeypatch, tmp_path, verdicts, names=("org/first", "org/second")):
    """Each screen reads the next (name -> (verdict, mlx-lm version)) from `verdicts`, a list of sweeps."""
    real = ms.connect
    monkeypatch.setattr(ms, "connect", lambda *a, **k: real(tmp_path / "d.db"))
    conn = ms.connect()
    for n in names:
        ms.record(conn, ms.Seen(name=n, source="t", kind="weights", lane="code", why="seeded"))
    conn.close()
    plan = [{"name": n, "state": screen.READY, "candidate": n, "modality": "code", "why_not": ""} for n in names]
    monkeypatch.setattr(screen_cmd, "_screen_plan", lambda want: plan)
    monkeypatch.setattr(memory, "check_model", lambda *a, **k: (True, ""))
    monkeypatch.setattr(screen, "argv", lambda r, **k: ["screen", r["name"]])
    ran = []
    monkeypatch.setattr(subprocess, "run", lambda argv, **kw: (argv[0] == "screen" and ran.append(argv[-1])) or _Done())
    now = {}

    def receipt(out):
        verdict, version = verdicts[ran[-1]]
        env = {"versions": {"mlx-lm": version}}
        c = ms.connect()
        try:
            rid = c.execute("INSERT INTO runs (path, environment, recorded_at) VALUES (?, ?, ?)",
                            (str(out), json.dumps(env), time.time())).lastrowid
            c.commit()
        finally:
            c.close()
        now["verdict"] = verdict
        return {"run_id": rid, "environment": env, "summary": {"x": {"passed": 0}}}
    monkeypatch.setattr(measure_cmd, "_receipt_at", receipt)
    monkeypatch.setattr(screen, "outcome", lambda *a, **k: now["verdict"])
    return ran


def _sweep():
    return cli._report_screen(argparse.Namespace(lane="", top=5, limit=5, run=True, json=False))


def _latest(name):
    conn = ms.connect()
    try:
        row = conn.execute("SELECT v.* FROM verdicts v JOIN proposals p ON p.id = v.proposal_id "
                           "WHERE p.name = ? ORDER BY v.id DESC LIMIT 1", (name,)).fetchone()
        return dict(row)
    finally:
        conn.close()


DEAD = screen.decide_class(reasons.SERVER_DEAD)
FAILED = screen.decide_class(reasons.CONTENT_FAILED)


def test_a_candidate_that_kills_the_server_twice_on_one_version_is_declined_until_it_moves(monkeypatch, tmp_path):
    verdicts = {"org/first": (DEAD, "0.32.0"), "org/second": (FAILED, "0.32.0")}
    _setup(monkeypatch, tmp_path, verdicts)
    assert _sweep() == 1
    first = _latest("org/first")
    assert (first["outcome"], first["failure_class"]) == ("queued", reasons.SERVER_DEAD)
    assert _sweep() == 1
    got = _latest("org/first")
    assert (got["outcome"], got["reason"], got["failure_class"]) == ("declined", reasons.RUNTIME, reasons.KILLS_SERVER)
    assert got["until"] == "version:mlx-lm>0.32.0"
    assert ms.until_met(got["until"], {"versions": {"mlx-lm": "0.33.0"}})
    assert not ms.until_met(got["until"], {"versions": {"mlx-lm": "0.32.0"}})


def test_deaths_on_different_runtime_versions_are_not_counted_together(monkeypatch, tmp_path):
    verdicts = {"org/first": (DEAD, "0.31.0"), "org/second": (FAILED, "0.32.0")}
    _setup(monkeypatch, tmp_path, verdicts)
    _sweep()
    verdicts["org/first"] = (DEAD, "0.32.0")
    _sweep()
    assert (_latest("org/first")["outcome"], _latest("org/first")["failure_class"]) == ("queued", reasons.SERVER_DEAD)


def test_another_candidates_death_is_not_this_ones(monkeypatch, tmp_path):
    verdicts = {"org/first": (DEAD, "0.32.0"), "org/second": (DEAD, "0.32.0")}
    _setup(monkeypatch, tmp_path, verdicts, names=("org/first",))
    _sweep()
    _setup(monkeypatch, tmp_path, verdicts, names=("org/second",))
    _sweep()
    for n in ("org/first", "org/second"):
        assert (_latest(n)["outcome"], _latest(n)["failure_class"]) == ("queued", reasons.SERVER_DEAD)


def test_a_restarted_server_does_not_fail_the_sweep(monkeypatch, tmp_path):
    ran = _setup(monkeypatch, tmp_path, {"org/first": (DEAD, "0.32.0"), "org/second": (FAILED, "0.32.0")})
    monkeypatch.setattr(mlx_server, "generating", lambda base, timeout, opener=None: True)
    assert _sweep() == 0 and ran == ["org/first"]
    assert _latest("org/first")["failure_class"] == reasons.SERVER_DEAD


def test_a_gpu_fault_still_fails_the_sweep_with_the_server_up(monkeypatch, tmp_path):
    """Negative control: only a server death is waited out."""
    fault = screen.decide_class(reasons.GPU_FAULT)
    verdicts = {"org/first": (DEAD, "0.32.0"), "org/second": (FAILED, "0.32.0")}
    _setup(monkeypatch, tmp_path, verdicts)
    monkeypatch.setattr(mlx_server, "generating", lambda base, timeout, opener=None: True)
    assert _sweep() == 0
    verdicts["org/first"] = (fault, "0.32.0")
    assert _sweep() == 1 and _latest("org/first")["failure_class"] == reasons.GPU_FAULT, "a GPU fault is no server kill"


def test_the_wait_looks_again_until_the_server_generates(monkeypatch):
    answers = iter((False, None, True))
    clock = iter((0.0, 1.0, 2.0, 3.0))
    slept = []
    monkeypatch.setattr(screen_cmd, "SERVER_BACK_WAIT_S", 600.0)
    monkeypatch.setattr(mlx_server, "generating", lambda base, timeout, opener=None: next(answers))
    monkeypatch.setattr(screen_cmd.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(screen_cmd.time, "sleep", slept.append)
    assert screen_cmd.server_back("http://x") is True and len(slept) == 2


def test_the_wait_gives_up_at_its_bound(monkeypatch):
    clock = iter((0.0, 400.0, 700.0))
    monkeypatch.setattr(screen_cmd, "SERVER_BACK_WAIT_S", 600.0)
    monkeypatch.setattr(mlx_server, "generating", lambda base, timeout, opener=None: None)
    monkeypatch.setattr(screen_cmd.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(screen_cmd.time, "sleep", lambda s: None)
    assert screen_cmd.server_back("http://x") is False


def test_the_thresholds_are_registered_knobs():
    for name, unit in (("screen_server_kills", "screens"), ("screen_server_back_wait", "s")):
        k = knobs.KNOBS[name]
        assert k.unit == unit and k.default() in k.values and "#1544" in k.note, name
    assert reasons.CLASSES[reasons.KILLS_SERVER] == ("declined", reasons.RUNTIME)
    assert reasons.KILLS_SERVER in reasons.STOPS and reasons.KILLS_SERVER not in reasons.NEVER_RAN


def test_one_already_past_the_count_on_the_installed_version_is_declined_unscreened(monkeypatch, tmp_path):
    verdicts = {"org/first": (DEAD, "0.32.0")}
    ran = _setup(monkeypatch, tmp_path, verdicts, names=("org/first",))
    monkeypatch.setattr(screen_cmd, "SERVER_KILLS", 3)
    _sweep()
    _sweep()
    assert ran == ["org/first", "org/first"] and _latest("org/first")["failure_class"] == reasons.SERVER_DEAD
    monkeypatch.setattr(screen_cmd, "SERVER_KILLS", 2)
    monkeypatch.setattr(screen, "_installed", lambda pkg: {"mlx-lm": "0.33.0"}.get(pkg, "0"))
    verdicts["org/first"] = (DEAD, "0.33.0")
    _sweep()
    assert len(ran) == 3 and _latest("org/first")["failure_class"] == reasons.SERVER_DEAD, "a moved runtime screens it"
    monkeypatch.setattr(screen, "_installed", lambda pkg: {"mlx-lm": "0.32.0"}.get(pkg, "0"))
    _sweep()
    got = _latest("org/first")
    assert len(ran) == 3 and (got["outcome"], got["failure_class"]) == ("declined", reasons.KILLS_SERVER)


def test_an_engine_candidates_death_is_not_waited_out_on_the_mlx_server(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, {"tts:org/voice": (DEAD, "0.32.0")}, names=("tts:org/voice",))
    monkeypatch.setattr(mlx_server, "generating", lambda base, timeout, opener=None: True)
    assert _sweep() == 1
