"""`soh unverified`: the Stop hook flags final-message claims no tool result in the turn supports (#1380)."""
from __future__ import annotations

import io
import json
import re
import shutil
from argparse import Namespace
from pathlib import Path

import pytest

from harness import paths
from harness import unverified as uv
from harness.commands import unverified as cmd
from harness.completion import CompletionError

FIXTURE = Path(__file__).parent / "fixtures" / "unverified" / "planted.jsonl"
SUPPORTED = ["make check passed: 1287 passed and 4 skipped.",
             "PR #1422 is open and mergeable.",
             "Job 0211 finished with exit 0 after 38 minutes.",
             "Job 0212 is queued for the night.",
             "The gateway is up and the decide lane serves imajev-4b-Q8_0."]
UNSUPPORTED = ["The nightly CI on Linux and Windows is green.",
               "The store is at schema 91.",
               "Job 0213 failed at 02:14 with an out-of-memory error.",
               "The discovery loop starts every night at 21:00.",
               "The router holds 9 models in memory."]
PLAN = "I will open the follow-up issue next."


class Fake:
    """Shown when every number-bearing term of the claim is in the context it was given; else half its terms."""

    def __init__(self, fail=None):
        self.seen: dict[str, str] = {}
        self.fail = fail

    def __call__(self, question, schema, context, timeout):
        assert set(schema) == {"kind", "support"} and timeout > 0
        claim = question.split("Sentence: ", 1)[1]
        self.seen[claim] = context
        if self.fail:
            raise self.fail
        if claim.startswith("I will"):
            return {"answers": {"kind": "other", "support": "not_shown"}}
        want, have = uv.terms(claim), uv.terms(context)
        digits = {t for t in want if re.search(r"\d", t)}
        shown = digits <= have if digits else len(want & have) * 2 >= len(want)
        return {"answers": {"kind": "fact", "support": "shown" if shown else "not_shown"}}


def _turn(path=FIXTURE):
    got = uv.turn_of(path)
    assert got is not None
    return got


def _event(path=FIXTURE, **kw):
    return {"session_id": "s1", "transcript_path": str(path), "hook_event_name": "Stop",
            "stop_hook_active": False, **kw}


def _log() -> list[dict]:
    path = paths.logs() / uv.LOG
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


def test_planted_turn_flags_the_unsupported_claims_and_spares_the_supported_ones():
    turn_id, turn = _turn()
    assert turn_id == "t1"
    text = uv.final_text(turn)
    assert set(SUPPORTED + UNSUPPORTED) <= set(uv.candidates(text))
    got = uv.check(text, turn, Fake())
    flagged = set(got["flagged"])
    assert len(flagged & set(UNSUPPORTED)) >= 4
    assert len(flagged & set(SUPPORTED)) <= 1
    assert PLAN not in flagged
    assert got["decision"] == uv.BLOCK and got["checked"] == got["candidates"]


def test_only_the_current_turns_tool_results_count_as_support():
    turn_id, turn = _turn()
    fake = Fake()
    got = uv.check(uv.final_text(turn), turn, fake)
    assert "The store is at schema 91." in got["flagged"]
    assert "91" not in fake.seen["The store is at schema 91."]
    assert "1287 passed" in fake.seen[SUPPORTED[0]]
    assert "MERGEABLE" in fake.seen[SUPPORTED[1]]


def test_a_claim_no_tool_output_shares_a_term_with_is_flagged_whatever_the_model_says():
    turn_id, turn = _turn()
    always = lambda q, s, context, timeout: {"answers": {"kind": "fact", "support": "shown"},  # noqa: E731
                                              "probabilities": {"support": {"shown": 1.0, "not_shown": 0.0}}}
    got = uv.check("The nightly CI on Linux and Windows is green.\nPR #1422 is open and mergeable.", turn, always)
    assert got["flagged"] == ["The nightly CI on Linux and Windows is green."]


