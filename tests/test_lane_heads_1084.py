"""Ranked lane heads reach a download: lane turns, the fetch's own reason, a night sized by its ceiling, a capped day fetch. #1084."""
import argparse
import sqlite3
import time
from datetime import datetime

import pytest

from harness import ceiling, day_fetch, downloads, fetching, funnel, gguf, rank, screen, throttle
from harness import memory_store as ms
from harness.commands import discover as discover_cmd
from harness.commands import loop as loop_cmd
from harness.commands import measure as measure_cmd
from harness.commands import screen as screen_cmd

GIB = fetching.GIB
MICA = "sky7350/Mica-v0.1-4B"
GAP = ("needs its own runner: model type 'qwen3_5_text': ml-explore/mlx-lm#869 added qwen3_5 and left "
       "qwen3_5_text out")


def _seed(conn, name, gib, lane="code", times=0):
    for i in range(times + 1):
        ms.record(conn, ms.Seen(name=name, source=f"s{i}", url=f"u{i}", why="", relevance=0, kind="weights",
                                registry=ms.HUGGINGFACE, lane=lane, resolved=name))
    ms.set_size(conn, name, int(gib * GIB))
    ms.decide(conn, name, "queued", tier="inspect", detail="fits")


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(fetching, "have", lambda *a, **k: False)
    monkeypatch.setattr(fetching, "download", lambda name, snapshot=None, **k: f"/x/{name}")
    monkeypatch.setattr(fetching, "requires", lambda name, conn=None: [])
    monkeypatch.setattr(screen, "runner_gap", lambda *a, **k: "")
    monkeypatch.setattr(rank, "serving", lambda *a, **k: set())
    monkeypatch.setattr(rank, "lanes_with_receipts", lambda *a, **k: set())
    conn = ms.connect(tmp_path / "d.db")
    yield conn
    conn.close()


# --- 1. lane turns ---------------------------------------------------------

def test_a_code_flood_does_not_keep_the_retrieval_head_out_of_the_first_fetch(store):
    """10-20: a code-lane flood filled the download budget while the retrieval head waited behind it."""
    for i in range(40):
        _seed(store, f"org/code-{i:02d}", 16, times=3)
    _seed(store, "tencent/EVIE-Preview-4.5B", 9, lane="retrieval")
    ranked = [r["name"] for r in fetching.in_rank_order(fetching.queued(store), store)]
    assert ranked[-1] == "tencent/EVIE-Preview-4.5B", "the fixture must rank the retrieval head last"
    got = fetching.run(store, limit=3, free=1000 * GIB, budget=40 * GIB)
    assert "tencent/EVIE-Preview-4.5B" in [g["repo"] for g in got if g["ok"]]


def test_every_lanes_first_comes_before_any_lanes_second():
    rows = [{"name": n, "lane": lane} for n, lane in
            [("c1", "code"), ("c2", "code"), ("c3", "code"), ("r1", "retrieval"), ("i1", "image"), ("i2", "image")]]
    assert [r["name"] for r in fetching.by_lane_turns(rows)] == ["c1", "r1", "i1", "c2", "i2", "c3"]


def test_a_parent_takes_its_turn_in_its_childs_lane(store):
    for name, lane in [("org/c1", "code"), ("org/c2", "code"), ("org/base", "code"), ("org/edge", "retrieval")]:
        _seed(store, name, 1, lane=lane)
    pid = store.execute("SELECT id FROM proposals WHERE name = 'org/edge'").fetchone()["id"]
    store.execute("INSERT INTO lineage (proposal_id, parent, kind) VALUES (?, 'org/base', 'finetune')", (pid,))
    rows = [{"name": n, "lane": lane} for n, lane in
            [("org/c1", "code"), ("org/c2", "code"), ("org/base", "code"), ("org/edge", "retrieval")]]
    got = [r["name"] for r in fetching.by_lane_turns(rows, store)]
    assert got.index("org/base") < got.index("org/c2")


# --- 2. the funnel names the fetch's own reason ------------------------------

