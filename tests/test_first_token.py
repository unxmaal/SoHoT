"""Time to first token for every text candidate. #468."""
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from evals.core import Case, Result, first_token, summarize
from evals.runners import claude_code as CC
from evals.runners.text import CompletionRunner
from harness import completion, publish, report, runs, throughput
from harness import memory_store as ms

THINK_AT, ANSWER_AT = 0.2, 0.5
PIECES = ["def add(a, b):", "\n    return", " a + b\n"]
USAGE = {"prompt_tokens": 40, "completion_tokens": 12, "total_tokens": 52}
TIMINGS = {"prompt_n": 40, "prompt_ms": 123.0, "prompt_per_second": 325.2}


class Fake(ThreadingHTTPServer):
    """A chat server with known delays: reasoning at THINK_AT, answer at ANSWER_AT."""
    daemon_threads = True
    ignore_stream = False
    refuse = ""
    usage_in_stream = True
    drip_s = 0.0
    logprobs = None

    def __init__(self):
        super().__init__(("127.0.0.1", 0), Handler)
        self.seen = []

    @property
    def url(self):
        return f"http://127.0.0.1:{self.server_address[1]}"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        data = body.encode() if isinstance(body, str) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        s = self.server
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        s.seen.append(payload)
        if s.refuse and s.refuse in payload:
            return self._send(400, f"{s.refuse} is not supported", "text/plain")
        if not payload.get("stream") or s.ignore_stream:
            choice = {"message": {"role": "assistant", "content": "".join(PIECES)},
                      "finish_reason": "stop"}
            if s.logprobs:
                choice["logprobs"] = {"content": s.logprobs}
            return self._send(200, {"choices": [choice], "usage": USAGE,
                                    "timings": TIMINGS})
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        start = time.perf_counter()

        def emit(chunk, at=None):
            if at is not None:
                time.sleep(max(0.0, at - (time.perf_counter() - start)))
            self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
            self.wfile.flush()

        def delta(d, **extra):
            return {"choices": [{"index": 0, "delta": d, **extra}]}
        emit(delta({"role": "assistant"}))
        emit(delta({"reasoning_content": "thinking"}), THINK_AT)
        for i, piece in enumerate(PIECES):
            lp = ({"logprobs": {"content": [s.logprobs[i]]}}
                  if s.logprobs and i < len(s.logprobs) else {})
            emit(delta({"content": piece}, **lp), ANSWER_AT + i * s.drip_s)
        last = delta({}, finish_reason="stop")
        last["timings"] = TIMINGS
        emit(last)
        if s.usage_in_stream and "stream_options" in payload:
            emit({"choices": [], "usage": USAGE})
        self.wfile.write(b"data: [DONE]\n\n")


@pytest.fixture
def fake():
    srv = Fake()
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield srv
    srv.shutdown()
    srv.server_close()


def ask(srv, stream=True, **kw):
    return completion.complete_full("write add", "m", srv.url, modality="code",
                                    stream=stream, **kw)


def test_streaming_pins_first_reasoning_and_first_content(fake):
    got = ask(fake)
    t = got.timing
    assert THINK_AT <= t["first_reasoning_s"] < ANSWER_AT <= t["ttft_s"] < 5
    assert t["prefill_s"] == pytest.approx(0.123)
    assert fake.seen[0]["stream"] is True
    assert fake.seen[0]["stream_options"] == {"include_usage": True}


def test_streaming_scores_exactly_what_the_whole_answer_scored(fake):
    """Same assembled text, same usage: streaming changes timing, never content."""
    streamed, whole = ask(fake), ask(fake, stream=False)
    assert streamed.text == whole.text == "".join(PIECES)
    assert streamed.usage == whole.usage == USAGE
    assert completion.artifact(streamed.text, "code") == completion.artifact(whole.text, "code")
    assert whole.timing["ttft_s"] is None and whole.timing["first_reasoning_s"] is None


def test_streamed_logprobs_equal_the_whole_ones(fake):
    fake.logprobs = [{"token": p, "logprob": -0.1 * i, "top_logprobs": []}
                     for i, p in enumerate(PIECES)]
    streamed = ask(fake, top_logprobs=5)
    whole = ask(fake, stream=False, top_logprobs=5)
    assert streamed.tokens == whole.tokens == fake.logprobs


