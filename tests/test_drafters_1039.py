"""#1039: a speculative-decoding drafter is an attachment, at inspect from its card and at screen from llama.cpp's ctx_other refusal."""
import argparse
import json
import subprocess
from pathlib import Path

import pytest

from harness import cli, coherence, downloads, fetching, load_log, memory, paths, reasons, screen
from harness import inspect as ins
from harness import memory_store as ms
from harness.commands import measure as measure_cmd
from harness.commands import screen as screen_cmd

CARDS = Path(__file__).parent / "fixtures" / "registry" / "drafters_1039"
#: eval.log lines 1092571-1092613: the Alittlehammmer drafter on llama.cpp 0.5.0, port 49215, verdict 12827.
DFLASH = (Path(__file__).parent / "fixtures" / "load_log" / "dflash-ctx-other.log").read_text(
    encoding="utf-8").splitlines(keepends=True)
ALIAS = "Qwen3.6-35B-A3B-DFlash-Q4_K_M"
LITTLE, ANBEELD = "Alittlehammmer/Qwen3.6-35B-A3B-DFlash-GGUF-llama.cpp", "Anbeeld/gemma-4-31B-it-DFlash-GGUF"
ZLAB, MIMO, QWOPUS = "z-lab/Qwen3.6-35B-A3B-DFlash", "XiaomiMiMo/MiMo-V2.5-Pro-FP4-DFlash", "Jackrong/Qwopus3.8-27B-Flash"
GIB = fetching.GIB


def _card(repo: str) -> dict:
    return json.loads((CARDS / f"{repo.replace('/', '_')}.json").read_text(encoding="utf-8"))


def _500(alias=ALIAS):
    return ('chunk-bytes: gateway returned HTTP 500: {"error":{"code":500,"message":'
            f'"model name={alias} failed to load","type":"server_error"}}}}')


@pytest.mark.parametrize("repo", [LITTLE, ANBEELD, ZLAB])
def test_a_drafters_card_reads_as_an_attachment(repo):
    assert ins.card_facts(_card(repo)).attaches_to == screen.DRAFTER


@pytest.mark.parametrize("repo", [MIMO, QWOPUS])
def test_a_full_model_tagged_dflash_or_speculative_decoding_is_not_one(repo):
    assert ins.card_facts(_card(repo)).attaches_to == ""


def test_the_gguf_architecture_alone_names_the_llama_cpp_drafter():
    data = _card(LITTLE)
    assert not screen.is_drafter(data["tags"], data.get("config"))
    assert screen.is_drafter([], gguf={"architecture": "dflash"})
    assert not screen.is_drafter([], gguf={"architecture": "qwen3"})


@pytest.mark.parametrize("repo", [LITTLE, ANBEELD])
def test_inspect_then_fetch_declines_a_drafter_without_downloading_it(tmp_path, repo):
    conn = ms.connect(tmp_path / "d.db")
    try:
        ms.record(conn, ms.Seen(name=repo, source="t", lane="code", registry=ms.HUGGINGFACE, resolved=repo))
        ms.set_size(conn, repo, 4 * GIB)
        assert ms.set_card(conn, repo, ins.card_facts(_card(repo)))
        ms.decide(conn, repo, "queued", tier="inspect", detail="fits")
        got = fetching.run(conn, {repo: 4 * GIB}, limit=1,
                           snapshot=lambda *a, **k: pytest.fail("a drafter must never be downloaded"))
        assert got and not got[0]["ok"] and "attaches to a model" in got[0]["why"]
        v = conn.execute("SELECT v.outcome, v.tier, v.reason, v.until FROM verdicts v JOIN proposals p "
                         "ON p.state_verdict_id = v.id WHERE p.name = ?", (repo,)).fetchone()
        assert tuple(v) == ("declined", "fetch", reasons.CANDIDATE, "")
    finally:
        conn.close()


def test_llama_servers_ctx_other_refusal_is_an_attachment_not_a_runtime_gap(monkeypatch):
    monkeypatch.setattr(screen, "_installed", lambda pkg: "11146")
    ex = load_log.cut(DFLASH, ALIAS)
    assert ex is not None and ex.status == 1
    v = load_log.decided(_500(), ex, f"llamacpp:{ALIAS}", LITTLE, None, "here")
    assert (v.outcome, v.reason, v.until, v.failure_class) == (
        "declined", reasons.CANDIDATE, "", reasons.ATTACHMENT)
    assert "requires ctx_other" in v.detail and v.detail.startswith("a speculative-decoding drafter")
    # Another child error stays the runtime's, waiting on a newer llama.cpp.
    other = [line.replace("dflash requires ctx_other to be set", "boom") for line in DFLASH]
    assert load_log.decided(_500(), load_log.cut(other, ALIAS), f"llamacpp:{ALIAS}", LITTLE, None,
                            "here").failure_class == reasons.LOAD_FAILED_RUNTIME


class _Done:
    returncode = 0
    stderr = ""


