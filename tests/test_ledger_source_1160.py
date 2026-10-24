"""soh ledger counts cloud tokens from OTel where it exported, transcripts or ccusage as a lower bound (#1160)."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from harness import cli, ledger, otel
from harness import memory_store as ms
from harness.commands import ledger as ledger_cmd

UTC = timezone.utc
DAY = "2026-10-14"


def at(hour: int, minute: int = 0) -> float:
    return datetime(2026, 10, 14, hour, minute, tzinfo=UTC).timestamp()


def iso(t: float) -> str:
    return datetime.fromtimestamp(t, UTC).isoformat().replace("+00:00", "Z")


def rec(t: float, mid: str, out: int, stop=None, session="s1", req="r", cache_read=0, model="claude-opus-5-5"):
    return {"type": "assistant", "timestamp": iso(t), "sessionId": session, "requestId": f"{req}-{mid}",
            "uuid": f"u-{mid}-{out}-{stop}",
            "message": {"id": mid, "model": model, "stop_reason": stop,
                        "usage": {"input_tokens": 1, "output_tokens": out, "cache_read_input_tokens": cache_read,
                                  "cache_creation_input_tokens": 0}}}


def write(path, recs):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in recs), encoding="utf-8")
    return path


def api(t: float, out: int, session="s1", ms_=30000.0, inp=10, cache_read=0, rid="x"):
    return {"key": f"api_request:{rid}", "received_at": t, "at": t, "session_id": session, "prompt_id": "",
            "name": "api_request", "tool": "", "model": "claude-opus-5-5", "query_source": "", "success": 1,
            "duration_ms": ms_, "input_tokens": inp, "output_tokens": out, "cache_read_tokens": cache_read,
            "cache_creation_tokens": 0, "cache_creation_5m_tokens": 0, "cache_creation_1h_tokens": 0,
            "cost_usd": None, "result_bytes": None, "attrs": "{}"}


# --- the transcript tally -------------------------------------------------------------------------

def test_a_streaming_partial_and_its_final_record_count_the_final_one_only(tmp_path):
    f = write(tmp_path / "s1.jsonl", [rec(at(10), "m1", 12), rec(at(10), "m1", 640, stop="end_turn"),
                                      rec(at(10), "m1", 3)])
    got = ledger.usage_messages([f], at(0))
    assert [(m["output"], m["final"]) for m in got] == [(640, True)]


def test_the_final_record_wins_even_when_a_partial_reads_higher(tmp_path):
    f = write(tmp_path / "s1.jsonl", [rec(at(10), "m1", 900), rec(at(10), "m1", 640, stop="tool_use"),
                                      rec(at(10), "m1", 950)])
    assert [m["output"] for m in ledger.usage_messages([f], at(0))] == [640]


def test_a_message_with_no_final_record_keeps_its_largest_partial(tmp_path):
    f = write(tmp_path / "s1.jsonl", [rec(at(10), "m1", 8), rec(at(10), "m1", 40)])
    assert [(m["output"], m["final"]) for m in ledger.usage_messages([f], at(0))] == [(40, False)]


def test_a_forked_subagent_copy_of_the_spawning_message_counts_once(tmp_path):
    main = write(tmp_path / "p" / "s1.jsonl", [rec(at(10), "m1", 500, stop="tool_use")])
    sub = write(tmp_path / "p" / "s1" / "subagents" / "agent-a.jsonl",
                [rec(at(10), "m1", 500, stop="tool_use"), rec(at(10, 5), "m2", 70, stop="end_turn")])
    assert sorted(m["output"] for m in ledger.usage_messages([main, sub], at(0))) == [70, 500]


def test_records_outside_the_window_are_not_counted(tmp_path):
    f = write(tmp_path / "s1.jsonl", [rec(at(1), "m0", 5, stop="end_turn"), rec(at(10), "m1", 7, stop="end_turn")])
    assert [m["output"] for m in ledger.usage_messages([f], at(5), at(11))] == [7]


# --- which source counts a day --------------------------------------------------------------------

def messages():
    # s1 exported from 09:59:30 to 11:00; m-early ran before the export was on, m-in during it.
    return [{"at": at(8), "session": "s1", "model": "claude-opus-5-5", "final": True, "input": 1, "output": 300,
             "cache_read": 0, "cache_write": 0},
            {"at": at(10), "session": "s1", "model": "claude-opus-5-5", "final": False, "input": 1, "output": 20,
             "cache_read": 0, "cache_write": 0}]


def test_an_exported_day_counts_otel_and_only_what_the_export_did_not_see_from_transcripts():
    ev = [api(at(10), 400, rid="a"), api(at(11), 600, rid="b")]
    d = ledger.cloud_days([DAY], {"available": False}, ev, messages(), tz=UTC)[DAY]
    assert d["otel"]["output"] == 1000 and d["outside"]["output"] == 300
    assert d["tokens"]["output"] == 1300 and d["source"] == "otel+transcripts" and d["lower_bound"]
    assert d["transcripts"]["output"] == 320 and d["outside_messages"] == 1


def test_a_day_the_export_saw_whole_is_otel_and_not_a_lower_bound():
    ev = [api(at(8), 350, rid="a"), api(at(10), 400, rid="b")]
    d = ledger.cloud_days([DAY], {"available": False}, ev, messages(), tz=UTC)[DAY]
    assert (d["tokens"]["output"], d["source"], d["lower_bound"]) == (750, "otel", False)


def test_a_request_starting_before_its_event_is_inside_the_span():
    msg = [{**messages()[1], "at": at(9, 50)}]
    ev = [api(at(10), 400, ms_=11 * 60 * 1000, rid="a")]
    assert ledger.cloud_days([DAY], {"available": False}, ev, msg, tz=UTC)[DAY]["source"] == "otel"
    ev = [api(at(10), 400, ms_=0, rid="a")]
    assert ledger.cloud_days([DAY], {"available": False}, ev, msg, tz=UTC)[DAY]["source"] == "otel+transcripts"


def test_another_sessions_transcripts_are_not_covered_by_this_ones_export():
    msg = [{**messages()[1], "session": "s2"}]
    d = ledger.cloud_days([DAY], {"available": False}, [api(at(10), 400, rid="a")], msg, tz=UTC)[DAY]
    assert d["tokens"]["output"] == 420 and d["lower_bound"]


def test_a_day_without_export_is_ccusage_then_transcripts_and_a_lower_bound():
    cc = {"available": True, "days": {DAY: {"tokens": {"input": 1, "output": 9, "cache_read": 0, "cache_write": 0},
                                            "models": {}}}}
    d = ledger.cloud_days([DAY], cc, [], messages(), tz=UTC)[DAY]
    assert (d["tokens"]["output"], d["source"], d["lower_bound"]) == (9, "ccusage", True)
    d = ledger.cloud_days([DAY], {"available": False}, [], messages(), tz=UTC)[DAY]
    assert (d["tokens"]["output"], d["source"], d["lower_bound"]) == (320, "transcripts", True)
    d = ledger.cloud_days([DAY], {"available": False}, [], [], tz=UTC)[DAY]
    assert (d["tokens"], d["source"]) == (None, None)


def test_the_window_names_its_sources_and_keeps_ccusage_as_the_cross_check():
    cc = {"available": True, "source": "ccusage@x", "days": {"2026-10-13": {
        "tokens": {"input": 1, "output": 9, "cache_read": 0, "cache_write": 0}, "models": {}}}}
    L = ledger.build(since=at(0) - 86400, now=at(23), cloud_doc=cc, rows=[], limits=[], power=[], tz=UTC,
                     events=[api(at(8), 350, rid="a"), api(at(10), 400, rid="b")], messages=messages())
    c = L["cloud"]
    assert c["tokens"]["output"] == 9 + 750 and c["sources"] == {"ccusage": 1, "otel": 1}
    assert c["lower_bound"] and c["ccusage"]["tokens"]["output"] == 9
    assert [d["cloud"]["source"] for d in L["days"]] == ["ccusage", "otel"]
    assert L["days"][1]["cloud"]["models"]["claude-opus-5-5"]["output"] == 750


def test_the_gap_is_otel_output_over_the_transcripts_for_the_same_requests():
    g = ledger.gap([api(at(10), 400, rid="a"), api(at(11), 600, rid="b")], messages())
    assert (g["otel_output"], g["transcript_output"], g["ratio"], g["transcript_messages"]) == (1000, 20, 50.0, 1)


# --- the command ----------------------------------------------------------------------------------

def test_compare_shows_the_ledger_column_and_the_gap(monkeypatch, tmp_path, capsys):
    conn = ms.connect()
    try:
        otel.store(conn, events=[api(at(10), 400, rid="a"), api(at(11), 600, rid="b")])
    finally:
        conn.close()
    write(tmp_path / "projects" / "p" / "s1.jsonl",
          [rec(at(10), "m1", 20), rec(at(10, 30), "m2", 60, stop="end_turn")])
    monkeypatch.setenv("SOH_CLAUDE_PROJECTS", str(tmp_path / "projects"))
    monkeypatch.setattr(ledger, "cloud", lambda day, **kw: {"available": False, "why": "no npx"})
    real = ledger_cmd.gather_compare
    monkeypatch.setattr(ledger_cmd, "gather_compare", lambda day: real(day, tz=UTC))
    assert cli.main(["ledger", "--compare", DAY]) == 0
    out = capsys.readouterr().out
    assert cli.main(["ledger", "--compare", DAY, "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    rows = {r["row"]: r for r in doc["rows"]}
    assert (rows["output"]["otel_events"], rows["output"]["transcripts"], rows["output"]["ledger"]) == (1000, 80, 1000)
    assert rows["requests"]["transcripts"] == 2 and doc["source"]["source"] == "otel"
    assert doc["gap"]["ratio"] == 12.5 and "12.50x" in out and "$" not in out


def test_the_text_report_names_each_days_source_and_the_lower_bound(monkeypatch, capsys):
    cc = {"available": True, "source": "ccusage@x", "days": {"2026-10-13": {
        "tokens": {"input": 1, "output": 9, "cache_read": 0, "cache_write": 0}, "models": {}}}}
    L = ledger.build(since=at(0) - 86400, now=at(23), cloud_doc=cc, rows=[], limits=[], power=[], tz=UTC,
                     events=[api(at(8), 350, rid="a"), api(at(10), 400, rid="b")], messages=messages())
    L["recorded"], L["otel"] = [], {}
    ledger_cmd.show(L)
    got = capsys.readouterr()
    err = got.out + got.err
    assert "(ccusage@x 1 day, otel 1 day)" in err and "lower bound:" in err
    assert "2026-10-13 >=ccusage" in err and "2026-10-14 otel " in err


def test_the_morning_line_says_where_the_cloud_figure_came_from():
    from harness.commands.morning import ledger_line
    led = {"day": DAY, "energy_kwh": None, "plan": {}, "displaced": {}, "recorded_at": None,
           "cloud": {"input": 1, "output": 2, "cache_read": 0, "cache_write": 0}}
    assert "cache write; plan" in ledger_line(led)
    assert "cache write (at least, ccusage); plan" in ledger_line({**led, "cloud_source": "ccusage",
                                                                    "cloud_lower_bound": True})
    assert "cache write (otel); plan" in ledger_line({**led, "cloud_source": "otel"})
