"""soh ledger --by: counted cloud tokens by model, per agent type and per pull request. #2118."""
from __future__ import annotations

import json

from harness import cli, token_flow
from harness.commands import ledger as ledger_cmd
from tests.test_token_flow_2031 import SINCE, SINCE_ARG, T0, flow, rec, write
from tests.test_token_flow_prs_2031 import opens

UNMODELED = object()

N = 3132
EXPECTED = {
    "counted": N, "tokens": {"input": 12, "output": 120, "cache_read": 0, "cache_write": 3000}, "requests": 2,
    "streams": 2,
    "kinds": [{"kind": "main", "input": 5, "output": 50, "cache_read": 0, "cache_write": 1000, "requests": 1,
               "streams": 1, "counted": 1055, "share": 1055 / N},
              {"kind": "subagent", "input": 7, "output": 70, "cache_read": 0, "cache_write": 2000, "requests": 1,
               "streams": 1, "counted": 2077, "share": 2077 / N}],
    "agents": [{"agent": "sohot-fix", "input": 7, "output": 70, "cache_read": 0, "cache_write": 2000, "requests": 1,
                "streams": 1, "counted": 2077, "share": 2077 / N}],
    "causes": [{"kind": "subagent", "cause": "cold start", "cache_write": 2000, "events": 1, "share": 2000 / N},
               {"kind": "main", "cause": "cold start", "cache_write": 1000, "events": 1, "share": 1000 / N}],
    "expiry": {"cache_write": 0, "events": 0, "share": 0.0, "median_tokens": None, "median_idle_s": None,
               "by_ttl": {}, "tools": []},
    "terms": [{"term": "subagent cache write, cold start", "tokens": 2000, "share": 2000 / N},
              {"term": "main cache write, cold start", "tokens": 1000, "share": 1000 / N},
              {"term": "subagent output", "tokens": 70, "share": 70 / N},
              {"term": "main output", "tokens": 50, "share": 50 / N},
              {"term": "subagent input", "tokens": 7, "share": 7 / N},
              {"term": "main input", "tokens": 5, "share": 5 / N}],
    "top": [{"stream": "agent-a1", "kind": "subagent", "agent": "sohot-fix", "input": 7, "output": 70,
             "cache_read": 0, "cache_write": 2000, "requests": 1, "counted": 2077, "share": 2077 / N,
             "expiry_rewrites": 0},
            {"stream": "s1", "kind": "main", "agent": "", "input": 5, "output": 50, "cache_read": 0,
             "cache_write": 1000, "requests": 1, "counted": 1055, "share": 1055 / N, "expiry_rewrites": 0}],
    "prs": [], "no_pr": {"counted": N, "share": 1.0}}


def on(model, recs: list[dict]) -> list[dict]:
    """The same records with the transcript's message.model set to `model`, or dropped for UNMODELED."""
    for r in recs:
        if r["type"] != "assistant":
            continue
        if model is UNMODELED:
            r["message"].pop("model", None)
        else:
            r["message"]["model"] = model
    return recs


def plant(root) -> None:
    write(root, "proj/s1.jsonl", on("A", [rec(T0, "m1", cw=1000, inp=5, out=50, ttl="1h")]))
    write(root, "proj/s1/subagents/agent-a1.jsonl", on("A", [
        rec(T0 + 5, "a1", cw=2000, inp=7, out=70, agent="sohot-fix"),
        rec(T0 + 9, "a2", cw=100, cr=2000, inp=3, out=30, agent="sohot-fix")]))
    write(root, "proj/s1/subagents/agent-b1.jsonl", on("B", [
        rec(T0 + 6, "b1", cw=400, inp=1, out=9, agent="sohot-fix"),
        rec(T0 + 8, "b2", cw=60, cr=400, inp=2, out=20, agent="sohot-fix")]))


def model_rows(A: dict) -> dict:
    return {(m["kind"], m["agent"], m["model"]): m["counted"] for m in A["models"]}


