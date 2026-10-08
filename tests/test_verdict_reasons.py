"""Why a verdict happened is a column the failing code writes. #408, #406.

Every fixture here is built with no model, no server and no network.
"""
import argparse
import ast
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
import respx

from evals import environment
from evals import run as R
from evals.core import Case, Result, summarize
from evals.runners.base import BaseRunner, RunnerError
from evals.runners.process import ProcessRunner
from evals.runners.text import CompletionRunner
from harness import completion, engines, reasons, screen
from harness import memory_store as ms

ROOT = Path(__file__).resolve().parents[1]
GW = "http://gw.test"
URL = f"{GW}/v1/chat/completions"
CASE = Case("chunk-bytes", "extract", "write it")

#: The table the screen must apply, written out rather than read from CLASSES.
EXPECTED = {
    reasons.SERVER_DEAD: ("queued", "harness"),
    reasons.GPU_FAULT: ("declined", "machine"),
    reasons.REFUSED_BY_GATEWAY: ("queued", "harness"),
    reasons.HARNESS_ERROR: ("queued", "harness"),
    reasons.TIMEOUT: ("declined", "limit"),
    reasons.TOKEN_BUDGET_EXHAUSTED: ("declined", "limit"),
    reasons.LOAD_FAILED_RUNTIME: ("declined", "runtime"),
    reasons.LOAD_FAILED_LAYOUT: ("declined", "runtime"),
    reasons.BACKEND_FAULT: ("declined", "runtime"),
    reasons.MISSING_FILE_IN_SNAPSHOT: ("broken", "candidate"),
    reasons.CRASHED: ("broken", "candidate"),
    reasons.CONTENT_FAILED: ("broken", "candidate"),
    reasons.RUNAWAY: ("broken", "candidate"),
}


class Fake(BaseRunner):
    """A runner that fails with a class and a sentence nothing can parse."""

    def __init__(self, cls, limit=""):
        self.candidate = self.spec = "org/x"
        self.cls, self.limit = cls, limit

    def generate(self, case):
        raise RunnerError("zq-opaque-7", failure_class=self.cls, limit=self.limit)


def _screen(rows, cand="org/x", facts=None):
    return screen.outcome(0, summarize(rows), candidate=cand, facts=facts)


# --- every class maps to its outcome with no substring downstream -----------

def test_every_class_has_an_expected_verdict():
    assert set(EXPECTED) == set(reasons.CLASSES)


@pytest.mark.parametrize("cls", sorted(EXPECTED))
def test_a_runner_class_decides_the_screen_verdict(cls):
    v = _screen([Fake(cls, "timeout_s>180").run(CASE)],
                facts={"memory_gb": 96})
    assert (v.outcome, v.reason, v.failure_class) == (*EXPECTED[cls], cls)
    assert v.reason in reasons.REASONS


def test_a_terminal_limit_or_runtime_verdict_says_what_reopens_it():
    assert _screen([Fake(reasons.TIMEOUT, "timeout_s>180").run(CASE)]).until \
        == "limit:timeout_s>180"
    assert _screen([Fake(reasons.LOAD_FAILED_RUNTIME).run(CASE)]).until \
        .startswith("version:mlx-lm>")
    gpu = _screen([Fake(reasons.GPU_FAULT).run(CASE)], facts={"memory_gb": 96})
    assert gpu.until == "memory_gb:>96"


def test_a_harness_class_outranks_a_content_failure_in_the_same_run():
    rows = [Fake(reasons.CONTENT_FAILED).run(CASE),
            Fake(reasons.REFUSED_BY_GATEWAY).run(CASE)]
    assert _screen(rows).outcome == "queued"


#: Files that decide from classes and must never read a phrase themselves.
#: The CLI's verbs, which live in harness/commands since #484.
CLI = ("harness/cli.py", *sorted(p.relative_to(ROOT).as_posix()
                                 for p in (ROOT / "harness" / "commands").glob("*.py")))
DECIDERS = ("harness/screen.py", *CLI, "harness/fetching.py",
            "harness/adopt.py", "evals/run.py")
