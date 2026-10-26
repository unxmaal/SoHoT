"""A limit that binds records a limit_cuts row, and the limits that leave no trace are an inventory that only shrinks (#1087)."""
from __future__ import annotations

import json
import sqlite3
import subprocess
import urllib.error
from pathlib import Path

import httpx
import pytest

from harness import binding, cuts, day_fetch, feeds, fetching, gateway_switch, knob_backlog, knobs, limit_trace, memory
from harness import memory_store as ms
from tests.test_harness_fetching_budget import _seed, _sizes, store  # noqa: F401
from tests.test_repo_lane import upstream  # noqa: F401

REPO = Path(__file__).resolve().parents[1]
GIB = fetching.GIB
SITE = "harness/fetching.py:run(limit)"


def _rows(conn, knob=None):
    sql, params = "SELECT knob, value, what, kept, dropped FROM limit_cuts", []
    if knob:
        sql, params = sql + " WHERE knob = ?", [knob]
    return [dict(zip(("knob", "value", "what", "kept", "dropped"), r)) for r in conn.execute(sql, params)]


@pytest.fixture
def conn():
    c = ms.connect()
    yield c
    c.close()


def test_take_records_a_cut_only_when_it_drops_something(conn):
    assert cuts.take([1, 2, 3], 5, SITE, "x", conn=conn) == [1, 2, 3]
    assert cuts.take([1, 2, 3], None, SITE, "x", conn=conn) == [1, 2, 3]
    assert cuts.take([1, 2, 3], 3, SITE, "x", conn=conn) == [1, 2, 3]
    cuts.filled([1, 2], None, SITE, "x", conn=conn)
    assert _rows(conn) == []
    assert cuts.take([1, 2, 3, 4], 3, SITE, "fetch order", conn=conn) == [1, 2, 3]
    assert _rows(conn) == [{"knob": SITE, "value": 3.0, "what": "fetch order", "kept": 3, "dropped": 1}]


def test_a_full_limit_page_is_a_cut_of_unknown_size(conn):
    cuts.filled([1, 2], 3, SITE, "page", conn=conn)
    assert _rows(conn) == []
    cuts.filled([1, 2, 3], 3, SITE, "page", conn=conn)
    assert _rows(conn) == [{"knob": SITE, "value": 3.0, "what": "page", "kept": 3, "dropped": None}]


@pytest.mark.parametrize("exc", [subprocess.TimeoutExpired(["x"], 1), httpx.ReadTimeout("slow"), TimeoutError(),
                                 urllib.error.URLError(TimeoutError("timed out"))])
def test_a_timeout_in_any_spelling_is_recorded_and_still_raised(conn, exc):
    with pytest.raises(type(exc)):
        with cuts.timeout("harness/router.py:TIMEOUT", "router GET", conn=conn):
            raise exc
    assert [r["knob"] for r in _rows(conn)] == ["harness/router.py:TIMEOUT"]
    assert _rows(conn)[0]["value"] == knobs.resolve("harness/router.py:TIMEOUT")


def test_an_error_that_is_not_a_timeout_records_nothing(conn):
    with pytest.raises(httpx.ConnectError):
        with cuts.timeout("harness/router.py:TIMEOUT", "router GET", conn=conn):
            raise httpx.ConnectError("refused")
    with pytest.raises(urllib.error.URLError):
        with cuts.timeout("harness/router.py:TIMEOUT", "router GET", conn=conn):
            raise urllib.error.URLError(ConnectionRefusedError())
    assert _rows(conn) == []


def test_a_registered_knob_records_its_registered_value(conn):
    cuts.cut("discover_top", "screen", conn=conn)
    assert _rows(conn)[0]["value"] == float(knobs.KNOBS["discover_top"].default())


