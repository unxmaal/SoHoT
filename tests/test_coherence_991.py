"""#991: the four verdicts pinned in terminal_reason_coherent, the paths that wrote them, and `soh coherence`."""
import sqlite3

import pytest

from harness import coherence, live_audit
from harness import inspect as ins
from harness import memory_store as ms
from harness.memory_store import transitions


def _see(conn, name, registry=ms.HUGGINGFACE, lane="code"):
    ms.record(conn, ms.Seen(name=name, source="t", registry=registry, lane=lane, resolved=name))


def _held(conn, name):
    return conn.execute("SELECT p.state, v.tier, v.reason, v.until, v.reopen_kind FROM proposals p "
                        "JOIN verdicts v ON v.id = p.state_verdict_id WHERE p.name = ?", (name,)).fetchone()


def _old(conn, name, outcome, tier, reason, until="", detail="", at=None, **kw):
    """A verdict as a pre-#991 writer left it, past the guard decide() now has."""
    _see(conn, name)
    row = {"outcome": outcome, "tier": tier, "detail": detail, "decided_at": at or 1791000000.0,
           "until": until, "reason": reason, **kw}
    pid = conn.execute("SELECT id FROM proposals WHERE name = ?", (name,)).fetchone()[0]
    vid = transitions._write(conn, pid, name, row)
    conn.commit()
    return vid


@pytest.fixture
def store(tmp_path):
    conn = ms.connect(tmp_path / "s.db")
    yield conn
    conn.close()


# --- the writer refuses each kind the audit names --------------------------

@pytest.mark.parametrize("outcome,tier,reason,until", [
    ("broken", "screen", "limit", "limit:max_tokens.code>4000"),
    ("broken", "inspect", "upstream", ""),
    ("declined", "inspect", "machine", ""),
    ("declined", "fetch", "harness", "format:.pth"),
])
def test_the_one_writer_refuses_a_verdict_the_audit_calls_incoherent(store, outcome, tier, reason, until):
    _see(store, "org/x")
    with pytest.raises(ms.IllegalTransition):
        ms.decide(store, "org/x", outcome, tier=tier, reason=reason, until=until)
    assert _held(store, "org/x") is None


@pytest.mark.parametrize("tier,at", [("", "-"), ("inspect", "inspect")])
def test_the_refusal_names_the_proposal_the_outcome_the_tier_and_why(store, tier, at):
    _see(store, "org/x")
    with pytest.raises(ms.IllegalTransition) as got:
        ms.decide(store, "org/x", "declined", tier=tier, reason="harness")
    assert str(got.value) == f"org/x: declined at {at}: a harness fault holds a terminal state"


@pytest.mark.parametrize("state,reason,why", [
    ("declined", "harness", "a harness fault holds a terminal state"),
    ("broken", "", "broken with reason empty"),
    ("broken", "machine", "broken with reason machine"),
    ("declined", "runtime", "reason runtime with no until and no retest"),
])
def test_incoherent_says_which_contradiction_it_found(state, reason, why):
    assert transitions.incoherent(state, reason) == why


def test_a_retest_tier_and_a_named_reopen_may_still_write_without_an_until(store):
    _see(store, "org/x")
    ms.decide(store, "org/x", "declined", tier="screen", reason="machine")
    assert store.execute("SELECT next_retest_at FROM proposals").fetchone()[0] is not None
    ms.decide(store, "org/x", "broken", tier="screen", reopen=ms.RETRACTION, reopen_why="a person said so")
    assert _held(store, "org/x")["state"] == "broken"


# --- the two GitHub repos: GitHub's size is the history, not the tree -------

def test_a_long_history_with_no_weights_in_the_tree_is_cloned_and_read(tmp_path):
    cloned = []

    def run(argv, cwd=None, timeout=180.0):
        if argv[1] == "clone":
            cloned.append(argv)
            d = tmp_path / "unslothai__unsloth"
            d.mkdir(exist_ok=True)
            (d / "train.py").write_text("import torch\n" * 5000, encoding="utf-8")
            (d / "sticker.png").write_bytes(b"\0" * 400_000)
        return "2026-10-17T00:00:00+00:00"

    got = ins.inspect("unslothai/unsloth", tmp_path, meta={"size": 551_645}, run=run,
                      sizer=lambda m: -1, kb_cap=250)
    assert cloned and got.verdict not in ("too-big", ins.WEIGHTS_IN_GIT), got.why
    assert got.source_kb == 551_645


# --- the gone model: a name the registry no longer has ----------------------

