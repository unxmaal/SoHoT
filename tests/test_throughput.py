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


def test_a_cold_load_is_not_timed_into_the_first_level():
    """The first request after a model is evicted pays for the load. Timed,
    it made a 1.9x speedup read as 6.8x on the Studio. #333."""
    calls = []

    def post(payload):
        calls.append(payload)
        time.sleep(0.3 if len(calls) == 1 else 0.01)
        return {"usage": {"completion_tokens": 1}}
    got = throughput.sweep("eval-7b", ["t"] * 4, levels=(1,), post=post)
    assert len(calls) == 5 and got[0]["n"] == 4
    assert got[0]["p95_s"] < 0.2
    assert got[0]["warmup_s"] >= 0.3 and got[0]["warmup_ok"]


def test_a_warm_server_reads_the_same_with_or_without_the_warmup():
    """Negative control: a steady server's warm-up costs what any request
    does."""
    got = throughput.sweep("eval-7b", ["t"] * 4, levels=(1,), post=Fake().post)
    assert abs(got[0]["warmup_s"] - got[0]["p50_s"]) < 0.05
