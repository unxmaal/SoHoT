"""#881: the screen queue is ordered by expected value against the incumbent, not recency."""
import pytest

from harness import rank
from harness import memory_store as ms

DAY = 86400.0
NOW = 2_000_000_000.0
GIB = 1024 ** 3
INC = {"code": "llamacpp:Ornith-1.5-35B-Q4_K_M"}


@pytest.fixture(autouse=True)
def runnable_here(monkeypatch):
    """GGUF rows drop on a machine without llama.cpp; this file tests order, not this machine."""
    monkeypatch.setattr(rank, "unrunnable", lambda row, machine=None: "")


def row(name, *, gib, age_days, times=1, **kw):
    return {"name": name, "lane": "code", "times": times, "description": "",
            "size_bytes": int(gib * GIB), "first_seen": NOW - age_days * DAY,
            "last_seen": NOW - min(age_days, 1) * DAY, **kw}


def order(rows, **kw):
    kw.setdefault("bases_by_lane", {})
    return [r["name"] for r in rank.rank(rows, serving=(), measured_lanes={"code"},
                                         ceiling_gib=66.0, incumbents_by_lane=INC,
                                         now=NOW, **kw, conn=None)]


def test_an_old_27b_peer_screens_before_three_fresh_sub_1b_releases():
    rows = [row("Qwen/Qwen3.6-27B-GGUF", gib=14.3, age_days=38),
            *(row(f"fresh/Tiny-0.{i}B", gib=0.5, age_days=0, times=3) for i in (3, 5, 8))]
    assert order(rows)[0] == "Qwen/Qwen3.6-27B-GGUF"


def test_a_peer_outranks_a_tiny_release_of_the_same_age():
    rows = [row("fresh/Tiny-0.8B", gib=0.5, age_days=0, times=3),
            row("zz/Qwen3.6-27B-GGUF", gib=14.3, age_days=0, times=3)]
    assert order(rows)[0] == "zz/Qwen3.6-27B-GGUF"


def test_the_longer_wait_ranks_first_on_otherwise_equal_rows():
    rows = [row("a/Peer-27B", gib=15.0, age_days=1), row("b/Peer-27B", gib=15.0, age_days=30)]
    assert order(rows) == ["b/Peer-27B", "a/Peer-27B"]


def test_the_head_says_it_is_a_peer_of_the_incumbent():
    got = rank.rank([row("Qwen/Qwen3.6-27B-GGUF", gib=14.3, age_days=38)], serving=(),
                    measured_lanes={"code"}, ceiling_gib=66.0, incumbents_by_lane=INC,
                    bases_by_lane={}, now=NOW, conn=None)[0]["value_why"]
    assert "27B, a size peer of the incumbent Ornith-1.5-35B-Q4_K_M (35B)" in got
    assert "waiting 38 days" in got


def test_a_full_precision_base_ranks_below_its_queued_quant():
    rows = [row("Qwen/Qwen3.6-27B", gib=51.8, age_days=38),
            row("someone/Qwen3.6-27B-Q4-GGUF", gib=15.0, age_days=5,
                parents=[("Qwen/Qwen3.6-27B", "quantized")])]
    got = rank.rank(rows, serving=(), measured_lanes={"code"}, ceiling_gib=66.0,
                    incumbents_by_lane=INC, bases_by_lane={}, now=NOW, conn=None)
    assert [r["name"] for r in got] == ["someone/Qwen3.6-27B-Q4-GGUF", "Qwen/Qwen3.6-27B"]
    assert "a quantised form is queued: someone/Qwen3.6-27B-Q4-GGUF" in got[1]["value_why"]
    alone = rank.rank(rows[:1], serving=(), measured_lanes={"code"}, ceiling_gib=66.0,
                      incumbents_by_lane=INC, bases_by_lane={}, now=NOW, conn=None)[0]["value"]
    assert got[1]["value"] == pytest.approx(alone + rank.QUANT_QUEUED)
    assert rank.QUANT_QUEUED < 0


def test_a_requant_of_the_incumbent_ranks_below_a_peer_from_another_family():
    rows = [row("x/ornith15-35b-a3b-mtp", gib=16.0, age_days=14,
                parents=[("ornith-ai/Ornith-1.5-35B-A3B", "quantized")]),
            row("google/gemma-4-31B-qat", gib=16.0, age_days=14)]
    assert order(rows)[0] == "google/gemma-4-31B-qat"


def test_the_family_the_incumbent_is_built_on_breaks_a_peer_tie():
    rows = [row("a/gemma-4-31B-qat", gib=16.0, age_days=14),
            row("z/Qwen3.8-31B-GGUF", gib=16.0, age_days=14)]
    assert order(rows)[0] == "a/gemma-4-31B-qat"
    assert order(rows, bases_by_lane={"code": {"qwen"}})[0] == "z/Qwen3.8-31B-GGUF"


def test_each_adopt_decline_costs_rank():
    lost = row("a/Peer-27B", gib=15.0, age_days=10, adopt_declines=4)
    fresh = row("b/Peer-27B", gib=15.0, age_days=10)
    assert order([lost, fresh]) == ["b/Peer-27B", "a/Peer-27B"]


