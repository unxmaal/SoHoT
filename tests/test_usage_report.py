"""#481: what real use says per alias, across a switch, and on the report pages."""
import json

import pytest

from harness import cli, publish, report, usage
from harness import memory_store as ms

NOW = 1_800_000_000.0
DAY = 86400.0


def req(at, alias="sohot-code", served="openai/old", spec="old", ttft=None, err="",
        calls=0, valid=0, client="opencode/1.2", prompt=10, completion=5, total=1.0):
    return {"at": at, "alias": alias, "lane": usage.lane_of(alias), "served": served,
            "spec": spec, "client": client, "call_type": "acompletion",
            "stream": int(ttft is not None), "prompt_tokens": prompt,
            "completion_tokens": completion, "ttft_s": ttft, "total_s": total,
            "tool_calls": calls, "tool_calls_valid": valid,
            "finish_reason": "" if err else "stop", "error_class": err, "error_code": ""}


@pytest.fixture
def conn():
    c = ms.connect()
    yield c
    c.close()


def put(conn, rows):
    usage.insert(conn, [(r, None) for r in rows])


def switch(conn, lane="code", old="old", new="new", at=NOW - DAY):
    cur = conn.execute("INSERT INTO gateway_switches (lane, old_spec, new_spec, how, "
                       "requested_at, switched_at, in_flight) VALUES (?, ?, ?, 'idle', ?, ?, 0)",
                       (lane, old, new, at - 60, at))
    conn.commit()
    return cur.lastrowid


# ---- the window and the per-alias figures ------------------------------------


@pytest.mark.parametrize("text,seconds", [("7d", 7 * DAY), ("12h", 12 * 3600.0),
                                          ("30m", 1800.0), ("90s", 90.0), ("2", 2 * DAY)])
def test_since_reads_days_hours_minutes_and_seconds(text, seconds):
    assert usage.parse_since(text) == seconds


def test_since_refuses_what_it_cannot_read():
    with pytest.raises(ValueError):
        usage.parse_since("last week")


def test_summary_is_per_alias_and_served_model(conn):
    put(conn, [req(NOW - 10, ttft=t) for t in (0.1, 0.2, 0.3, 0.4, 1.0)]
        + [req(NOW - 10, err="Timeout"), req(NOW - 10, calls=4, valid=3)]
        + [req(NOW - 10, alias="q3-4b", served="openai/q3")])
    got = {(s["alias"], s["served"]): s for s in usage.summary(conn, since=DAY, now=NOW)}
    code = got[("sohot-code", "openai/old")]
    assert code["requests"] == 7 and code["errors"] == 1
    assert code["error_rate"] == pytest.approx(1 / 7)
    assert code["prompt_tokens"] == 70 and code["completion_tokens"] == 35
    assert code["ttft_p50"] == pytest.approx(0.3) and code["ttft_p95"] == pytest.approx(1.0)
    assert (code["tool_calls"], code["invalid_calls"]) == (4, 1)
    assert code["invalid_rate"] == pytest.approx(0.25)
    assert got[("q3-4b", "openai/q3")]["requests"] == 1


def test_summary_honours_the_window_and_the_lane(conn):
    put(conn, [req(NOW - 10), req(NOW - 3 * DAY), req(NOW - 10, alias="sohot-web")])
    assert sum(s["requests"] for s in usage.summary(conn, since=DAY, now=NOW)) == 2
    only = usage.summary(conn, lane="code", since=7 * DAY, now=NOW)
    assert [s["requests"] for s in only] == [2]


def test_a_rate_with_nothing_to_divide_is_none_not_zero(conn):
    put(conn, [req(NOW - 10)])
    s = usage.summary(conn, since=DAY, now=NOW)[0]
    assert s["invalid_rate"] is None and s["ttft_p50"] is None


# ---- across an alias switch --------------------------------------------------


def test_each_switch_compares_the_requests_before_it_with_those_after(conn):
    at = NOW - DAY
    sid = switch(conn, at=at)
    put(conn, [req(at - 100) for _ in range(3)]
        + [req(at + 100, served="openai/new", spec="new") for _ in range(5)]
        + [req(at + 100, alias="sohot-web")])
    [c] = usage.around_switches(conn, since=7 * DAY, now=NOW)
    assert c["switch"]["id"] == sid
    assert (c["before"]["requests"], c["after"]["requests"]) == (3, 5)


