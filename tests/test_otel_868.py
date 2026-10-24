"""Claude Code's OTLP export as a ledger and context source: receive, store once, compare one day (#868)."""
from __future__ import annotations

import gzip
import json
import shutil
import subprocess
import threading
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import pytest

from harness import cli, context_report as cr, ledger, otel
from harness import memory_store as ms
from harness.commands import ledger as ledger_cmd

FIX = Path(__file__).parent / "fixtures" / "otel"
UTC = timezone.utc
DAY = "2026-10-14"
NOW = datetime(2026, 10, 16, tzinfo=UTC).timestamp()


def load(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def stored():
    conn = ms.connect()
    try:
        return otel.events(conn, 0, NOW), otel.metrics(conn, 0, NOW)
    finally:
        conn.close()


def put(metrics=(), events=()):
    conn = ms.connect()
    try:
        return otel.store(conn, metrics=metrics, events=events)
    finally:
        conn.close()


def fixture_rows():
    return otel.parse_metrics(load("metrics.json"), 1.0), otel.parse_logs(load("logs.json"), 1.0)


# --- parsing and storing ---------------------------------------------------------------------------

def test_a_fixture_export_stores_the_expected_rows():
    mt, ev = fixture_rows()
    assert put(mt, ev) == {"metrics": 11, "events": 7}
    events, metrics = stored()
    by = {e["key"]: e for e in events}
    req_b = next(e for e in by.values() if e["name"] == "api_request" and e["session_id"] == "s2")
    assert (req_b["model"], req_b["cost_usd"], req_b["input_tokens"], req_b["output_tokens"],
            req_b["cache_read_tokens"], req_b["cache_creation_tokens"], req_b["cache_creation_5m_tokens"],
            req_b["cache_creation_1h_tokens"]) == ("claude-sonnet-5-5", 0.25, 50, 30, 0, 400, 300, 100)
    assert req_b["at"] == datetime(2026, 10, 14, 11, tzinfo=UTC).timestamp()
    tools = {e["tool"]: e for e in events if e["name"] == "tool_result"}
    assert set(tools) == {"Bash", "mcm-engine search"}
    assert (tools["Bash"]["result_bytes"], tools["Bash"]["success"]) == (400, 1)
    assert (tools["mcm-engine search"]["result_bytes"], tools["mcm-engine search"]["success"]) == (1003, 0)
    assert next(e for e in events if e["name"] == "user_prompt")["prompt_id"] == "p1"
    assert next(e for e in events if e["name"] == "tool_decision")["tool"] == "mcm-engine search"
    tok = [m for m in metrics if m["name"] == "token.usage"]
    assert sorted((m["session_id"], m["type"], m["value"]) for m in tok) == [
        ("s1", "cacheRead", 1000), ("s1", "input", 100), ("s1", "output", 20),
        ("s2", "cacheCreation", 400), ("s2", "input", 50), ("s2", "output", 30)]
    assert {m["temporality"] for m in metrics if m["name"] == "active_time.total"} == {"cumulative"}


def test_content_attributes_never_reach_the_store():
    put(*fixture_rows())
    events, metrics = stored()
    blob = json.dumps([events, metrics], default=str)
    for leak in ("SECRET-PROMPT", "SECRET-INPUT", "SECRET-ERROR", "eric@example.invalid", "tool_parameters"):
        assert leak not in blob, leak


def test_a_retried_export_adds_nothing():
    mt, ev = fixture_rows()
    put(mt, ev)
    again_mt, again_ev = otel.parse_metrics(load("metrics.json"), 99.0), otel.parse_logs(load("logs.json"), 99.0)
    assert put(again_mt, again_ev) == {"metrics": 0, "events": 0}
    events, metrics = stored()
    assert (len(events), len(metrics)) == (7, 11)


def test_a_recorded_claude_code_export_parses_and_its_events_agree_with_its_metrics():
    ev = [r for doc in load("recorded-logs.json") for r in otel.parse_logs(doc, 0)]
    mt = [r for doc in load("recorded-metrics.json") for r in otel.parse_metrics(doc, 0)]
    e, m = otel.from_events(ev), otel.from_metrics(mt)
    assert e["requests"] == 2 and e["tool_results"] == 1 and e["sessions"] == 1
    for k in ("input", "output", "cache_read", "cache_write", "models"):
        assert e[k] == m[k], k
    assert e["cache_write_5m"] + e["cache_write_1h"] == e["cache_write"]
    assert e["tool_tokens"] == 2
    assert "PROMPT-MARKER" not in json.dumps(ev)


def test_metric_totals_add_deltas_and_take_a_cumulative_series_at_its_largest():
    mt, _ = fixture_rows()
    assert otel.metric_total(mt, "active_time.total") == {"": 9.0}
    assert round(otel.metric_total(mt, "cost.usage")[""], 6) == 9.35


# --- the receiver ----------------------------------------------------------------------------------

@pytest.fixture
def receiver():
    srv = otel.server(port=0)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


def post(url, body: bytes, ctype="application/json", encoding=""):
    req = urllib.request.Request(url, data=body, method="POST", headers={"Content-Type": ctype})
    if encoding:
        req.add_header("Content-Encoding", encoding)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"{}")


