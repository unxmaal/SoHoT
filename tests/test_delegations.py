"""Each delegation is a row whose outcome the caller records later. #829."""
import json
from http.server import BaseHTTPRequestHandler

import pytest

from harness import delegations, usage
from harness import memory_store as ms
from tests.test_mcp_delegate import (SCHEMA, SERVED, Handler, _call, fake,  # noqa: F401
                                     mcp_server)

CALL_ID = "0b9e6c1e-6a4e-4c0e-9d1f-2d3f4a5b6c7d"


@pytest.fixture
def conn():
    c = ms.connect()
    yield c
    c.close()


@pytest.fixture
def gateway_id(monkeypatch):
    """The fake answers as LiteLLM's proxy does, naming its call id in a header."""
    def end_headers(self):
        self.send_header("x-litellm-call-id", CALL_ID)
        BaseHTTPRequestHandler.end_headers(self)
    monkeypatch.setattr(Handler, "end_headers", end_headers)


def _row(conn, call_id):
    return conn.execute("SELECT * FROM delegations WHERE call_id = ?", (call_id,)).fetchone()


# ---- the table and its migration ----------------------------------------------

def test_the_store_is_schema_69_with_the_table_and_the_join_column(conn):
    assert ms.SCHEMA_VERSION == 69
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(delegations)")}
    assert {"call_id", "id_source", "at", "lane", "spec", "model", "seconds",
            "prompt_tokens", "completion_tokens", "outcome", "why", "outcome_at"} <= cols
    assert "call_id" in {r["name"] for r in conn.execute("PRAGMA table_info(gateway_requests)")}


OLD_GATEWAY_REQUESTS = """
CREATE TABLE gateway_requests (id INTEGER PRIMARY KEY, at REAL NOT NULL,
    alias TEXT NOT NULL DEFAULT '', lane TEXT NOT NULL DEFAULT '');
"""


def test_a_schema_67_store_gains_the_table_and_column_on_connect(old_store):
    path = old_store(67, "INSERT INTO gateway_requests (at, alias) VALUES (1.0, 'sohot-code');",
                     ddl=OLD_GATEWAY_REQUESTS)
    c = ms.connect(path)
    try:
        assert c.execute("SELECT value FROM meta WHERE key='schema'").fetchone()[0] == "69"
        assert c.execute("SELECT call_id FROM gateway_requests").fetchone()[0] == ""
        delegations.record(c, "x", "code")
        assert _row(c, "x")["outcome"] is None
    finally:
        c.close()


# ---- record, outcome, report --------------------------------------------------

def test_a_recorded_call_has_no_outcome_until_told(conn):
    call_id = delegations.record(conn, delegations.new_id(), "code")
    row = _row(conn, call_id)
    assert row["outcome"] is None and row["why"] == ""


def test_outcome_sets_used_and_why(conn):
    call_id = delegations.record(conn, delegations.new_id(), "code")
    got = delegations.outcome(conn, call_id, "Used", "it worked")
    assert (got["outcome"], got["why"], got["previous"], got["note"]) == (
        "used", "it worked", None, "")
    row = _row(conn, call_id)
    assert (row["outcome"], row["why"]) == ("used", "it worked")
    assert row["outcome_at"] is not None


def test_an_unknown_call_id_is_an_error(conn):
    with pytest.raises(delegations.UnknownCall, match="no delegation has call id"):
        delegations.outcome(conn, "does-not-exist", "used")
    assert conn.execute("SELECT COUNT(*) FROM delegations").fetchone()[0] == 0


def test_a_bad_outcome_is_refused(conn):
    call_id = delegations.record(conn, delegations.new_id(), "code")
    with pytest.raises(ValueError, match="used, edited, discarded"):
        delegations.outcome(conn, call_id, "kept")
    assert _row(conn, call_id)["outcome"] is None


def test_re_recording_overwrites_and_keeps_the_old_one(conn):
    call_id = delegations.record(conn, delegations.new_id(), "code")
    delegations.outcome(conn, call_id, "used", "fine")
    got = delegations.outcome(conn, call_id, "discarded", "wrong api")
    assert (got["outcome"], got["previous"], got["note"]) == ("discarded", "used", "overwrote used")
    assert got["why"] == _row(conn, call_id)["why"] == "wrong api (was used: fine)"


