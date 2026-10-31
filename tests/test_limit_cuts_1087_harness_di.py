"""Limits in harness/d* through harness/i* record a limit_cuts row when they bind, and only then (#1087)."""
from __future__ import annotations

import argparse
import contextlib
import json
import sqlite3
import subprocess
import sys
import time
import urllib.error
from datetime import datetime
from types import SimpleNamespace

import pytest

from harness import cuts
from harness import memory_store as ms


def _cuts() -> list[tuple]:
    """(knob, kept, dropped) of every cut, spooled or flushed into this home's store."""
    path = cuts._spool_path()
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    out = [(r["knob"], r["kept"], r["dropped"]) for r in map(json.loads, lines)]
    if ms.db_path().exists():
        with contextlib.closing(sqlite3.connect(ms.db_path())) as c:
            with contextlib.suppress(sqlite3.Error):
                out += [tuple(r) for r in c.execute("SELECT knob, kept, dropped FROM limit_cuts ORDER BY id")]
    return out


def _knobs() -> list[str]:
    return [k for k, _, _ in _cuts()]


@pytest.fixture
def conn():
    c = ms.connect()
    yield c
    c.close()


# ---- day_fetch ------------------------------------------------------------------------------------

def _at(hour, minute=30):
    return datetime.now().replace(hour=hour, minute=minute, second=0, microsecond=0).timestamp()


class _Proc:
    pid, returncode = 4242, 0

    def poll(self):
        return 0

    def wait(self, timeout=None):
        return 0


def _day(monkeypatch, hour, *, counter=True, stopped_s=0.0):
    from harness import day_fetch, throttle
    monkeypatch.setattr(day_fetch, "room", lambda conn, b: (3, "sized"))
    monkeypatch.setattr(throttle, "available", lambda: counter)
    return day_fetch.run(argparse.Namespace(budget_gib=None), clock=lambda: _at(hour), store=SimpleNamespace(
        close=lambda: None), backlog=0, environ={day_fetch.ENABLE: "1"}, running=lambda root: [],
        popen=lambda argv: _Proc(), counter=(lambda pid: SimpleNamespace(poll=lambda w: 0)) if counter else None,
        hold=lambda proc, cap, read, **k: {"stopped_s": stopped_s})


@pytest.mark.parametrize("hour,knob", [(21, "day_fetch_night_start"), (6, "day_fetch_night_end")])
def test_the_night_refuses_a_day_fetch_and_says_which_edge_held_it(monkeypatch, hour, knob):
    assert not _day(monkeypatch, hour)["started"]
    assert _knobs() == [knob]


def test_a_day_fetch_that_runs_unthrottled_records_nothing(monkeypatch):
    assert _day(monkeypatch, 10)["started"]
    assert _cuts() == []


def test_a_day_fetch_paused_to_hold_its_rate_records_the_cap(monkeypatch):
    assert _day(monkeypatch, 10, stopped_s=3.0)["started"]
    assert _knobs() == ["day_fetch_cap"]


def test_without_a_byte_counter_the_capped_hours_refuse_and_the_morning_window_ends_at_them(monkeypatch):
    assert not _day(monkeypatch, 10, counter=False)["started"]
    assert _knobs() == ["day_fetch_cap_end"]
    assert _day(monkeypatch, 8, counter=False)["started"]
    assert _knobs() == ["day_fetch_cap_end", "day_fetch_cap_start"]


def test_without_a_byte_counter_an_evening_window_ends_at_night_and_records_nothing(monkeypatch):
    assert _day(monkeypatch, 17, counter=False)["started"]
    assert _cuts() == []


# ---- degenerate -----------------------------------------------------------------------------------

def test_a_short_budget_cut_reply_is_a_cut_of_the_measure_floor():
    from harness import degenerate as dg
    assert dg.judged("") == ({}, False)
    assert _cuts() == []
    assert dg.judged("x" * (dg.MIN_CHARS - 1)) == ({}, False)
    assert _knobs() == ["degenerate_min_chars"]