PHRASES = (reasons._SERVER_DEAD + reasons._GPU_FAULT + reasons._GATEWAY
           + reasons._HARNESS + reasons._ABOUT_THE_SNAPSHOT
           + reasons._ARCHITECTURE_GAPS + reasons._LLAMACPP_LOAD_FAILED
           + reasons._DIFFUSERS_LAYOUT_GAPS + (reasons._LOAD_FAILED, "no measured size"))
OLD_NAMES = ("NOT_THE_CANDIDATE", "ARCHITECTURE_GAPS", "DIFFUSERS_LAYOUT_GAPS",
             "SERVER_DEAD", "ABOUT_THE_SNAPSHOT", "LLAMACPP_LOAD_FAILED",
             "LOAD_FAILED", "refused_by_harness", "is_architecture_gap",
             "load_failure", "until_for")


def phrase_uses(path, root=ROOT):
    """Phrase literals and phrase-list names in code; comments and
    docstrings are prose and excluded."""
    tree = ast.parse((root / path).read_text(encoding="utf-8"))
    # A phrase is READ when it is compared, listed or searched for; a writer
    # formatting its own message is where the text comes from, not a reader.
    read = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Compare):
            read += [n.left, *n.comparators]
        elif isinstance(n, (ast.Tuple, ast.List, ast.Set)):
            read += n.elts
        elif isinstance(n, ast.Call) and getattr(n.func, "attr", "") in (
                "startswith", "endswith", "find", "index", "count", "search",
                "match", "fullmatch"):
            read += n.args
    hits = []
    for n in read:
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            hits += [p for p in PHRASES if p in n.value.lower()]
    for n in ast.walk(tree):
        name = getattr(n, "id", None) or getattr(n, "attr", None)
        if isinstance(n, (ast.Name, ast.Attribute)) and name in OLD_NAMES:
            hits.append(name)
    return sorted(hits)


@pytest.mark.parametrize("path", DECIDERS)
def test_no_decider_reads_a_phrase(path):
    assert phrase_uses(path) == [], path


def test_the_phrase_guard_fires_on_a_phrase(tmp_path):
    """Red-proof: the guard sees a phrase literal and an old list name, and
    not a comment."""
    (tmp_path / "bad.py").write_text(
        '"""connection refused, in a docstring only"""\n'
        'x = "Generation thread died" in s\ny = screen.NOT_THE_CANDIDATE\n'
        'z = ("model type", "x")\nw = s.startswith("timed out after")\n'
        'raise SystemExit("nothing ran: no candidate matched any case")\n'
        '# connection refused, in a comment only\n', encoding="utf-8")
    assert phrase_uses("bad.py", tmp_path) == [
        "NOT_THE_CANDIDATE", "generation thread died", "model type"]


def _calls(path, name):
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    return [n for n in ast.walk(tree) if isinstance(n, ast.Call)
            and getattr(n.func, "attr", getattr(n.func, "id", "")) == name]


def test_upstream_text_is_classified_at_the_runner_boundary_and_one_stderr_read():
    assert len(_calls("evals/runners/base.py", "classify")) == 1
    assert sum(len(_calls(p, "classify")) for p in CLI) == 1
    assert _calls("harness/screen.py", "classify") == []


def test_decide_never_reads_its_condition_out_of_the_detail():
    tree = ast.parse((ROOT / "harness/memory_store/transitions.py").read_text(encoding="utf-8"))
    fn = next(n for n in tree.body
              if isinstance(n, ast.FunctionDef) and n.name == "decide")
    called = {getattr(c.func, "id", getattr(c.func, "attr", ""))
              for c in ast.walk(fn) if isinstance(c, ast.Call)}
    assert "until_for" not in called and "legacy_reason" not in called


def store_writes(path):
    """Calls that write a verdict: ms.decide/decide_or_skip, or bare inside
    memory_store. A **kw pass-through or a named reopen is exempt."""
    for name in ("decide", "decide_or_skip"):
        for call in _calls(path, name):
            owner = getattr(getattr(call.func, "value", None), "id", "")
            if isinstance(call.func, ast.Attribute) and owner != "ms":
                continue
            if isinstance(call.func, ast.Name) and not path.startswith("harness/memory_store/"):
                continue
            kws = {k.arg for k in call.keywords}
            if None in kws or "reopen" in kws:
                continue
            yield call, kws