def test_report_per_lane_rates_and_median(conn):
    ids = [delegations.record(conn, f"c{i}", "code", at=950.0, seconds=s)
           for i, s in enumerate((1, 2, 3, 10))]
    for call_id, what in zip(ids, ("used", "used", "edited")):
        delegations.outcome(conn, call_id, what)
    delegations.record(conn, "d0", "decide", at=990.0, seconds=0.5)
    delegations.record(conn, "old", "code", at=800.0, seconds=99)
    delegations.outcome(conn, "old", "discarded")

    rows = delegations.report(conn, since=100, now=1000.0)
    assert [r["lane"] for r in rows] == ["code", "decide"]
    code, decide = rows
    assert (code["count"], code["recorded"], code["recorded_rate"]) == (4, 3, 0.75)
    assert code["used_rate"] == pytest.approx(2 / 3)
    assert code["edited_rate"] == pytest.approx(1 / 3)
    assert code["discarded_rate"] == 0.0 and code["median_seconds"] == 2.5
    assert (decide["count"], decide["recorded"], decide["used_rate"],
            decide["median_seconds"]) == (1, 0, None, 0.5)


def test_new_ids_are_distinct_and_marked_local():
    a, b = delegations.new_id(), delegations.new_id()
    assert a != b and a.startswith("local-") and len(a) == 38


# ---- delegate records and returns the id ---------------------------------------

def test_a_gateway_completion_is_keyed_by_litellm_s_call_id(fake, gateway_id, conn):
    from harness import delegate
    got = delegate.complete("code", "write add")
    assert got["call_id"] == CALL_ID
    row = _row(conn, CALL_ID)
    assert (row["lane"], row["spec"], row["model"], row["id_source"]) == (
        "code", "sohot-code", SERVED, "gateway")
    assert (row["prompt_tokens"], row["completion_tokens"]) == (9, 7)
    assert row["seconds"] == got["seconds"] and row["outcome"] is None


def test_a_call_with_no_gateway_id_gets_a_generated_one(fake, conn):
    from harness import delegate
    got = delegate.complete("code", "write add")
    assert got["call_id"].startswith("local-")
    assert _row(conn, got["call_id"])["id_source"] == "local"


def _requests(conn):
    return [dict(r) for r in conn.execute("SELECT * FROM gateway_requests")]


def test_a_direct_call_s_request_row_carries_the_delegation_s_id(fake, conn, monkeypatch):
    from harness import completion, delegate
    monkeypatch.setattr(completion, "is_gateway", lambda base, *a, **k: False)
    got = delegate.complete("code", "write add")
    (r,) = _requests(conn)
    assert r["call_id"] == got["call_id"] and r["client"] == usage.DIRECT_CLIENT
    joined = conn.execute("SELECT d.lane, d.id_source FROM delegations d JOIN gateway_requests g "
                          "ON g.call_id = d.call_id").fetchall()
    assert [tuple(j) for j in joined] == [("code", "local")]


def test_a_gateway_call_is_left_to_the_gateway_to_log_under_litellm_s_id(fake, gateway_id, conn,
                                                                         monkeypatch):
    from harness import completion, delegate
    monkeypatch.setattr(completion, "is_gateway", lambda base, *a, **k: True)
    assert delegate.complete("code", "write add")["call_id"] == CALL_ID
    assert _requests(conn) == [] and _row(conn, CALL_ID)["id_source"] == "gateway"


def test_a_lane_command_writes_no_delegation(fake, conn, monkeypatch):
    from types import SimpleNamespace

    from harness import completion
    from harness.commands import lanes
    monkeypatch.setattr(completion, "is_gateway", lambda base, *a, **k: False)
    monkeypatch.setattr(lanes, "_text_route", lambda a, lane: fake_route(fake, lane))
    lanes._complete(SimpleNamespace(model=None, gateway=None), "svg", "a cat")
    assert conn.execute("SELECT COUNT(*) FROM delegations").fetchone()[0] == 0
    (r,) = _requests(conn)
    assert r["call_id"] == ""