def test_a_server_that_answers_whole_leaves_ttft_unknown_not_the_total(fake):
    fake.ignore_stream = True
    got = ask(fake)
    assert got.text == "".join(PIECES) and got.usage == USAGE
    assert got.timing["ttft_s"] is None
    assert got.timing["prefill_s"] == pytest.approx(0.123)


def test_a_server_that_refuses_stream_options_is_asked_without_them(fake):
    fake.refuse = "stream_options"
    got = ask(fake)
    assert got.text == "".join(PIECES) and got.timing["ttft_s"] >= ANSWER_AT
    assert got.usage == {}, "no usage block is an absence, never an error"
    assert "stream_options" not in fake.seen[-1] and fake.seen[-1]["stream"]


def test_a_server_that_refuses_streaming_falls_back_to_a_whole_answer(fake):
    fake.refuse = "stream"
    got = ask(fake)
    assert got.text == "".join(PIECES) and got.timing["ttft_s"] is None
    assert "stream" not in fake.seen[-1]


def test_a_slow_writer_still_times_out_on_the_total(fake):
    fake.drip_s = 0.3
    with pytest.raises(completion.CompletionError) as got:
        ask(fake, timeout=0.6)
    assert got.value.failure_class == "timeout"


def test_the_first_case_without_a_warm_up_is_cold_and_the_rest_warm(fake):
    case = Case(id="add", modality="code", prompt="Write add(a, b).",
                assertions={"checks": ["add(2, 3) == 5"]})
    r = CompletionRunner(fake.url, "m")
    first, second = r.run(case), r.run(case)
    assert first.passed and second.passed
    assert first.cold is True and second.cold is False
    assert first.ttft_s >= ANSWER_AT and first.first_reasoning_s >= THINK_AT
    assert first.prefill_s == pytest.approx(0.123)
    assert first.metrics["completion_tokens"] == USAGE["completion_tokens"]
    warmed = CompletionRunner(fake.url, "m")
    warmed.warm()
    assert warmed.run(case).cold is False


def _row(i, ttft, cold=False):
    return Result(f"c{i}", "m", True, 1.0, 0, "", ttft_s=ttft, cold=cold,
                  first_reasoning_s=None if ttft is None else ttft / 2,
                  prefill_s=None)


def test_ttft_summary_is_over_warm_rows_and_skips_the_unknown():
    rows = [_row(0, 9.0, cold=True)] + [_row(i, t) for i, t in
                                        enumerate([0.1, 0.2, 0.3, 0.4, None], 1)]
    got = first_token(rows)
    assert got["ttft_median_s"] == 0.25 and got["ttft_p95_s"] == 0.4
    assert got["ttft_n"] == 4 and got["ttft_cold_s"] == 9.0
    assert got["first_reasoning_median_s"] == 0.125
    assert got["prefill_median_s"] is None
    assert summarize(rows)["m"]["ttft_median_s"] == 0.25
    assert first_token([_row(0, None)])["ttft_median_s"] is None


def _receipt(rows):
    return {"generated": "2026-10-06T10:00:00",
            "receipt": {"modality": "code", "tier": "measure"},
            "environment": {"hw_model": "Mac17,15", "os": "macOS-27", "arch": "arm64"},
            "rows": rows}


def test_the_timings_round_trip_through_the_results_table():
    conn = ms.connect()
    rows = [{"case_id": "a", "candidate": "m", "passed": True, "seconds": 2.0,
             "ttft_s": 0.5, "first_reasoning_s": 0.2, "prefill_s": 0.12,
             "cold": True},
            {"case_id": "b", "candidate": "m", "passed": True, "seconds": 1.0,
             "ttft_s": 0.3, "first_reasoning_s": None, "prefill_s": None,
             "cold": False},
            {"case_id": "c", "candidate": "m", "passed": True, "seconds": 1.0}]
    rid = runs.record(conn, "runs/ttft", _receipt(rows))
    got = runs.rows(conn, rid)
    assert [(r["ttft_s"], r["first_reasoning_s"], r["prefill_s"], r["cold"])
            for r in got] == [(0.5, 0.2, 0.12, True), (0.3, None, None, False),
                              (None, None, None, None)]
    assert runs.summarize(got)["m"]["ttft_median_s"] == 0.3
    conn.close()


def test_an_older_store_gains_the_columns():
    import sqlite3
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE results (id INTEGER PRIMARY KEY, seconds REAL)")
    ms._add_first_token(conn)
    ms._add_first_token(conn)
    assert {"ttft_s", "first_reasoning_s", "prefill_s", "cold"} <= ms._columns(conn, "results")


