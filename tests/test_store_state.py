"""A proposal's state is a column one transition table writes. #409."""
import inspect
import random
import re
import sqlite3

import pytest

from harness import disk, fetching
from harness import memory_store as ms

MAC = {"fingerprint": "mac", "runtimes": "cpu,mlx", "memory_gb": 32.0,
       "ceiling_gb": 22.0, "hw_model": "m", "os": "o", "arch": "a",
       "accelerator": ""}
BOX = {**MAC, "fingerprint": "box", "runtimes": "cpu,cuda"}


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr("harness.paths.home", lambda: tmp_path)
    conn = ms.connect(tmp_path / "s.db")
    yield conn
    conn.close()


def _see(conn, name, lane="code"):
    ms.record(conn, ms.Seen(name=name, source="t", resolved=name,
                            kind="weights", registry=ms.HUGGINGFACE, lane=lane))


def _state(conn, name):
    return tuple(conn.execute(
        "SELECT p.state, v.tier FROM proposals p LEFT JOIN verdicts v "
        "ON v.id = p.state_verdict_id WHERE p.name = ?", (name,)).fetchone())


def _count(conn):
    return conn.execute("SELECT COUNT(*) FROM verdicts").fetchone()[0]


def _bypass(conn, name, outcome, tier="inspect", detail="", until=""):
    """A newer verdict row that never went through decide()."""
    conn.execute(
        "INSERT INTO verdicts (proposal_id, outcome, tier, detail, until, "
        "decided_at) SELECT id, ?, ?, ?, ?, 0 FROM proposals WHERE name = ?",
        (outcome, tier, detail, until, name))
    conn.commit()


# --- the transition table --------------------------------------------------

@pytest.mark.parametrize("terminal", ms.TERMINAL)
@pytest.mark.parametrize("waypoint", ms.WAYPOINTS)
def test_a_waypoint_cannot_overwrite_a_terminal_state(store, terminal, waypoint):
    _see(store, "org/w")
    ms.decide(store, "org/w", terminal, tier=ms.ADOPT, detail="decided")
    n = _count(store)
    with pytest.raises(ms.IllegalTransition):
        ms.decide(store, "org/w", waypoint, tier=ms.ADOPT, detail="again")
    assert _state(store, "org/w") == (terminal, ms.ADOPT)
    assert _count(store) == n


def test_a_waypoint_over_a_waypoint_is_allowed(store):
    """Negative control: queued is open to every tier."""
    _see(store, "org/w")
    ms.decide(store, "org/w", "queued", tier=ms.SCREEN, detail="x")
    ms.decide(store, "org/w", "queued", tier=ms.INSPECT, detail="y")
    assert _state(store, "org/w") == ("queued", ms.INSPECT)


def test_inspect_cannot_requeue_a_screened_candidate(store):
    """#393: the loop's inspect sent every screened candidate round again."""
    _see(store, "org/w")
    ms.decide(store, "org/w", "screened", tier=ms.SCREEN, detail="1 passed")
    with pytest.raises(ms.IllegalTransition):
        ms.decide(store, "org/w", "queued", tier=ms.INSPECT, detail="named")
    ms.decide(store, "org/w", "queued", tier=ms.SCREEN, detail="not measured")
    assert _state(store, "org/w") == ("queued", ms.SCREEN)


def test_an_earlier_tier_cannot_replace_a_later_tiers_answer(store):
    _see(store, "org/w")
    ms.decide(store, "org/w", "measured", tier=ms.ADOPT, detail="won")
    with pytest.raises(ms.IllegalTransition):
        ms.decide(store, "org/w", "declined", tier=ms.INSPECT,
                  detail="too-big: 40 GiB over a smaller ceiling")
    ms.decide(store, "org/w", "declined", tier=ms.ADOPT, detail="lost a rematch")
    assert _state(store, "org/w") == ("declined", ms.ADOPT)


def test_a_retraction_reopens_and_records_why(store):
    _see(store, "org/w")
    held = ms.decide(store, "org/w", "broken", tier=ms.SCREEN, detail="0 of 3")
    vid = ms.retract(store, "org/w", "the server had died", tier=ms.SCREEN)
    row = store.execute("SELECT outcome, detail, reopens, reopen_kind "
                        "FROM verdicts WHERE id = ?", (vid,)).fetchone()
    assert tuple(row) == ("queued", "retracted: the server had died", held,
                          ms.RETRACTION)
    assert _state(store, "org/w") == ("queued", ms.SCREEN)
    assert "org/w" in ms.pending(store)