def fake_route(fake, lane):
    from harness import serving
    return f"sohot-{lane}", serving.Route(fake.url, f"sohot-{lane}", {})


def test_decide_records_its_call_too(fake, gateway_id, conn):
    from harness import delegate
    fake.reply = '{"kind": "B", "urgent": "A"}'
    got = delegate.decide("triage", SCHEMA)
    assert got["call_id"] == CALL_ID and _row(conn, CALL_ID)["lane"] == "decide"


def test_a_store_that_cannot_be_written_never_fails_the_delegation(fake, monkeypatch, capsys):
    from harness import delegate

    def broken():
        raise RuntimeError("store is locked")
    monkeypatch.setattr(ms, "connect", broken)
    got = delegate.complete("code", "write add")
    assert got["text"] and got["call_id"].startswith("local-")
    assert "not recorded" in capsys.readouterr().err


def test_the_gateway_log_keeps_the_call_id_it_answered_with():
    row = usage.row({"standard_logging_object": {"litellm_call_id": CALL_ID,
                                                 "model_group": "sohot-code"}}, {})
    assert row["call_id"] == CALL_ID
    assert usage.row({}, {})["call_id"] == ""


# ---- the MCP surface ----------------------------------------------------------

def test_local_complete_and_local_decide_over_mcp_carry_the_call_id(fake, gateway_id, mcp_server):
    got = mcp_server.local_complete(prompt="write add", lane="code")
    assert got.call_id == CALL_ID
    fake.reply = '{"kind": "B", "urgent": "A"}'
    assert mcp_server.local_decide(question="triage", schema=SCHEMA).call_id == CALL_ID
    tools = {t.name: t for t in mcp_server.SERVER._tool_manager.list_tools()}
    for name in ("local_complete", "local_decide", "delegated"):
        assert "call_id" in tools[name].output_schema["required"], name


def test_the_delegated_tool_records_and_refuses_an_unknown_id(fake, gateway_id, mcp_server, conn):
    from mcp.server.mcpserver.exceptions import ToolError, UnexpectedToolError
    call_id = mcp_server.local_complete(prompt="write add").call_id
    got = mcp_server.delegated(call_id=call_id, outcome="edited", why="renamed a var")
    assert (got.outcome, got.why, got.previous) == ("edited", "renamed a var", None)
    again = mcp_server.delegated(call_id=call_id, outcome="used")
    assert again.previous == "edited" and again.note == "overwrote edited"
    with pytest.raises(ToolError, match="no delegation has call id") as e:
        _call(mcp_server, "delegated", call_id="nope", outcome="used")
    assert not isinstance(e.value, UnexpectedToolError)


# ---- the CLI ------------------------------------------------------------------

def _soh(capsys, *argv):
    from harness import cli
    rc = cli.main(["delegated", *argv, "--json"])
    return rc, json.loads(capsys.readouterr().out.strip().splitlines()[-1])


def test_the_cli_records_reports_and_refuses_an_unknown_id(conn, capsys):
    delegations.record(conn, "abc", "code", seconds=4.0)
    rc, got = _soh(capsys, "abc", "discarded", "--why", "hallucinated an import")
    assert rc == 0 and got["outcome"] == "discarded"
    assert _row(conn, "abc")["why"] == "hallucinated an import"
    rc, got = _soh(capsys, "nope", "used")
    assert rc == 1 and got["ok"] is False and "no delegation has call id" in got["error"]
    rc, got = _soh(capsys, "--report", "--since", "1d")
    assert rc == 0
    assert got["report"] == [{"lane": "code", "count": 1, "recorded": 1, "recorded_rate": 1.0,
                              "used_rate": 0.0, "edited_rate": 0.0, "discarded_rate": 1.0,
                              "median_seconds": 4.0}]


def test_the_cli_needs_an_id_and_outcome_or_report(capsys):
    rc, got = _soh(capsys)
    assert rc == 2 and got["ok"] is False
