"""A GGUF-first repo with no top-level config.json routes to llama-server, and a loader missing a file in our own snapshot is the harness's fault. #911."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from evals.core import Case, summarize  # noqa: E402
from evals.runners.base import BaseRunner, RunnerError  # noqa: E402
from harness import downloads, gguf, reasons, screen  # noqa: E402
from harness import memory_store as ms  # noqa: E402
from harness.commands import loop as loop_cmd  # noqa: E402

REPO = "Ninnix96/Qwengram-0.8B"
SNAP = "/HF_ROOT/hub/models--Ninnix96--Qwengram-0.8B/snapshots/9efeb01d97b8156062e0a524a70b417dd7f045a7"
LIVE = ("chunk-bytes: warm-up: gateway returned HTTP 404: {\"error\": \"[Errno 2] "
        f"No such file or directory: '{SNAP}/config.json'\"}}")
#: The top level of the live Qwengram-0.8B snapshot; its safetensors/ and runtime/ subdirectories hold the rest.
TOP = {"QwenGram-0.8B-BF16.gguf": 64, "QwenGram-0.8B-Q4_K_M.gguf": 32,
       "QwenGram-0.8B-Q6_K.gguf": 40, "QwenGram-0.8B-Q8_0.gguf": 48,
       "reader.safetensors": 8, "arbiter.pt": 1, "tokenizer.json": 1,
       "tokenizer_config.json": 1, "README.md": 1}


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("LLAMACPP_MODELS_DIR", str(tmp_path / "gguf"))
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf"))
    (tmp_path / "gguf").mkdir()
    return tmp_path


def _hub(files, lane="code"):
    snap = downloads.hub_dir(REPO) / "snapshots" / "abc"
    snap.mkdir(parents=True)
    for name, size in files.items():
        (snap / name).write_bytes(b"x" * size)
    (snap / "safetensors").mkdir()
    (snap / "safetensors" / "config.json").write_text("{}", encoding="utf-8")
    import fakes
    fakes.hub_ref(snap)
    conn = ms.connect()
    ms.record(conn, ms.Seen(name=REPO, source="t", lane=lane))
    downloads.record(conn, REPO, downloads.HUB, snap.parent.parent)
    return conn


def test_gguf_beside_no_config_json_is_served_by_llama_server(home):
    conn = _hub(TOP)
    try:
        assert gguf.adopt_pending(conn) == [REPO]
        assert screen.candidate_for("code", REPO, conn=conn) == "llamacpp:QwenGram-0.8B-Q4_K_M"
    finally:
        conn.close()


def test_gguf_beside_a_loadable_safetensors_repo_stays_with_mlx(home):
    conn = _hub({**TOP, "config.json": 1, "model.safetensors": 8})
    try:
        assert gguf.adopt_pending(conn) == []
        assert screen.candidate_for("code", REPO, conn=conn) == REPO
    finally:
        conn.close()


def test_a_missing_config_json_in_our_snapshot_is_harness_error():
    runner = BaseRunner()
    runner.candidate, runner.spec = REPO, REPO
    case_id, _, detail = LIVE.partition(": ")
    summary = summarize([runner.failed(Case(case_id, "code", "p"), RunnerError(detail))])
    v = screen.outcome(0, summary, candidate=REPO)
    assert (v.outcome, v.failure_class) == ("queued", reasons.HARNESS_ERROR)


def test_the_loop_reopens_a_broken_screen_that_missed_a_file_in_our_snapshot(home, monkeypatch):
    conn = ms.connect()
    try:
        for name in (REPO, "org/real-gap", "org/declined"):
            ms.record(conn, ms.Seen(name=name, source="t", lane="code"))
        ms.decide(conn, REPO, "broken", tier=ms.SCREEN, reason=reasons.CANDIDATE,
                  detail=f"it ran and passed nothing: {LIVE}")
        ms.decide(conn, "org/real-gap", "broken", tier=ms.SCREEN, reason=reasons.CANDIDATE,
                  detail="it ran and passed nothing: chunk-bytes: gateway returned HTTP 404: "
                         "No such file or directory: 'tokenizer.json'")
        ms.decide(conn, "org/declined", "declined", tier=ms.SCREEN, reason=reasons.CANDIDATE,
                  detail=f"it ran and passed nothing: {LIVE}")
        conn.commit()
    finally:
        conn.close()
    assert loop_cmd._reopen_missing_in_snapshot() == [REPO]
    assert loop_cmd._reopen_missing_in_snapshot() == []
    conn = ms.connect()
    try:
        states = dict(conn.execute("SELECT name, state FROM proposals").fetchall())
        tier = conn.execute("SELECT v.tier FROM proposals p JOIN verdicts v "
                            "ON v.id = p.state_verdict_id WHERE p.name = ?", (REPO,)).fetchone()[0]
    finally:
        conn.close()
    assert states == {REPO: "queued", "org/real-gap": "broken", "org/declined": "declined"}
    assert tier == ms.SCREEN