@pytest.mark.parametrize("p,flagged", [(0.95, False), (0.9, False), (0.75, True), (0.2, True)])
def test_a_factual_claim_is_flagged_below_the_shown_probability(p, flagged):
    turn_id, turn = _turn()
    model = lambda q, s, context, timeout: {"answers": {"kind": "fact", "support": "shown" if p >= 0.5 else "x"},  # noqa: E731
                                             "probabilities": {"support": {"shown": p, "not_shown": 1 - p}}}
    got = uv.check("PR #1422 is open and mergeable.", turn, model)
    assert bool(got["flagged"]) is flagged
    assert ("unverified_shown_p" in _cut_knobs()) is (flagged and p >= 0.5)
    other = lambda q, s, context, timeout: {"answers": {"kind": "other", "support": "not_shown"},  # noqa: E731
                                             "probabilities": {"support": {"shown": 0.0}}}
    assert uv.check("PR #1422 is open and mergeable.", turn, other)["flagged"] == []


def test_the_near_miss_turn_puts_every_claim_before_the_model_with_its_tool_output():
    turn_id, turn = _turn(FIXTURE.with_name("near_miss.jsonl"))
    fake = Fake()
    got = uv.check(uv.final_text(turn), turn, fake)
    assert got["candidates"] == got["checked"] == 10
    assert all(fake.seen.values())


def test_a_cited_or_self_marked_unverified_claim_is_not_checked():
    text = ("Job 0213 failed at 02:14, unverified: check soh jobs show 0213.\n"
            "The gate was moved to 21:00 per RULE #1237.\n"
            "The limit sits at harness/watchdog.py:120 and is 3600 s.\n"
            "The nightly probably ran at 02:00.\n"
            "Did job 0214 finish?\n"
            "The router holds 9 models in memory.")
    assert uv.candidates(text) == ["The router holds 9 models in memory."]


def test_the_turn_starts_at_a_prompt_never_at_a_tool_result_or_meta_record():
    records = [json.loads(line) for line in FIXTURE.read_text(encoding="utf-8").splitlines()]
    starts = [r["uuid"] for r in records if uv.starts_turn(r)]
    assert starts == ["t0", "t1"]
    peer = {"type": "user", "isMeta": True, "origin": {"kind": "peer"}, "message": {"content": "x"}}
    compact = {"type": "user", "isCompactSummary": True, "message": {"content": "x"}}
    assert uv.starts_turn(peer) and not uv.starts_turn(compact)


def test_a_second_stop_on_the_same_turn_is_allowed():
    first = uv.hook(_event(), Fake())
    assert first["decision"] == uv.BLOCK
    again = Fake()
    second = uv.hook(_event(), again)
    assert (second["decision"], second["why"]) == (uv.ALLOW, "already blocked this turn")
    assert again.seen == {}
    active = uv.hook(_event(stop_hook_active=True), Fake())
    assert (active["decision"], active["why"]) == (uv.ALLOW, "stop_hook_active")


def test_a_block_that_cannot_be_remembered_is_allowed(monkeypatch):
    monkeypatch.setattr(uv, "_remember", lambda session, turn: False)
    got = uv.hook(_event(), Fake())
    assert (got["decision"], got["why"]) == (uv.ALLOW, "state not writable")


@pytest.mark.parametrize("exc,why", [(RuntimeError("model said 1287 passed"), "error: RuntimeError"),
                                     (TimeoutError("slow"), "timeout: TimeoutError"),
                                     (CompletionError("read timed out", "timeout"), "timeout: CompletionError"),
                                     (CompletionError("bad reply"), "error: CompletionError")])
def test_any_internal_error_allows_the_stop_and_logs_why(exc, why):
    got = uv.hook(_event(), Fake(fail=exc))
    assert (got["decision"], got["why"]) == (uv.ALLOW, why)
    assert _log()[-1]["why"] == why
    assert "1287" not in json.dumps(_log())
    missing = uv.hook(_event(path=Path("nowhere.jsonl")), Fake())
    assert (missing["decision"], missing["why"]) == (uv.ALLOW, "error: FileNotFoundError")
    assert uv.hook({}, Fake())["decision"] == uv.ALLOW