def _row(conn, name):
    return next(r for r in funnel.proposals(conn, top=3, budget=40 * GIB) if r["name"] == name)


def test_the_funnel_names_the_runner_gap_the_fetch_recorded(store, monkeypatch):
    """soh morning said Mica was 'nothing holds it: 1 of the rows a sweep tries'; the fetch said it needs its own runner."""
    _seed(store, MICA, 8, lane="decide")
    monkeypatch.setattr(screen, "runner_gap", lambda lane, name, *a, **k: GAP if name == MICA else "")
    fetching.run(store, limit=3, free=1000 * GIB, budget=40 * GIB)
    # The next sweep's inspect rewrites the queued waypoint over the fetch's verdict.
    ms.decide(store, MICA, "queued", tier="inspect", detail="fits")
    got = _row(store, MICA)
    assert got["reason"] == fetching.SKIPPED
    assert "needs its own runner" in got["why"]


def _queued_since(conn, name, at):
    conn.execute("UPDATE verdicts SET decided_at = ? WHERE tier = 'inspect' AND proposal_id = "
                 "(SELECT id FROM proposals WHERE name = ?)", (at, name))
    conn.commit()


def _failed_download(conn, name, at):
    rid = downloads.start(conn, name, downloads.HUB, "/x", proposal=name)
    downloads.finish(conn, rid, failed=True)
    conn.execute("UPDATE downloads SET finished_at = ?, proposal_id = (SELECT id FROM proposals WHERE name = ?) "
                 "WHERE id = ?", (at, name, rid))
    conn.commit()


def _fetch_skip(conn, name, detail, at):
    vid = ms.decide(conn, name, "queued", tier="fetch", detail=detail, reason="limit")
    conn.execute("UPDATE verdicts SET decided_at = ? WHERE id = ?", (at, vid))
    conn.commit()


def test_a_budget_skip_after_a_failed_download_is_the_reason(store):
    """HauhauCS Gemma4-26B: soh morning said 'last download failed'; the fetch had since printed a budget skip."""
    name = "HauhauCS/Gemma4-26B"
    _seed(store, name, 16)
    now = time.time()
    _queued_since(store, name, now - 5 * 86400)
    _failed_download(store, name, now - 3 * 86400)
    _fetch_skip(store, name, "16.0 GiB would take this run past its 40 GiB budget", now - 86400)
    got = _row(store, name)
    assert got["reason"] == fetching.SKIPPED and "past its 40 GiB budget" in got["why"]


def test_a_failed_download_after_the_skip_is_the_reason(store):
    """Negative control: the newer of the two answers wins."""
    name = "HauhauCS/Gemma4-26B"
    _seed(store, name, 16)
    now = time.time()
    _queued_since(store, name, now - 5 * 86400)
    _fetch_skip(store, name, "16.0 GiB would take this run past its 40 GiB budget", now - 3 * 86400)
    _failed_download(store, name, now - 86400)
    assert _row(store, name)["reason"] == fetching.FAILED


def test_a_download_is_not_read_back_as_a_skip(store):
    _seed(store, "org/landed", 1)
    ms.decide(store, "org/landed", "queued", tier="fetch", detail=fetching.DOWNLOADED, reason="candidate")
    assert _row(store, "org/landed")["reason"] != fetching.SKIPPED


# --- 3. the night is sized by its ceiling -----------------------------------

def _verdicts(rows):
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE verdicts (id INTEGER PRIMARY KEY, tier TEXT, decided_at REAL, run_id INTEGER)")
    conn.executemany("INSERT INTO verdicts (tier, decided_at, run_id) VALUES ('screen', ?, ?)", rows)
    return conn


def test_seconds_per_screen_is_the_mean_gap_between_screens_in_one_sweep():
    now = time.time()
    rows = [(now - 100_000, 1), (now - 100_000 + 300, 2), (now - 100_000 + 900, 3),
            # The next night: its first screen's gap reaches back past a ceiling and is not a screen's time.
            (now - 10_000, 4), (now - 10_000 + 120, None), (now - 10_000 + 420, 5)]
    assert ceiling.screen_s(_verdicts(rows), now=now) == pytest.approx((300 + 600 + 300) / 3)


