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


def test_a_level_whose_requests_all_fail_serves_nothing_per_hour():
    """A dead server answered 299 refusals in no time and read 1.6M/h. #666."""
    def post(payload):
        raise ConnectionError("refused")
    got = throughput.sweep("eval-7b", ["t"] * 4, levels=(1,), post=post)
    assert got[0]["errors"] == 4 and got[0]["per_hour"] == 0.0


def test_only_answered_requests_count_toward_the_rate():
    clock, calls = Clock(), []

    def post(payload):
        calls.append(1)
        clock.now += 1.0
        if len(calls) % 2:
            raise RuntimeError("HTTP 500")
        return {"usage": {"completion_tokens": 1}}
    got = throughput.sweep("eval-7b", ["t"] * 4, levels=(1,), post=post, clock=clock)
    assert got[0]["errors"] == 2 and got[0]["wall_s"] == 4.0
    assert got[0]["per_hour"] == 1800.0


def test_a_platform_with_no_load_average_records_none(monkeypatch):
    monkeypatch.setattr(throughput, "sys", __import__("types").SimpleNamespace(platform="win32"))
    got = throughput.sweep("eval-7b", ["t"], levels=(1,), post=lambda p: _reply("x"))
    assert got[0]["load_avg"] == [None, None]


def _code_case(cid="add", checks=("add(1, 2) == 3",), preamble="", prompt="Write add(a, b)."):
    from evals.core import Case
    return Case(id=cid, modality="code", prompt=prompt, context="",
                assertions={"checks": list(checks)}, preamble=preamble)


def test_code_cases_become_the_requests_the_code_lane_sends():
    from harness import completion
    got = throughput.code_requests([_code_case()])
    assert got[0]["messages"] == [
        {"role": "system", "content": completion.SYSTEM["code"]},
        {"role": "user", "content": completion.user_message("Write add(a, b).")}]
    assert got[0]["temperature"] == completion.DEFAULT_TEMPERATURE
    assert "chat_template_kwargs" not in got[0]
    assert got[0]["_id"] == "add"


def test_a_request_keeps_its_own_temperature_and_its_private_keys_are_not_sent():
    seen = []
    req = throughput.code_requests([_code_case()])[0]
    throughput.sweep("ornith", [req], levels=(1,), max_tokens=4000,
                     post=lambda p: seen.append(p) or _reply("def add(a, b): return a + b"))
    assert seen[-1]["temperature"] == 0.2 and seen[-1]["max_tokens"] == 4000
    assert not [k for k in seen[-1] if k.startswith("_")]


def test_each_level_runs_the_code_checks_and_records_each_case_outcome():
    reqs = throughput.code_requests([_code_case("good", prompt="good"), _code_case("bad", prompt="bad")])

    def post(p):
        return _reply("```python\ndef add(a, b):\n    return a + b\n```"
                      if p["messages"][-1]["content"] == "good" else "def add(a, b):\n    return a - b")
    got = throughput.sweep("ornith", reqs, levels=(1,), post=post)
    assert got[0]["code_checked"] == 2 and got[0]["code_passed"] == 1
    assert got[0]["outcomes"] == {"good": True, "bad": False}


def test_a_failed_code_request_is_a_failed_case_not_a_missing_one():
    def post(p):
        raise RuntimeError("HTTP 500")
    got = throughput.sweep("ornith", throughput.code_requests([_code_case()]), levels=(1,), post=post)
    assert got[0]["code_checked"] == 1 and got[0]["code_passed"] == 0
    assert got[0]["outcomes"] == {"add": False}


def test_spread_takes_evenly_spaced_items_in_order():
    assert throughput.spread(list(range(10)), 3) == [0, 3, 6]
    assert throughput.spread([1, 2], 5) == [1, 2]
    assert throughput.spread([], 2) == []


def test_throughput_takes_a_code_split_in_place_of_texts():
    a = cli.build_parser().parse_args(
        ["throughput", "--model", "llamacpp:x", "--code", "holdout"])
    assert a.code == "holdout" and a.texts is None and a.claims is None


def test_code_cases_are_one_side_of_the_code_split(tmp_path):
    from harness import holdout
    for i in range(8):
        (tmp_path / f"c{i}.yaml").write_text(
            f"id: c{i}\nmodality: code\nprompt: Write f{i}.\nassert:\n  checks:\n    - \"f{i}() == {i}\"\n",
            encoding="utf-8")
    split = holdout.for_lane("code", tmp_path)
    got = throughput.code_cases("holdout", tmp_path)
    assert [c.id for c in got] == sorted(split.holdout) and got
    assert {c.id for c in throughput.code_cases("dev", tmp_path)} == set(split.dev)


def test_a_thinking_reply_records_its_first_token_of_any_kind_beside_the_first_answer_token():
    def post(p):
        return {**_reply("x"), "_ttft_s": 3.0, "_first_s": 0.1}
    got = throughput.sweep("ornith", ["t"] * 2, levels=(1,), post=post)
    assert got[0]["ttft_p50_s"] == 3.0 and got[0]["first_token_p50_s"] == 0.1


def test_the_streamed_post_reports_the_earlier_of_reasoning_and_content():
    assert throughput.first_token({"ttft_s": 3.4, "first_reasoning_s": 0.09}) == 0.09
    assert throughput.first_token({"ttft_s": 0.5, "first_reasoning_s": None}) == 0.5
    assert throughput.first_token({}) is None


def test_throughput_passes_its_request_timeout_to_the_sweep(monkeypatch, tmp_path):
    seen = {}
    level = {"concurrency": 1, "per_hour": 1.0, "p50_s": 1.0, "p95_s": 1.0, "errors": 0,
             "completion_tokens": 1}
    monkeypatch.setattr(throughput, "sweep", lambda *a, **k: seen.update(k) or [level])
    texts = tmp_path / "t.jsonl"
    texts.write_text('{"text": "t"}\n', encoding="utf-8")
    a = cli.build_parser().parse_args(
        ["throughput", "--model", "eval-7b", "--texts", str(texts), "--timeout", "900", "--n", "1"])
    a.func(a)
    assert seen["timeout"] == 900.0