def test_a_looping_reply_records_the_repeat_threshold_and_a_varied_one_records_nothing():
    import random
    from harness import degenerate as dg
    rng = random.Random(7)
    varied = "".join(rng.choice("abcdefghijklmnopqrstuvwxyz0123456789{}()=+-") for _ in range(dg.MIN_CHARS * 2))
    assert dg.judged(varied)[1] is False
    assert _cuts() == []
    assert dg.judged("the same line again and again\n" * 100)[1] is True
    assert _knobs() == ["degenerate_repeat"]


def test_a_collapsed_reply_records_the_entropy_threshold():
    from harness import degenerate as dg
    import random
    rng = random.Random(3)
    collapsed = "".join(rng.choice("ab") for _ in range(dg.MIN_CHARS * 2))
    got, bad = dg.judged(collapsed)
    assert bad and got["tail_repeat"] < dg.REPEAT_SHARE
    assert _knobs() == ["degenerate_entropy"]


# ---- delegate -------------------------------------------------------------------------------------

def test_a_max_tokens_under_one_is_a_cut_of_the_preflight_floor():
    from harness import delegate
    delegate._preflight("hello", max_tokens=1)
    assert _cuts() == []
    with pytest.raises(delegate.Refused):
        delegate._preflight("hello", max_tokens=0)
    assert _knobs() == ["harness/delegate.py:_preflight(max_tokens)"]


def test_a_request_over_the_unknown_context_cap_is_a_cut_of_max_tokens(monkeypatch):
    from harness import delegate
    monkeypatch.setattr(delegate.context, "served_ctx", lambda spec: None)
    delegate._budget("m", delegate.MAX_TOKENS, "hi")
    assert _cuts() == []
    with pytest.raises(delegate.Refused):
        delegate._budget("m", delegate.MAX_TOKENS + 1, "hi")
    assert _knobs() == ["harness/delegate.py:MAX_TOKENS"]


def test_an_estimated_prompt_names_chars_per_token_and_a_counted_one_names_nothing(monkeypatch):
    from harness import delegate
    monkeypatch.setattr(delegate.context, "served_ctx", lambda spec: 100)
    monkeypatch.setattr(delegate, "counter", lambda spec: lambda text: 1)
    with pytest.raises(delegate.Refused):
        delegate._budget("m", 200, "x" * 30)
    assert _cuts() == []
    monkeypatch.setattr(delegate, "counter", lambda spec: None)
    with pytest.raises(delegate.Refused):
        delegate._budget("m", 95, "x" * 30)
    assert _knobs() == ["delegate_chars_per_token"]


def _failing(monkeypatch, failure):
    from harness import completion, delegate, reasons, serving
    where = serving.Route("http://127.0.0.1:1", "m", {})
    monkeypatch.setattr(delegate, "route", lambda lane, model: ("m", where))
    monkeypatch.setattr(delegate, "_budget", lambda *a: None)
    monkeypatch.setattr(delegate, "_allowance", lambda where, mt, timeout: timeout or delegate.TIMEOUT_S)
    monkeypatch.setattr(delegate, "as_work", lambda *a, **k: contextlib.nullcontext({}))
    monkeypatch.setattr(delegate, "generate", lambda spec, where, lane, prompt, call: call(prompt))

    def fail(*a, **k):
        raise completion.CompletionError("no", getattr(reasons, failure))
    monkeypatch.setattr(completion, "complete_full", fail)
    return delegate


def test_a_reply_cut_at_its_budget_records_the_complete_default(monkeypatch):
    delegate = _failing(monkeypatch, "TOKEN_BUDGET_EXHAUSTED")
    with pytest.raises(delegate.completion.CompletionError):
        delegate.complete("code", "write it", max_tokens=16)
    assert _knobs() == ["harness/delegate.py:complete(max_tokens)"]


def test_a_timeout_at_the_floor_is_a_cut_and_one_the_caller_set_is_not(monkeypatch):
    delegate = _failing(monkeypatch, "TIMEOUT")
    with pytest.raises(delegate.completion.CompletionError):
        delegate.complete("code", "write it", max_tokens=16, timeout=5.0)
    assert _cuts() == []
    with pytest.raises(delegate.completion.CompletionError):
        delegate.complete("code", "write it", max_tokens=16)
    assert _knobs() == ["harness/delegate.py:TIMEOUT_S"]