@pytest.mark.parametrize("path", sorted(
    p.relative_to(ROOT).as_posix() for p in (ROOT / "harness").rglob("*.py")))
def test_every_production_verdict_says_why(path):
    for call, kws in store_writes(path):
        assert "reason" in kws, f"{path}:{call.lineno} without reason="


def test_the_writer_guard_sees_the_writers():
    """Red-proof: the guard is not vacuous."""
    assert sum(len(list(store_writes(p))) for p in CLI) >= 10
    assert len(list(store_writes("harness/fetching.py"))) >= 5


def test_decide_refuses_a_reason_outside_the_vocabulary(tmp_path):
    conn = ms.connect(tmp_path / "d.db")
    ms.record(conn, ms.Seen(name="org/x", source="t"))
    with pytest.raises(ValueError):
        ms.decide(conn, "org/x", "broken", tier=ms.SCREEN, reason="vibes")
    vid = ms.decide(conn, "org/x", "broken", tier=ms.SCREEN, reason="candidate")
    assert conn.execute("SELECT reason FROM verdicts WHERE id = ?",
                        (vid,)).fetchone()[0] == "candidate"
    ms.retract(conn, "org/x", "test")
    assert ms.latest(conn, "org/x")["outcome"] == "queued"
    assert conn.execute("SELECT reason FROM verdicts ORDER BY id DESC LIMIT 1"
                        ).fetchone()[0] == "reopened"
    conn.close()


# --- the overnight cases, as fixtures ----------------------------------------

def _reply(text, reasoning=None):
    msg = {"content": text}
    if reasoning:
        msg["reasoning_content"] = reasoning
    return httpx.Response(200, json={"choices": [{"message": msg}],
                                     "usage": {"completion_tokens": 3}},
                          request=httpx.Request("POST", URL))


@respx.mock
def test_generation_thread_died_is_the_harnesss_and_stops_the_loop():
    respx.post(URL).mock(return_value=httpx.Response(
        404, text='{"error": "generation thread died"}'))
    row = CompletionRunner(GW, "org/x").run(CASE)
    v = _screen([row])
    assert (v.outcome, v.reason, v.failure_class) == (
        "queued", "harness", reasons.SERVER_DEAD)
    assert v.failure_class in reasons.STOPS


def _process(stderr, rc=1):
    eng = engines.resolve("mflux:Qwen/Qwen-Image-Bench")
    return eng, SimpleNamespace(ok=rc == 0, returncode=rc, stderr=stderr,
                                peak_kb=0, seconds=1.0)


def test_a_metal_gpu_timeout_declines_the_candidate_that_caused_it(tmp_path, monkeypatch):
    eng, out = _process(
        "RuntimeError: [METAL] Command buffer execution failed: Caused GPU "
        "Timeout Error (00000002:kIOGPUCommandBufferCallbackErrorTimeout)")
    from harness import proc
    monkeypatch.setattr(proc, "run", lambda *a, **k: out)
    runner = ProcessRunner(eng, tmp_path)
    runner.spec = "mflux:Qwen/Qwen-Image-Bench"
    row = runner.run(Case("fox-snow", "image", "a fox"))
    v = screen.outcome(0, summarize([row]), candidate=runner.spec,
                       key=eng.name, facts={"memory_gb": 96})
    assert (v.outcome, v.reason, v.until) == ("declined", "machine", "memory_gb:>96")
    assert v.failure_class in reasons.STOPS