def test_the_receiver_stores_json_exports_over_http(receiver):
    assert post(receiver + "/v1/logs", (FIX / "logs.json").read_bytes()) == (200, {})
    assert post(receiver + "/v1/metrics", gzip.compress((FIX / "metrics.json").read_bytes()),
                encoding="gzip") == (200, {})
    assert post(receiver + "/v1/traces", b"{}") == (200, {})
    events, metrics = stored()
    assert (len(events), len(metrics)) == (7, 11)


def test_the_receiver_refuses_protobuf_and_says_which_protocol_to_set(receiver):
    status, body = post(receiver + "/v1/logs", b"\x0a\x00", ctype="application/x-protobuf")
    assert status == 415 and "http/json" in body["error"]
    assert post(receiver + "/v1/nope", b"{}")[0] == 404
    assert post(receiver + "/v1/logs", b"{not json")[0] == 400
    assert stored() == ([], [])


def test_the_receiver_binds_loopback_only():
    with pytest.raises(ValueError, match="loopback"):
        otel.server(host="0.0.0.0", port=0)


def test_the_printed_settings_send_json_to_the_receiver(capsys):
    assert cli.main(["otel", "env", "--json"]) == 0
    env = json.loads(capsys.readouterr().out)["env"]
    assert env["CLAUDE_CODE_ENABLE_TELEMETRY"] == "1"
    assert env["OTEL_EXPORTER_OTLP_PROTOCOL"] == "http/json"
    assert env["OTEL_EXPORTER_OTLP_ENDPOINT"] == f"http://127.0.0.1:{otel.PORT}"
    assert env["OTEL_METRICS_EXPORTER"] == env["OTEL_LOGS_EXPORTER"] == "otlp"


# --- the comparison ---------------------------------------------------------------------------------

def _sources(monkeypatch, tmp_path):
    put(*fixture_rows())
    root = tmp_path / "projects" / "p"
    root.mkdir(parents=True)
    shutil.copy(FIX / "transcript.jsonl", root / "t.jsonl")
    monkeypatch.setenv("SOH_CLAUDE_PROJECTS", str(tmp_path / "projects"))
    real = ledger.cloud

    def fake_cloud(first_day, **kw):
        return real(first_day, runner=lambda argv, **k: subprocess.CompletedProcess(
            argv, 0, (FIX / "ccusage-daily.json").read_text(encoding="utf-8"), ""), which=lambda n: "/x/npx")

    monkeypatch.setattr(ledger, "cloud", fake_cloud)


def test_one_day_side_by_side_matches_the_hand_totals(monkeypatch, tmp_path):
    _sources(monkeypatch, tmp_path)
    C = ledger_cmd.gather_compare(DAY, tz=UTC)
    rows = {r["row"]: r for r in C["rows"]}
    want = {  # by hand from tests/fixtures/otel: two api_requests, two tool_results on the day
        "input": (150, 150, 150, None, 150),
        "output": (50, 50, 50, None, 50),
        "cache_read": (1000, 1000, 1000, None, 1000),
        "cache_write": (400, 400, 400, None, 400),
        "cache_write_5m": (300, None, None, None, None),
        "cache_write_1h": (100, None, None, None, None),
        "requests": (2, None, None, None, None),
        "tool_results": (2, None, None, 2, None),
        "tool_tokens": (100 + 250, None, None, 100 + 250, None),
        "sessions": (2, None, None, None, None),
    }
    for k, w in want.items():
        assert tuple(rows[k][s] for s in otel.SOURCES) == w, k
    models = {m["model"]: m for m in C["models"]}
    assert (models["claude-opus-5-5"]["otel_events"], models["claude-opus-5-5"]["otel_metrics"],
            models["claude-opus-5-5"]["ccusage"]) == (1120, 1120, 1120)
    assert "usd" not in rows