def test_seconds_per_screen_falls_back_when_the_store_has_none():
    assert ceiling.screen_s(_verdicts([]), now=time.time()) == ceiling.SCREEN_S


def test_screens_that_fit_take_the_screen_share_of_what_is_left(monkeypatch):
    monkeypatch.setattr(ceiling, "screen_s", lambda conn, now=None, days=None: 600.0)
    monkeypatch.setattr("harness.memory_store.connect",
                        lambda *a, **k: type("S", (), {"close": lambda s: None})())
    sweep = ceiling.Sweep(6 * 3600, clock=lambda: 0.0)
    assert loop_cmd._sized(0, sweep)["screens"] == int(6 * 3600 * ceiling.SCREEN_FRACTION // 600)
    assert loop_cmd._sized(3, sweep)["screens"] == 3


def test_a_screen_that_would_end_past_its_share_is_not_started():
    assert screen_cmd.out_of_time(1000.0, 600.0, 500.0)
    assert not screen_cmd.out_of_time(1000.0, 400.0, 500.0)
    assert not screen_cmd.out_of_time(None, 600.0, 500.0)


def _spend(monkeypatch, top, backlog=()):
    seen = {}
    monkeypatch.setattr("harness.disk.sweep", lambda *a, **k: {})
    for name in ("_reopen_retests", "_reopen_missing_in_snapshot", "_reverify", "_sweeps"):
        monkeypatch.setattr(loop_cmd, name, lambda *a, **k: {})
    monkeypatch.setattr(ceiling, "screen_s", lambda conn, now=None, days=None: 600.0)
    monkeypatch.setattr(screen_cmd, "screenable_backlog", lambda want="", **k: list(backlog))
    monkeypatch.setattr(screen_cmd, "cmd_fetch", lambda a: seen.setdefault("fetch", a) and 0)
    monkeypatch.setattr(discover_cmd, "cmd_discover", lambda a: seen.setdefault("screen", a) and 0)
    monkeypatch.setattr(measure_cmd, "measurable", lambda store, top, want="": seen.setdefault("measure", top) and [])
    monkeypatch.setattr(measure_cmd, "resume_first", lambda store, fresh, want="": fresh)
    monkeypatch.setattr("harness.memory_store.connect",
                        lambda *a, **k: type("S", (), {"close": lambda s: None})())
    loop_cmd._loop_spend(argparse.Namespace(top=top, budget_gib=40, lane=""), 0,
                         sweep=ceiling.Sweep(6 * 3600, clock=lambda: 0.0))
    return seen


def test_unset_top_lets_the_ceiling_size_fetch_screen_and_measure(monkeypatch):
    """DISCOVER_TOP=3 capped all three; 4h42m of the 10-20 ceiling went unused."""
    seen = _spend(monkeypatch, None, backlog=["a"])
    fits = int(6 * 3600 * ceiling.SCREEN_FRACTION // 600)
    assert seen["fetch"].limit == fits - 1
    assert seen["screen"].limit == loop_cmd.EVERY and seen["screen"].screen_until is not None
    assert seen["measure"] == loop_cmd.EVERY


def test_an_explicit_top_still_caps_every_step(monkeypatch):
    seen = _spend(monkeypatch, 3)
    assert seen["fetch"].limit == 3 and seen["screen"].limit == 3 and seen["screen"].screen_until is None
    assert seen["measure"] == 3


# --- 4. the day fetch -------------------------------------------------------

def _at(hour, minute=0):
    return datetime.now().replace(hour=hour, minute=minute, second=0, microsecond=0).timestamp()


ON = {day_fetch.ENABLE: "1"}


def test_the_day_fetch_is_off_until_enabled():
    assert "off" in day_fetch.why_not_now(_at(10), environ={}, running=lambda root: [])


@pytest.mark.parametrize("hour", [20, 23, 0, 7])
def test_the_day_fetch_starts_nothing_at_night(hour):
    assert "night" in day_fetch.why_not_now(_at(hour), environ=ON, running=lambda root: [])


def test_the_day_fetch_waits_for_a_running_sweep():
    loop = [{"what": "discover loop", "pid": 4242}]
    assert "discover loop" in day_fetch.why_not_now(_at(10), environ=ON, running=lambda root: loop)
    assert day_fetch.why_not_now(_at(10), environ=ON, running=lambda root: []) == ""


@pytest.mark.parametrize("hour,capped", [(8, False), (9, True), (15, True), (16, False), (19, False)])
def test_the_rate_cap_holds_between_its_hours(hour, capped):
    assert day_fetch.capped(_at(hour, 30)) is capped


class _Store:
    def close(self):
        pass


class _Proc:
    pid, returncode = 4242, 0

    def __init__(self, argv):
        self.argv = argv

    def poll(self):
        return 0

    def wait(self, timeout=None):
        return 0


def _day(monkeypatch, hour, backlog=0, fits=18, counter=None):
    started = []
    monkeypatch.setattr(day_fetch, "room", lambda conn, b: (max(0, fits - b), "sized"))
    got = day_fetch.run(argparse.Namespace(budget_gib=None), clock=lambda: _at(hour, 30), store=_Store(),
                        backlog=backlog, environ=ON, running=lambda root: [],
                        popen=lambda argv: started.append(argv) or _Proc(argv), counter=counter,
                        hold=lambda proc, cap, read, **k: {"bytes": 0, "seconds": 0, "capped_s": 0,
                                                           "capped_bytes": 0, "stopped_s": 0, "stopped": ""})
    return got, started


def test_a_full_buffer_starts_no_download(monkeypatch):
    got, started = _day(monkeypatch, 10, backlog=18)
    assert not got["started"] and "buffer is full" in got["why"] and not started


def test_the_day_fetch_child_leaves_the_router_and_stops_before_night(monkeypatch):
    got, started = _day(monkeypatch, 10, backlog=4, counter=lambda pid: type("R", (), {"poll": lambda s, w: 0})())
    argv = started[0]
    assert argv[argv.index("--limit") + 1] == "14" and "--hold-router" in argv
    assert float(argv[argv.index("--until") + 1]) == pytest.approx(_at(day_fetch.NIGHT_START_H))
    assert argv[argv.index("--budget-gib") + 1] == f"{day_fetch.budget_gib():g}"


def test_with_no_byte_counter_the_capped_hours_start_nothing(monkeypatch):
    monkeypatch.setattr(throttle, "available", lambda: False)
    got, started = _day(monkeypatch, 10)
    assert not got["started"] and "byte counter" in got["why"] and not started
    got, started = _day(monkeypatch, 8)
    argv = started[0]
    assert float(argv[argv.index("--until") + 1]) == pytest.approx(_at(day_fetch.CAP_START_H))


# --- 6. a day download leaves the router alone; the night restarts it once ----

def test_a_held_router_is_not_restarted_and_the_night_restarts_it_once(store, monkeypatch, _no_real_services):
    _seed(store, "org/coder-GGUF", 4)
    monkeypatch.setattr(fetching.lanes, "GGUF_SERVED", tuple(fetching.lanes.GGUF_SERVED) + ("code",))
    monkeypatch.setattr(gguf, "adopt", lambda conn, name: "/models/coder-Q4_K_M.gguf")
    fetching.run(store, limit=1, free=1000 * GIB, budget=40 * GIB, refresh=False)
    assert _no_real_services == [] and gguf.unlisted() == ["coder-Q4_K_M"]
    gguf.relist()
    assert _no_real_services == [("coder-Q4_K_M",)] and gguf.unlisted() == []


def test_a_closed_window_starts_no_download(store):
    _seed(store, "org/late", 1)
    got = fetching.run(store, limit=3, free=1000 * GIB, budget=40 * GIB, stop_at=100.0, clock=lambda: 200.0)
    assert not [g for g in got if g["ok"]] and "window has closed" in got[-1]["why"]
