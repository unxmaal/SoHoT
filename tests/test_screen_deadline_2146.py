"""A served LLM's screen is bounded by one cold load plus its lane's clock per case, so a screen window can be granted. #2146."""
from __future__ import annotations

import pytest

from harness import completion


@pytest.mark.parametrize("spec", ["hf-text:org/model", "org/model", "llamacpp:org/model", "vllm:org/model", "ds4:org/model"])
def test_each_served_llm_spelling_gets_a_real_bound_and_a_speech_or_agent_engine_does_not(spec):
    from harness import screen
    from evals.run import SCREEN_CASES
    assert screen.deadline_s(spec, "code") == pytest.approx(
        completion.LOAD_TIMEOUT_S + SCREEN_CASES * completion.timeout_for(completion.budget("code")))
    assert screen.deadline_s(spec) > 0, "a lane the caller does not name is still bounded"
    assert screen.deadline_s("stt:org/model", "code") is None
    assert screen.deadline_s("claude-code:x", "agent") is None


@pytest.mark.parametrize("lane,each", [("code", 32768 / 25.0), ("svg", 180.0), ("repo", 32768 / 25.0),
                                       ("agent", 900.0), ("craft", 900.0), ("", 180.0), (None, 180.0)])
def test_a_served_llm_screen_is_bounded_by_its_lanes_clock_per_case(lane, each):
    from evals.run import SCREEN_CASES
    from harness import screen
    assert screen.deadline_s("org/model", lane) == pytest.approx(completion.LOAD_TIMEOUT_S + SCREEN_CASES * each)