# ---- delegations ----------------------------------------------------------------------------------

def test_an_answer_seen_below_the_share_is_one_near_miss():
    from harness import delegations
    answer = "\n".join(f"line number {i} of the answer, long enough to look for" for i in range(8))
    near: list = []
    assert delegations.judge(answer, "", [("Edit", "line number 1 of the answer, long enough to look for")],
                             near=near) is None
    assert near == [answer]
    near.clear()
    assert delegations.judge(answer, "", [("Edit", answer)], near=near)[0] == delegations.ACCEPTED
    assert delegations.judge(answer, "", [("Edit", "nothing")], near=near) is None
    assert near == []


def test_expired_delegations_record_the_expiry_and_a_short_answer_the_span_floor(conn, tmp_path, monkeypatch):
    from harness import delegations
    delegations.record(conn, delegations.new_id(), "code", at=time.time() - 60)
    delegations.close(conn, root=tmp_path)
    assert _cuts() == []
    old = delegations.record(conn, delegations.new_id(), "code", at=time.time() - 3 * 86400)
    monkeypatch.setattr(delegations, "calls", lambda path, wanted: [
        {"call_id": old, "answer": "ok", "prompt": "", "later": []}])
    (tmp_path / "p").mkdir()
    (tmp_path / "p" / "s.jsonl").write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr("harness.context_report.transcripts", lambda root, newer_than=0: [tmp_path / "p" / "s.jsonl"])
    assert delegations.close(conn, root=tmp_path)["unknown"] == 1
    assert sorted(_cuts()) == [("delegation_expiry", None, 1), ("delegation_span_chars", None, 1)]


def test_a_pending_answer_seen_below_the_share_is_a_cut_of_the_share(conn, tmp_path, monkeypatch):
    from harness import delegations
    answer = "\n".join(f"line number {i} of the answer, long enough to look for" for i in range(8))
    cid = delegations.record(conn, delegations.new_id(), "code", at=time.time() - 60)
    later = [("Edit", "nothing of it")]
    monkeypatch.setattr(delegations, "calls", lambda path, wanted: [
        {"call_id": cid, "answer": answer, "prompt": "", "later": later}])
    (tmp_path / "p").mkdir()
    (tmp_path / "p" / "s.jsonl").write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr("harness.context_report.transcripts", lambda root, newer_than=0: [tmp_path / "p" / "s.jsonl"])
    assert delegations.close(conn, root=tmp_path)["pending"] == 1
    assert _cuts() == []
    later[:] = [("Edit", "line number 1 of the answer, long enough to look for")]
    assert delegations.close(conn, root=tmp_path)["pending"] == 1
    assert _cuts() == [("delegation_span_share", None, 1)]


# ---- disk and downloads ---------------------------------------------------------------------------

def test_rejected_weights_inside_their_grace_are_one_cut_per_cleanup(conn, tmp_path):
    from harness import disk
    now = 2_000_000_000.0

    def entry(name, decided_at):
        return disk.Entry(path=str(tmp_path / name), name=name, kind="hub", repo=name, size=1,
                          mtime=now, group=disk.REJECTED, why="broken", decided_at=decided_at)
    young = [entry("a", now - 3600), entry("b", now - 7200)]
    inv = disk.Inventory(str(tmp_path / "hub"), str(tmp_path / "gguf"), young, [], [])
    assert disk.delete(inv, now, disk.REJECTED, conn) == []
    assert _cuts() == [("harness/disk.py:GRACE_SECONDS", None, 2)]
    inv = disk.Inventory(str(tmp_path / "hub"), str(tmp_path / "gguf"), [], [], [])
    disk.delete(inv, now, disk.REJECTED, conn)
    assert len(_cuts()) == 1


