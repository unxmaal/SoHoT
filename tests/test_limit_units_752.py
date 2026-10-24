"""A recorded limit and the value the registry chooses for it are in one declared unit (#752)."""
import pytest

from harness import audio, knobs
from harness.knobs.base import Knob
from harness.memory_store import revisit


def _waits_on(exc) -> str:
    name, value = exc.limit
    return f"limit:{name}>{value:g}"


def test_every_knob_with_a_limit_declares_its_unit():
    for k in knobs.KNOBS.values():
        if k.limit:
            assert k.unit in knobs.UNITS, f"{k.name} records {k.limit} in no declared unit"


def test_a_limit_without_a_unit_is_refused_at_registration():
    with pytest.raises(ValueError, match="unit"):
        Knob("x", ("harness/audio.py:TIMEOUT_S",), (1,), limit="x_s")
    assert Knob("x", ("harness/audio.py:TIMEOUT_S",), (1,), limit="x_s", unit="s").unit == "s"
    assert Knob("x", ("harness/audio.py:TIMEOUT_S",), (1,)).unit == ""


def test_two_knobs_sharing_one_limit_name_are_refused():
    a = Knob("a", ("harness/audio.py:TIMEOUT_S",), (1,), limit="same", unit="s")
    b = Knob("b", ("harness/audio.py:TOKEN_CAP_FILL",), (1,), limit="same", unit="share")
    with pytest.raises(ValueError, match="same"):
        knobs.collect({"one": [("a", a)], "two": [("b", b)]})
    c = Knob("c", ("harness/audio.py:TOKEN_CAP_FILL",), (1,), limit="other", unit="share")
    assert set(knobs.collect({"one": [("a", a)], "two": [("c", c)]})[0]) == {"a", "c"}


def test_a_knob_binding_via_another_must_name_one_with_a_limit():
    a = Knob("a", ("harness/audio.py:TIMEOUT_S",), (1,), limit="a_s", unit="s")
    b = Knob("b", ("harness/audio.py:TOKEN_CAP_FILL",), (1,), binds_via="a")
    assert set(knobs.collect({"one": [("a", a), ("b", b)]})[0]) == {"a", "b"}
    with pytest.raises(ValueError, match="no knob with a limit"):
        knobs.collect({"one": [("b", Knob("b", ("harness/audio.py:TOKEN_CAP_FILL",), (1,), binds_via="zz"))]})
    with pytest.raises(ValueError, match="one or the other"):
        Knob("c", ("harness/audio.py:TIMEOUT_S",), (1,), limit="c_s", unit="s", binds_via="a")
    assert knobs.KNOBS["tts_cap_fill"].binds_via == "tts_token_floor"


def test_a_recorded_limit_in_another_unit_than_its_knob_is_refused():
    assert knobs.hit("tts_budget_s", 8.0, "s") == ("tts_budget_s", 8.0)
    with pytest.raises(ValueError, match="tokens"):
        knobs.hit("tts_budget_s", 200, "tokens")
    with pytest.raises(ValueError, match="no knob"):
        knobs.hit("tts_tokens", 200, "tokens")


def test_the_tts_cap_records_the_seconds_its_budget_allowed_in_the_unit_its_knob_declares():
    hz = audio.codec_hz("chatterbox")
    budget = audio.token_budget("hello there", "chatterbox")
    exc = audio.TokenCap(8.0, budget, hz)
    name, value = exc.limit
    assert knobs.limit_units()[name] == "s"
    assert value == pytest.approx(budget / hz)
    assert knobs.limits()[name] == audio.TOKEN_BUDGET_MIN_S


def test_a_tts_verdict_cut_at_its_budget_reopens_once_the_harness_would_give_that_text_more(monkeypatch):
    text, hz = "hello there", audio.codec_hz("chatterbox")
    before = audio.token_budget(text, "chatterbox")
    until = _waits_on(audio.TokenCap(8.0, before, hz))
    assert not revisit.until_met(until, {"limits": knobs.limits()})
    monkeypatch.setattr(audio, "TOKEN_CAP_FILL", 0.99)
    assert not revisit.until_met(until, {"limits": knobs.limits()}), "a stricter fill gives the clip no more room"
    monkeypatch.setattr(audio, "TOKEN_BUDGET_MIN_S", 16.0)
    assert audio.token_budget(text, "chatterbox") > before
    assert revisit.until_met(until, {"limits": knobs.limits()})


def test_a_long_text_whose_budget_the_floor_did_not_set_waits_until_the_floor_passes_it(monkeypatch):
    text, hz = " ".join(["word"] * 30), audio.codec_hz("chatterbox")
    before = audio.token_budget(text, "chatterbox")
    until = _waits_on(audio.TokenCap(30.0, before, hz))
    monkeypatch.setattr(audio, "TOKEN_BUDGET_MIN_S", 16.0)
    assert audio.token_budget(text, "chatterbox") == before
    assert not revisit.until_met(until, {"limits": knobs.limits()})
    monkeypatch.setattr(audio, "TOKEN_BUDGET_MIN_S", 60.0)
    assert audio.token_budget(text, "chatterbox") > before
    assert revisit.until_met(until, {"limits": knobs.limits()})