def test_an_audio_server_that_cannot_load_the_model_waits_on_its_runtime():
    """The 12:50Z sweep: m-a-p/YuE2-3B in the tts lane was recorded broken for
    mlx-audio failing to build the architecture."""
    runner = Fake("")
    runner.candidate, runner.spec = "YuE2-3B", "tts:m-a-p/YuE2-3B"
    runner.generate = lambda case: (_ for _ in ()).throw(RunnerError(
        "tts failed: HTTP 500: {\"detail\":\"Failed to load model "
        "'m-a-p/YuE2-3B': Could not determine model type\"}"))
    row = runner.run(Case("long-clause", "tts", "say it"))
    assert row.failure_class == reasons.LOAD_FAILED_RUNTIME
    v = screen.outcome(0, summarize([row]), candidate=runner.spec, key="YuE2-3B")
    assert (v.outcome, v.reason) == ("declined", "runtime")
    assert v.until.startswith("version:mlx-audio>")


def test_a_tts_model_that_loaded_and_misspoke_is_still_the_candidates():
    """Negative control: only the load failure is the runtime's."""
    assert reasons.classify("tts failed: HTTP 500: synthesis produced NaN",
                            candidate="tts:org/x") == reasons.CRASHED


def test_a_refused_sampling_setting_is_the_harnesss(tmp_path, monkeypatch):
    """#401: guidance_scale the runner chose, refused by the pipeline."""
    eng, out = _process("ValueError: guidance_scale has to be 0 for this model")
    from harness import proc
    monkeypatch.setattr(proc, "run", lambda *a, **k: out)
    runner = ProcessRunner(eng, tmp_path)
    runner.spec = "mflux:Qwen/Qwen-Image-Bench"
    row = runner.run(Case("fox-snow", "image", "a fox"))
    v = screen.outcome(0, summarize([row]), candidate=runner.spec, key=eng.name)
    assert (v.outcome, v.reason) == ("queued", "harness")


def test_a_genuine_content_failure_stays_the_candidates():
    """Negative control: a checker's own failure is broken and terminal."""
    row = Result("chunk-bytes", "org/x", False, 1.0, 0, "expected 3 chunks, got 2",
                 failure_class=reasons.CONTENT_FAILED)
    v = _screen([row])
    assert (v.outcome, v.reason) == ("broken", "candidate")
    assert v.outcome in ms.TERMINAL


@respx.mock
def test_a_thinking_model_gets_one_retry_with_thinking_off_in_a_screen():
    route = respx.post(URL).mock(side_effect=[
        _reply(None, reasoning="x" * 14746), _reply("print('ok')")])
    runner = CompletionRunner(GW, "org/x")
    runner.screening = True
    text, _ = runner.generate(CASE)
    assert text == "print('ok')"
    first, second = (json.loads(c.request.content) for c in route.calls)
    assert "chat_template_kwargs" not in first
    assert second["chat_template_kwargs"] == {"enable_thinking": False}
    assert runner.extra_metrics()["thinking_disabled"] == 1


@respx.mock
def test_a_measurement_does_not_change_the_exam():
    """Negative control: outside a screen the budget failure is the row."""
    route = respx.post(URL).mock(return_value=_reply(None, reasoning="x" * 99))
    row = CompletionRunner(GW, "org/x").run(CASE)
    assert route.call_count == 1
    assert row.failure_class == reasons.TOKEN_BUDGET_EXHAUSTED


@respx.mock
def test_a_budget_still_exhausted_is_a_limit_a_bigger_budget_meets():
    respx.post(URL).mock(return_value=_reply(None, reasoning="x" * 99))
    runner = CompletionRunner(GW, "org/x")
    runner.screening = True
    v = _screen([runner.run(CASE)])
    # The lane's budget names the limit, so raising one lane reopens only its verdicts. #628.
    want = f"limit:max_tokens.extract>{completion.budget('extract')}"
    assert (v.outcome, v.reason, v.until) == ("declined", "limit", want)
    assert v.outcome not in ("broken",)
    assert not ms.until_met(want, {"limits": {"max_tokens.extract": completion.budget("extract")}})
    assert not ms.until_met(want, {"limits": {"max_tokens.code": 32768}})
    assert ms.until_met(want, {"limits": {"max_tokens.extract": 16000}})


