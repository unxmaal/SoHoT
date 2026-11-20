"""The status page at a glance: each fixture state's tile colors and headlines, detail only behind <details>. #2078."""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

import pytest

from harness import deploy_state as ds
from harness import memory_store as ms
from harness import queue_hold, queue_pause, store_service
from harness import status_page as sp
from harness import status_view as sv
from harness import workqueue as wq

NOW = time.time()
NO_FEATURES = lambda conn, now, q: {"rows": []}  # noqa: E731
BEAT = {"status": "finished", "started": NOW - 3600, "finished": NOW - 600, "rc": 0,
        "line": "last discovery loop finished 10m ago, rc 0"}
CRASH = "RuntimeError: the sweep died in the middle of a lane"
FLOW = {"available": True, "counted": 1000, "days": 7, "expiry": {"cache_write": 0, "events": 0, "share": 0.5},
        "terms": [{"term": "subagent cache write, rewrite after expiry", "tokens": 600, "share": 0.6},
                  {"term": "main input", "tokens": 150, "share": 0.15}]}


def _mon(rows=("gateway   OK   Process", "system_data   OK   Filesystem"), running=True):
    return lambda: {"installed": True, "running": running, "current": True, "webhook": True, "problems": [],
                    "summary": ["Service Name   Status   Type", *rows]}


def _deploys(*rows):
    conn = ms.connect()
    try:
        mid = ms.remember_machine(conn)
        for i, (outcome, detail) in enumerate(rows):
            conn.execute("INSERT INTO deploys (sha, machine_id, stage, outcome, started_at, detail) VALUES (?,?,?,?,?,?)",
                         (f"{i + 1}" * 40, mid, outcome, outcome, NOW - 300 + i, detail))
        conn.commit()
    finally:
        conn.close()


def _gather(tmp_path, backup_at=None, **kw):
    d = store_service.backup_dir()
    d.mkdir(parents=True, exist_ok=True)
    b = d / f"{store_service.BACKUP_PREFIX}2026-11-19{store_service.BACKUP_SUFFIX}"
    b.write_text("x", encoding="utf-8")
    os.utime(b, (backup_at or NOW, backup_at or NOW))
    args = {"connect": ms.connect, "beat": BEAT, "where": tmp_path, "mon": _mon(), "features": NO_FEATURES,
            "health": lambda lane: {"lane": lane, "spec": "m", "base": "http://127.0.0.1:1", "generating": True, "why": ""},
            "reach": lambda since, now: [{"node": "n1", "down_now": False, "down_s": 0.0}], "flow": lambda now: FLOW}
    args.update(kw)
    return sp.gather(NOW, **args)


def _tiles(r) -> dict:
    return {t["key"]: (t["state"], t["headline"]) for t in sv.tiles(r, NOW)}


def _outside(page: str) -> str:
    return re.sub(r"<details[^>]*><summary>(.*?)</summary>.*?</details>", r"\1", page, flags=re.S)


def _drawn(page: str) -> dict:
    return dict((k, s) for s, k in re.findall(r"<details class='tile (\w+)' data-tile='(\w+)'>", page))


def test_all_clear_is_six_green_tiles_and_one_line(tmp_path):
    _deploys(("deployed", "serving"))
    r = _gather(tmp_path)
    got = _tiles(r)
    assert {k: s for k, (s, _) in got.items()} == dict.fromkeys(("deploy", "queue", "discovery", "monitor", "services",
                                                                 "store"), sv.OK)
    assert got["deploy"][1] == "release 1 · 5 min ago"
    assert got["queue"][1] == "idle · last job never"
    assert got["discovery"][1].startswith("ran 10 min ago · next ")
    assert got["monitor"][1] == "2/2 checks OK"
    assert got["services"][1] == "1 node up · lane generating"
    assert re.fullmatch(r"schema \d+ · backup just now", got["store"][1])
    page = sp.page(r, NOW)
    assert "All clear." in page and "class='alert'" not in page
    assert _drawn(page) == {k: s for k, (s, _) in got.items()}