def test_the_screen_holds_a_drafter_at_fetch_so_no_retest_refetches_it(monkeypatch, tmp_path):
    real = ms.connect
    monkeypatch.setattr(ms, "connect", lambda *a, **k: real(tmp_path / "d.db"))
    conn = ms.connect()
    ms.record(conn, ms.Seen(name=LITTLE, source="t", kind="weights", lane="code", why="seeded"))
    gguf = tmp_path / f"{ALIAS}.gguf"
    gguf.write_bytes(b"GGUF")
    downloads.record(conn, LITTLE, downloads.GGUF, gguf, file=gguf.name, at=1791246487.4)
    conn.close()
    spec = f"llamacpp:{ALIAS}"
    plan = [{"name": LITTLE, "state": screen.READY, "candidate": spec, "modality": "code", "why_not": ""}]
    monkeypatch.setattr(screen_cmd, "_screen_plan", lambda want: plan)
    monkeypatch.setattr(screen_cmd, "snapshot_gap", lambda r, c: "")
    monkeypatch.setattr(memory, "check_model", lambda *a, **k: (True, ""))
    monkeypatch.setattr(screen, "argv", lambda r, **k: ["screen", r["name"]])
    monkeypatch.setattr(subprocess, "run", lambda argv, **kw: _Done())
    monkeypatch.setattr(measure_cmd, "_receipt_at", lambda out: {"summary": {ALIAS: {"passed": 0}}})
    monkeypatch.setattr(screen_cmd, "verdict_of_run", lambda *a, **k: screen.decide_class(
        reasons.LOAD_LOG_UNREAD, _500(), spec))
    paths.logs().mkdir(parents=True, exist_ok=True)
    (paths.logs() / "eval.log").write_text("".join(DFLASH), encoding="utf-8")
    cli._report_screen(argparse.Namespace(lane="", top=5, limit=5, run=True, json=False))
    conn = ms.connect()
    try:
        row = conn.execute("SELECT p.attaches_to, p.next_retest_at, v.outcome, v.tier, v.reason, v.until, "
                           "v.failure_class FROM proposals p JOIN verdicts v ON v.id = p.state_verdict_id "
                           "WHERE p.name = ?", (LITTLE,)).fetchone()
        assert tuple(row) == (screen.DRAFTER, None, "declined", ms.FETCH, reasons.CANDIDATE, "",
                              reasons.ATTACHMENT)
    finally:
        conn.close()


def _held(conn, name, tags, until, detail):
    ms.record(conn, ms.Seen(name=name, source="t", kind="weights", lane="code", registry=ms.HUGGINGFACE))
    conn.execute("UPDATE proposals SET card_tags = ?, card_read = 'card' WHERE name = ?", (json.dumps(tags), name))
    ms.decide(conn, name, "queued", tier=ms.FETCH, reason=reasons.CANDIDATE)
    return ms.decide(conn, name, "declined", tier=ms.SCREEN, reason=reasons.RUNTIME, until=until, detail=detail)


def test_coherence_re_decides_held_drafters_and_leaves_a_full_model(tmp_path):
    conn = ms.connect(tmp_path / "d.db")
    try:
        ctx = ("the installed runtime could not load it: llama-server: llama_init_from_model: failed to "
               "initialize the context: dflash requires ctx_other to be set (server-load.log)")
        little = _held(conn, LITTLE, _card(LITTLE)["tags"], "version:llama.cpp>11146", ctx)
        zlab = _held(conn, ZLAB, _card(ZLAB)["tags"], "format:unread-tensors",
                     "the installed runtime could not load it: chunk-bytes: gateway returned HTTP 404")
        _held(conn, MIMO, _card(MIMO)["tags"], "version:llama.cpp>11146",
              "the installed runtime could not load it: llama-server: unknown model architecture: 'mimo_v2'")
        ms.record(conn, ms.Seen(name=ANBEELD, source="t", kind="weights", lane="code", registry=ms.HUGGINGFACE))
        conn.execute("UPDATE proposals SET card_tags = ?, card_read = 'card' WHERE name = ?",
                     (json.dumps(_card(ANBEELD)["tags"]), ANBEELD))
        queued = ms.decide(conn, ANBEELD, "queued", tier="inspect", detail="fits", reason=reasons.CANDIDATE)
        conn.commit()
        found = coherence.changes(conn)
        assert {c["verdict_id"] for c in found} == {little, zlab, queued}
        assert all(c["now"] == ["declined", ms.FETCH, reasons.CANDIDATE, ""] for c in found)
        coherence.apply(conn, found)
        rows = {r["name"]: r for r in conn.execute(
            "SELECT p.name, p.attaches_to, p.next_retest_at, v.tier, v.reason, v.until, v.failure_class "
            "FROM proposals p JOIN verdicts v ON v.id = p.state_verdict_id")}
        for name in (LITTLE, ZLAB, ANBEELD):
            assert (rows[name]["attaches_to"], rows[name]["tier"], rows[name]["reason"], rows[name]["until"],
                    rows[name]["next_retest_at"]) == (screen.DRAFTER, ms.FETCH, reasons.CANDIDATE, "", None)
        assert (rows[MIMO]["attaches_to"], rows[MIMO]["reason"]) == ("", reasons.RUNTIME)
        assert coherence.changes(conn) == []
        # The card re-read keeps a drafter as one, so the audit's attachment check has nothing to say.
        assert ms.stale_attachments(conn) == []
    finally:
        conn.close()
