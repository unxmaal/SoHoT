"""soh ledger --by: rewrites after a compaction, and counted cloud tokens per pull request a stream opened. #2031."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from harness import cli, token_flow
from harness.commands import ledger as ledger_cmd
from tests.test_token_flow_2031 import PLANTED, SINCE, SINCE_ARG, T0, flow, idle_stream, rec, write

URL = "https://github.com/unxmaal/SoHoT/pull/{n}"


def stamp(at: float) -> str:
    return datetime.fromtimestamp(at, timezone.utc).isoformat().replace("+00:00", "Z")


def boundary(at: float) -> dict:
    return {"type": "system", "subtype": "compact_boundary", "content": "Conversation compacted",
            "timestamp": stamp(at), "uuid": f"cb-{at}", "compactMetadata": {"trigger": "auto"}}


def result(at: float, rid: str, text: str, as_list: bool = False) -> dict:
    content = [{"type": "text", "text": text}] if as_list else text
    return {"type": "user", "timestamp": stamp(at), "uuid": f"r-{rid}",
            "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": f"toolu_{rid}",
                                                     "content": content}]},
            "toolUseResult": {"stdout": text}}


def opens(at: float, rid: str, n: int, *, cw=0, cr=0, out=10, agent=None, as_list=False) -> list[dict]:
    """A request that runs gh pr create and the result that prints the new pull request's URL."""
    cmd = {"command": f"git push -u origin b && gh pr create --title t --body-file tmp/{n}/body.md"}
    return [rec(at, rid, cw=cw, cr=cr, out=out, agent=agent, tool=("Bash", cmd)),
            result(at + 2, rid, f"X11 forwarding request failed\n{URL.format(n=n)}\n", as_list)]


def cause_of(A: dict, kind: str, cause: str) -> dict:
    return next((c for c in A["causes"] if (c["kind"], c["cause"]) == (kind, cause)), {"cache_write": 0, "events": 0})


def pr_row(A: dict, pr: str) -> dict:
    return next((p for p in A["prs"] if p["pr"] == pr), {"counted": 0, "requests": 0})


def test_a_write_after_a_compaction_boundary_is_its_own_cause_with_the_planted_size(tmp_path):
    write(tmp_path, "proj/s1.jsonl", [rec(T0, "m1", cw=5000, ttl="1h"), rec(T0 + 30, "m2", cw=200, cr=5000, ttl="1h"),
                                      boundary(T0 + 40), rec(T0 + 60, "m3", cw=PLANTED, cr=900, ttl="1h"),
                                      rec(T0 + 90, "m4", cw=50, cr=PLANTED, ttl="1h")])
    A = flow(tmp_path)
    assert cause_of(A, "main", token_flow.COMPACTED) == {
        "kind": "main", "cause": token_flow.COMPACTED, "cache_write": PLANTED, "events": 1,
        "share": PLANTED / A["counted"]}
    assert cause_of(A, "main", token_flow.REWRITE)["events"] == 0
    assert cause_of(A, "main", token_flow.GROWTH)["cache_write"] == 250
    assert sum(c["cache_write"] for c in A["causes"]) == A["tokens"]["cache_write"]


def test_without_the_boundary_the_same_write_is_a_rewrite_and_a_boundary_after_it_changes_nothing(tmp_path):
    reqs = [rec(T0, "m1", cw=5000, ttl="1h"), rec(T0 + 60, "m2", cw=PLANTED, cr=900, ttl="1h")]
    write(tmp_path, "proj/s1.jsonl", [*reqs, boundary(T0 + 61)])
    A = flow(tmp_path)
    assert cause_of(A, "main", token_flow.REWRITE)["cache_write"] == PLANTED
    assert cause_of(A, "main", token_flow.COMPACTED)["events"] == 0


def test_a_compaction_before_an_expired_idle_is_counted_as_the_compaction(tmp_path):
    write(tmp_path, "proj/s1/subagents/agent-a1.jsonl",
          [*idle_stream("a", "5m")[:2], boundary(T0 + 100), *idle_stream("a", "5m")[2:]])
    A = flow(tmp_path)
    assert cause_of(A, "subagent", token_flow.COMPACTED)["cache_write"] == PLANTED
    assert A["expiry"]["events"] == 0


def test_each_planted_pull_request_gets_the_tokens_of_the_stream_that_opened_it(tmp_path):
    write(tmp_path, "proj/s1/subagents/agent-a1.jsonl", [
        rec(T0, "a1", cw=1000, inp=2, out=20, agent="sohot-fix"), *opens(T0 + 10, "a2", 101, cw=PLANTED, cr=1000,
                                                                         agent="sohot-fix"),
        rec(T0 + 20, "a3", cw=5, cr=PLANTED, out=7, agent="sohot-fix")])
    write(tmp_path, "proj/s2/subagents/agent-b1.jsonl", [
        rec(T0, "b1", cw=300), *opens(T0 + 10, "b2", 102, cw=40, cr=300, as_list=True),
        rec(T0 + 30, "b3", cw=60, cr=340), *opens(T0 + 40, "b4", 103, cw=8, cr=400)])
    write(tmp_path, "proj/s3/subagents/agent-c1.jsonl", [rec(T0, "c1", cw=900, out=3)])
    A = flow(tmp_path)
    assert pr_row(A, "unxmaal/sohot#101") == {
        "pr": "unxmaal/sohot#101", "input": 4, "output": 37, "cache_read": 1000 + PLANTED,
        "cache_write": 1000 + PLANTED + 5, "requests": 3, "streams": 1, "counted": 1000 + PLANTED + 5 + 4 + 37,
        "share": (1000 + PLANTED + 5 + 4 + 37) / A["counted"]}
    assert (pr_row(A, "unxmaal/sohot#102")["cache_write"], pr_row(A, "unxmaal/sohot#102")["requests"]) == (340, 2)
    assert (pr_row(A, "unxmaal/sohot#103")["cache_write"], pr_row(A, "unxmaal/sohot#103")["requests"]) == (68, 2)
    assert A["no_pr"]["counted"] == 900 + 1 + 3
    assert sum(p["counted"] for p in A["prs"]) + A["no_pr"]["counted"] == A["counted"]