def test_a_backup_stamped_after_the_gather_time_is_just_now_not_in_the_future(tmp_path):
    r = _gather(tmp_path, backup_at=NOW + 1200)
    assert re.fullmatch(r"schema \d+ · backup just now", _tiles(r)["store"][1])
    assert "backup in " not in sp.page(r, NOW)
    assert sv.ago(NOW + 1200, NOW) == "just now" and sp._ago(NOW + 1200, NOW).endswith("(0 min ago)")


def test_a_long_queue_pause_is_a_red_queue_tile(tmp_path):
    from harness import queue_stale
    body = queue_hold.text("owner testing a model", None)
    old = time.strftime(queue_hold._STAMP, time.localtime(NOW - queue_stale.QUEUE_STALE_S - 3600))
    queue_pause._pause_flag().parent.mkdir(parents=True, exist_ok=True)
    queue_pause._pause_flag().write_text(old + body[len(old):], encoding="utf-8")
    r = _gather(tmp_path)
    assert _tiles(r)["queue"] == (sv.BAD, "paused 13 h")
    page = sp.page(r, NOW)
    assert _drawn(page)["queue"] == sv.BAD
    assert "owner testing a model" not in _outside(page) and "owner testing a model" in page
    assert ("pause", sv.WARN) in {(e["kind"], e["state"]) for e in r["timeline"]["events"]}


def test_a_recent_pause_is_amber(tmp_path):
    queue_pause.pause("a deploy runs")
    assert _tiles(_gather(tmp_path))["queue"] == (sv.WARN, "paused 1 min")


def test_a_failing_deploy_is_red_and_its_detail_and_path_stay_folded(tmp_path):
    where = f"{Path.home()}/localharness/releases/3-abcdef0123456789"
    _deploys(("deployed", "ok"), (ds.ROLLED_BACK, f"smoke before the switch failed in {where}"),
             (ds.ROLLED_BACK, f"smoke before the switch failed in {where}"))
    r = _gather(tmp_path)
    assert _tiles(r)["deploy"] == (sv.BAD, "2 failed · last 5 min ago")
    page = sp.page(r, NOW)
    assert _drawn(page)["deploy"] == sv.BAD
    out = _outside(page)
    assert "smoke before the switch" not in out and str(Path.home()) not in out
    assert "smoke before the switch" in page and str(Path.home()) not in page
    assert "<summary><b class='badge bad' role='img' aria-label='failing'>✕</b> Deploy failing</summary>" in page
    assert "3" * 9 not in page and "3" * 8 in page


def test_a_crashed_discovery_is_red_and_its_error_stays_folded(tmp_path):
    r = _gather(tmp_path, beat={**BEAT, "rc": 1, "error": CRASH})
    state, head = _tiles(r)["discovery"]
    assert state == sv.BAD and re.fullmatch(r"failed 10 min ago · next \d\d:\d\d", head)
    page = sp.page(r, NOW)
    assert _drawn(page)["discovery"] == sv.BAD
    assert CRASH not in _outside(page) and CRASH in page
    assert any(e["kind"] == "discovery" and e["state"] == sv.BAD for e in r["timeline"]["events"])


def test_with_the_store_down_its_tiles_say_so_and_the_error_stays_folded(tmp_path):
    def down():
        raise OSError("connection refused at the store socket")
    r = _gather(tmp_path, connect=down)
    got = _tiles(r)
    assert got["store"] == (sv.BAD, "store down")
    assert got["queue"] == (sv.UNKNOWN, "jobs not read")
    assert got["deploy"] == (sv.UNKNOWN, "history not read")
    assert got["discovery"][0] == sv.OK and got["monitor"][0] == sv.OK
    page = sp.page(r, NOW)
    assert "connection refused" not in _outside(page) and "connection refused" in page
    assert "Store down" in _outside(page)


