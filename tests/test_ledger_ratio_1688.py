"""soh ledger and soh morning lead with local over cloud tokens against the 3:1 target. #1688."""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone

from harness import cli, ledger, morning
from harness import memory_store as ms
from harness.commands import morning as morning_cmd
from tests.test_morning_867 import _beat, _gh, _git

UTC = timezone.utc
FIX = ledger.paths.REPO / "tests" / "fixtures" / "ledger"
CLOUD = {"input": 1000, "output": 2000, "cache_read": 4000, "cache_write": 3000}
COUNTED = [("work", "", 100, 50), ("internal", "extract", 400, 100), ("unknown", "decide", 200, 50)]
NOT_COUNTED = [("eval", "code", 10_000, 5_000), ("smoke", "code", 1000, 1000), ("watchdog", "decide", 30, 2),
               ("discover", "code", 7, 7), ("unknown", "", 999, 999), (None, "", 5, 5)]


def at(day: str, hour: int = 12) -> float:
    return datetime.fromisoformat(f"{day}T{hour:02d}:00:00+00:00").timestamp()


def local(day: str, hour: int = 12) -> float:
    return datetime.fromisoformat(f"{day}T{hour:02d}:00:00").timestamp()


def test_the_rule_counts_delegations_internal_and_interactive_lanes_and_cloud_less_cache_reads():
    assert ledger.local_vs_cloud(COUNTED + NOT_COUNTED, CLOUD) == {"local": 900, "cloud": 6000}
    assert ledger.local_vs_cloud(COUNTED, None) == {"local": 900, "cloud": None}


def test_an_eval_row_or_a_cache_read_leaves_the_ratio_unchanged():
    base = ledger.local_vs_cloud(COUNTED, CLOUD)
    more = ledger.local_vs_cloud(COUNTED + [("eval", "decide", 50_000, 9_000)], {**CLOUD, "cache_read": 9_999_999})
    assert more == base


def _gw(day: str, purpose: str, lane: str, pin_: int, pout: int, alias: str = "") -> tuple:
    return (at(day), alias or (f"sohot-{lane}" if lane else "eval-7b"), lane, "python-httpx", purpose, pin_, pout, "")


def _otel(day: str) -> dict:
    return {"name": "api_request", "at": at(day), "session_id": "s1", "model": "claude-opus-5-5",
            "duration_ms": 1000, "input_tokens": 100,
            "output_tokens": 200, "cache_read_tokens": 1_000_000, "cache_creation_tokens": 300}


def _built(extra_rows=(), extra_events=(), **kw):
    doc = {"available": True, "source": "ccusage@x",
           **ledger.parse_ccusage(json.loads((FIX / "ccusage-daily.json").read_text(encoding="utf-8")))}
    rows = [_gw("2026-10-08", "work", "", 1000, 200), _gw("2026-10-08", "eval", "code", 90_000, 9_000),
            _gw("2026-10-09", "internal", "extract", 60, 30),
            _gw("2026-10-10", "unknown", "code", 1500, 300), _gw("2026-10-10", "watchdog", "code", 40, 1),
            *extra_rows]
    return ledger.build(since=at("2026-10-08", 0), now=at("2026-10-11"), cloud_doc=doc, rows=rows, limits=[],
                        power=[], tz=UTC, events=[_otel("2026-10-10"), *extra_events], **kw)


def test_the_ledger_counts_each_day_on_fixture_otel_ccusage_and_gateway_rows():
    L = _built()
    assert {d["day"]: d["ratio"] for d in L["days"]} == {
        "2026-10-08": {"local": 1200, "cloud": 6000}, "2026-10-09": {"local": 90, "cloud": 30},
        "2026-10-10": {"local": 1800, "cloud": 600}, "2026-10-11": {"local": 0, "cloud": None}}
    y, w = L["ratio"]["yesterday"], L["ratio"]["week"]
    assert (y["last_day"], y["ratio"], y["target"]) == ("2026-10-10", 3.0, 3.0)
    assert (w["first_day"], w["days"], w["local"], w["cloud"]) == ("2026-10-04", 3, 3090, 6630)
    assert ledger.ratio_line(L["ratio"]) == ("local:cloud 2026-10-10 3.0:1 (1,800 local / 600 cloud); "
                                             "7d 1:2 (3,090 local / 6,630 cloud, 3 of 7 days); target 3.0:1")