def test_a_partial_download_kept_by_its_age_alone_is_a_cut(conn, tmp_path, monkeypatch):
    from harness import disk, downloads
    hub = tmp_path / "hub"
    blob = hub / "models--org--x" / "blobs" / "abc.incomplete"
    blob.parent.mkdir(parents=True)
    blob.write_bytes(b"abc")
    now = time.time()
    row = {"path": str(blob.parent.parent), "started_at": now - 60, "finished_at": None, "repo": "org/x"}
    monkeypatch.setattr(disk, "_rows", lambda c: {downloads.key(blob.parent.parent): row})
    inv = disk.Inventory(str(hub), str(tmp_path / "gguf"), [],
                         [{"path": str(blob), "dir": str(blob.parent.parent), "size": 3}], [])
    assert disk.clear_incomplete(inv, conn, now=now) == []
    assert _cuts() == [("harness/downloads.py:IN_FLIGHT_SECONDS", None, 1)]
    row["started_at"] = now - 3 * 86400
    assert len(disk.clear_incomplete(inv, conn, now=now)) == 1
    assert len(_cuts()) == 1


# ---- ds4 and vllm ---------------------------------------------------------------------------------

def test_a_ds4_version_read_that_times_out_is_a_cut(monkeypatch):
    from harness import ds4

    def slow(*a, **k):
        raise subprocess.TimeoutExpired(a[0], 10)
    monkeypatch.setattr(ds4.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stdout="2026.10.01\n"))
    assert ds4.version() == "2026.10.01"
    assert _cuts() == []
    monkeypatch.setattr(ds4.subprocess, "run", slow)
    assert ds4.version() == ""
    assert _knobs() == ["harness/ds4.py:version->subprocess.run(timeout)"]


def test_a_models_probe_that_times_out_is_a_cut_and_a_refused_one_is_not(monkeypatch):
    from harness import ds4

    def opener(exc):
        def open_(url, timeout=None):
            raise exc
        return SimpleNamespace(open=open_)
    monkeypatch.setattr(ds4, "_DIRECT", opener(urllib.error.URLError(ConnectionRefusedError())))
    assert ds4._models("http://127.0.0.1:1") is None
    assert _cuts() == []
    monkeypatch.setattr(ds4, "_DIRECT", opener(urllib.error.URLError(TimeoutError())))
    assert ds4._models("http://127.0.0.1:1") is None
    assert _knobs() == ["harness/ds4.py:_models->_DIRECT.open(timeout)"]


@pytest.mark.parametrize("gib,knob", [(1, "harness/ds4.py:START_FLOOR_S"), (100, "harness/ds4.py:START_S_PER_GIB")])
def test_a_ds4_launch_names_the_larger_part_of_its_wait(monkeypatch, gib, knob):
    from harness import ds4, vllm
    seen = {}

    @contextlib.contextmanager
    def served(argv, port, **kw):
        seen.update(kw)
        raise RuntimeError("did not serve")
        yield
    monkeypatch.setattr(ds4, "preflight", lambda spec, port_: None)
    monkeypatch.setattr(ds4, "argv", lambda spec, port_: ["ds4-server"])
    monkeypatch.setattr(ds4, "start_timeout", lambda spec: ds4.START_FLOOR_S + ds4.START_S_PER_GIB * gib)
    monkeypatch.setattr(vllm, "served", served)
    with pytest.raises(ds4.Unservable), ds4.serving("ds4:x", 1):
        pass
    assert seen["timeout_knob"] == knob


def test_a_server_that_never_answers_records_the_knob_its_caller_named(tmp_path):
    from harness import vllm
    from tests.test_vllm import _free_port, _utf8_env
    child = tmp_path / "child.py"
    child.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="did not serve"):
        with vllm.served([sys.executable, str(child)], _free_port(), log=tmp_path / "s.log", env=_utf8_env(),
                         timeout=0.5, poll=0.1, grace=1.0, timeout_knob="harness/ds4.py:START_FLOOR_S"):
            pass
    assert _knobs() == ["harness/ds4.py:START_FLOOR_S"]


# ---- engines, env, exclusive ----------------------------------------------------------------------

