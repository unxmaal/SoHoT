"""Delegation outcomes are closed: internal calls are not delegations, evidence infers, silence expires. #1158."""
import json
import time
from pathlib import Path

import pytest

from harness import delegations, ledger
from harness import memory_store as ms
from tests.test_mcp_delegate import fake, mcp_server  # noqa: F401

REPO = Path(__file__).resolve().parents[1]
ANSWER = ("def add(a, b):\n    \"\"\"The sum of two numbers, as the caller asked.\"\"\"\n"
          "    return a + b  # integer and float alike, nothing else\n")
PROMPT = "Write add(a, b) for the harness: return the sum of two numbers, nothing else."


@pytest.fixture
def conn():
    c = ms.connect()
    yield c
    c.close()


def _count(conn):
    return conn.execute("SELECT COUNT(*) FROM delegations").fetchone()[0]


def _row(conn, call_id):
    return conn.execute("SELECT * FROM delegations WHERE call_id = ?", (call_id,)).fetchone()


def _use(uid, name, given):
    return {"type": "assistant", "message": {"role": "assistant", "content": [
        {"type": "tool_use", "id": uid, "name": name, "input": given}]}}


def _result(uid, body, error=False):
    return {"type": "user", "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": uid, "is_error": error,
         "content": [{"type": "text", "text": json.dumps(body)}]}]}}


def _transcript(root: Path, call_id: str, *later, answer=ANSWER, prompt=PROMPT, name="session") -> Path:
    path = root / "-Users-someone-project" / f"{name}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    recs = [_use("t1", "mcp__soh__local_complete", {"prompt": prompt, "lane": "code"}),
            _result("t1", {"text": answer, "lane": "code", "call_id": call_id, "report": "..."}),
            *later]
    path.write_text("".join(json.dumps(r) + "\n" for r in recs), encoding="utf-8")
    return path


# ---- internal callers are not delegations ------------------------------------------------------

def test_a_morning_brief_call_writes_no_delegation_row(fake, conn, monkeypatch):  # noqa: F811
    from harness import completion, morning
    monkeypatch.setattr(completion, "is_gateway", lambda base, *a, **k: False)
    monkeypatch.setattr("harness.delegate.busy", lambda: "")
    assert morning._ask("condense last night")
    assert _count(conn) == 0
    (r,) = conn.execute("SELECT purpose, call_id FROM gateway_requests").fetchall()
    assert (r["purpose"], r["call_id"]) == ("internal", "")


def test_a_program_s_decide_is_internal_and_an_agent_s_is_a_delegation(fake, conn, monkeypatch):  # noqa: F811
    from harness import completion, delegate
    from tests.test_delegations import SCHEMA
    monkeypatch.setattr(completion, "is_gateway", lambda base, *a, **k: False)
    fake.reply = '{"kind": "B", "urgent": "A"}'
    delegate.decide("triage", SCHEMA)
    assert _count(conn) == 0
    got = delegate.decide("triage", SCHEMA, delegated=True)
    assert _row(conn, got["call_id"])["lane"] == "decide"
    purposes = sorted(r[0] for r in conn.execute("SELECT purpose FROM gateway_requests"))
    assert purposes == ["internal", "work"]


def test_every_mcp_result_carries_the_outcome_instruction(fake, mcp_server, conn):  # noqa: F811
    from tests.test_delegations import SCHEMA
    got = mcp_server.local_complete(prompt="write add", lane="code")
    assert got.call_id in got.report and "delegated" in got.report
    assert _row(conn, got.call_id) is not None
    fake.reply = '{"kind": "B", "urgent": "A"}'
    dec = mcp_server.local_decide(question="triage", schema=SCHEMA)
    assert dec.call_id in dec.report and "delegated" in dec.report
    tools = {t.name: t for t in mcp_server.SERVER._tool_manager.list_tools()}
    for name in ("local_complete", "local_decide"):
        assert "report" in tools[name].output_schema["properties"], name


# ---- inference from the caller's transcript ----------------------------------------------------

def test_an_answer_that_appears_in_a_later_tool_input_is_accepted(conn, tmp_path):
    cid = delegations.record(conn, delegations.new_id(), "code", at=time.time() - 60)
    _transcript(tmp_path, cid, _use("t2", "Read", {"file_path": "/x.py"}),
                _use("t3", "Edit", {"file_path": "/x.py", "old_string": "pass", "new_string": ANSWER}))
    got = delegations.close(conn, root=tmp_path)
    assert got["accepted"] == 1 and got["pending"] == 0
    row = _row(conn, cid)
    assert row["outcome"] == "accepted" and row["outcome_at"] is not None
    assert "Edit input" in row["why"] and "session" in row["why"]
    assert "return a + b" not in row["why"] and "session.jsonl" not in row["why"]