def _lane(**kw):
    base = {"lane": "code", "wanted": True, "serves": "m", "adopted": False,
            "adopted_how": "", "unverified": False, "stale": False,
            "pass_rate": 1.0, "median_s": 2.0, "metrics": {}, "age_days": 0.1}
    return {**base, **kw}


def test_the_report_puts_ttft_beside_the_median():
    html = report._lane_rows([_lane(ttft_median_s=0.31, ttft_p95_s=0.52),
                              _lane(lane="image", ttft_median_s=None, ttft_p95_s=None)], {})
    assert "0.31s / 0.52s" in html and "--" in html


def test_the_published_export_carries_ttft_as_plain_numbers():
    row = publish._row("m", {"pass_rate": 1.0, "median_s": 2.0,
                             "ttft_median_s": 0.3123, "ttft_p95_s": "x"})
    assert row["ttft_median_s"] == 0.312 and row["ttft_p95_s"] is None
    assert "0.31s" in publish._ttft_cell(row)


def test_throughput_reports_ttft_per_level():
    def post(payload):
        return {"usage": {"completion_tokens": 5}, "_ttft_s": 0.2}
    got = throughput.sweep("m", ["a", "b"], levels=(1,), post=post)
    assert got[0]["ttft_p50_s"] == 0.2 and got[0]["ttft_p95_s"] == 0.2


# --- claude -p -----------------------------------------------------------------

def _events(text="def add(a, b): return a + b"):
    ev = [{"type": "system", "subtype": "init"},
          {"type": "stream_event", "event": {"type": "message_start"}},
          {"type": "stream_event", "event": {"type": "content_block_delta",
                                             "delta": {"type": "thinking_delta", "thinking": ""}}},
          {"type": "stream_event", "event": {"type": "content_block_delta",
                                             "delta": {"type": "text_delta", "text": ""}}},
          {"type": "stream_event", "event": {"type": "content_block_delta",
                                             "delta": {"type": "text_delta", "text": "def"}}},
          {"type": "result", "subtype": "success", "is_error": False,
           "result": text, "usage": {"output_tokens": 9}}]
    return [json.dumps(e) + "\n" for e in ev]


def test_claude_code_ttft_is_the_first_text_delta():
    lines = list(zip([0.1, 0.2, 1.0, 1.5, 2.0, 2.5], _events()))
    proc = CC.Streamed(0, lines, "")
    r = CC.ClaudeCodeRunner("m", execute=lambda argv, **kw: proc)
    text, _ = r.generate(Case(id="add", modality="code", prompt="p"))
    assert text.startswith("def add")
    assert r.timing() == {"ttft_s": 2.0, "first_reasoning_s": 1.0,
                          "prefill_s": None, "cold": False}
    assert r.extra_metrics()["completion_tokens"] == 9


def test_claude_code_without_line_times_leaves_ttft_unknown():
    class Proc:
        returncode, stderr = 0, ""
        stdout = json.dumps({"result": "ok"})
    r = CC.ClaudeCodeRunner("m", execute=lambda argv, **kw: Proc())
    r.generate(Case(id="x", modality="extract", prompt="p"))
    assert r.timing()["ttft_s"] is None


def test_claude_code_asks_for_partial_messages():
    argv = CC.ClaudeCodeRunner("m").argv(Case(id="x", modality="code", prompt="p"))
    assert argv[argv.index("--output-format") + 1] == "stream-json"
    assert "--include-partial-messages" in argv and "--verbose" in argv
    assert argv[-2:] == ["--tools", ""]


def test_stream_run_times_each_line_as_it_arrives(tmp_path):
    script = ("import sys, time\n"
              "sys.stdout.write(sys.stdin.read().upper() + '\\n'); sys.stdout.flush()\n"
              "time.sleep(0.4)\n"
              "print('late', flush=True)\n")
    got = CC.stream_run([sys.executable, "-c", script], cwd=str(tmp_path),
                        input="café", timeout=30)
    assert got.returncode == 0 and got.stdout == "CAFÉ\nlate\n"
    (t0, _), (t1, _) = got.line_times
    assert t1 - t0 >= 0.3


def test_stream_run_times_out(tmp_path):
    import subprocess
    with pytest.raises(subprocess.TimeoutExpired):
        CC.stream_run([sys.executable, "-c", "import time; time.sleep(30)"],
                      cwd=str(tmp_path), input="", timeout=0.5)