def test_the_turn_deadline_allows_the_stop(monkeypatch):
    ticks = iter(range(0, 1000, 4))
    monkeypatch.setattr(uv, "TURN_TIMEOUT_S", 10.0)
    got = uv.hook(_event(), Fake(), clock=lambda: next(ticks))
    assert (got["decision"], got["why"]) == (uv.ALLOW, "timeout")
    assert 0 < got["checked"] < got["candidates"]
    assert "unverified_turn_timeout_s" in _cut_knobs()


def _cut_knobs() -> list[str]:
    from harness import cuts
    from harness import memory_store as ms
    conn = ms.connect()
    try:
        cuts.flush(conn)
        return [r[0] for r in conn.execute("SELECT knob FROM limit_cuts")]
    finally:
        conn.close()


def test_a_turn_starting_before_the_bytes_read_is_allowed(monkeypatch):
    monkeypatch.setattr(uv, "TRANSCRIPT_BYTES", 200)
    got = uv.hook(_event(), Fake())
    assert (got["decision"], got["why"]) == (uv.ALLOW, "turn longer than unverified_transcript_bytes")


def test_claims_past_the_per_turn_limit_go_unchecked(monkeypatch):
    monkeypatch.setattr(uv, "CLAIMS_PER_TURN", 3)
    turn_id, turn = _turn()
    fake = Fake()
    got = uv.check(uv.final_text(turn), turn, fake)
    assert got["checked"] == 3 and len(fake.seen) == 3 and got["candidates"] > 3
    assert "unverified_claims" in _cut_knobs()


def test_the_log_holds_counts_and_flagged_claims_never_other_transcript_text():
    uv.hook(_event(), Fake())
    rows = _log()
    assert len(rows) == 1
    row = rows[0]
    assert set(row) == {"at", "session", "turn", "decision", "why", "candidates", "checked", "flagged", "seconds"}
    assert sorted(row["flagged"]) == sorted(UNSUPPORTED)
    text = json.dumps(rows)
    for leak in ["Where do things stand", "1287", "MERGEABLE", "imajev", "follow-up issue", "reverify"]:
        assert leak not in text


def test_the_hook_command_prints_a_block_naming_the_claims_and_nothing_else(capsys):
    a = Namespace(hook=True, transcript="", settings=False)
    assert cmd.cmd_unverified(a, Fake(), stdin=io.StringIO(json.dumps(_event()))) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["decision"] == "block"
    for claim in UNSUPPORTED:
        assert claim in out["reason"]
    for claim in SUPPORTED:
        assert claim not in out["reason"]
    assert cmd.cmd_unverified(a, Fake(), stdin=io.StringIO(json.dumps(_event()))) == 0
    assert capsys.readouterr().out == ""
    assert cmd.cmd_unverified(a, Fake(), stdin=io.StringIO("not json")) == 0
    assert capsys.readouterr().out == ""


def test_the_transcript_mode_writes_no_state_and_no_log(tmp_path, capsys):
    copy = tmp_path / "t.jsonl"
    shutil.copy(FIXTURE, copy)
    a = Namespace(hook=False, transcript=str(copy), settings=False)
    assert cmd.cmd_unverified(a, Fake()) == 0
    assert "5 flagged" in capsys.readouterr().out
    assert _log() == [] and not (paths.home() / uv.STATE).exists()


def test_the_settings_block_is_printed_never_written(capsys):
    a = Namespace(hook=False, transcript="", settings=True)
    assert cmd.cmd_unverified(a) == 0
    out = capsys.readouterr().out
    assert '"Stop"' in out and "soh unverified --hook" in out
    assert uv.settings("x")["hooks"]["Stop"][0]["hooks"][0]["timeout"] > uv.TURN_TIMEOUT_S