def test_an_answer_reindented_in_a_shell_heredoc_still_counts(conn, tmp_path):
    cid = delegations.record(conn, delegations.new_id(), "code", at=time.time() - 60)
    pasted = "cat > x.py <<'EOF'\n" + "\n".join("\t" + " ".join(ln.split()) for ln in ANSWER.splitlines()) + "\nEOF"
    _transcript(tmp_path, cid, _use("t2", "Bash", {"command": pasted}))
    assert delegations.close(conn, root=tmp_path)["accepted"] == 1


def test_lines_the_prompt_already_held_are_not_evidence(conn, tmp_path):
    cid = delegations.record(conn, delegations.new_id(), "code", at=time.time() - 60)
    echo = PROMPT + "\nok"
    _transcript(tmp_path, cid, _use("t2", "Write", {"file_path": "/n.md", "content": PROMPT}), answer=echo)
    assert delegations.close(conn, root=tmp_path)["pending"] == 1
    assert _row(conn, cid)["outcome"] is None


def test_the_task_asked_again_of_a_cloud_agent_is_rejected(conn, tmp_path):
    cid = delegations.record(conn, delegations.new_id(), "code", at=time.time() - 60)
    _transcript(tmp_path, cid, _use("t2", "Agent", {"description": "write add", "prompt": PROMPT}),
                _use("t3", "Edit", {"new_string": ANSWER}))
    assert delegations.close(conn, root=tmp_path)["rejected"] == 1
    assert "asked again" in _row(conn, cid)["why"]


def test_resending_the_answer_to_the_local_model_is_not_acceptance(conn, tmp_path):
    cid = delegations.record(conn, delegations.new_id(), "code", at=time.time() - 60)
    _transcript(tmp_path, cid, _use("t2", "mcp__soh__local_complete", {"prompt": "fix this:\n" + ANSWER}))
    assert delegations.close(conn, root=tmp_path)["pending"] == 1


def test_evidence_in_another_session_or_before_the_answer_does_not_count(conn, tmp_path):
    cid = delegations.record(conn, delegations.new_id(), "code", at=time.time() - 60)
    _transcript(tmp_path, cid)
    other = tmp_path / "-Users-someone-project" / "other.jsonl"
    other.write_text(json.dumps(_use("x", "Edit", {"new_string": ANSWER})) + "\n", encoding="utf-8")
    early = tmp_path / "-Users-someone-project" / "early.jsonl"
    cid2 = delegations.record(conn, delegations.new_id(), "code", at=time.time() - 60)
    early.write_text("".join(json.dumps(r) + "\n" for r in (
        _use("e0", "Edit", {"new_string": ANSWER}),
        _use("e1", "mcp__soh__local_complete", {"prompt": PROMPT}),
        _result("e1", {"text": ANSWER, "call_id": cid2}))), encoding="utf-8")
    assert delegations.close(conn, root=tmp_path)["pending"] == 2


# ---- expiry ------------------------------------------------------------------------------------

def test_a_delegation_with_no_evidence_expires_to_unknown_and_a_young_one_waits(conn, tmp_path):
    now = time.time()
    old = delegations.record(conn, delegations.new_id(), "code", at=now - 25 * 3600)
    young = delegations.record(conn, delegations.new_id(), "code", at=now - 3600)
    gone = delegations.record(conn, delegations.new_id(), "extract", at=now - 30 * 3600)
    _transcript(tmp_path, old, _use("t2", "Read", {"file_path": "/x.py"}), name="a")
    _transcript(tmp_path, young, name="b")
    got = delegations.close(conn, root=tmp_path, now=now, expiry_h=24)
    assert (got["unknown"], got["pending"]) == (2, 1)
    assert _row(conn, old)["outcome"] == "unknown"
    assert "no later tool input held the answer" in _row(conn, old)["why"]
    assert "no transcript" in _row(conn, gone)["why"]
    assert _row(conn, young)["outcome"] is None
    assert conn.execute("SELECT COUNT(*) FROM delegations WHERE outcome IS NULL AND at < ?",
                        (now - 24 * 3600,)).fetchone()[0] == 0