def test_with_no_store_a_cut_is_spooled_and_the_next_write_moves_it():
    assert not ms.db_path().exists()
    cuts.cut(SITE, "spooled", value=2, kept=2, dropped=5)
    assert not ms.db_path().exists(), "a cut must never create a store"
    spooled = [json.loads(line) for line in cuts._spool_path().read_text(encoding="utf-8").splitlines()]
    assert [(r["knob"], r["dropped"]) for r in spooled] == [(SITE, 5)]
    c = ms.connect()
    try:
        assert cuts.flush(c) == 1
        assert [r["what"] for r in _rows(c)] == ["spooled"]
        assert not cuts._spool_path().exists()
    finally:
        c.close()


def test_a_cut_with_no_connection_writes_an_existing_store_and_takes_the_spool_with_it():
    cuts._spool({"at": 1.0, "knob": SITE, "value": 1.0, "what": "older", "kept": 0, "dropped": 1})
    ms.connect().close()
    cuts.cut(SITE, "newer", value=1)
    c = ms.connect()
    try:
        assert sorted(r["what"] for r in _rows(c)) == ["newer", "older"]
    finally:
        c.close()
    assert not cuts._spool_path().exists()


def test_a_cut_a_read_only_or_older_store_refuses_reaches_the_home_store_instead(tmp_path):
    ms.connect().close()
    ro = sqlite3.connect(f"file:{ms.db_path()}?mode=ro", uri=True)
    cuts.cut(SITE, "read only", value=1, conn=ro)
    ro.close()
    old = sqlite3.connect(tmp_path / "old.db")
    cuts.cut(SITE, "older schema", value=1, conn=old)
    assert old.execute("SELECT name FROM sqlite_master WHERE name = 'limit_cuts'").fetchone() is None
    old.close()
    c = ms.connect()
    try:
        assert [r["what"] for r in _rows(c)] == ["read only", "older schema"]
    finally:
        c.close()


def test_a_cut_no_store_takes_stays_spooled(tmp_path, monkeypatch):
    monkeypatch.setattr(cuts, "_own_store", lambda: None)
    cuts.cut(SITE, "first", value=1)
    cuts.cut(SITE, "second", value=1)
    got = [json.loads(line)["what"] for line in cuts._spool_path().read_text(encoding="utf-8").splitlines()]
    assert got == ["first", "second"]


def test_a_cut_inside_the_callers_transaction_leaves_the_commit_to_the_caller(conn):
    conn.execute("INSERT INTO meta (key, value) VALUES ('x', 'y')")
    assert conn.in_transaction
    cuts.cut(SITE, "in a transaction", value=1, conn=conn)
    conn.rollback()
    assert _rows(conn) == []
    cuts.cut(SITE, "on its own", value=1, conn=conn)
    assert not conn.in_transaction
    assert [r["what"] for r in _rows(conn)] == ["on its own"]


def test_binding_counts_a_registered_knobs_cuts_and_the_backlog_counts_a_sites(conn):
    for _ in range(binding.BINDING_MIN_HITS):
        cuts.cut("discover_top", "screen", value=3, conn=conn)
    cuts.cut(SITE, "fetch", value=1, conn=conn)
    row = next(r for r in binding.count(conn) if r["knob"] == "discover_top")
    assert (row["source"], row["hits"], row["binding"], row["value"]) == ("cut", binding.BINDING_MIN_HITS, True, 3.0)
    assert "discover_top" in binding.render(binding.count(conn)) and "3 cut(s)" in binding.render(binding.count(conn))
    site = next(r for r in knob_backlog.by_binding(conn) if r["site"] == SITE)
    assert (site["hits"], site["tiers"]) == (1, {"cut": 1})


def test_fewer_cuts_than_the_minimum_are_counted_but_not_binding(conn):
    cuts.cut("discover_top", "screen", value=3, conn=conn)
    row = next(r for r in binding.count(conn) if r["knob"] == "discover_top")
    assert (row["hits"], row["binding"]) == (1, False)