def test_an_ordinary_write_records_no_retraction(store):
    _see(store, "org/w")
    vid = ms.decide(store, "org/w", "queued", tier=ms.INSPECT, detail="fits")
    assert tuple(store.execute("SELECT reopens, reopen_kind FROM verdicts "
                               "WHERE id = ?", (vid,)).fetchone()) == (None, "")


def test_a_writer_that_read_a_stale_state_is_checked_again(store, monkeypatch):
    """The state moved between this writer's read and its write."""
    _see(store, "org/w")
    ms.decide(store, "org/w", "declined", tier=ms.ADOPT, detail="lost")
    real = ms._held
    calls = []

    def stale(conn, pid):
        calls.append(pid)
        row = dict(real(conn, pid))
        if len(calls) == 1:
            row.update(state="queued", id=None)
        return row

    monkeypatch.setattr(ms.transitions, "_held", stale)
    n = _count(store)
    with pytest.raises(ms.IllegalTransition):
        ms.decide(store, "org/w", "queued", tier=ms.INSPECT, detail="named")
    assert len(calls) == 2
    assert _count(store) == n
    assert _state(store, "org/w") == ("declined", ms.ADOPT)


def test_every_retraction_migration_writes_through_the_state(store):
    """A migration that inserted a row directly would leave state behind."""
    fns = sorted(n for n in dir(ms) if re.match(r"_(retract|relane|reopen|requeue)_", n))
    assert len(fns) > 10, fns
    for fn in fns:
        body = inspect.getsource(getattr(ms, fn))
        assert "INSERT INTO verdicts" not in body, fn


# --- readers follow the column, not the newest row ---------------------------

@pytest.fixture
def split(store):
    """Each proposal's newest row says the opposite of its state."""
    _see(store, "org/settled")
    ms.decide(store, "org/settled", "queued", tier=ms.INSPECT, detail="fits")
    ms.decide(store, "org/settled", "declined", tier=ms.INSPECT, detail="dead")
    _bypass(store, "org/settled", "queued", detail="a sighting")
    _see(store, "org/open")
    ms.decide(store, "org/open", "queued", tier=ms.INSPECT, detail="fits")
    _bypass(store, "org/open", "declined", detail="never decided")
    _see(store, "org/survivor")
    ms.decide(store, "org/survivor", "screened", tier=ms.SCREEN, detail="1 passed")
    _bypass(store, "org/survivor", "declined", tier=ms.MEASURE)
    _see(store, "org/measured")
    ms.decide(store, "org/measured", "measured", tier=ms.MEASURE, detail="won")
    _bypass(store, "org/measured", "screened", tier=ms.SCREEN)
    return store


def test_pending_reads_the_state(split):
    got = ms.pending(split, limit=10)
    assert "org/open" in got and "org/settled" not in got


def test_settled_reads_the_state(split):
    assert ms.settled(split) == {"org/settled", "org/measured"}


def test_by_registry_reads_the_state(split):
    ms.set_registry(split, "org/settled", ms.GITHUB)
    assert ms.by_registry(split) == {ms.HUGGINGFACE: 2}


def test_judgeable_reads_the_state(split):
    names = {r["name"] for r in ms.judgeable(split)}
    assert names == {"org/open"}


def test_survivors_read_the_state(split):
    assert [r["name"] for r in ms.survivors(split)] == ["org/survivor"]


def test_latest_reads_the_state(split):
    assert ms.latest(split, "org/settled") == {"outcome": "declined",
                                               "tier": ms.INSPECT}


def test_the_fetch_queue_reads_the_state(split):
    names = {r["name"] for r in fetching.queued(split, needs_lane=False)}
    assert names == {"org/open"}


def test_disk_reads_the_state(split):
    got = disk.latest_verdicts(split)
    assert got["org/settled"]["outcome"] == "declined"
    assert got["org/open"]["outcome"] == "queued"


def test_retire_unlisted_reads_the_state(split):
    _see(split, "org/repo")
    for name in ("org/open", "org/settled"):
        ms.link(split, "org/repo", name, "needs")
    assert ms.retire_unlisted(split, "org/repo", keep=[]) == ["org/open"]


