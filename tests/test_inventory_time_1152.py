"""`soh inventory time`: planted hours give exact category totals, and the store is only ever read. #1152."""
import datetime as dt
import hashlib
import json
import sqlite3

import pytest

from harness import cli, inventory_time as it, ledger, paths
from harness import memory_store as ms

UTC = dt.timezone.utc
#: 08:00 UTC, so with tz=UTC the ten planted hours are all daytime.
T0 = 1791964800
H = 3600


def _iso(t: float) -> str:
    return dt.datetime.fromtimestamp(t, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _rich(t: float) -> str:
    return dt.datetime.fromtimestamp(t).strftime("[%m/%d/%y %H:%M:%S]")


def _req(conn, at, total, purpose, client="python-httpx/0.28.1", lane="", call_id=""):
    conn.execute("INSERT INTO gateway_requests (at, client, lane, purpose, total_s, call_id) VALUES (?,?,?,?,?,?)",
                 (at, client, lane, purpose, total, call_id))


def plant(home, conn):
    """Ten hours from T0, one planted per category, plus the blocking facts."""
    mid = ms.remember_machine(conn)
    conn.execute("UPDATE machines SET first_seen = ? WHERE id = ?", (T0, mid))
    _req(conn, T0, 3000, "eval")                                   # h0 measurement
    _req(conn, T0 + H, 2000, "work", lane="code")                  # h1 work, which the eval under it
    _req(conn, T0 + H, 2500, "eval")                               # does not take
    _req(conn, T0 + 2 * H, 2400, "unknown", client="Python-urllib/3.12")   # h2 infovore
    conn.execute("INSERT INTO jobs (kind, argv, state, created_at, started_at, finished_at, machine_id) "
                 "VALUES ('command', ?, 'done', ?, ?, ?, ?)",
                 (json.dumps(["uv", "run", "soh", "discover", "--loop"]), T0 + 3 * H, T0 + 3 * H, T0 + 4 * H, mid))
    run = home / "runs" / "r5"
    run.mkdir(parents=True)
    (run / "progress.json").write_text(json.dumps({"started_at": T0 + 5 * H, "last_progress_at": T0 + 5 * H + 3000}),
                                       encoding="utf-8")
    conn.execute("INSERT INTO runs (path, lane, tier, machine_id, generated_at, recorded_at) "
                 "VALUES ('r5', 'code', 'measure', ?, ?, ?)", (mid, T0 + 5 * H + 3000, T0))
    conn.execute("INSERT INTO lane_probes (at, machine_id, lane, outcome, reason) VALUES (?, ?, 'code', 'up', '')",
                 (T0 + 6 * H + 60, mid))
    conn.execute("INSERT INTO lane_probes (at, machine_id, lane, outcome, reason) VALUES "
                 "(?, ?, 'code', 'skipped', 'the model is not resident; a probe would load it')", (T0 + 7 * H + 60, mid))
    acts = [(T0 + 60, "memory_warn", "notify", 0), (T0 + H + 60, "overrun", "stop", 0),
            (T0 + 2 * H + 60, "memory", "pause", 1)]
    for at, crit, action, dry in acts:
        conn.execute("INSERT INTO watchdog_actions (at, machine_id, criterion, subject, action, dry_run) "
                     "VALUES (?, ?, ?, 'job 0001', ?, ?)", (at, mid, crit, action, dry))
    conn.execute("INSERT INTO day_clearances (machine_id, cleared_at, said, until) VALUES (?, ?, 'eric', ?)",
                 (mid, T0 + 3 * H, T0 + 5 * H))
    conn.commit()
    logs = home / "logs"
    logs.mkdir()
    (logs / "discover.log").write_text(
        f"=== sweep {_iso(T0 + 4 * H)} top=3 budget=12GiB ===\n=== sweep ===\n"
        f"=== sweep killed by SIGTERM {_iso(T0 + 5 * H)} ===\n", encoding="utf-8")
    (logs / "mcp.log").write_text(
        f"{_rich(T0 + 5 * H + 30)} INFO     Tool 'local_complete' failed: 'Error  server.py:438\n"
        "                             executing tool local_complete: this\n"
        "                             machine is busy with eval for 30s\n"
        "                    INFO     Processing request of type      server.py:700\n", encoding="utf-8")
    (home / "ledger").mkdir()
    (home / "ledger" / "power.jsonl").write_text("".join(
        json.dumps({"at": T0 + 8 * H + 60 * k, "gpu_active_ratio": 0.9, "gpu_power": 30.0}) + "\n"
        for k in range(10)), encoding="utf-8")
    return mid


@pytest.fixture
def home(tmp_path):
    h = paths.home()
    conn = ms.connect()
    plant(h, conn)
    conn.close()
    return h


def _built(home):
    conn = ledger.open_ro(ms.db_path())
    try:
        src = it.gather(conn, home, T0 + 10 * H)
    finally:
        conn.close()
    return it.build(src, tz=UTC)


def test_planted_hours_give_exact_category_totals(home):
    L = _built(home)
    got = {r["category"]: r["hours"] for r in L["pareto"]}
    assert got == {"measurement": 2, "discovery": 2, "work": 1, "infovore": 1, "idle-but-loaded": 1,
                   "idle": 1, "other": 1, "idle-unrecorded": 1}
    hours = [h["category"] for h in L["hours"]]
    assert hours == ["measurement", "work", "infovore", "discovery", "discovery", "measurement",
                     "idle-but-loaded", "idle", "other", "idle-unrecorded"]
    assert L["window"]["hours"] == 10
    assert L["pareto"][-1]["cumulative"] == 1.0


def test_an_overlapped_second_goes_to_the_earlier_category():
    hrs = it.account([(0, 2000, it.WORK), (0, 2500, it.MEASUREMENT)], 0, H)
    assert hrs[0]["seconds"] == {"work": 2000, "measurement": 500, "idle-unrecorded": 1100}
    assert hrs[0]["category"] == "work"


def test_the_blocked_hours_by_reason_and_the_daytime_taken(home):
    b = _built(home)["blocked"]
    assert b["by_reason"] == {"day_clearance": 2, "memory": 1, "watchdog": 1, "refused": 1, "idle_models": 1}
    assert b["any"] == 6
    assert b["daytime_hours"] == 10
    # Every non-work hour but idle and idle-unrecorded, plus the work hour a watchdog stop marked.
    assert b["daytime_taken"] == 8
    assert b["refused"] == 1 and b["failed"] == 1


def test_night_hours_are_not_daytime():
    hrs = [{"hour": T0 - 4 * H, "category": it.MEASUREMENT}, {"hour": T0, "category": it.MEASUREMENT}]
    b = it.blocked(hrs, tz=UTC)
    assert b["daytime_hours"] == 1 and b["daytime_taken"] == 1


def test_local_work_percentiles_callers_and_outcomes():
    reqs = [{"purpose": "work", "client": "soh-delegate", "lane": "code", "total_s": float(s), "ttft_s": None,
             "prompt_tokens": 10, "completion_tokens": 1} for s in range(1, 11)]
    reqs.append({"purpose": "eval", "client": "x", "lane": "code", "total_s": 99.0, "ttft_s": None,
                 "prompt_tokens": 1, "completion_tokens": 1})
    dels = [{"at": 1000.0 + 10, "lane": "extract", "id_source": "gateway", "seconds": 1.0, "outcome": None,
             "client": "python-httpx/0.28.1"},
            {"at": 5000.0, "lane": "extract", "id_source": "gateway", "seconds": 2.0, "outcome": "used",
             "client": "python-httpx/0.28.1"},
            {"at": 6000.0, "lane": "code", "id_source": "local", "seconds": 3.0, "outcome": None, "client": None}]
    got = it.local_work(reqs, dels, mornings=[1000.0])
    (r,) = got["requests"]
    assert (r["requests"], r["prompt_tokens"]) == (10, 100)
    assert r["seconds"] == {"p50": 5.0, "p90": 9.0, "p99": 10.0}
    callers = {(d["caller"], d["lane"]): d["outcomes"] for d in got["delegations"]}
    assert callers[("morning unit", "extract")]["pending"] == 1
    assert callers[("python-httpx/0.28.1", "extract")]["used"] == 1
    assert callers[("local", "code")]["pending"] == 1
    assert got["outcomes"] == {"used": 1, "edited": 0, "discarded": 0, "accepted": 0, "rejected": 0,
                               "unknown": 0, "pending": 2}


def test_a_sweep_ends_at_its_kill_line_else_its_last_sign_of_life_within_the_next_start():
    got = it.sweeps([0.0, 10000.0, 20000.0], [500.0],
                    [(1000.0, 1500.0, it.MEASUREMENT), (12000.0, 30000.0, it.MEASUREMENT)], span=6 * H)
    assert got[0] == (0.0, 500.0)
    assert got[1] == (10000.0, 20000.0)
    assert got[2] == (20000.0, 20000.0 + it.SWEEP_FLOOR_SECONDS)


def test_refusals_are_read_from_rich_wrapped_lines():
    text = (f"{_rich(T0)} INFO     Tool 'local_complete' failed: 'Error  server.py:438\n"
            "                    executing tool local_complete:\n"
            "                    Ornith returned no answer\n"
            f"{_rich(T0 + 5)} INFO     Tool 'local_decide' failed: 'Error  server.py:438\n"
            "                    executing tool local_decide: this machine\n"
            "                    is busy with external for 3s\n")
    got = it.refusals(text)
    assert [(r["at"], r["tool"], r["refused"]) for r in got] == [
        (T0, "local_complete", False), (T0 + 5, "local_decide", True)]


def _pr(n, paths_, title="x", created="2026-10-20T00:00:00Z", state="MERGED", closes=()):
    return {"number": n, "title": title, "labels": [], "createdAt": created, "state": state,
            "additions": 10 * len(paths_), "deletions": 0,
            "files": [{"path": p, "additions": 10, "deletions": 0} for p in paths_],
            "closingIssuesReferences": [{"number": c} for c in closes]}


def test_effort_areas_counts_lines_window_and_sample_agreement():
    now = dt.datetime(2026, 10, 23, tzinfo=UTC).timestamp()
    prs = [_pr(2, ["harness/watchdog.py", "harness/cli.py", "tests/test_watchdog.py"], closes=[1]),
           _pr(4, ["evals/run.py"], created="2026-09-01T00:00:00Z"),
           _pr(5, ["tests/test_harness_exclusive.py"]),
           _pr(6, ["README.md"], title="Nightly fixes", state="CLOSED"),
           _pr(7, ["evals/run.py"], title="Watchdog stops an overrun eval", closes=[8])]
    issues = [{"number": 1, "title": "anything", "labels": [], "createdAt": "2026-10-19T00:00:00Z"},
              {"number": 3, "title": "Screen records broken", "labels": [], "createdAt": "2026-09-02T00:00:00Z"},
              {"number": 8, "title": "anything", "labels": [], "createdAt": "2026-09-02T00:00:00Z"}]
    areas = it.classify(prs, issues)
    # A title that names an area decides it; paths decide a PR whose title names none, and an issue
    # without one takes the paths of the merged PR that closed it, never that PR's title.
    assert areas == {2: "guards", 4: "measurement", 5: "serving", 6: "meta", 7: "guards",
                     1: "guards", 3: "measurement", 8: "measurement"}
    e = it.effort(prs, issues, now, sample={"1": "guards", "3": "discovery", "999": "meta"})
    assert e["all"]["guards"] == {"issues": 1, "prs": 2, "merged": 2, "lines": 40}
    assert e["all"]["measurement"] == {"issues": 2, "prs": 1, "merged": 1, "lines": 10}
    assert e["all"]["meta"] == {"issues": 0, "prs": 1, "merged": 0, "lines": 0}
    assert e["recent"]["measurement"] == {"issues": 0, "prs": 0, "merged": 0, "lines": 0}
    assert e["sample"]["checked"] == 2 and e["sample"]["agree"] == 1 and e["sample"]["rate"] == 0.5


def test_the_shipped_sample_has_thirty_hand_checked_items_in_the_closed_set():
    s = it.load_sample()
    assert len(s) == 30 and set(s.values()) <= set(it.AREAS)


#: SQLite's WAL index: a mode=ro reader of a WAL store maps it, and an empty -wal holds no write.
SIDECARS = ("-shm", "-wal")


def _snapshot(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file() and not p.name.endswith(SIDECARS)}


def test_the_command_opens_the_store_mode_ro_and_writes_nothing(home, monkeypatch, capsys):
    before = _snapshot(home)
    db = ms.db_path()
    db.chmod(0o444)
    real = sqlite3.connect
    opened = []

    def spy(target, *a, **kw):
        opened.append((str(target), kw.get("uri", False)))
        return real(target, *a, **kw)

    def refuse(*a, **kw):
        raise AssertionError("ms.connect would migrate and write the store")

    monkeypatch.setattr(sqlite3, "connect", spy)
    monkeypatch.setattr(ms, "connect", refuse)
    assert cli.main(["inventory", "time", "--json", "--no-effort", "--since", _iso(T0)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] and out["window"]["hours"] >= 10
    store = [(t, uri) for t, uri in opened if db.name in t]
    assert store and all(t.endswith("?mode=ro") and uri for t, uri in store)
    assert _snapshot(home) == before
    wal = db.with_name(db.name + "-wal")
    assert not wal.exists() or wal.stat().st_size == 0