def test_an_h3_clip_under_the_minimum_frames_is_a_cut():
    from pathlib import Path
    from harness import engines
    eng = engines.resolve("h3")
    eng.argv("a fox", Path("/out.mp4"), {"frames": engines.H3_MIN_FRAMES})
    assert _cuts() == []
    with pytest.raises(ValueError):
        eng.argv("a fox", Path("/out.mp4"), {"frames": engines.H3_MIN_FRAMES - 1})
    assert _knobs() == ["harness/engines.py:H3_MIN_FRAMES"]


def test_a_weights_location_short_of_free_space_is_a_cut(tmp_path, monkeypatch):
    from harness import env
    monkeypatch.setattr(env, "free_gb", lambda path: env.HF_MIN_FREE_GB)
    assert env.usable(str(tmp_path))
    assert _cuts() == []
    monkeypatch.setattr(env, "free_gb", lambda path: env.HF_MIN_FREE_GB - 1)
    assert not env.usable(str(tmp_path))
    assert _knobs() == ["harness/env.py:HF_MIN_FREE_GB"]


def test_a_cloud_eval_that_waited_for_a_slot_is_a_cut(monkeypatch):
    from harness import exclusive
    monkeypatch.delenv(exclusive.HELD_ENV, raising=False)
    monkeypatch.delenv(exclusive.CLOUD_HELD_ENV, raising=False)
    with exclusive._cloud("eval", None, 0.0, None) as waited:
        assert waited is False
    assert _cuts() == []
    tries = iter([False] * exclusive.CLOUD_SLOTS)
    real = exclusive._take
    monkeypatch.setattr(exclusive, "_take", lambda fd: next(tries, None) is not False and real(fd))
    with exclusive._cloud("eval", None, 0.0, None) as waited:
        assert waited is True
    assert _knobs() == ["cloud_evals"]


# ---- family ---------------------------------------------------------------------------------------

class _Rows:
    def __init__(self, rows):
        self.rows = rows

    def execute(self, *a):
        return SimpleNamespace(fetchall=lambda: self.rows)


def test_a_lineage_chain_ended_by_a_size_change_is_one_cut_per_standing(monkeypatch):
    from harness import family
    monkeypatch.setattr(family, "graph", lambda conn: {"org/a-7b-ft": ["org/a-70b"], "org/b-7b-ft": ["org/b-7b"]})
    st = family.standing(_Rows([(1.0, "declined", "code: x", "org/b-7b-ft", "code")]))
    assert st.families and _cuts() == []
    family.standing(_Rows([(1.0, "declined", "code: x", "org/a-7b-ft", "code"),
                           (2.0, "declined", "code: x", "org/a-7b-ft", "code")]))
    assert _cuts() == [("family_size_ratio", None, 1)]


def _standing(lost=(), compared=0.0):
    from harness import family
    fam = family.Family("code", "fam", "org/fam", lost=list(lost), last_compared=compared)
    fam.demoted = len(lost) >= family.LOSSES_TO_DEMOTE
    return family.Standing(parents_of={"org/fam-ft": ["org/fam"]}, families={("code", "fam"): fam})


def test_demoted_members_moved_last_record_the_losses_threshold():
    from harness import family
    rows = [{"name": "org/fam-ft", "lane": "code"}, {"name": "org/other", "lane": "code"}]
    assert family.measure_order(rows, _standing(lost=["org/fam-x"])) == rows
    assert _cuts() == []
    st = _standing(lost=[f"org/fam-{i}" for i in range(family.LOSSES_TO_DEMOTE)])
    assert [r["name"] for r in family.measure_order(rows, st)] == ["org/other", "org/fam-ft"]
    assert _cuts() == [("family_losses_to_demote", None, 1)]