def test_the_fetch_records_the_count_under_the_knob_that_fed_it(store):
    # Equal sizes: fetch order follows this machine's ceiling, and an order-dependent budget skip is a real cut. #1087.
    for name in ("org/a", "org/b", "org/c", "org/d"):
        _seed(store, name, 1)
    fetching.run(store, _sizes(store), limit=2, free=500 * GIB, budget=int(12 * GIB),
                 limit_knob="discover_top", budget_knob="day_fetch_budget")
    assert [(r["knob"], r["value"], r["kept"], r["dropped"]) for r in _rows(store)] == [("discover_top", 2.0, 2, 2)]


def test_a_download_the_budget_refuses_is_a_cut_of_the_budget_knob(store):
    _seed(store, "org/a", 5)
    _seed(store, "org/b", 9)
    fetching.run(store, _sizes(store), limit=5, free=500 * GIB, budget=int(12 * GIB), budget_knob="day_fetch_budget")
    assert [(r["knob"], r["value"], r["kept"], r["dropped"]) for r in _rows(store)] == [("day_fetch_budget", 12.0, 1, 1)]


def test_a_fetch_that_names_no_knob_records_under_its_own_backlog_site(store):
    for name in ("org/a", "org/b"):
        _seed(store, name, 1)
    fetching.run(store, _sizes(store), limit=1, free=500 * GIB, budget=int(12 * GIB))
    assert [(r["knob"], r["kept"], r["dropped"]) for r in _rows(store)] == [(SITE, 1, 1)]


def test_the_day_fetch_and_the_loop_carry_the_knob_that_sets_each_argv_limit():
    from harness import cli
    argv = day_fetch.child_argv(3, 40.0, 0.0)
    a = cli.build_parser().parse_args(argv[3:])
    assert (a.limit_knob, a.budget_knob) == ("screen_fraction", "day_fetch_budget")
    a = cli.build_parser().parse_args(["fetch", "--run"])
    assert (a.limit_knob, a.budget_knob) == (SITE, "download_budget")


def test_the_reserve_is_recorded_only_when_it_decided_the_refusal(monkeypatch):
    monkeypatch.setattr(memory, "need_gb", lambda *a, **k: 20.0)
    monkeypatch.setattr(memory, "available_gb", lambda: 24.0)
    monkeypatch.setattr(memory, "ceiling_gb", lambda: 64.0)
    ok, _ = memory.check_model("org/m", reserve_gb=memory.DEFAULT_RESERVE_GB)
    assert not ok
    monkeypatch.setattr(memory, "need_gb", lambda *a, **k: 30.0)
    assert not memory.check_model("org/m", reserve_gb=memory.DEFAULT_RESERVE_GB)[0]
    assert memory.check_model("org/m", reserve_gb=1.5)[0] is False
    spooled = [json.loads(line) for line in cuts._spool_path().read_text(encoding="utf-8").splitlines()]
    assert [r["knob"] for r in spooled] == ["harness/memory.py:DEFAULT_RESERVE_GB"]


def test_a_feed_that_runs_out_of_retries_records_the_retries_knob_it_was_given():
    def fail(*a, **k):
        raise urllib.error.HTTPError("u", 503, "busy", {}, None)
    import urllib.request
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(urllib.request, "urlopen", fail)
        with pytest.raises(feeds.FeedError):
            feeds.fetch("https://x.test/feed", retries=1, sleep=lambda s: None, retries_knob="harness/inspect.py:SIZE_RETRIES")
    spooled = [json.loads(line) for line in cuts._spool_path().read_text(encoding="utf-8").splitlines()]
    assert [(r["knob"], r["value"]) for r in spooled] == [("harness/inspect.py:SIZE_RETRIES", 1.0)]