def test_models_are_one_entry_per_kind_agent_and_model_each_the_sum_of_its_stream(tmp_path):
    plant(tmp_path)
    A = flow(tmp_path)
    assert len(A["models"]) == 3
    assert model_rows(A) == {("main", token_flow.UNNAMED, "A"): 1055, ("subagent", "sohot-fix", "A"): 2210,
                             ("subagent", "sohot-fix", "B"): 492}
    assert [m["counted"] for m in A["models"]] == [2210, 1055, 492]
    assert A["models"][0]["share"] == 2210 / A["counted"]


def test_the_models_are_a_partition_of_the_counted_tokens(tmp_path):
    plant(tmp_path)
    A = flow(tmp_path)
    assert sum(m["counted"] for m in A["models"]) == A["counted"]


def test_a_record_with_no_model_lands_under_a_question_mark_and_is_not_dropped(tmp_path):
    write(tmp_path, "proj/s1.jsonl", on(UNMODELED, [rec(T0, "m1", cw=1000, inp=5, out=50, ttl="1h")]))
    A = flow(tmp_path)
    assert model_rows(A) == {("main", token_flow.UNNAMED, "?"): 1055}
    assert sum(m["counted"] for m in A["models"]) == A["counted"]


def test_a_pull_request_carries_the_models_of_the_requests_that_worked_toward_it(tmp_path):
    write(tmp_path, "proj/s1.jsonl", on("A", [rec(T0, "m1", cw=1000, inp=5, out=50, ttl="1h")]))
    write(tmp_path, "proj/s1/subagents/agent-b1.jsonl", on("B", [
        rec(T0 + 6, "b1", cw=400, inp=1, out=9, agent="sohot-fix"), *opens(T0 + 8, "b2", 77, cw=60, out=20,
                                                                           agent="sohot-fix"),
        rec(T0 + 20, "b3", cw=5, cr=460, out=4, agent="sohot-fix")]))
    A = flow(tmp_path)
    assert len(A["prs"]) == 1
    assert A["prs"][0]["counted"] > 0
    assert A["prs"][0]["models"] == {"B": A["prs"][0]["counted"]}


def test_ledger_by_prints_a_by_model_block_and_the_json_account_carries_models(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SOH_CLAUDE_PROJECTS", str(tmp_path))
    plant(tmp_path)
    assert cli.main(["ledger", "--by", "--since", SINCE_ARG]) == 0
    out = capsys.readouterr().out.splitlines()
    at = out.index("by model")
    block = out[at + 1:out.index("", at + 1)]
    assert out[at - 1] == "" and len(block) == 3
    assert [line.split()[:3] for line in block] == [["subagent", "sohot-fix", "A"], ["main", "A", "1"],
                                                    ["subagent", "sohot-fix", "B"]]
    assert cli.main(["ledger", "--by", "--since", SINCE_ARG, "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert len(doc["models"]) == 3 and {m["model"] for m in doc["models"]} == {"A", "B"}
    assert all("models" in p for p in doc["prs"])


def test_the_pull_request_line_lists_its_models_largest_first(capsys):
    B = {"prs": [{"pr": "o/r#1", "streams": 1, "requests": 3, "counted": 90, "share": 1.0, "input": 1, "output": 2,
                  "cache_write": 87, "models": {"A": 10, "B": 80}}],
         "no_pr": {"counted": 0, "share": 0.0}}
    ledger_cmd.show_prs(B, 5)
    assert "B=80 A=10" in capsys.readouterr().out


def test_with_every_request_on_one_model_the_other_keys_are_unchanged_and_models_has_one_entry_per_kind_and_agent(
        tmp_path):
    write(tmp_path, "proj/s1.jsonl", [rec(T0, "m1", cw=1000, inp=5, out=50, ttl="1h")])
    write(tmp_path, "proj/s1/subagents/agent-a1.jsonl", [rec(T0 + 5, "a1", cw=2000, inp=7, out=70, agent="sohot-fix")])
    A = flow(tmp_path)
    assert len(A["models"]) == 2 and {m["model"] for m in A["models"]} == {"claude-test"}
    old = {k: v for k, v in A.items() if k != "models"}
    old["prs"] = [{k: v for k, v in p.items() if k != "models"} for p in old["prs"]]
    assert old == EXPECTED