def test_a_full_set_of_diversity_slots_is_a_cut_only_when_another_family_waits():
    from harness import family
    st, now = _standing(), 100 * family.DAY
    rows = [{"name": "org/fam", "lane": "code"}, {"name": "org/fam-ft", "lane": "code"}]
    picks = family.reserve(rows, st, now=now, slots=1)[1]
    assert [p["name"] for p in picks] == ["org/fam"] and _cuts() == []
    family.reserve(rows + [{"name": "org/new", "lane": "code"}], st, now=now, slots=1)
    assert _cuts() == [("diversity_slots", 1, 1)]


def test_a_row_passed_over_for_a_recent_comparison_is_a_window_cut():
    from harness import family
    now = 100 * family.DAY
    rows = [{"name": "org/fam", "lane": "code"}, {"name": "org/new", "lane": "code"}]
    family.reserve(rows, _standing(compared=0.0), now=now, slots=2)
    assert _cuts() == []
    picks = family.reserve(rows, _standing(compared=now - family.DAY), now=now, slots=2)[1]
    assert [p["name"] for p in picks] == ["org/new"]
    assert _cuts() == [("diversity_family_window_days", None, 1)]


# ---- feeds and benchmarks -------------------------------------------------------------------------

def test_an_unreachable_feed_records_the_unreachable_retries_and_a_busy_one_the_retries(monkeypatch):
    from harness import feeds

    def refused(*a, **k):
        raise urllib.error.URLError(ConnectionRefusedError())
    monkeypatch.setattr(feeds.urllib.request, "urlopen", refused)
    with pytest.raises(feeds.FeedError):
        feeds.fetch("https://example.invalid/feed", sleep=lambda s: None)
    assert _knobs() == ["feed_unreachable_retries"]

    def busy(*a, **k):
        raise urllib.error.HTTPError("u", 503, "busy", {}, None)
    monkeypatch.setattr(feeds.urllib.request, "urlopen", busy)
    with pytest.raises(feeds.FeedError):
        feeds.fetch("https://example.invalid/feed", sleep=lambda s: None)
    got = _knobs()
    assert got.count("feed_unreachable_retries") == 1 and got[-1] == "harness/feeds.py:RETRIES"


def test_benchmark_reads_skipped_inside_the_interval_are_one_cut(conn):
    from harness import benchmarks
    lane = sorted(benchmarks.LANE_QUERIES)[0]
    now = time.time()
    benchmarks.sweep(conn, lanes=[lane], get=lambda url, params=None: [], now=now)
    assert _cuts() == []
    benchmarks.sweep(conn, lanes=[lane], get=lambda url, params=None: [], now=now + 60)
    assert _cuts() == [("harness/feeds.py:DEFAULT_INTERVAL_DAYS", None, 2)]


# ---- fetching -------------------------------------------------------------------------------------

def test_a_download_that_would_go_under_the_disk_floor_is_a_cut():
    from harness import fetching
    gib = fetching.GIB
    assert fetching.plan("org/x", gib, free=fetching.DISK_FLOOR + 2 * gib).ok
    assert _cuts() == []
    assert not fetching.plan("org/x", gib, free=fetching.DISK_FLOOR).ok
    assert _knobs() == ["disk_floor"]


def test_fetch_order_over_a_full_page_of_judgeable_rows_is_a_cut(monkeypatch):
    from harness import fetching, rank
    page = []
    monkeypatch.setattr(ms, "judgeable", lambda conn, limit: page)
    monkeypatch.setattr(rank, "rank", lambda rows, **k: rows[:1])
    monkeypatch.setattr(rank, "serving", lambda: {})
    monkeypatch.setattr(rank, "lanes_with_receipts", lambda conn: set())
    rows = [{"name": "b"}, {"name": "a"}]
    page[:] = [{"name": "a"}]
    assert fetching.in_rank_order(rows, conn=object()) == [{"name": "a"}, {"name": "b"}]
    assert _cuts() == []
    page[:] = [{"name": "a"}] * 1_000_000
    fetching.in_rank_order(rows, conn=object())
    assert _knobs() == ["harness/fetching.py:in_rank_order->_ms.judgeable(limit)"]


# ---- github, holdout, inspect ---------------------------------------------------------------------

