"""A llama-server load failure is decided from its child's own log, kept with the run. #953."""
import argparse
import itertools
import subprocess
from pathlib import Path

import pytest

from harness import cli, downloads, live_audit, load_log, memory, paths, reasons, screen
from harness import candidates as cands
from harness import memory_store as ms
from harness.commands import measure as measure_cmd
from harness.commands import screen as screen_cmd

FIXTURES = Path(__file__).parent / "fixtures" / "load_log"
#: eval.log lines 32355-32390: K2-Horizon on 0.5.0, port 55991, verdict 9289.
K2 = (FIXTURES / "k2-horizon-unknown-arch.log").read_text(encoding="utf-8").splitlines(keepends=True)
#: eval.log lines 28716-28756: Nex-N2 on 0.5.0, port 52611, verdict 9144.
NEX = (FIXTURES / "nex-n2-offset-mismatch.log").read_text(encoding="utf-8").splitlines(keepends=True)
K2_ALIAS, NEX_ALIAS = "K2-Horizon-7B-Q4_K_M", "Nex-N2-mini-Turbo-Phase-Twin"
K2_REPO, NEX_REPO = "IFM/K2-Horizon-7B-GGUF", "Frosty40/Nex-N2-mini-Turbo-Phase-Twin"


def _500(alias):
    return ('chunk-bytes: gateway returned HTTP 500: {"error":{"code":500,"message":'
            f'"model name={alias} failed to load","type":"server_error"}}}}')


def test_the_nex_n2_reply_alone_is_no_longer_a_runtime_gap():
    """Red first: before #953 this 500 was load_failed_runtime with a llama.cpp until."""
    got = reasons.classify(_500(NEX_ALIAS), reasons.RUNNER, f"llamacpp:{NEX_ALIAS}")
    assert got == reasons.LOAD_LOG_UNREAD
    v = screen.decide_class(got, _500(NEX_ALIAS), f"llamacpp:{NEX_ALIAS}")
    assert (v.outcome, v.reason, v.until) == ("queued", "harness", "")


def test_an_unknown_architecture_stays_a_runtime_gap(monkeypatch):
    monkeypatch.setattr(screen, "_installed", lambda pkg: "11146")
    ex = load_log.cut(K2, K2_ALIAS)
    assert reasons.classify("".join(ex.lines), reasons.RUNNER, f"llamacpp:{K2_ALIAS}") \
        == reasons.LOAD_FAILED_RUNTIME
    v = load_log.decided(_500(K2_ALIAS), ex, f"llamacpp:{K2_ALIAS}", K2_REPO, None, "here")
    assert (v.outcome, v.reason, v.until) == ("declined", "runtime", "version:llama.cpp>11146")
    assert "unknown model architecture: 'k2-horizon'" in v.detail


def test_a_header_that_disagrees_with_itself_is_the_files_fault(tmp_path):
    conn = ms.connect(tmp_path / "d.db")
    gguf = tmp_path / f"{NEX_ALIAS}.gguf"
    gguf.write_bytes(b"GGUF")
    downloads.record(conn, NEX_REPO, downloads.GGUF, gguf, file=gguf.name, at=1791246487.4)
    ex = load_log.cut(NEX, NEX_ALIAS)
    v = load_log.decided(_500(NEX_ALIAS), ex, f"llamacpp:{NEX_ALIAS}", NEX_REPO, conn, "here")
    assert (v.outcome, v.reason, v.failure_class) == ("declined", "candidate", reasons.LOAD_FAILED_FILE)
    assert v.until == "commit_after:2026-10-06T00:28:07Z"
    assert "has offset 1078173696, expected 1046716416" in v.detail


def test_the_excerpt_keeps_only_its_own_port_and_the_routers_spawn_and_exit():
    ex = load_log.cut(K2, K2_ALIAS)
    assert ex.first == 5 and ex.status == 1
    assert ex.lines[0].rstrip().endswith("on port 55991")
    assert ex.lines[-1].rstrip().endswith(f"instance name={K2_ALIAS} exited with status 1")
    assert not any(line.startswith("[55987]") for line in ex.lines)
    assert any("/opt/homebrew/Cellar/llama.cpp/0.5.0/bin/llama-server" in line for line in ex.lines)


