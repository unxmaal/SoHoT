"""What the fetch tier refuses, and which lane it spends on. #211.

The size itself is proposals.size_bytes; tests/test_store_size.py. #413.
"""
import pytest

from harness import fetching


# --- a refusal about this harness is not a verdict about the candidate -----

def test_our_own_gap_is_named_as_ours():
    assert fetching.plan("org/x", 0).reason == "harness"


def test_a_real_refusal_is_not_ours():
    """The negative control: an oversized model must still be settled, or
    every sweep re-offers it. The cap is a limit we chose, so it says so. #406."""
    over = fetching.plan("org/x", int(64.6 * fetching.GIB), cap=60 * fetching.GIB)
    assert (over.reason, over.until) == ("limit", "limit:download_gib>60")
    full = fetching.plan("org/x", int(49.3 * fetching.GIB), free=60 * fetching.GIB,
                         floor=50 * fetching.GIB)
    assert full.reason == "machine"


def test_the_plan_for_an_unsized_repo_still_refuses():
    """The refusal is right. Only the VERDICT it produced was wrong."""
    p = fetching.plan("org/x", 0)
    assert not p.ok and p.reason == "harness"


# --- the scoped loop must scope the step that spends the disk ---------------
#
# A REAL STORE, NOT A FAKE CONNECTION. These used a stub whose execute()
# returned an object with only fetchall(), which stopped working the moment
# queued() asked the store a second question. A fake that models one call is a
# test of that call, not of the function.

from harness import memory_store as ms       # noqa: E402


def _seed(conn, name, lane, registry=ms.HUGGINGFACE, kind="candidate"):
    ms.record(conn, ms.Seen(name=name, source="test", url="", why="",
                            relevance=0, kind=kind, registry=registry,
                            lane=lane, resolved=name))
    ms.set_size(conn, name, 104857600)
    ms.decide(conn, name, "queued", tier="inspect", detail="fits")


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(fetching, "have", lambda *a, **k: False)
    monkeypatch.setattr("harness.rank.serving", lambda *a, **k: set())
    monkeypatch.setattr("harness.rank.lanes_with_receipts", lambda *a, **k: set())
    conn = ms.connect(tmp_path / "d.db")
    yield conn
    conn.close()


def test_a_lane_scoped_fetch_leaves_the_other_lanes_alone(store):
    """The loop printed "(spending only on the image lane)" and then considered
    whisper-tiny, wav2vec2, gpt2 and vicuna. Issue #211."""
    _seed(store, "org/img", "image")
    _seed(store, "org/asr", "stt")
    assert [r["name"] for r in fetching.queued(store, lane="image")] == ["org/img"]
    assert len(fetching.queued(store)) == 2, "unscoped must keep both"


def test_a_text_candidate_is_fetchable_for_the_web_lane(store):
    """lanes.serves, not equality, so #208 survives here too."""
    _seed(store, "org/txt", "code")
    assert len(fetching.queued(store, lane="web")) == 1
    assert len(fetching.queued(store, lane="image")) == 0
