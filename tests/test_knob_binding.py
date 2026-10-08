"""Per knob and lane, count the limit that shows it binding; past a threshold, say so in the loop and the audit (#636, #637)."""
import pytest

from evals.core import Case
from evals.runners.speech import SpeechRunner
from harness import audio, binding, knobs, reasons, runs
from harness import memory_store as ms

DAY = 86400.0
NOW = 1_800_000_000.0
M = {"fingerprint": "Mac17,15/macOS/arm64", "hw_model": "Mac17,15", "os": "macOS-27.0.1-arm64-arm-64bit",
     "arch": "arm64", "memory_gb": 96.0, "accelerator": "unified 96GB", "runtimes": "cpu,mlx",
     "ceiling_gb": 66.0, "versions": {}}
_SEQ = iter(range(1, 10_000))


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setattr(ms, "this_machine", lambda: dict(M))
    c = ms.connect(tmp_path / "d.db")
    ms.remember_machine(c, dict(M))
    yield c
    c.close()


def record(conn, lane, limits, *, at=NOW - DAY, env=None):
    """One run in `lane`: limits is one hit_limit per row, '' for a row that hit none."""
    rows = [{"candidate": "m", "case_id": f"c{i}", "passed": not lim, "seconds": 1.0,
             "failure_class": reasons.TIMEOUT if lim else "", "limit": lim}
            for i, lim in enumerate(limits)]
    env = env if env is not None else {"hw_model": M["hw_model"], "os": M["os"], "arch": "arm64"}
    return runs.record(conn, f"runs/r{next(_SEQ)}-{lane}",
                       {"receipt": {"modality": lane}, "environment": env, "specs": {"m": "m"},
                        "rows": rows}, at=at)


def row(found, knob, lane):
    return next(r for r in found if r["knob"] == knob and r["lane"] == lane)


def test_a_budget_hit_on_a_large_share_of_a_lanes_rows_is_binding(conn):
    record(conn, "code", ["max_tokens.code>32768"] * 4 + [""] * 6)
    got = row(binding.count(conn, now=NOW), "reply_budget", "code")
    assert (got["hits"], got["of"], got["limit"]) == (4, 10, "max_tokens.code")
    assert got["binding"]


def test_a_limit_counts_only_for_the_knob_that_names_it(conn):
    record(conn, "code", ["timeout_s>180"] * 3 + ["load_timeout_s>1800"] + [""] * 6)
    found = binding.count(conn, now=NOW)
    assert row(found, "request_timeout", "code")["hits"] == 3
    assert row(found, "load_timeout", "code")["hits"] == 1
    assert row(found, "reply_budget", "code")["hits"] == 0


def test_a_rare_hit_is_counted_but_not_binding(conn):
    record(conn, "code", ["timeout_s>180"] + [""] * 99)
    got = row(binding.count(conn, now=NOW), "request_timeout", "code")
    assert got["hits"] == 1 and not got["binding"]


def test_runs_older_than_the_window_are_not_counted(conn):
    window = knobs.KNOBS["binding_window"].default()
    record(conn, "code", ["timeout_s>180"] * 10, at=NOW - (window + 1) * DAY)
    assert row(binding.count(conn, now=NOW), "request_timeout", "code")["of"] == 0


def test_another_machines_runs_are_not_this_machines_binding(conn):
    other = {"hw_model": "Mac14,12", "os": "macOS-27.0.1-arm64-arm-64bit", "arch": "arm64"}
    record(conn, "code", ["timeout_s>180"] * 10, env=other)
    here = runs.here(conn)
    assert row(binding.count(conn, now=NOW, machines=here), "request_timeout", "code")["of"] == 0
    assert row(binding.count(conn, now=NOW), "request_timeout", "code")["of"] == 10


def _proposal(conn, name):
    ms.record(conn, ms.Seen(name=name, source="test", url="", why="", relevance=0, kind="candidate",
                            registry=ms.HUGGINGFACE, lane="code", resolved=name))


def test_a_ceiling_refusal_counts_for_the_memory_ceiling(conn):
    for i in range(3):
        _proposal(conn, f"org/big-{i}")
        ms.decide(conn, f"org/big-{i}", "declined", tier="inspect", reason="machine",
                  detail="too-big: over the 66 GiB ceiling", until="ceiling_gb:>66", at=NOW - DAY)
    _proposal(conn, "org/small")
    ms.decide(conn, "org/small", "queued", tier="inspect", detail="fits", at=NOW - DAY)
    got = row(binding.count(conn, now=NOW), "memory_ceiling", "")
    assert (got["hits"], got["of"], got["limit"]) == (3, 4, "ceiling_gb")
    assert got["binding"]


def test_the_report_names_only_the_binding_knobs(conn):
    record(conn, "code", ["max_tokens.code>32768"] * 5 + [""] * 5)
    text = binding.render(binding.count(conn, now=NOW))
    assert "reply_budget" in text and "code" in text and "5 of 10" in text
    assert "request_timeout" not in text
    assert binding.render([]) == "  no knob is binding"


def test_the_loop_reports_binding_knobs(conn, capsys):
    from harness.commands import loop
    record(conn, "code", ["max_tokens.code>32768"] * 5 + [""] * 5)
    loop._report_binding(conn, now=NOW)
    out = capsys.readouterr().out
    assert "=== binding knobs ===" in out and "reply_budget" in out


def test_a_runaway_names_the_cutoff_it_tripped(tmp_path, monkeypatch):
    def ran_away(*a, **k):
        raise audio.Runaway("30s of audio for 9 words (3.3s/word, ceiling 0.95)",
                            audio.SECONDS_PER_WORD_CEILING)
    monkeypatch.setattr(audio, "speak", ran_away)
    runner = SpeechRunner("kokoro", tmp_path)
    got = runner.run(Case("say-it", "tts", "one two three four five six seven eight nine"))
    assert not got.passed
    assert got.failure_class == reasons.RUNAWAY
    assert got.limit == f"seconds_per_word>{audio.SECONDS_PER_WORD_CEILING:g}"


def test_a_runaway_is_a_candidate_failure_not_a_harness_one():
    assert reasons.CLASSES[reasons.RUNAWAY] == ("broken", reasons.CANDIDATE)
    assert reasons.classify("tts ran away: 30s of audio for 9 words") == reasons.RUNAWAY


def test_the_audit_reports_binding_knobs_without_failing(tmp_path, monkeypatch):
    from harness import live_audit
    monkeypatch.setattr(ms, "this_machine", lambda: dict(M))
    path = tmp_path / "d.db"
    c = ms.connect(path)
    ms.remember_machine(c, dict(M))
    record(c, "code", ["max_tokens.code>32768"] * 5 + [""] * 5, at=__import__("time").time() - DAY)
    c.close()
    got = live_audit.audit(path)
    assert [r["knob"] for r in got["binding"]] == ["reply_budget"]
    assert "binding" not in {ch["name"] for ch in got["checks"]}
    text = live_audit.report_text(got)
    assert "binding knobs:" in text and "reply_budget" in text