@pytest.mark.parametrize("beat", [BEAT, {**BEAT, "rc": 1, "error": CRASH}, {**BEAT, "status": "stalled"}, {}])
def test_every_headline_is_at_most_six_words(tmp_path, beat):
    _deploys(("deployed", "ok"), (ds.ROLLED_BACK, "x"))
    for t in sv.tiles(_gather(tmp_path, beat=beat or None), NOW):
        assert len([w for w in t["headline"].split() if w != "·"]) <= 6, t


def test_status_json_carries_the_ratio_days_causes_and_timeline(tmp_path):
    conn = ms.connect()
    try:
        from harness import ledger
        day = ledger.day_of(NOW - 86400)
        conn.execute("INSERT INTO ledger_days (day, recorded_at, detail) VALUES (?,?,?)",
                     (day, NOW, json.dumps({"ratio": {"local": 2000, "cloud": 90000}})))
        job = wq.add(["true"], title="t", kind="command", conn=conn)
        conn.execute("UPDATE jobs SET state = ?, finished_at = ?, machine_id = ? WHERE id = ?",
                     (wq.FAILED, NOW - 60, ms.remember_machine(conn), int(job["id"])))
        conn.commit()
    finally:
        conn.close()
    _deploys(("deployed", "ok"))
    r = json.loads(sp.as_json(_gather(tmp_path)))
    ra = r["ratio"]
    assert len(ra["days"]) == 7 and ra["days"][-1] == {"day": day, "local": 2000, "cloud": 90000}
    assert ra["days"][0]["cloud"] is None
    assert ra["counted"] == 1000 and ra["causes"][-1] == {"term": "other", "tokens": 250}
    kinds = {(e["kind"], e["state"]) for e in r["timeline"]["events"]}
    assert {("deploy", sv.OK), ("job", sv.BAD), ("discovery", sv.OK)} <= kinds
    page = sp.page(sp.gather(NOW, connect=ms.connect, beat=BEAT, where=tmp_path, mon=_mon(), features=NO_FEATURES,
                             health=lambda lane: {"lane": lane}, reach=lambda s, n: [], flow=lambda n: FLOW), NOW)
    assert "1:45" in page and "largest: <b>subagent cache write, rewrite after expiry</b> 60%" in page
    assert page.count("class='chk'") == 2 and page.count("class='ev ") >= 3


def test_formatting_rules():
    assert sv.short(f"{Path.home()}/x and " + "a" * 40) == "~/x and " + "a" * 8
    assert [sv.tok(n) for n in (950, 84423, 1696127, 99076748)] == ["950", "84k", "1.7M", "99M"]
    assert sv.ago(NOW - 720, NOW) == "12 min ago" and sv.ago(NOW - 4 * 3600, NOW) == "4 h ago"
    assert sv.ratio_text(1 / 45) == "1:45" and sv.ratio_text(3.0) == "3:1" and sv.ratio_text(2.5) == "2.5:1"
    assert "<time title='" in sv._when(NOW - 720, NOW)


def test_the_timeline_shows_only_jobs_this_machine_ran(tmp_path):
    conn = ms.connect()
    try:
        mid = ms.remember_machine(conn)
        conn.execute("INSERT INTO machines (id, fingerprint, first_seen, last_seen) VALUES (999, 'Other1,1/os/arm64/x', 0, 0)")
        for title, machine in (("mine", mid), ("theirs", 999), ("nobody's", None)):
            job = wq.add(["true"], title=title, kind=title, conn=conn)
            conn.execute("UPDATE jobs SET state = ?, finished_at = ?, machine_id = ? WHERE id = ?",
                         (wq.DONE, NOW - 60, machine, int(job["id"])))
        conn.commit()
    finally:
        conn.close()
    jobs = [e["label"].split()[2] for e in _gather(tmp_path)["timeline"]["events"] if e["kind"] == "job"]
    assert jobs == ["mine"]