def test_a_gh_call_that_times_out_is_a_cut(monkeypatch):
    from harness import github

    def slow(*a, **k):
        raise subprocess.TimeoutExpired(a[0], 60)
    monkeypatch.setattr(github.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stdout="{}"))
    assert github._gh("repos/a/b") == "{}"
    assert _cuts() == []
    monkeypatch.setattr(github.subprocess, "run", slow)
    with pytest.raises(subprocess.TimeoutExpired):
        github._gh("repos/a/b")
    assert _knobs() == ["harness/github.py:_gh->subprocess.run(timeout)"]


@pytest.mark.parametrize("n,knob", [(2, "harness/holdout.py:MIN_HOLDOUT"), (4, "harness/holdout.py:MIN_DEV")])
def test_a_lane_too_small_to_split_names_the_side_that_ran_short(monkeypatch, n, knob):
    from harness import holdout
    monkeypatch.setattr(holdout, "_draw", lambda c: int(c.id[1:]) / 100)
    big = holdout.assign("code", [SimpleNamespace(id=f"c{i}") for i in range(40)])
    assert not big.too_small and _cuts() == []
    assert holdout.assign("code", [SimpleNamespace(id=f"c{i}") for i in range(n)]).too_small
    assert _knobs() == [knob]


def test_a_task_split_short_of_dev_cases_names_min_dev(monkeypatch):
    from harness import holdout
    monkeypatch.setattr(holdout, "task_of", lambda c: "")
    monkeypatch.setattr(holdout, "_draw", lambda c: 0.0)
    cases = [SimpleNamespace(id=f"c{i}") for i in range(10)]
    got = holdout._assign_tasks("code", cases)
    assert got.too_small and _knobs() == ["harness/holdout.py:MIN_DEV"]


def _clone(tmp_path, files):
    def run(argv, cwd=None, timeout=180.0):
        d = tmp_path / "a__b"
        d.mkdir(exist_ok=True)
        for rel, data in files.items():
            (d / rel).write_bytes(data)
        return "2026-01-01T00:00:00+00:00"
    return run


def test_weights_in_git_past_the_clone_cap_are_a_cut(tmp_path):
    from harness import inspect as ins
    run = _clone(tmp_path, {"model.safetensors": b"\0" * 3000})
    ins.inspect("a/b", tmp_path, meta={"size": 10}, run=run, kb_cap=10, facts=lambda m, cache=None: {"size": 1})
    assert _cuts() == []
    assert ins.inspect("a/b", tmp_path, meta={"size": 10}, run=run, kb_cap=2).verdict == ins.WEIGHTS_IN_GIT
    assert _knobs() == ["clone_kb_cap"]


def test_named_weights_past_the_size_limit_are_one_cut(tmp_path, monkeypatch):
    from harness import inspect as ins
    ids = [f"org/model-{c}" for c in "abcd"]
    run = _clone(tmp_path, {"g.py": "\n".join(f'load("{i}")' for i in ids).encode()})
    sized = lambda m, cache=None: {"size": 1, "lane": ""}  # noqa: E731
    monkeypatch.setattr(ins, "SIZE_LIMIT", 2 * len(ids))
    ins.inspect("a/b", tmp_path, meta={"size": 10}, run=run, facts=sized)
    assert _cuts() == []
    monkeypatch.setattr(ins, "SIZE_LIMIT", 2)
    got = ins.inspect("a/b", tmp_path, meta={"size": 10}, run=run, facts=sized)
    assert len(got.unsized) == len(ids) - len(got.weights)
    assert _cuts() == [("size_limit", len(got.weights), len(got.unsized))]


def test_a_repo_idle_past_the_dead_days_is_a_cut():
    from harness import inspect as ins
    fresh = ins.Fit(repo="a/b", entry_points=["main.py"], last_commit=datetime.now().astimezone().isoformat())
    assert ins.decide(fresh).verdict == "fits" and _cuts() == []
    old = ins.Fit(repo="a/b", entry_points=["main.py"], last_commit="2019-01-01T00:00:00+00:00")
    assert ins.decide(old).verdict == "dead"
    assert _knobs() == ["dead_days"]