def test_revisitable_reads_the_state(store):
    _see(store, "org/cuda")
    ms.decide(store, "org/cuda", "declined", tier="fetch",
              detail="needs-cuda", until="runtime:cuda")
    _bypass(store, "org/cuda", "queued", detail="a sighting")
    _see(store, "org/back")
    ms.retract(store, "org/back", "worth another look")
    _bypass(store, "org/back", "declined", until="runtime:cuda")
    assert [r["name"] for r in ms.revisitable(store, BOX)] == ["org/cuda"]


def test_a_retraction_migration_reads_the_state(store):
    _see(store, "org/g")
    ms.decide(store, "org/g", "broken", tier=ms.SCREEN,
              detail="guidance_scale has to be 0")
    _bypass(store, "org/g", "screened", tier=ms.SCREEN)
    ms._requeue_broken_matching(store)
    assert _state(store, "org/g") == ("queued", ms.SCREEN)


# --- the property ------------------------------------------------------------

OUTCOMES = ms.VERDICTS
TIERS = (*ms.LADDER, "")


@pytest.mark.parametrize("seed", range(40))
def test_state_is_the_fold_of_the_accepted_transitions(tmp_path, seed):
    rng = random.Random(seed)
    conn = ms.connect(tmp_path / f"p{seed}.db")
    try:
        _see(conn, "org/p")
        tried = []
        for i in range(rng.randint(1, 30)):
            outcome, tier = rng.choice(OUTCOMES), rng.choice(TIERS)
            retract = ms.RETRACTION if rng.random() < 0.15 else ""
            try:
                ms.decide(conn, "org/p", outcome, tier=tier, detail=f"d{i % 3}",
                          reopen=retract, reopen_why="because" if retract else "")
                accepted = True
            except ms.IllegalTransition:
                accepted = False
            tried.append((outcome, tier, retract, accepted))
            want = ms.fold([(o, t, r) for o, t, r, _ in tried])
            got = _state(conn, "org/p")
            assert (got[0], got[1] or "") == want, tried
            # Exactly the moves the fold skips were refused.
            before = ms.fold([(o, t, r) for o, t, r, _ in tried[:-1]])
            assert accepted == (not ms.transition_refused(
                before[0], before[1], outcome, tier, retract)), tried
        held = conn.execute(
            "SELECT p.state, v.outcome, v.proposal_id FROM proposals p "
            "JOIN verdicts v ON v.id = p.state_verdict_id").fetchone()
        assert held is None or held[0] == held[1]
    finally:
        conn.close()


# --- the migration -----------------------------------------------------------

def test_schema_24_backfills_the_state_from_the_newest_row(tmp_path, monkeypatch):
    monkeypatch.setattr("harness.paths.home", lambda: tmp_path)
    path = tmp_path / "old.db"
    ddl = (ms._DDL.replace(",\n    -- Written only by decide(); see "
                           "transition_refused(). #409.\n    state       TEXT "
                           "NOT NULL DEFAULT '',\n    state_verdict_id INTEGER",
                           "")
           .replace(",\n    -- A named reopen: the state verdict it overrode, "
                    "and which kind. #409.\n    reopens     INTEGER REFERENCES "
                    "verdicts(id),\n    reopen_kind TEXT NOT NULL DEFAULT ''", ""))
    assert "state_verdict_id" not in ddl and "reopen" not in ddl
    raw = sqlite3.connect(path)
    raw.executescript(ddl)
    raw.execute("INSERT INTO meta VALUES ('schema', '24')")
    for pid, name in ((1, "org/a"), (2, "org/b"), (3, "org/none")):
        raw.execute("INSERT INTO proposals (id, name, first_seen, last_seen) "
                    "VALUES (?, ?, 0, 0)", (pid, name))
    for pid, outcome, tier, detail in (
            (1, "declined", "adopt", "lost"),
            (1, "queued", "inspect", "named by a neighbor"),
            (2, "broken", "screen", "0 of 3"),
            (2, "queued", "screen", "retracted: our server died")):
        raw.execute("INSERT INTO verdicts (proposal_id, outcome, tier, detail, "
                    "decided_at) VALUES (?, ?, ?, ?, 0)",
                    (pid, outcome, tier, detail))
    raw.commit()
    raw.close()
    conn = ms.connect(path)
    try:
        assert _state(conn, "org/a") == ("queued", "inspect")
        assert _state(conn, "org/b") == ("queued", "screen")
        assert _state(conn, "org/none") == ("", None)
        audit = ms.state_audit(conn)
        assert audit["folds_differently"] == [
            {"name": "org/a", "state": "queued", "folded": "declined"}]
        assert [r["name"] for r in audit["terminal_then_open"]] == [
            "org/a", "org/b"]
    finally:
        conn.close()