def test_two_concurrent_loads_each_get_their_own_excerpt():
    mixed = [line for pair in itertools.zip_longest(NEX, K2) for line in pair if line]
    k2, nex = load_log.cut(mixed, K2_ALIAS), load_log.cut(mixed, NEX_ALIAS)
    assert all(not line.startswith("[52611]") for line in k2.lines)
    assert all(not line.startswith("[55991]") for line in nex.lines)
    assert reasons.classify("".join(k2.lines), reasons.RUNNER, f"llamacpp:{K2_ALIAS}") \
        == reasons.LOAD_FAILED_RUNTIME
    assert reasons.classify("".join(nex.lines), reasons.RUNNER, f"llamacpp:{NEX_ALIAS}") \
        == reasons.LOAD_FAILED_FILE


def test_no_spawn_line_for_the_alias_leaves_it_the_harnesss(tmp_path):
    log = tmp_path / "eval.log"
    log.write_text("".join(NEX), encoding="utf-8")
    assert load_log.find(K2_ALIAS, [log]) is None
    unread = screen.decide_class(reasons.LOAD_LOG_UNREAD, _500(K2_ALIAS), f"llamacpp:{K2_ALIAS}")
    assert load_log.redecide(unread, f"llamacpp:{K2_ALIAS}", K2_REPO, tmp_path, None, [log]) == unread
    assert not (tmp_path / load_log.FILE).exists()


def test_a_load_that_exited_cleanly_is_not_the_failure():
    clean = [line.replace("exited with status 1", "exited with status 0") for line in K2]
    assert load_log.cut(clean, K2_ALIAS) is None


#: llama.cpp's own message for a tensor past the end of the file, in Nex-N2's load.
SHORT = [line.replace("tensor 'blk.0.ffn_gate_inp.weight' has offset 1078173696, expected 1046716416",
                      "tensor 'blk.0.ffn_gate_inp.weight' data is not within the file bounds, "
                      "model is corrupted or incomplete") for line in NEX]


def test_a_short_copy_is_ours_to_refetch():
    ex = load_log.cut(SHORT, NEX_ALIAS)
    assert reasons.classify("".join(ex.lines), reasons.RUNNER, f"llamacpp:{NEX_ALIAS}") == reasons.SHORT_COPY
    assert reasons.CLASSES[reasons.SHORT_COPY] == ("queued", "harness")


class _Done:
    returncode = 0
    stderr = ""


def _latest(conn, name):
    return conn.execute("SELECT v.* FROM verdicts v JOIN proposals p ON p.state_verdict_id = v.id "
                        "WHERE p.name = ?", (name,)).fetchone()


def _screen(monkeypatch, tmp_path, log_lines, name=NEX_REPO, alias=NEX_ALIAS):
    real = ms.connect
    monkeypatch.setattr(ms, "connect", lambda *a, **k: real(tmp_path / "d.db"))
    conn = ms.connect()
    ms.record(conn, ms.Seen(name=name, source="t", kind="weights", lane="code", why="seeded"))
    gguf = tmp_path / f"{alias}.gguf"
    gguf.write_bytes(b"GGUF")
    downloads.record(conn, name, downloads.GGUF, gguf, file=gguf.name, at=1791246487.4)
    conn.close()
    spec = f"llamacpp:{alias}"
    plan = [{"name": name, "state": screen.READY, "candidate": spec, "modality": "code", "why_not": ""}]
    monkeypatch.setattr(screen_cmd, "_screen_plan", lambda want: plan)
    monkeypatch.setattr(screen_cmd, "snapshot_gap", lambda r, c: "")
    monkeypatch.setattr(memory, "check_model", lambda *a, **k: (True, ""))
    monkeypatch.setattr(screen, "argv", lambda r, **k: ["screen", r["name"]])
    monkeypatch.setattr(subprocess, "run", lambda argv, **kw: _Done())
    monkeypatch.setattr(measure_cmd, "_receipt_at", lambda out: {"summary": {alias: {"passed": 0}}})
    monkeypatch.setattr(screen_cmd, "verdict_of_run", lambda *a, **k: screen.decide_class(
        reasons.LOAD_LOG_UNREAD, _500(alias), spec))
    paths.logs().mkdir(parents=True, exist_ok=True)
    (paths.logs() / "eval.log").write_text("".join(log_lines), encoding="utf-8")
    cli._report_screen(argparse.Namespace(lane="", top=5, limit=5, run=True, json=False))
    return next(paths.runs().glob("screen-*"))