def test_the_screen_warms_untimed_so_a_cold_load_is_not_the_case_timeout(monkeypatch):
    """#406: command-a-plus timed out at 180 s on its cold 46 GiB load."""
    clock = {"t": 0.0}
    asked = []

    def post(gateway, payload, timeout):
        asked.append(timeout)
        clock["t"] += 300.0 if len(asked) == 1 else 2.0   # the load, then the case
        return _reply("ok")

    monkeypatch.setattr(completion, "_post", post)
    monkeypatch.setattr("time.perf_counter", lambda: clock["t"])
    runner = CompletionRunner(GW, "org/x")
    runner.warm()
    row = runner.run(CASE)
    assert asked == [completion.LOAD_TIMEOUT_S, completion.TIMEOUT_S]
    assert row.seconds == 2.0


def test_a_warm_up_that_times_out_is_a_limit_on_every_case(monkeypatch):
    def post(gateway, payload, timeout):
        raise httpx.ReadTimeout("slow")

    monkeypatch.setattr(completion, "_post", post)
    runner = CompletionRunner(GW, "org/x")
    with pytest.raises(RunnerError) as got:
        runner.warm()
    row = runner.failed(CASE, got.value)
    assert row.failure_class == reasons.TIMEOUT
    assert row.limit == f"load_timeout_s>{completion.LOAD_TIMEOUT_S:g}"
    v = _screen([row])
    assert (v.outcome, v.reason) == ("declined", "limit")


def _args(tmp_path, screen_):
    return argparse.Namespace(
        screen=screen_, repeat=1, adherence="", cases=str(ROOT / "evals" / "cases"),
        modality="code", candidates="org/x", from_winners=False, gateway=GW,
        out=str(tmp_path / "out"))


@pytest.fixture
def quiet_receipt(monkeypatch):
    """Receipt fields that would read the real machine."""
    for name, value in (("accelerator_id", "unified:test"), ("where_id", "test"),
                        ("swap_used_mb", 0), ("instruments", {}), ("engines", {})):
        monkeypatch.setattr(R, name, lambda *a, _v=value, **k: _v)
    monkeypatch.setattr(ms.machines, "_THIS_MACHINE", None)
    monkeypatch.setattr(environment, "capture", lambda: {})
    monkeypatch.setattr(R, "warn_if_pressed", lambda *a, **k: SimpleNamespace(
        as_dict=lambda: {}))


class Warmed(Fake):
    def __init__(self, warm_error=None):
        super().__init__(reasons.CONTENT_FAILED)
        self.warmed, self.warm_error = 0, warm_error

    def warm(self):
        self.warmed += 1
        if self.warm_error:
            raise self.warm_error


@pytest.mark.parametrize("screening,warmed", [(True, 1), (False, 0)])
def test_evals_run_warms_only_a_screen(tmp_path, monkeypatch, quiet_receipt,
                                       screening, warmed):
    runner = Warmed()
    monkeypatch.setattr(R, "build_runner", lambda *a, **k: runner)
    R._execute(_args(tmp_path, screening))
    assert runner.warmed == warmed and runner.screening is screening


def test_a_failed_warm_up_becomes_every_cases_row_with_its_class(
        tmp_path, monkeypatch, quiet_receipt):
    runner = Warmed(RunnerError("warm-up: timed out", failure_class=reasons.TIMEOUT,
                                limit="load_timeout_s>1800"))
    monkeypatch.setattr(R, "build_runner", lambda *a, **k: runner)
    R._execute(_args(tmp_path, True))
    data = json.loads((tmp_path / "out" / "results.json").read_text(encoding="utf-8"))
    assert {r["failure_class"] for r in data["rows"]} == {reasons.TIMEOUT}
    assert data["summary"]["org/x"]["failure_classes"] == {
        reasons.TIMEOUT: len(data["rows"])}
    assert data["summary"]["org/x"]["limits"] == ["load_timeout_s>1800"]
    # The store's results rows carry it, which is what every tier reads. #410.
    from harness import runs
    conn = ms.connect()
    try:
        stored = runs.receipt_at(conn, tmp_path / "out")
    finally:
        conn.close()
    assert {r["failure_class"] for r in stored["rows"]} == {reasons.TIMEOUT}
    assert stored["summary"]["org/x"]["failure_classes"] == {
        reasons.TIMEOUT: len(stored["rows"])}
    assert stored["summary"]["org/x"]["limits"] == ["load_timeout_s>1800"]