def test_a_main_session_keeps_only_the_requests_up_to_its_pull_request(tmp_path):
    write(tmp_path, "proj/s1.jsonl", [rec(T0, "m1", cw=100, ttl="1h"), *opens(T0 + 10, "m2", 7, cw=20, cr=100),
                                      rec(T0 + 30, "m3", cw=PLANTED, cr=120, ttl="1h")])
    A = flow(tmp_path)
    assert pr_row(A, "unxmaal/sohot#7")["cache_write"] == 120
    assert A["no_pr"]["counted"] == PLANTED + 1 + 10


def test_a_pull_request_url_printed_by_any_other_command_is_no_opening(tmp_path):
    view = {"command": "gh pr view 55 --json url"}
    write(tmp_path, "proj/s1/subagents/agent-a1.jsonl", [
        rec(T0, "a2", cw=100, tool=("Bash", {"command": "gh pr create --fill"})),
        result(T0 + 1, "a2", "pull request create failed: GraphQL: No commits between main and b"),
        rec(T0 + 5, "a1", cw=10, cr=100, tool=("Bash", view)), result(T0 + 6, "a1", URL.format(n=55))])
    A = flow(tmp_path)
    assert A["prs"] == [] and A["no_pr"]["counted"] == A["counted"]


def test_merged_only_keeps_merged_rows_and_folds_the_rest_and_asks_gh_once_a_repo(tmp_path):
    write(tmp_path, "proj/s1/subagents/agent-a1.jsonl", [*opens(T0, "a1", 1, cw=500)])
    write(tmp_path, "proj/s2/subagents/agent-b1.jsonl", [*opens(T0, "b1", 2, cw=70)])
    write(tmp_path, "proj/s3/subagents/agent-c1.jsonl", [*opens(T0, "c1", 3, cw=9)])
    A = flow(tmp_path)
    asked = []

    def gh(argv):
        asked.append(argv)
        return json.dumps([{"number": 1}, {"number": 3}, {"number": 99}])
    merged = token_flow.merged_prs(A["prs"], gh)
    assert merged == {"unxmaal/sohot#1", "unxmaal/sohot#3", "unxmaal/sohot#99"}
    assert asked == [["pr", "list", "--repo", "unxmaal/sohot", "--state", "merged", "--limit", "1000", "--json",
                      "number"]]
    M = token_flow.merged_only(A, merged)
    assert [p["pr"] for p in M["prs"]] == ["unxmaal/sohot#1", "unxmaal/sohot#3"]
    assert M["not_merged"]["counted"] == 70 + 1 + 10
    assert sum(p["counted"] for p in M["prs"]) + M["not_merged"]["counted"] + M["no_pr"]["counted"] == M["counted"]


def test_ledger_by_prints_the_pull_request_table_and_merged_asks_gh(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SOH_CLAUDE_PROJECTS", str(tmp_path))
    write(tmp_path, "proj/s1/subagents/agent-a1.jsonl", [*opens(T0, "a1", 41, cw=PLANTED, agent="sohot-fix")])
    write(tmp_path, "proj/s2/subagents/agent-b1.jsonl", [*opens(T0, "b1", 42, cw=300)])
    assert cli.main(["ledger", "--by", "--since", SINCE_ARG]) == 0
    text = capsys.readouterr().out
    assert "counted by pull request, joined on the stream whose gh pr create opened it (2; median" in text
    assert "unxmaal/sohot#41" in text and "unxmaal/sohot#42" in text and token_flow.NO_PR in text
    monkeypatch.setattr(ledger_cmd, "gather_by", lambda a, now, gh=None, _g=ledger_cmd.gather_by: _g(
        a, now, gh=lambda argv: json.dumps([{"number": 41}])))
    assert cli.main(["ledger", "--by", "--since", SINCE_ARG, "--merged", "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert [p["pr"] for p in doc["prs"]] == ["unxmaal/sohot#41"]
    assert doc["not_merged"]["counted"] == 300 + 1 + 10


def test_ledger_by_merged_with_gh_failing_says_so_and_keeps_every_row(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SOH_CLAUDE_PROJECTS", str(tmp_path))
    write(tmp_path, "proj/s1/subagents/agent-a1.jsonl", [*opens(T0, "a1", 41, cw=PLANTED)])

    def broken(argv):
        raise RuntimeError("gh pr list failed: offline")
    monkeypatch.setattr(ledger_cmd, "gather_by", lambda a, now, gh=None, _g=ledger_cmd.gather_by: _g(a, now, gh=broken))
    assert cli.main(["ledger", "--by", "--since", SINCE_ARG, "--merged"]) == 0
    text = capsys.readouterr().out
    assert "merged    unread: gh pr list failed: offline" in text and "unxmaal/sohot#41" in text


def test_the_window_since_is_honoured_for_pull_request_rows(tmp_path):
    write(tmp_path, "proj/s1/subagents/agent-a1.jsonl", [rec(SINCE - 3600, "a0", cw=4000),
                                                         *opens(T0, "a1", 5, cw=60, cr=4000)])
    A = flow(tmp_path)
    assert pr_row(A, "unxmaal/sohot#5")["cache_write"] == 60