def test_eval_rows_and_cache_reads_leave_the_built_ratio_unchanged():
    more = _built(extra_rows=[_gw("2026-10-10", "eval", "code", 70_000, 7_000),
                              _gw("2026-10-09", "smoke", "decide", 500, 5)],
                  extra_events=[{**_otel("2026-10-10"), "input_tokens": 0, "output_tokens": 0,
                                 "cache_creation_tokens": 0, "cache_read_tokens": 8_000_000}])
    assert more["ratio"] == _built()["ratio"]


def test_days_before_the_window_come_from_ledger_days_and_a_live_day_wins():
    L = _built(recorded_ratio={"2026-10-05": {"local": 10, "cloud": 370}, "2026-10-10": {"local": 1, "cloud": 1}})
    assert (L["ratio"]["week"]["days"], L["ratio"]["week"]["local"], L["ratio"]["week"]["cloud"]) == (4, 3100, 7000)
    assert L["ratio"]["yesterday"]["local"] == 1800


def _ccusage(monkeypatch):
    doc = json.loads((FIX / "ccusage-daily.json").read_text(encoding="utf-8"))
    real = ledger.cloud

    def fake(first_day, **kw):
        return real(first_day, runner=lambda argv, **k: subprocess.CompletedProcess(argv, 0, json.dumps(doc), ""),
                    which=lambda n: "/x/npx")
    monkeypatch.setattr(ledger, "cloud", fake)


def _rows(*rows):
    conn = ms.connect()
    conn.executemany("INSERT INTO gateway_requests (at, alias, lane, client, purpose, prompt_tokens, "
                     "completion_tokens) VALUES (?, ?, ?, 'python-httpx', ?, ?, ?)", rows)
    conn.commit()
    conn.close()


def test_the_ledger_text_leads_with_the_ratio(monkeypatch, capsys):
    _ccusage(monkeypatch)
    _rows((local("2026-10-08"), "sohot-decide", "decide", "unknown", 12000, 6000))
    assert cli.main(["ledger", "--since", "2026-10-08"]) == 0
    first = capsys.readouterr().out.splitlines()[0]
    assert first.startswith("local:cloud ") and first.endswith("; target 3.0:1"), first


def test_morning_leads_with_the_ratio_and_the_target_from_recorded_days(monkeypatch, capsys, tmp_path):
    _ccusage(monkeypatch)
    _rows((local("2026-10-08"), "sohot-decide", "decide", "unknown", 12000, 6000),
          (local("2026-10-08"), "sohot-code", "code", "eval", 900_000, 90_000))
    assert cli.main(["ledger", "--since", "2026-10-08", "--record"]) == 0
    capsys.readouterr()
    now = local("2026-10-09", 6)
    d = tmp_path / "deploy"
    (d / ".git").mkdir(parents=True)
    conn = ms.connect()
    try:
        r = morning.gather(conn, now, now - 18 * 3600, beat=_beat(), gh=_gh(), git=_git(0), where=d,
                           lanes=lambda c: [])
    finally:
        conn.close()
    assert r["ratio"]["yesterday"] == {**r["ratio"]["yesterday"], "local": 18000, "cloud": 6000, "ratio": 3.0}
    assert morning_cmd.render(r)[0] == ("local:cloud 2026-10-08 3.0:1 (18,000 local / 6,000 cloud); "
                                        "7d 3.0:1 (18,000 local / 6,000 cloud, 1 of 7 days); target 3.0:1")


def test_morning_without_a_counted_day_says_so():
    conn = ms.connect()
    try:
        r = morning.ratio(conn, local("2026-10-09", 6))
    finally:
        conn.close()
    assert ledger.ratio_line(r) == ("local:cloud 2026-10-08 n/a (no cloud count); 7d n/a (no cloud count); "
                                    "target 3.0:1")