# --- the backfill classifies old rows and decides nothing --------------------

OLD = (
    ("broken", "screen", "it ran and passed nothing: x: gateway returned HTTP "
     "404: {\"error\": \"generation thread died\"}", "harness"),
    ("broken", "screen", "it ran and passed nothing: x: bartowski/Qwen_Qwen3.5-4B "
     "returned no answer: it spent the whole 4000-token budget on reasoning", "limit"),
    ("broken", "screen", "it ran and passed nothing: x: timed out after 180.0s", "limit"),
    ("broken", "screen", "it ran and passed nothing: fox: no fox", "candidate"),
    ("declined", "screen", "the installed runtime could not load it: x", "runtime"),
    ("declined", "inspect", "too-big: smallest weight it names is 59.9 GiB", "machine"),
    ("declined", "inspect", "dead: last commit 3.1 years ago", "upstream"),
    ("queued", "screen", "not screened: needs 40.0 GB but only 9.0 GB is safely "
     "available", "memory"),
    ("queued", "fetch", "retracted: 'x' was a fact about this harness", "reopened"),
    ("screened", "screen", "1 case(s) passed a screen", "candidate"),
    ("declined", "fetch", "60.7 GiB is over the 60 GiB cap", "limit"),
)


def test_the_backfill_classifies_every_old_row_and_reopens_only_ours(tmp_path):
    db = tmp_path / "old.db"
    conn = ms.connect(db)
    for i, (outcome, tier, detail, _) in enumerate(OLD):
        ms.record(conn, ms.Seen(name=f"org/m{i}", source="t"))
        ms.decide(conn, f"org/m{i}", outcome, tier=tier, detail=detail)
    conn.execute("UPDATE verdicts SET reason = ''")
    conn.execute("INSERT OR REPLACE INTO meta VALUES ('schema', '25')")
    conn.commit()
    before = conn.execute("SELECT id, outcome FROM verdicts ORDER BY id").fetchall()
    states = dict(conn.execute("SELECT name, state FROM proposals").fetchall())
    conn.close()
    again = ms.connect(db)
    try:
        got = [r[0] for r in again.execute(
            "SELECT reason FROM verdicts WHERE id <= ? ORDER BY id",
            (before[-1][0],))]
        assert got == [want for *_, want in OLD]
        # No existing row changes outcome; reopens are appended rows. RULE #292.
        assert again.execute("SELECT id, outcome FROM verdicts WHERE id <= ? "
                             "ORDER BY id", (before[-1][0],)).fetchall() == before
        now = dict(again.execute("SELECT name, state FROM proposals").fetchall())
        # A harness fact and a timeout the warm-up now absorbs are reopened.
        assert {n for n in now if now[n] != states[n]} == {"org/m0", "org/m2"}
        assert now["org/m0"] == now["org/m2"] == "queued"
        kinds = again.execute("SELECT detail, reopen_kind, reason FROM verdicts "
                              "WHERE id > ? ORDER BY id", (before[-1][0],)).fetchall()
        assert [(k[1], k[2]) for k in kinds] == [("retraction", "reopened")] * 2
        assert "refused_by_gateway" in kinds[0][0] or "server_dead" in kinds[0][0]
        assert "warms the model" in kinds[1][0]
        # A budget and a cap the harness chose stay declined, reopenable.
        until = dict(again.execute(
            "SELECT p.name, v.until FROM proposals p JOIN verdicts v "
            "ON v.id = p.state_verdict_id").fetchall())
        assert until["org/m1"] == "limit:max_tokens>4000"
        assert until["org/m10"] == "limit:download_gib>60"
        # Machine and upstream facts are not touched (#383 class 4).
        assert now["org/m5"] == "declined" and now["org/m6"] == "declined"
        assert ms.reason_audit(again)["terminal_harness_or_limit"] == 2
    finally:
        again.close()