def test_a_reopen_must_say_why(store):
    _see(store, "org/w")
    ms.decide(store, "org/w", "broken", tier=ms.SCREEN, detail="0 of 3")
    with pytest.raises(ms.IllegalTransition):
        ms.decide(store, "org/w", "queued", tier=ms.SCREEN,
                  reopen=ms.RETRACTION, reopen_why=" ")
    assert _state(store, "org/w") == ("broken", ms.SCREEN)


def test_an_unknown_reopen_is_refused(store):
    _see(store, "org/w")
    ms.decide(store, "org/w", "broken", tier=ms.SCREEN, detail="0 of 3")
    with pytest.raises(ms.IllegalTransition):
        ms.decide(store, "org/w", "queued", tier=ms.SCREEN,
                  reopen="whim", reopen_why="felt like it")


def test_a_reopen_kind_can_be_limited_to_some_states(store, monkeypatch):
    """The shape #431's retest needs: a named kind, its own source states."""
    monkeypatch.setitem(ms.REOPENS, "retest", ("broken", "declined"))
    _see(store, "org/w")
    ms.decide(store, "org/w", "measured", tier=ms.ADOPT, detail="won")
    with pytest.raises(ms.IllegalTransition):
        ms.decide(store, "org/w", "queued", tier=ms.SCREEN,
                  reopen="retest", reopen_why="7 days on")
    _see(store, "org/x")
    ms.decide(store, "org/x", "broken", tier=ms.SCREEN, detail="0 of 3")
    vid = ms.decide(store, "org/x", "queued", tier=ms.SCREEN,
                    reopen="retest", reopen_why="7 days on")
    assert store.execute("SELECT reopen_kind FROM verdicts WHERE id = ?",
                         (vid,)).fetchone()[0] == "retest"
    assert _state(store, "org/x") == ("queued", ms.SCREEN)


# --- a refusal in a tier loop skips one candidate, never the sweep -----------

def _race(monkeypatch, victim):
    """Another writer answers `victim` between this tier's plan and its write."""
    real = ms.decide
    fired = []

    def racing(conn, name, outcome, **kw):
        if name == victim and not fired:
            fired.append(name)
            real(conn, name, "measured", tier=ms.ADOPT, detail="decided elsewhere")
        return real(conn, name, outcome, **kw)

    monkeypatch.setattr(ms, "decide", racing)
    return fired


def test_a_refused_fetch_write_does_not_stop_the_next(store, monkeypatch, capsys):
    monkeypatch.setattr(fetching, "have", lambda *a, **k: False)
    monkeypatch.setattr(fetching, "download",
                        lambda name, snapshot=None, **k: f"/x/{name}")
    monkeypatch.setattr(fetching, "requires", lambda name, conn=None: [])
    monkeypatch.setattr("harness.rank.serving", lambda *a, **k: set())
    monkeypatch.setattr("harness.rank.lanes_with_receipts", lambda *a, **k: set())
    for name in ("org/a", "org/b"):
        _see(store, name)
        ms.set_size(store, name, fetching.GIB)
        ms.decide(store, name, "queued", tier=ms.INSPECT, detail="fits")
    fired = _race(monkeypatch, "org/a")
    got = fetching.run(store, {"org/a": fetching.GIB, "org/b": fetching.GIB},
                       limit=5, free=500 * fetching.GIB)
    assert fired and {g["repo"] for g in got} == {"org/a", "org/b"}
    assert _state(store, "org/a") == ("measured", ms.ADOPT)
    assert _state(store, "org/b") == ("queued", "fetch")
    assert "skipped org/a" in capsys.readouterr().out


class _Done:
    returncode = 0
    stderr = ""