@pytest.mark.parametrize("name,billions", [
    ("Qwen/Qwen3.6-27B", 27.0), ("ornith-ai/Ornith-1.5-35B-A3B", 35.0),
    ("llamacpp:Ornith-1.5-35B-Q4_K_M", 35.0), ("TheOneWhoWill/Shibai-700M-Base", 0.7),
    ("Qwen/Qwen3.5-0.8B", 0.8), ("x/Bolt-74B-A9B-24GB", 74.0), ("org/no-size", 0.0)])
def test_parameters_are_read_from_the_name(name, billions):
    assert rank.params_b(name) == billions


def test_the_incumbents_base_families_come_from_lineage(tmp_path):
    conn = ms.connect(tmp_path / "s.db")
    ms.record(conn, ms.Seen(name="ornith-ai/Ornith-1.5-35B-A3B", source="t", lane="code"))
    pid = conn.execute("SELECT id FROM proposals").fetchone()[0]
    conn.execute("INSERT INTO lineage (proposal_id, parent, kind) VALUES (?, ?, ?)",
                 (pid, "Qwen/Qwen3.5-35B-A3B", "finetune"))
    assert rank.incumbent_bases(conn, INC["code"]) == {"qwen"}
    conn.close()


# --- re-screens of a measured loss are capped ------------------------------

def test_a_decline_at_adopt_is_retested_once_then_final(tmp_path):
    conn = ms.connect(tmp_path / "s.db")
    ms.record(conn, ms.Seen(name="Qwen/Qwen3.5-0.8B", source="t", lane="code"))
    ms.decide(conn, "Qwen/Qwen3.5-0.8B", "declined", tier=ms.ADOPT, at=NOW, detail="lost")
    week = ms.RETEST_AFTER_SECONDS
    assert ms.reopen_due_retests(conn, NOW + week) == ["Qwen/Qwen3.5-0.8B"]
    ms.decide(conn, "Qwen/Qwen3.5-0.8B", "declined", tier=ms.ADOPT, at=NOW + week + 1,
              detail="lost again")
    assert conn.execute("SELECT next_retest_at FROM proposals").fetchone()[0] is None
    assert ms.reopen_due_retests(conn, NOW + 100 * week) == []
    assert ms.retest_counts(conn, NOW + 100 * week)["final"] == 1
    conn.close()


def test_a_screen_rejection_keeps_three_retests():
    assert ms.retest_limit(ms.SCREEN) == ms.RETESTS == 3
    assert ms.retest_limit(ms.ADOPT) == 1


def test_a_retest_scheduled_before_the_cap_does_not_reopen_a_repeated_loser(tmp_path):
    conn = ms.connect(tmp_path / "s.db")
    ms.record(conn, ms.Seen(name="Qwen/Qwen3.5-0.8B", source="t", lane="code"))
    for i in range(4):
        conn.execute("INSERT INTO verdicts (proposal_id, tier, outcome, decided_at) "
                     "SELECT id, 'adopt', 'declined', ? FROM proposals", (NOW - 10 + i,))
    ms.decide(conn, "Qwen/Qwen3.5-0.8B", "declined", tier=ms.ADOPT, at=NOW, detail="lost")
    conn.execute("UPDATE proposals SET next_retest_at = ?", (NOW + 1,))
    assert ms.due_retests(conn, NOW + 2) == []
    conn.close()


def test_weights_over_half_the_ceiling_rank_below_a_lighter_peer():
    rows = [row("a/Peer-27B", gib=40.0, age_days=10), row("b/Peer-27B", gib=30.0, age_days=10)]
    assert order(rows) == ["b/Peer-27B", "a/Peer-27B"]


def test_the_fetch_and_the_screen_read_the_incumbents_lineage_alike(monkeypatch):
    from harness import fetching, screen
    from harness.commands import screen as screen_cmd
    monkeypatch.setattr(fetching, "have", lambda *a, **k: False)
    monkeypatch.setattr(rank, "serving", lambda *a, **k: set())
    monkeypatch.setattr(rank, "lanes_with_receipts", lambda *a, **k: set())
    monkeypatch.setattr(rank, "incumbents", lambda conn=None: dict(INC))
    monkeypatch.setattr(screen, "plan", lambda ranked, **k: ranked)
    conn = ms.connect()
    ms.record(conn, ms.Seen(name="ornith-ai/Ornith-1.5-35B-A3B", source="t", lane="code"))
    conn.execute("INSERT INTO lineage (proposal_id, parent, kind) SELECT id, "
                 "'Qwen/Qwen3.5-35B-A3B', 'finetune' FROM proposals")
    for name in ("z/Qwen3.8-31B-GGUF", "a/gemma-4-31B-qat"):
        ms.record(conn, ms.Seen(name=name, source="t", lane="code", resolved=name,
                                registry=ms.HUGGINGFACE))
        ms.set_size(conn, name, 16 * GIB)
        ms.decide(conn, name, "queued", tier="inspect", detail="fits")
    fetch = [r["name"] for r in fetching.queued(conn, lane="code")]
    conn.commit()
    conn.close()
    plan = [r["name"] for r in screen_cmd._screen_plan("code")]
    assert fetch[0] == "z/Qwen3.8-31B-GGUF"
    assert plan == fetch