def test_the_compare_verb_prints_every_source(monkeypatch, tmp_path, capsys):
    _sources(monkeypatch, tmp_path)
    real = ledger_cmd.gather_compare
    monkeypatch.setattr(ledger_cmd, "gather_compare", lambda day: real(day, tz=UTC))
    assert cli.main(["ledger", "--compare", DAY]) == 0
    out = capsys.readouterr().out
    assert "otel_events" in out and "ccusage" in out and "transcripts" in out
    assert "tokens by model" in out and "1,120" in out and "$" not in out


def test_the_ledger_shows_otel_beside_ccusage(monkeypatch):
    _, ev = fixture_rows()
    days = ledger_cmd.otel_days(ev, tz=UTC)
    assert (days[DAY]["input"], days["2026-10-15"]["input"]) == (150, 9000) and "usd" not in days[DAY]
    assert days[DAY]["requests"] == 2


# --- soh context from OTel --------------------------------------------------------------------------

def test_context_reads_tool_results_from_otel(capsys):
    put(*fixture_rows())
    assert cli.main(["context", "--source", "otel", "--since", "2026-10-14", "--until", "2026-10-15",
                     "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    got = {r["tool"]: (r["calls"], r["tokens"]) for r in doc["rows"]}
    assert got == {"Bash": (1, 100), "mcm-engine search": (1, 250)}
    assert doc["estimate"] == "bytes/4"


@pytest.mark.gauntlet("a-closed-table-fronting-an-open-set", site="harness/otel.py:_TOKEN_TYPES")
def test_a_token_type_the_table_does_not_name_is_reported_not_dropped():
    mt, _ = fixture_rows()
    extra = {**mt[0], "name": "token.usage", "type": "cacheCreation5m", "value": 7.0, "temporality": "delta"}
    got = otel.from_metrics(mt + [extra])
    assert got["unknown_types"] == {"cacheCreation5m": 7}
    assert got["input"] == 150 and otel.from_metrics(mt)["unknown_types"] == {}


@pytest.mark.gauntlet("a-closed-table-fronting-an-open-set", site="harness/otel.py:_BUILTIN")
def test_context_by_category_uses_the_table_and_asks_the_labeller_only_for_unknown_tools():
    asked = []

    def label(tool):
        asked.append(tool)
        return "memory"

    got = otel.categorize(["Bash", "Read", "mcm-engine search"], label=label)
    assert got == {"Bash": "shell", "Read": "read", "mcm-engine search": "memory"}
    assert asked == ["mcm-engine search"]


def test_a_labeller_that_fails_or_answers_off_list_leaves_other():
    def boom(tool):
        raise RuntimeError("refused")

    assert otel.categorize(["x tool"], label=boom) == {"x tool": "other"}
    assert otel.categorize(["x tool"], label=lambda t: "banana") == {"x tool": "other"}
    assert otel.categorize(["x tool"]) == {"x tool": "other"}


def test_context_by_category_from_transcripts(capsys, monkeypatch, tmp_path):
    root = tmp_path / "projects" / "p"
    root.mkdir(parents=True)
    shutil.copy(FIX / "transcript.jsonl", root / "t.jsonl")
    assert cli.main(["context", "--root", str(tmp_path / "projects"), "--since", "2026-10-14",
                     "--until", "2026-10-15", "--by", "category", "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert {r["category"]: r["tokens"] for r in doc["rows"]} == {"shell": 100, "other": 250}


def test_scan_and_otel_rows_share_a_shape():
    rows = cr.scan([FIX / "transcript.jsonl"], since=datetime(2026, 10, 14, tzinfo=UTC).timestamp())
    assert {r["tool"] for r in rows} == {"Bash", "mcm-engine search"}