def test_the_after_side_stops_at_the_next_switch(conn):
    first = switch(conn, at=NOW - 2 * DAY)
    switch(conn, old="new", new="newer", at=NOW - DAY)
    put(conn, [req(NOW - 1.5 * DAY) for _ in range(4)] + [req(NOW - 10) for _ in range(2)])
    got = {c["switch"]["id"]: c for c in usage.around_switches(conn, since=7 * DAY, now=NOW)}
    assert got[first]["after"]["requests"] == 4


def _regressed(conn, before_err, after_err, n_before=100, n_after=100, calls=False):
    at = NOW - DAY
    switch(conn, at=at)
    rows = []
    for i in range(n_before):
        bad = i < before_err
        rows.append(req(at - 100 - i, calls=1, valid=0 if bad else 1) if calls
                    else req(at - 100 - i, err="APIError" if bad else ""))
    for i in range(n_after):
        bad = i < after_err
        rows.append(req(at + 100 + i, spec="new", calls=1, valid=0 if bad else 1) if calls
                    else req(at + 100 + i, spec="new", err="APIError" if bad else ""))
    put(conn, rows)
    return usage.regressions(usage.around_switches(conn, since=7 * DAY, now=NOW))


def test_an_error_rate_up_beyond_noise_after_a_switch_is_a_warning_naming_it(conn):
    [w] = _regressed(conn, 2, 20)
    assert "sohot-code" in w and "old -> new" in w and "error rate" in w


def test_an_invalid_tool_call_rate_up_beyond_noise_is_a_warning(conn):
    [w] = _regressed(conn, 5, 40, calls=True)
    assert "invalid tool-call rate" in w and "old -> new" in w


def test_no_warning_below_the_minimum_request_count(conn):
    assert _regressed(conn, 0, 5, n_before=5, n_after=5) == []


def test_no_warning_when_the_rates_differ_by_noise(conn):
    assert _regressed(conn, 3, 5) == []


def test_no_warning_when_the_rate_went_down(conn):
    assert _regressed(conn, 20, 2) == []


# ---- soh usage ---------------------------------------------------------------


def test_soh_usage_prints_the_figures_and_the_warning(conn, capsys, monkeypatch):
    monkeypatch.setattr(usage.time, "time", lambda: NOW)
    _regressed(conn, 2, 20)
    assert cli.main(["usage", "--lane", "code", "--since", "7d"]) == 0
    out = capsys.readouterr().out
    assert "sohot-code" in out and "WARNING" in out and "old -> new" in out


def test_soh_usage_json_carries_summary_switches_and_warnings(conn, capsys, monkeypatch):
    monkeypatch.setattr(usage.time, "time", lambda: NOW)
    _regressed(conn, 2, 20)
    assert cli.main(["usage", "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["summary"] and doc["switches"] and doc["warnings"]


def test_soh_usage_text_turns_samples_on_and_off(conn, capsys):
    assert cli.main(["usage", "--text", "on"]) == 0
    assert usage.text_enabled(conn)
    assert cli.main(["usage", "--text", "off"]) == 0
    assert not usage.text_enabled(conn)


def test_soh_usage_with_nothing_recorded_says_so(capsys):
    assert cli.main(["usage"]) == 0
    assert "no requests" in capsys.readouterr().out


# ---- the report pages ---------------------------------------------------------


def test_real_use_per_lane_counts_only_lane_aliases(conn):
    put(conn, [req(NOW - 10, ttft=0.2), req(NOW - 10, err="Timeout"),
               req(NOW - 10, alias="q3-4b")])
    got = usage.real_use(conn, now=NOW)
    assert set(got) == {"code"} and got["code"]["requests"] == 2
    assert "client" not in json.dumps(got)


def test_the_local_report_has_a_real_use_section(conn, monkeypatch):
    monkeypatch.setattr(usage.time, "time", lambda: NOW)
    put(conn, [req(NOW - 10, ttft=0.25)])
    state = report.state(conn)
    assert state["real_use"]["code"]["requests"] == 1
    page = report.render(state, {})
    assert "Real use" in page and "sohot-code" in page


def test_the_local_report_says_when_nothing_was_recorded():
    page = report.render({**report.state(), "real_use": {}, "usage_warnings": []}, {})
    assert "No requests through the gateway" in page


def test_the_published_export_and_page_carry_real_use_without_clients(conn, monkeypatch):
    monkeypatch.setattr(usage.time, "time", lambda: NOW)
    put(conn, [req(NOW - 10, ttft=0.3, client="laptop-of-someone")])
    doc = publish.export(conn, now=NOW)
    code = {l["lane"]: l for l in doc["lanes"]}["code"]
    assert code["real_use"]["requests"] == 1
    assert "laptop-of-someone" not in json.dumps(doc)
    assert "Real use" in publish.render_site([doc], now=NOW)