def test_close_never_overwrites_a_reported_outcome(conn, tmp_path):
    cid = delegations.record(conn, delegations.new_id(), "code", at=time.time() - 30 * 3600)
    delegations.outcome(conn, cid, "discarded", "wrong import")
    _transcript(tmp_path, cid, _use("t2", "Edit", {"new_string": ANSWER}))
    got = delegations.close(conn, root=tmp_path)
    assert got["accepted"] == 0 and _row(conn, cid)["outcome"] == "discarded"


def test_the_cli_closes_and_reports_the_kinds(conn, tmp_path, capsys):
    from harness import cli
    cid = delegations.record(conn, delegations.new_id(), "code", seconds=2.0, at=time.time() - 60)
    _transcript(tmp_path, cid, _use("t2", "Write", {"content": ANSWER}))
    assert cli.main(["delegated", "--close", "--root", str(tmp_path), "--json"]) == 0
    assert json.loads(capsys.readouterr().out.strip().splitlines()[-1])["accepted"] == 1
    assert cli.main(["delegated", "--report", "--json"]) == 0
    (r,) = json.loads(capsys.readouterr().out.strip().splitlines()[-1])["report"]
    assert (r["accepted"], r["pending"], r["recorded"]) == (1, 0, 0)


def test_the_delegations_unit_runs_close_hourly_on_the_scheduler_only():
    text = (REPO / "scripts" / "launchd.sh").read_text(encoding="utf-8")
    assert "delegations" in text.split("declare -a SCHEDULER_ONLY=(")[1].split(")")[0].split()
    assert 'DELEGATIONS_EVERY_MIN="${DELEGATIONS_EVERY_MIN:-60}"' in text
    assert "soh delegated --close" in (REPO / "scripts" / "serve-delegations.sh").read_text(encoding="utf-8")


# ---- soh ledger: accepted local work against the census ----------------------------------------

def _census(where: Path):
    where.mkdir(parents=True)
    (where / "strata.json").write_text(json.dumps({"days": 14, "now": 1.0}), encoding="utf-8")
    rows = [{"final": {"shape": "small_code_edit"}, "weight": 7.0},
            {"final": {"shape": "small_code_edit"}, "weight": 7.0},
            {"final": {"shape": "media"}, "weight": 3.0}, {"final": {}, "weight": 9.0}]
    (where / "manifest.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def test_every_lane_maps_to_shapes_the_census_labels():
    from evals.analysis import demand
    assert {s for shapes in ledger.LANE_SHAPES.values() for s in shapes} <= set(demand.SHAPES)
    got = ledger.census()
    assert got["available"] and set(got["per_day"]) <= set(demand.SHAPES)


def test_the_census_is_read_as_cloud_subtasks_per_day(tmp_path):
    _census(tmp_path / "demand")
    got = ledger.census(tmp_path / "demand")
    assert got["available"] and got["per_day"] == {"media": round(3 / 14, 3), "small_code_edit": 1.0}
    assert ledger.census(tmp_path / "absent")["available"] is False


@pytest.mark.gauntlet("a-closed-table-fronting-an-open-set", site="harness/ledger.py:LANE_SHAPES")
def test_soh_ledger_prints_the_accepted_share_line(tmp_path):
    from harness.commands import ledger as ledger_cmd
    _census(tmp_path / "demand")
    day = ledger.day_start("2026-10-20")
    rows = [("a", day + 10, "code", "accepted", 9, 7), ("b", day + 20, "code", "used", 9, 7),
            ("c", day + 30, "code", "rejected", 9, 7), ("d", day + 40, "code", "unknown", 9, 7),
            ("e", day + 50, "extract", None, 9, 7), ("f", day + 60, "web", "edited", 1, 1)]
    A = ledger.accepted(rows, ["2026-10-20", "2026-10-21"], ledger.census(tmp_path / "demand"))
    code = A["lanes"]["code"]
    assert (code["accepted"], code["rejected"], code["unknown"], code["per_day"]) == (2, 1, 1, 1.0)
    assert code["days"] == {"2026-10-20": 2} and code["cloud_per_day"] == 1.0 and code["local_share"] == 0.5
    assert A["total"]["accepted"] == 3 and A["accepted_share"] == 0.75
    lines = ledger_cmd.accepted_lines(A)
    assert lines[0].startswith("accepted  share 75% of closed delegations: 3 accepted, 1 rejected")
    assert any("code" in ln and "local share 50.0%" in ln for ln in lines)
    assert any("web" in ln and "no census shape" in ln for ln in lines)
    gone = ledger_cmd.accepted_lines(ledger.accepted(rows, ["2026-10-20"], ledger.census(tmp_path / "x")))
    assert any("census unavailable" in ln for ln in gone)
