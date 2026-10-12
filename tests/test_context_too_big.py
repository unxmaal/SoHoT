"""A model whose weights alone exceed the budget. Issue #779.

choose() fell through to the KV arithmetic for these, and reported

    refused: 0.0 GiB of KV room holds 0 tokens at 262144 B/token,
             under the 8192-token floor

which reads as a context problem, fixable by asking for less context. It is
not: the weights do not fit and no context would make them. Measured with
Qwen2.5-32B-Instruct-Q4_K_M, 18.48 GiB, on a 12 GiB card.

The host side is named too, where the platform has a commit limit, because
that is the wall a partly offloaded model actually hits. Serving that model
left 0.58 GiB of commit headroom with 20.23 GiB of committed private memory in
one process.
"""
import pytest

from harness import context, memory

GIB = 1024 ** 3

#: Enough header for choose() to size a cache from; the numbers are the 32B's.
BIG = {"general.architecture": "qwen2", "qwen2.block_count": 64,
       "qwen2.embedding_length": 5120, "qwen2.attention.head_count": 40,
       "qwen2.attention.head_count_kv": 8, "qwen2.context_length": 32768}


@pytest.fixture
def no_commit_limit(monkeypatch):
    monkeypatch.setattr(memory, "commit_headroom_gb", lambda: None)


@pytest.fixture
def commit_headroom(monkeypatch):
    monkeypatch.setattr(memory, "commit_headroom_gb", lambda: 13.0)


def test_weights_over_the_budget_are_refused_for_the_weights(no_commit_limit):
    """THE POINT OF THIS FILE. The reason names the term that refused it."""
    got = context.choose(BIG, weights=int(18.48 * GIB), budget=int(10.0 * GIB))
    assert got.ctx == 0
    assert "18.5 GiB of weights over the 10.0 GiB budget" in got.why
    assert "KV room" not in got.why, (
        "the weights refused this, not the cache size")


def test_the_host_side_is_named_where_there_is_a_commit_limit(commit_headroom):
    got = context.choose(BIG, weights=int(18.48 * GIB), budget=int(10.0 * GIB))
    assert "13.0 GiB of commit headroom" in got.why


def test_the_reason_does_not_offer_the_shortfall_as_the_host_cost(commit_headroom):
    """A READER GIVEN THE SHORTFALL AND THE HEADROOM WOULD DO THE WRONG SUM.

    18.5 over a 10.0 budget is 8.5 GiB short, and 8.5 is less than 13.0, so
    offloading the remainder looks free. It is not: that model committed 20.23
    GiB of private host memory, the whole file plus overhead, and the machine
    ended up 0.58 GiB from its commit limit. The reason must not invite the
    subtraction.
    """
    got = context.choose(BIG, weights=int(18.48 * GIB), budget=int(10.0 * GIB))
    assert "whole file" in got.why
    assert "over by" not in got.why
    # "8.5" alone matches inside "18.5", which is the weights figure and
    # belongs there. The shortfall would appear as its own number.
    assert "by 8.5" not in got.why and " 8.5 GiB" not in got.why, (
        "naming the shortfall beside the headroom invites comparing them")


def test_no_claim_is_made_where_the_platform_has_no_commit_limit(no_commit_limit):
    """macOS grows swap until the disk is gone, so there is no figure to give.
    Silence beats a number nobody can act on."""
    got = context.choose(BIG, weights=int(18.48 * GIB), budget=int(10.0 * GIB))
    assert "commit headroom" not in got.why
    assert "host memory" not in got.why


def test_a_model_that_fits_is_unaffected(commit_headroom):
    """The early refusal must not catch anything the KV arithmetic would have
    planned.

    One slot, not eight: this header is the 32B's, at 262144 B/token, and 5.6
    GiB of room genuinely does not hold eight slots above the floor. That is
    the KV arithmetic refusing for its own reason, which is correct and is not
    what this test is about.
    """
    got = context.choose(BIG, weights=int(4.36 * GIB), budget=int(10.0 * GIB))
    assert got.ctx > 0, got.why
    assert "refused" not in got.why


def test_weights_exactly_at_the_budget_leave_no_room_and_say_so(commit_headroom):
    """Equal is not enough: the cache needs somewhere to go, and the old
    message would have blamed the cache for it."""
    got = context.choose(BIG, weights=int(10.0 * GIB), budget=int(10.0 * GIB))
    assert got.ctx == 0
    assert "of weights over the" in got.why