def test_a_refused_screen_write_does_not_stop_the_next(monkeypatch, tmp_path,
                                                      capsys):
    import argparse
    import subprocess

    from harness import cli, memory, screen

    real = ms.connect
    monkeypatch.setattr(ms, "connect", lambda *a, **k: real(tmp_path / "d.db"))
    conn = ms.connect()
    for n in ("org/first", "org/second"):
        _see(conn, n)
    conn.close()
    plan = [{"name": n, "state": screen.READY, "candidate": n,
             "modality": "code", "why_not": ""}
            for n in ("org/first", "org/second")]
    monkeypatch.setattr(cli, "_screen_plan", lambda want: plan)
    monkeypatch.setattr(memory, "check_model", lambda *a, **k: (True, ""))
    monkeypatch.setattr(screen, "argv", lambda r, **k: ["screen", r["name"]])
    ran = []
    monkeypatch.setattr(subprocess, "run", lambda argv, **kw: (
        argv[0] == "screen" and ran.append(argv[-1])) or _Done())
    monkeypatch.setattr(cli, "_receipt_at",
                        lambda out: {"summary": {"x": {"passed": 0}}})
    monkeypatch.setattr(screen, "outcome", lambda *a, **k: screen.Verdict(
        "broken", "it ran and passed nothing", "candidate"))
    fired = _race(monkeypatch, "org/first")
    cli._report_screen(argparse.Namespace(lane="", top=5, limit=5, run=True,
                                          json=False))
    assert fired and ran == ["org/first", "org/second"]
    conn = ms.connect()
    try:
        assert _state(conn, "org/first") == ("measured", ms.ADOPT)
        assert _state(conn, "org/second") == ("broken", ms.SCREEN)
    finally:
        conn.close()
    assert "skipped org/first" in capsys.readouterr().out


def test_a_refused_adoption_returns_to_the_measure_loop(monkeypatch, tmp_path,
                                                       capsys):
    import argparse
    import subprocess

    from harness import adopt, cli

    monkeypatch.setattr(subprocess, "run", lambda argv, **kw: _Done())
    monkeypatch.setattr(adopt, "default_for",
                        lambda lane, fallback, conn=None: "org/inc")
    monkeypatch.setattr(cli, "_receipt_at", lambda out: {
        "specs": {"inc": "tts:org/inc", "chal": "tts:org/chal"},
        "summary": {k: {"passed": 8, "total": 8, "pass_rate": 1.0,
                        "median_s": 1.0, "metrics": {"wer": w}}
                    for k, w in (("inc", 0.05), ("chal", 0.01))},
        "rows": [{"candidate": k, "case_id": f"c{i}", "passed": k == "chal"}
                 for k in ("inc", "chal") for i in range(8)]})
    real = ms.connect
    monkeypatch.setattr(ms, "connect", lambda *a, **k: real(tmp_path / "d.db"))

    def refuse(*a, **k):
        raise ms.IllegalTransition("org/chal: decided elsewhere")

    monkeypatch.setattr(adopt, "record", refuse)
    rc = cli._measure_and_adopt(argparse.Namespace(repeat=3),
                                {"name": "org/chal", "lane": "tts"})
    assert rc == 0
    assert "skipped org/chal" in capsys.readouterr().out


def test_a_refused_retirement_does_not_stop_the_next(split, monkeypatch):
    _see(split, "org/repo")
    _see(split, "org/open2")
    ms.decide(split, "org/open2", "queued", tier=ms.INSPECT, detail="fits")
    for name in ("org/open", "org/open2"):
        ms.link(split, "org/repo", name, "needs")
    fired = _race(monkeypatch, "org/open")
    assert ms.retire_unlisted(split, "org/repo", keep=[]) == ["org/open2"]
    assert fired


def test_a_retraction_raises_only_on_an_invalid_call(store):
    _see(store, "org/w")
    for outcome, tier in (("measured", ms.ADOPT), ("screened", ms.SCREEN),
                          ("queued", ms.INSPECT), ("broken", ms.SCREEN)):
        ms.retract(store, "org/w", "reset", tier=ms.INSPECT)
        ms.decide(store, "org/w", outcome, tier=tier, detail=outcome)
        ms.retract(store, "org/w", f"undo {outcome}", tier=ms.INSPECT)
        assert _state(store, "org/w") == ("queued", ms.INSPECT)
    with pytest.raises(ms.IllegalTransition):
        ms.retract(store, "org/w", "")
    with pytest.raises(KeyError):
        ms.retract(store, "org/nobody", "why")
