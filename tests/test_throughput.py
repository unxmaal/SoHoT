"""How much faster a server goes with several requests in flight. #310."""
import threading
import time

from harness import cli, exclusive, throughput


class Fake:
    """A server that records how many requests it held at once."""

    def __init__(self, fail_every=0):
        self.now = self.peak = self.calls = 0
        self.lock = threading.Lock()
        self.fail_every = fail_every

    def post(self, payload):
        with self.lock:
            self.now += 1
            self.calls += 1
            self.peak = max(self.peak, self.now)
            n = self.calls
        time.sleep(0.02)
        with self.lock:
            self.now -= 1
        if self.fail_every and n % self.fail_every == 0:
            raise RuntimeError("HTTP 500")
        return {"usage": {"completion_tokens": 100}}


def test_each_level_really_has_that_many_in_flight():
    for level in (1, 2, 4):
        fake = Fake()
        throughput.sweep("eval-7b", ["t"] * 8, levels=(level,), post=fake.post)
        assert fake.peak == level


def test_the_report_has_rate_latency_and_tokens():
    got = throughput.sweep("eval-7b", ["t"] * 8, levels=(1, 4),
                           post=Fake().post)
    assert [r["concurrency"] for r in got] == [1, 4]
    for r in got:
        assert r["n"] == 8 and r["errors"] == 0
        assert r["per_hour"] > 0 and r["p50_s"] > 0 and r["p95_s"] >= r["p50_s"]
        assert r["completion_tokens"] == 800


def test_a_failed_request_is_counted_not_hidden():
    got = throughput.sweep("eval-7b", ["t"] * 8, levels=(2,),
                           post=Fake(fail_every=4).post)
    assert got[0]["errors"] == 2
    assert got[0]["n"] == 8


def test_the_request_carries_the_text_and_the_output_budget():
    seen = []
    throughput.sweep("eval-7b", ["hello"], levels=(1,), max_tokens=300,
                     post=lambda p: seen.append(p) or {"usage": {}})
    assert seen[0]["model"] == "eval-7b" and seen[0]["max_tokens"] == 300
    assert "hello" in seen[0]["messages"][-1]["content"]


def test_the_sweep_holds_the_machine_lock():
    held = []
    throughput.sweep("eval-7b", ["t"], levels=(1,),
                     post=lambda p: held.append(
                         __import__("os").environ.get(exclusive.HELD_ENV)) or {})
    assert held and set(held) == {"1"}


def test_lh_throughput_is_a_command():
    a = cli.build_parser().parse_args(
        ["throughput", "--model", "eval-7b", "--texts", "x.jsonl",
         "--levels", "1,2,4"])
    assert a.func is cli.cmd_throughput and a.levels == "1,2,4"


class Clock:
    """Time that moves only when a request says so."""

    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def test_a_cold_load_is_not_timed_into_the_first_level():
    """The first request after a model is evicted pays for the load. Timed,
    it made a 1.9x speedup read as 6.8x on the Studio. #333."""
    clock, calls = Clock(), []

    def post(payload):
        calls.append(payload)
        clock.now += 18.0 if len(calls) == 1 else 0.5
        return {"usage": {"completion_tokens": 1}}
    got = throughput.sweep("eval-7b", ["t"] * 4, levels=(1,), post=post,
                           clock=clock)
    assert len(calls) == 5 and got[0]["n"] == 4
    assert got[0]["p95_s"] == 0.5
    assert got[0]["warmup_s"] == 18.0 and got[0]["warmup_ok"]


def test_a_warm_server_reads_the_same_with_or_without_the_warmup():
    """Negative control: on a steady server the warm-up costs what any
    request does. Exact, because the clock is ours (#349)."""
    clock = Clock()

    def post(payload):
        clock.now += 0.5
        return {"usage": {"completion_tokens": 1}}
    got = throughput.sweep("eval-7b", ["t"] * 4, levels=(1,), post=post,
                           clock=clock)
    assert got[0]["warmup_s"] == got[0]["p50_s"] == 0.5


SCHEMA = {"type": "object", "properties": {"c": {"type": "array"}}, "required": ["c"],
          "additionalProperties": False}
SHAPED = {"type": "json_schema", "json_schema": {"name": "claims", "strict": True, "schema": SCHEMA}}


def _reply(content, prompt=600, completion=80):
    return {"choices": [{"message": {"content": content}}],
            "usage": {"prompt_tokens": prompt, "completion_tokens": completion}}


def test_a_chat_request_is_sent_as_given_with_the_budget_and_temperature_zero():
    seen = []
    req = {"messages": [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}],
           "response_format": SHAPED}
    throughput.sweep("eval-7b", [req], levels=(1,), max_tokens=400,
                     post=lambda p: seen.append(p) or _reply('{"c": []}'))
    assert seen[-1]["messages"] == req["messages"]
    assert seen[-1]["response_format"] == SHAPED
    assert seen[-1]["max_tokens"] == 400 and seen[-1]["temperature"] == 0


def test_each_level_counts_the_replies_that_validate_against_their_schema():
    replies = iter(['{"c": []}', '{"c": []}', 'not json', '{"x": 1}', '{"c": [1]}'])
    req = {"messages": [{"role": "user", "content": "u"}], "response_format": SHAPED}
    got = throughput.sweep("eval-7b", [req] * 4, levels=(1,),
                           post=lambda p: _reply(next(replies)))
    assert got[0]["schema_checked"] == 4 and got[0]["schema_valid"] == 2


def test_a_request_with_no_schema_is_not_counted_as_checked():
    got = throughput.sweep("eval-7b", ["t"] * 3, levels=(1,), post=lambda p: _reply("x"))
    assert got[0]["schema_checked"] == 0 and got[0]["schema_valid"] == 0


def test_a_level_records_its_prompt_tokens_and_the_machine_load_beside_it():
    loads = iter([(3.0, 2.0, 1.0), (5.0, 2.0, 1.0)])
    got = throughput.sweep("eval-7b", ["t"] * 2, levels=(1,), post=lambda p: _reply("x"),
                           load=lambda: next(loads))
    assert got[0]["prompt_tokens"] == 1200
    assert got[0]["load_avg"] == [3.0, 5.0]


def test_claims_export_rows_become_the_requests_the_claims_lane_sends():
    from harness import completion
    from harness.checks import claims
    row = {"id": "x1", "system": "SYS", "transcript": "T", "schema": SCHEMA, "reviews": []}
    got = throughput.claims_requests([row])
    assert got == [{"messages": [{"role": "system", "content": "SYS"},
                                 {"role": "user", "content": completion.user_message("T")}],
                    "response_format": claims.response_format(SCHEMA)}]


def test_throughput_takes_claims_exports_in_place_of_texts():
    a = cli.build_parser().parse_args(
        ["throughput", "--model", "eval-7b", "--claims", "a.jsonl", "--claims", "b.jsonl"])
    assert a.claims == ["a.jsonl", "b.jsonl"] and a.texts is None


def test_throughput_refuses_neither_texts_nor_claims(capsys):
    a = cli.build_parser().parse_args(["throughput", "--model", "eval-7b"])
    assert a.func(a) != 0
