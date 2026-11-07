"""A reply cut at the reply budget inside a tool call is token_budget_exhausted, and a failed episode keeps its steps. #1547."""
from __future__ import annotations

import json
import threading

import pytest

from evals import run
from evals.core import summarize
from evals.runners import repo_repair
from evals.runners.agent import AgentRunner
from harness import completion, reasons, runs
from tests.test_agent_lane import Fake, Handler, case

#: llama-server's body for run 696's agent-refactor-synth-0326 step 9, verbatim.
CUT = ('{"error":{"code":500,"message":"Failed to parse tool call arguments as JSON: [json.exception.parse_error.101] '
       'parse error at line 1, column 16: syntax error while parsing object - unexpected end of input; expected \'}\'",'
       '"type":"server_error"}}')
MALFORMED = ('{"error":{"code":500,"message":"Failed to parse tool call arguments as JSON: [json.exception.parse_error.101] '
             'parse error at line 1, column 9: syntax error while parsing value - invalid literal; last read: \'{\\"a\\": x\'",'
             '"type":"server_error"}}')


class Erring(Handler):
    def do_POST(self):
        turn = self.server.script[0] if self.server.script else {}
        if "status" not in turn:
            return super().do_POST()
        self.rfile.read(int(self.headers["Content-Length"]))
        self.server.script.pop(0)
        body = turn["body"].encode()
        self.send_response(turn["status"])
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def serve():
    servers = []

    def start(script):
        s = Fake(script)
        s.RequestHandlerClass = Erring
        threading.Thread(target=s.serve_forever, daemon=True).start()
        servers.append(s)
        return s
    yield start
    for s in servers:
        s.shutdown()


TWO_STEPS = [{"calls": [("list_dir", {})]}, {"calls": [("read_file", {"path": "config/production.ini"})]}]


def test_a_reply_cut_inside_a_tool_call_is_the_reply_budget_not_a_crash(serve):
    s = serve(TWO_STEPS + [{"status": 500, "body": CUT}])
    r = AgentRunner(s.url, "fake", max_tokens=8000).run(case("agent-read-service-port"))
    assert not r.passed and "step 3" in r.detail
    assert r.failure_class == reasons.TOKEN_BUDGET_EXHAUSTED
    assert r.limit == "max_tokens.agent>8000"


def test_a_failed_episode_keeps_its_steps_metrics_and_transcript(serve):
    s = serve(TWO_STEPS + [{"status": 500, "body": CUT}])
    r = AgentRunner(s.url, "fake", served_ctx=262144).run(case("agent-read-service-port"))
    m = r.metrics
    assert m["agent_steps"] == 3 and m["agent_tool_calls"] == 2 and m["agent_valid_call_rate"] == 1.0
    assert m["prompt_tokens"] == 200 and m["completion_tokens"] == 20 + completion.budget("agent")
    assert m["agent_ctx"] == 262144 and m["agent_model_s"] > 0 and r.ttft_s is not None
    record = json.loads(r.output)
    assert record["stopped"] == "error" and record["steps"][-1]["cut"] is True
    assert "unexpected end of input" in record["error"]


def test_one_cut_row_does_not_make_the_candidates_metrics_partial(serve):
    s = serve(TWO_STEPS + [{"status": 500, "body": CUT}, {"calls": [("list_dir", {})]},
                           {"content": "Production listens on 8443."}])
    runner = AgentRunner(s.url, "fake")
    rows = [runner.run(case("agent-read-service-port")), runner.run(case("agent-read-service-port"))]
    assert [x.passed for x in rows] == [False, True]
    got = summarize(rows)["fake"]["metric_n"]
    assert {got[k] for k in ("agent_model_s", "agent_steps", "agent_wall_s", "completion_tokens",
                             "prompt_tokens", "agent_ttft_sum_s")} == {2}


def test_the_failed_rows_transcript_is_written_to_the_run_dir(serve, tmp_path):
    s = serve(TWO_STEPS + [{"status": 500, "body": CUT}])
    runner = AgentRunner(s.url, "fake")
    c = case("agent-read-service-port")
    r = run._one_case(runner, c, None, None, None, None, None, tmp_path)
    assert r.artifact_path and json.loads(open(r.artifact_path, encoding="utf-8").read())["steps"]


def test_a_malformed_call_the_budget_did_not_cut_is_not_put_down_to_the_budget(serve):
    s = serve(TWO_STEPS + [{"status": 500, "body": MALFORMED}])
    r = AgentRunner(s.url, "fake").run(case("agent-read-service-port"))
    assert r.failure_class == reasons.CRASHED and not r.limit
    assert r.metrics["agent_steps"] == 3 and "cut" not in json.loads(r.output)["steps"][-1]


def test_a_cut_call_reported_short_of_the_budget_is_not_the_budget():
    runner = AgentRunner("http://x", "fake", max_tokens=8000)
    exc = completion.CompletionError(f"gateway returned HTTP 500: {CUT}", usage={"completion_tokens": 120})
    assert not runner._cut_in_call(exc)
    exc.usage = {"completion_tokens": 8000}
    assert runner._cut_in_call(exc)


def test_the_repair_harness_names_its_own_budget_and_none_when_it_shrank_the_ask():
    def chat(*a, **k):
        raise completion.CompletionError(f"gateway returned HTTP 500: {CUT}")
    runner = repo_repair.RepoRepairRunner("http://x", "fake", chat=chat, max_tokens=32768)
    runner._budget = 32768
    with pytest.raises(completion.CompletionError) as got:
        runner._step(0, [], [], 10.0)
    assert got.value.failure_class == reasons.TOKEN_BUDGET_EXHAUSTED and got.value.limit == ("max_tokens.repo", 32768)
    runner.max_tokens = 1000
    with pytest.raises(completion.CompletionError) as got:
        runner._step(0, [], [], 10.0)
    assert got.value.failure_class == "" and not got.value.limit


def _row(case_id, detail, cls="crashed"):
    return {"case_id": case_id, "candidate": "llamacpp:m", "passed": False, "seconds": 1.0,
            "detail": detail, "failure_class": cls, "metrics": {"agent_ctx": 262144}}


def test_a_stored_row_crashed_on_a_cut_call_is_reclassed_from_its_detail(store_run, store_conn):
    cut = f"step 9: gateway returned HTTP 500: {CUT}"
    rid = store_run("agent", "agent", rows=[_row("a", cut), _row("b", f"step 2: gateway returned HTTP 500: {MALFORMED}"),
                                           _row("c", "step 1: gateway returned HTTP 502: bad gateway")],
                    receipt={"max_tokens": 32000}, conn=store_conn)
    other = store_run("code", "code", rows=[_row("d", cut)], conn=store_conn)
    assert runs.class_cut_calls(store_conn) == 1
    got = {r["case_id"]: (r["failure_class"], r["limit"]) for r in runs.rows(store_conn, rid)}
    assert got == {"a": (reasons.TOKEN_BUDGET_EXHAUSTED, "max_tokens.agent>32000"),
                   "b": (reasons.CRASHED, ""), "c": (reasons.CRASHED, "")}
    assert [r["failure_class"] for r in runs.rows(store_conn, other)] == [reasons.CRASHED]
    assert runs.class_cut_calls(store_conn) == 0