def test_a_gateway_that_never_serves_the_new_alias_records_the_serve_wait(monkeypatch):
    monkeypatch.setattr(gateway_switch, "not_serving", lambda base, want: "code serves old")
    clock = iter([0.0, 0.0, gateway_switch.SERVE_WAIT_S + 1, gateway_switch.SERVE_WAIT_S + 1])
    assert gateway_switch._await_serving("http://gw", {}, lambda: next(clock), lambda s: None, 0.1) == "code serves old"
    spooled = [json.loads(line) for line in cuts._spool_path().read_text(encoding="utf-8").splitlines()]
    assert [r["knob"] for r in spooled] == ["harness/gateway_switch.py:SERVE_WAIT_S"]


def test_the_scanner_reads_every_way_code_names_the_knob_a_cut_records():
    src = ("from harness import cuts\n"
           "def f(items, limit_knob='discover_top', *, budget_knob='download_budget'):\n"
           "    cuts.take(items, 3, 'a.py:LIMIT', 'x')\n"
           "    cuts.cut(limit_knob, 'x')\n"
           "    reserve_knob = 'a.py:R1' if items else 'a.py:R2'\n"
           "    g(spill_knob='a.py:S' if items else 'a.py:T', other='a.py:NOT')\n"
           "    p.add_argument('--top-knob', default='a.py:TOP')\n"
           "    return ['--limit-knob', 'screen_fraction', '--limit', '3']\n")
    got = sorted(n for n, _ in limit_trace.names_in(src, "a.py"))
    assert got == ["a.py:LIMIT", "a.py:R1", "a.py:R2", "a.py:S", "a.py:T", "a.py:TOP", "discover_top",
                   "download_budget", "screen_fraction"]
    bad = "from harness import cuts\ndef f(name, limit_knob):\n    cuts.cut(name, 'x')\n    cuts.cut(limit_knob, 'x')\n"
    assert limit_trace.unnamed_in(bad, "a.py") == ["a.py:3"]


def test_a_limit_is_traced_by_a_recorded_limit_a_knob_name_or_its_site():
    names = {"discover_top": [], "harness/x.py:MAX": []}
    assert limit_trace.traced("scripts/serve-discover.sh:DISCOVER_TOP", "discover_top", names)
    assert limit_trace.traced("harness/x.py:MAX", "", names)
    assert not limit_trace.traced("harness/x.py:MIN", "", names)
    with_limit = next(k for k in knobs.KNOBS.values() if k.limit)
    assert limit_trace.traced(with_limit.sites[0], with_limit.name, {})
    via = next(k for k in knobs.KNOBS.values() if k.binds_via)
    assert limit_trace.traced(via.sites[0], via.name, {})
    without = next(k for k in knobs.KNOBS.values() if not k.limit and k.name not in limit_trace.named(REPO))
    assert not limit_trace.traced(without.sites[0], without.name, {})


def _inventory() -> list[str]:
    return knob_backlog.sites(REPO, limit_trace.DIR)


def test_every_cut_names_a_registered_knob_or_a_gating_site_and_names_it_where_a_scan_can_read_it():
    assert limit_trace.unknown(REPO) == []
    assert limit_trace.unnamed(REPO) == []


def test_no_limit_leaves_no_trace_unless_the_untraced_inventory_lists_it():
    new = sorted(set(limit_trace.untraced(REPO)) - set(_inventory()))
    assert not new, ("record a cut with harness.cuts when these bind, or list them in tests/gauntlet/untraced/:\n  "
                     + "\n  ".join(f"{limit_trace.file_of(s)}: {s}" for s in new))


def test_the_untraced_inventory_only_shrinks():
    gone = sorted(set(_inventory()) - set(limit_trace.untraced(REPO)))
    assert not gone, "traced or gone: remove from tests/gauntlet/untraced/:\n  " + "\n  ".join(
        f"{limit_trace.file_of(s)}: {s}" for s in gone)
    got = knob_backlog.added(REPO, directory=limit_trace.DIR)
    if got is None:
        pytest.skip(f"{knob_backlog.BASE} is not in this clone, or holds no untraced inventory yet")
    assert not got, "not untraced at the merge base with origin/main; trace these instead:\n  " + "\n  ".join(got)