def test_the_screen_keeps_the_childs_log_and_decides_from_it(monkeypatch, tmp_path):
    outdir = _screen(monkeypatch, tmp_path, NEX)
    kept = (outdir / load_log.FILE).read_text(encoding="utf-8")
    assert kept.startswith("# eval.log lines 5-40\n") and "[52611]" in kept
    conn = ms.connect()
    try:
        v = _latest(conn, NEX_REPO)
        assert (v["outcome"], v["reason"], v["until"]) == ("declined", "candidate",
                                                          "commit_after:2026-10-06T00:28:07Z")
        assert "has offset 1078173696" in v["detail"] and load_log.FILE in v["detail"]
    finally:
        conn.close()


def test_the_screen_sends_a_short_copy_back_to_fetch(monkeypatch, tmp_path):
    _screen(monkeypatch, tmp_path, SHORT)
    conn = ms.connect()
    try:
        v = _latest(conn, NEX_REPO)
        assert (v["outcome"], v["tier"], v["reason"]) == ("queued", ms.FETCH, "harness")
        assert not downloads.have(NEX_REPO, conn, stat=False)
    finally:
        conn.close()


def _held(conn, tmp_path, name, alias, until):
    run = tmp_path / "runs" / f"screen-{alias}-code"
    run.mkdir(parents=True)
    cid = cands.ensure(conn, f"llamacpp:{alias}", proposal=name, lane="code")
    ms.record(conn, ms.Seen(name=name, source="t", kind="weights", lane="code", why="seeded"))
    ms.decide(conn, name, "queued", tier=ms.FETCH, reason="candidate")
    return run, ms.decide(conn, name, "declined", tier=ms.SCREEN, reason="runtime", until=until,
                          detail=f"the installed runtime could not load it: {_500(alias)}",
                          run_path=str(run), candidate_id=cid)


def test_load_log_redecides_held_rows_from_the_router_log(monkeypatch, tmp_path):
    monkeypatch.setattr(screen, "_installed", lambda pkg: "99999")
    log = tmp_path / "eval.log"
    log.write_text("".join(NEX + K2), encoding="utf-8")
    conn = ms.connect(tmp_path / "d.db")
    k2_run, k2_id = _held(conn, tmp_path, K2_REPO, K2_ALIAS, "version:llama.cpp>11146")
    nex_run, nex_id = _held(conn, tmp_path, NEX_REPO, NEX_ALIAS, "version:llama.cpp>11146")
    conn.commit()
    assert {r["id"] for r in load_log.unkept(conn)} == {k2_id, nex_id}
    assert len(live_audit._load_log_kept(conn, pinned=frozenset())[0]) == 2
    found = load_log.changes(conn, [log])
    by = {c["name"]: c for c in found}
    # The version it failed on, not today's install.
    assert by[K2_REPO]["now"] == ["declined", "runtime", "version:llama.cpp>11146"]
    assert by[NEX_REPO]["now"][:2] == ["declined", "candidate"]
    assert "eval.log lines 46-77" in by[K2_REPO]["detail"]
    load_log.apply(conn, found)
    assert (k2_run / load_log.FILE).read_text(encoding="utf-8").startswith("# eval.log lines 46-77\n")
    assert load_log.unkept(conn) == [] and live_audit._load_log_kept(conn, pinned=frozenset()) == ([], [])
    v = _latest(conn, NEX_REPO)
    assert v["detail"].startswith("re-decided from the router log (#953): the file is malformed")
    conn.close()


def test_the_load_log_command_is_read_only_without_apply(tmp_path):
    log = tmp_path / "eval.log"
    log.write_text("".join(NEX), encoding="utf-8")
    db = tmp_path / "d.db"
    conn = ms.connect(db)
    run, vid = _held(conn, tmp_path, NEX_REPO, NEX_ALIAS, "version:llama.cpp>11146")
    conn.commit()
    conn.close()
    assert cli.main(["load-log", "--db", str(db), "--log", str(log)]) == 0
    assert not (run / load_log.FILE).exists()
    conn = ms.connect(db)
    assert _latest(conn, NEX_REPO)["id"] == vid
    conn.close()
    assert cli.main(["load-log", "--db", str(db), "--log", str(log), "--apply"]) == 0
    assert (run / load_log.FILE).is_file()


@pytest.mark.parametrize("name", ["eval.log", "llamacpp.err.log"])
def test_the_router_log_is_found_where_each_service_manager_writes_it(name):
    assert paths.logs() / name in load_log.router_logs()