def test_a_gone_name_is_declined_upstream_until_it_commits_again(tmp_path, monkeypatch):
    from harness import cli, github, paths
    monkeypatch.setattr(paths, "home", lambda: tmp_path)
    conn = ms.connect()
    _see(conn, "hellotung/patch-forcing")
    _see(conn, "org/nowhere", registry="")
    conn.close()

    class Client:
        stale: list = []
        spent = 0

        def __init__(self, **kw):
            pass

        def repo(self, name):
            raise github.NotFound(f"gh api repos/{name}: Not Found")

    def gone(model_id, **kw):
        raise ins.Gone(f"{model_id}: the registry has no model by that name")

    monkeypatch.setattr(github, "Client", Client)
    monkeypatch.setattr(ins, "inspect_model", gone)
    monkeypatch.setattr(ins, "hf_model", gone)
    args = type("A", (), {"repos": [], "from_store": True, "top": 10, "budget": 10, "shard": "",
                          "judge": False, "json": False})()
    assert cli._report_inspect(args) == 0
    conn = ms.connect()
    try:
        for name in ("hellotung/patch-forcing", "org/nowhere"):
            got = _held(conn, name)
            assert (got["state"], got["reason"]) == ("declined", "upstream"), name
            assert got["until"].startswith("commit_after:") and not live_audit._terminal_reason_coherent(conn)[0]
            assert ms.until_met(got["until"], {"last_commit": "2999-01-01T00:00:00Z"})
    finally:
        conn.close()


def test_a_name_no_registry_was_written_for_is_asked_of_both():
    from harness import github

    class Client:
        def repo(self, name):
            return {"pushed_at": "2026-10-18T00:00:00Z"}

    def no_model(url):
        raise RuntimeError("HTTP 404")
    assert ins.upstream_commit("org/x", "", fetch=no_model, client=Client()) == "2026-10-18T00:00:00Z"

    class Missing:
        def repo(self, name):
            raise github.NotFound("no")
    assert ins.upstream_commit("org/x", "", fetch=no_model, client=Missing()) == ""


# --- the GGUF: a budget the old migration left broken -----------------------

def test_the_v29_migration_declines_a_broken_budget_row_rather_than_keep_it(store):
    from harness.memory_store.migrations import prose
    _old(store, "org/budget", "broken", "screen", "limit",
         detail="it ran and passed nothing: x: returned no answer: it spent the whole 4000-token budget")
    prose._reopen_terminal_harness_and_limit_facts(store)
    assert tuple(_held(store, "org/budget")) == ("declined", "screen", "limit", "limit:max_tokens>4000", "")


# --- the repair --------------------------------------------------------------

def _the_four(conn):
    """The four pinned rows' shapes, as they sit in the 2026-10-18 store."""
    _old(conn, "omacom/omarchy-mac", "declined", "inspect", "machine",
         detail="too-big: source tree is 259 MB, which is weights in git, not a source repo")
    _old(conn, "unslothai/unsloth", "declined", "inspect", "machine",
         detail="too-big: source tree is 369 MB, which is weights in git, not a source repo")
    _old(conn, "bartowski/Qwen_Qwen3.5-4B-GGUF", "broken", "screen", "limit", until="limit:max_tokens>4000",
         detail="it ran and passed nothing: chunk-bytes: spent the whole 4000-token budget",
         run_path="/runs/screen-1791261916-code")
    conn.execute("UPDATE proposals SET next_retest_at = 1791866761.6 WHERE name LIKE 'bartowski/%'")
    _old(conn, "hellotung/patch-forcing", "broken", "inspect", "upstream", at=1791853337.0,
         detail="hellotung/patch-forcing: the registry has no model by that name")
    conn.commit()


def test_the_repair_moves_each_pinned_kind_to_a_coherent_verdict(store):
    _the_four(store)
    assert len(live_audit._terminal_reason_coherent(store, pinned=frozenset())[0]) == 4
    found = coherence.changes(store)
    assert {c["name"]: c["now"] for c in found} == {
        "omacom/omarchy-mac": ["queued", "inspect", "reopened", ""],
        "unslothai/unsloth": ["queued", "inspect", "reopened", ""],
        "bartowski/Qwen_Qwen3.5-4B-GGUF": ["declined", "screen", "limit", "limit:max_tokens.code>4000"],
        "hellotung/patch-forcing": ["declined", "inspect", "upstream", "commit_after:2026-10-13T01:02:17Z"],
    }
    assert len(coherence.apply(store, found)) == 4
    assert live_audit._terminal_reason_coherent(store, pinned=frozenset()) == ([], [])
    assert coherence.changes(store) == []
    qwen = store.execute("SELECT run_path FROM verdicts v JOIN proposals p ON p.state_verdict_id = v.id "
                         "WHERE p.name LIKE 'bartowski/%'").fetchone()[0]
    assert qwen == "/runs/screen-1791261916-code"
    assert [r["name"] for r in ms.revisitable(store, {})] == ["bartowski/Qwen_Qwen3.5-4B-GGUF"]


def test_soh_coherence_is_read_only_without_apply(tmp_path, capsys):
    from harness import cli
    db = tmp_path / "s.db"
    conn = ms.connect(db)
    _the_four(conn)
    conn.close()
    assert cli.main(["coherence", "--db", str(db)]) == 0
    assert "4 of 4" in capsys.readouterr().out
    conn = ms.connect(db)
    assert len(coherence.incoherent(conn)) == 4
    conn.close()
    assert cli.main(["coherence", "--db", str(db), "--apply"]) == 0
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        assert live_audit._terminal_reason_coherent(conn, pinned=frozenset()) == ([], [])
    finally:
        conn.close()


def test_the_pin_is_empty_now_that_the_four_are_repaired():
    assert live_audit.PINNED_INCOHERENT == frozenset()