def test_each_untraced_file_is_sorted_unique_and_holds_only_its_own_directory():
    files = sorted((REPO / limit_trace.DIR).glob("*.txt"))
    assert files
    for path in files:
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()
        assert lines and text.endswith("\n") and "\n\n" not in text, path.name
        assert lines == sorted(set(lines)), f"{path.name}: one site per line, sorted, no repeats"
        assert all(limit_trace.file_of(s) == path.name for s in lines), path.name


def test_an_untraced_line_added_on_a_branch_fails_against_the_merge_base(tmp_path):
    from tests.test_knob_merge import git
    inv = tmp_path / limit_trace.DIR
    inv.mkdir(parents=True)
    (inv / "harness.txt").write_text("harness/a.py:MAX_A\n", encoding="utf-8")
    git(tmp_path, "init", "-q", "-b", "main")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-q", "-m", "base")
    git(tmp_path, "update-ref", "refs/remotes/origin/main", "HEAD")
    git(tmp_path, "checkout", "-q", "-b", "work")
    (inv / "harness.txt").write_text("harness/a.py:MAX_A\nharness/b.py:MAX_B\n", encoding="utf-8")
    assert knob_backlog.added(tmp_path, directory=limit_trace.DIR) == ["harness/b.py:MAX_B"]
    assert knob_backlog.added(tmp_path) is None, "a list the merge base does not hold has nothing to grow from"


def test_every_never_cuts_exemption_gives_a_reason_names_a_gating_site_and_cuts_nothing():
    assert knobs.NEVER_CUTS
    assert limit_trace.exemption_problems(knobs.NEVER_CUTS) == []
    assert not set(knobs.NEVER_CUTS) & set(_inventory()), "an exempted site leaves the untraced inventory"


def test_the_exemption_check_parses_each_module_once_however_many_exemptions(monkeypatch):
    texts = {"a.py": "import time\nPOLL_S = 1.0\nWAIT_S = 2.0\ndef f():\n    time.sleep(POLL_S)\n", "b.py": "x = 1\n"}
    parsed = []
    real = limit_trace.ast.parse
    monkeypatch.setattr(limit_trace.ast, "parse", lambda text, *a, **k: parsed.append(text) or real(text, *a, **k))
    assert limit_trace.exemption_problems({"a.py:POLL_S": "pacing", "a.py:WAIT_S": "pacing"},
                                          root=None, texts=texts) == []
    assert sorted(parsed) == sorted(texts.values())


def test_an_exemption_with_no_reason_is_refused():
    texts = {"a.py": "import time\nPOLL_S = 1.0\ndef f():\n    time.sleep(POLL_S)\n"}
    assert limit_trace.exemption_problems({"a.py:POLL_S": "  "}, root=None, texts=texts) == ["a.py:POLL_S: no reason given"]
    assert limit_trace.exemption_problems({"a.py:POLL_S": "pacing"}, root=None, texts=texts) == []


@pytest.mark.parametrize("use", ["return items[:POLL_S]", "return min(len(items), POLL_S)", "return range(POLL_S)",
                                 "for i in items:\n        if i >= POLL_S:\n            break"])
def test_an_exempted_constant_that_bounds_work_is_refused(use):
    texts = {"a.py": f"POLL_S = 3\ndef f(items):\n    {use}\n",
             "b.py": "from a import POLL_S\n", "c.py": "import a\nx = [1][:a.POLL_S]\n"}
    got = limit_trace.exemption_problems({"a.py:POLL_S": "pacing"}, root=None, texts=texts)
    assert got and got[0].startswith("a.py:POLL_S: cuts work at a.py:"), got
    assert "a.py:POLL_S: cuts work at c.py:2" in got


