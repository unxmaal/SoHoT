"""Delegation without an MCP connection: `soh local`, `soh delegated` for either path, zero-delegation days. #1687."""
import json
import time

import pytest

from harness import cli, delegations, ledger, morning
from tests.test_delegation_outcomes_1158 import ANSWER, PROMPT, _result, _row, _use, conn  # noqa: F401
from tests.test_ledger_826 import UTC, at
from tests.test_ledger_826 import build as ledger_build
from tests.test_mcp_delegate import SCHEMA, fake, mcp_server  # noqa: F401
from tests.test_morning_867 import YESTERDAY, _report, _store, deploy_dir  # noqa: F401


@pytest.fixture
def direct(monkeypatch):
    from harness import completion
    monkeypatch.setattr(completion, "is_gateway", lambda base, *a, **k: False)


def _soh(capsys, *argv) -> tuple[int, dict]:
    rc = cli.main([*argv, "--json"])
    return rc, json.loads(capsys.readouterr().out.strip().splitlines()[-1])


def _gateway(conn, call_id):
    return conn.execute("SELECT purpose, lane, client, alias, call_id FROM gateway_requests WHERE call_id = ?",
                        (call_id,)).fetchone()


def test_the_cli_writes_the_same_gateway_row_as_the_mcp_tool(fake, mcp_server, direct, conn, capsys):  # noqa: F811
    mcp = mcp_server.local_complete(prompt="write add", lane="code")
    rc, got = _soh(capsys, "local", "complete", "write add", "--lane", "code")
    assert rc == 0 and got["ok"] and got["call_id"] != mcp.call_id and got["text"] == mcp.text
    a, b = _gateway(conn, mcp.call_id), _gateway(conn, got["call_id"])
    assert a is not None and b is not None
    assert tuple(a)[:4] == tuple(b)[:4] and a["purpose"] == "work"
    assert _row(conn, got["call_id"])["lane"] == _row(conn, mcp.call_id)["lane"] == "code"
    assert f"soh delegated {got['call_id']}" in got["report"]


def test_the_cli_decides_with_the_same_rows_as_local_decide(fake, mcp_server, direct, conn, capsys):  # noqa: F811
    fake.reply = '{"kind": "B", "urgent": "A"}'
    mcp = mcp_server.local_decide(question="triage", schema=SCHEMA, context="crash on start")
    rc, got = _soh(capsys, "local", "decide", "triage", "--schema", json.dumps(SCHEMA), "--context", "crash on start")
    assert rc == 0 and got["answers"] == mcp.answers
    assert tuple(_gateway(conn, mcp.call_id))[:4] == tuple(_gateway(conn, got["call_id"]))[:4]
    assert _row(conn, got["call_id"])["lane"] == "decide"


def test_soh_delegated_closes_a_call_id_opened_by_either_path(fake, mcp_server, direct, conn, capsys):  # noqa: F811
    mcp = mcp_server.local_complete(prompt="write add")
    _, cli_got = _soh(capsys, "local", "complete", "write add")
    for call_id, outcome in ((mcp.call_id, "used"), (cli_got["call_id"], "edited")):
        rc, got = _soh(capsys, "delegated", call_id, outcome, "renamed a var")
        assert rc == 0 and got["outcome"] == outcome
        row = _row(conn, call_id)
        assert (row["outcome"], row["why"]) == (outcome, "renamed a var")
    assert mcp_server.delegated(call_id=cli_got["call_id"], outcome="discarded").previous == "edited"


def test_the_human_output_ends_with_the_footer_and_the_follow_up(fake, direct, conn, capsys):  # noqa: F811
    assert cli.main(["local", "complete", "write add"]) == 0
    out = capsys.readouterr().out
    got = delegations.cli_result(out)
    assert got["text"] == fake.reply.rstrip("\n") and _row(conn, got["call_id"]) is not None
    assert f"soh delegated {got['call_id']} used|edited|discarded" in out


def test_a_cli_refusal_is_an_error_not_a_row(fake, direct, conn, capsys):  # noqa: F811
    rc, got = _soh(capsys, "local", "complete", "p", "--mode", "spans")
    assert rc == 1 and not got["ok"] and "spans" in got["error"]
    assert conn.execute("SELECT COUNT(*) FROM delegations").fetchone()[0] == 0


@pytest.mark.parametrize("as_json", [False, True])
def test_an_answer_from_a_bash_soh_local_call_is_inferred_from_the_transcript(conn, tmp_path, as_json):  # noqa: F811
    cid = delegations.record(conn, delegations.new_id(), "code", at=time.time() - 60)
    out = (json.dumps({"ok": True, "verb": "local", "text": ANSWER, "call_id": cid}) if as_json
           else f"{ANSWER}\n-- m, 1.0s, call_id {cid}\n{delegations.instruction(cid, cli=True)}\n")
    path = tmp_path / "-Users-someone-project" / "s.jsonl"
    path.parent.mkdir(parents=True)
    recs = [_use("t1", "Bash", {"command": f"soh local complete {json.dumps(PROMPT)}"}), _result("t1", out),
            _use("t2", "Edit", {"file_path": "/x.py", "old_string": "pass", "new_string": ANSWER})]
    recs[1]["message"]["content"][0]["content"] = [{"type": "text", "text": out}]
    path.write_text("".join(json.dumps(r) + "\n" for r in recs), encoding="utf-8")
    assert delegations.close(conn, root=tmp_path)["accepted"] == 1
    assert "Edit input" in _row(conn, cid)["why"]


def _cloud(day: str) -> dict:
    tokens = {"input": 10, "output": 5, "cache_read": 0, "cache_write": 0}
    return {"available": True, "days": {day: {"tokens": tokens, "models": {}}}}


def test_the_ledger_flags_a_day_with_cloud_work_and_no_delegation():
    got = ledger_build(cloud_doc=_cloud("2026-10-09"), tz=UTC)
    assert got["zero_delegation_days"] == ["2026-10-09"]
    assert [d["day"] for d in got["days"] if d["zero_delegation"]] == ["2026-10-09"]
    one = ledger_build(cloud_doc=_cloud("2026-10-09"), tz=UTC,
                       delegations=[("c1", at("2026-10-09"), "code", None, 3, 4)])
    assert one["zero_delegation_days"] == []


def test_the_morning_brief_names_last_night_s_zero_delegation_day(deploy_dir):  # noqa: F811
    c = _store()
    assert not any("zero delegations" in n for n in _report(c, deploy_dir)["needs"])
    detail = json.loads(c.execute("SELECT detail FROM ledger_days WHERE day = ?", (YESTERDAY,)).fetchone()[0])
    detail.pop("delegated")
    c.execute("UPDATE ledger_days SET detail = ? WHERE day = ?", (json.dumps(detail), YESTERDAY))
    c.commit()
    r = _report(c, deploy_dir)
    assert r["ledger"]["zero_delegation"]
    assert any(n.startswith(f"zero delegations on {YESTERDAY}") for n in r["needs"])
    assert not morning.ledger_row(c, time.time()).get("zero_delegation")