def test_an_exempted_parameter_is_read_by_its_bare_name_only():
    ok = {"a.py": "def f(proc, poll=1):\n    while proc.poll() is None:\n        sleep(poll)\n"}
    assert limit_trace.exemption_problems({"a.py:f(poll)": "pacing"}, root=None, texts=ok) == []
    bad = {"a.py": "def f(items, poll=1):\n    return items[:poll]\n"}
    assert limit_trace.exemption_problems({"a.py:f(poll)": "pacing"}, root=None, texts=bad) == [
        "a.py:f(poll): cuts work at a.py:2"]


def test_an_exemption_for_a_traced_limit_or_no_site_is_refused():
    got = limit_trace.exemption_problems({"harness/router.py:TIMEOUT": "x", "harness/nope.py:POLL_S": "x"})
    assert got == ["harness/nope.py:POLL_S: not a gating site the registry or the knob backlog holds",
                   "harness/router.py:TIMEOUT: already records its cuts"]


def _spooled_knobs() -> list[tuple]:
    path = cuts._spool_path()
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    return [(r["knob"], r["kept"], r["dropped"]) for r in map(json.loads, lines)]


def test_tool_calls_past_the_repair_turn_cap_are_a_cut(monkeypatch, upstream):  # noqa: F811
    from evals.runners import repo_repair
    from tests.test_repo_repair_890 import _call, _runner
    up = upstream
    monkeypatch.setattr(repo_repair, "CALLS_PER_TURN", 2)
    many = {"tool_calls": [_call("list_files")["tool_calls"][0] | {"id": f"c{i}"} for i in range(5)]}
    _runner([many, _call("finish")], []).run(up)
    assert ("repair_calls_per_turn", 2, 3) in _spooled_knobs()


def test_repair_tool_output_past_the_cap_is_a_cut():
    from evals import repo_tools
    repo_tools.cut("x" * repo_tools.OUTPUT_CAP)
    assert _spooled_knobs() == []
    repo_tools.cut("x" * (repo_tools.OUTPUT_CAP + 5))
    assert _spooled_knobs() == [("repair_output_cap", repo_tools.OUTPUT_CAP, 5)]


def test_repo_cases_the_fix_size_selector_leaves_out_are_a_cut(monkeypatch):
    import argparse
    from evals import repo_size, run
    monkeypatch.setattr(repo_size, "at_most", lambda chosen, limit: chosen[:1])
    args = argparse.Namespace(max_fix_lines=20, modality="repo")
    assert run.fix_sized(["a", "b", "c"], args) == ["a"]
    assert _spooled_knobs() == [("repo_max_fix_lines", 1, 2)]
    monkeypatch.setattr(repo_size, "at_most", lambda chosen, limit: chosen)
    run.fix_sized(["a"], args)
    assert len(_spooled_knobs()) == 1


def test_repo_cases_the_fix_size_floor_leaves_out_are_a_cut(monkeypatch):
    import argparse
    from evals import repo_size, run
    monkeypatch.setattr(repo_size, "at_least", lambda chosen, floor: chosen[1:])
    args = argparse.Namespace(max_fix_lines=None, min_fix_lines=21, modality="repo")
    assert run.fix_sized(["a", "b", "c"], args) == ["b", "c"]
    assert _spooled_knobs() == [("repo_min_fix_lines", 2, 1)]


@pytest.mark.gauntlet("a-closed-table-fronting-an-open-set", site="harness/limit_trace.py:CALLS")
def test_every_cuts_call_that_records_a_knob_is_one_the_scanner_reads():
    import inspect
    recorders = {name for name, fn in vars(cuts).items() if inspect.isfunction(fn) and fn.__module__ == cuts.__name__
                 and not name.startswith("_") and "knob" in inspect.signature(fn).parameters}
    assert recorders - {"value_of"} == set(limit_trace.CALLS)
    for name, at in limit_trace.CALLS.items():
        assert list(inspect.signature(getattr(cuts, name)).parameters)[at] == "knob", name
