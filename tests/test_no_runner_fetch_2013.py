"""#2013: a candidate no lane can run is refused before a byte is fetched; weights one already holds go stamped."""
import pytest

from harness import disk, fetching
from harness import memory_store as ms
from tests import fakes
from tests.test_harness_disk import DAY, NOW, inv, make_repo, world  # noqa: F401

GIB = fetching.GIB
OCR = "mlx-community/DeepSeek-OCR-bf16"


def _queued(conn, name, lane, tags=()):
    ms.record(conn, ms.Seen(name=name, source="t", kind="weights", lane=lane, registry=ms.HUGGINGFACE, resolved=name))
    ms.set_size(conn, name, 6 * GIB)
    if tags:
        fakes.carded(conn, name, {"tags": list(tags)})
    ms.decide(conn, name, "queued", tier="inspect", detail="fits")


def test_a_candidate_that_needs_its_own_runner_gets_the_refusal_and_no_download():
    conn = ms.connect()
    try:
        _queued(conn, OCR, "ocr", tags=("mlx", "safetensors"))
        got = fetching.for_test(conn, fetching.row(conn, OCR), free=900 * GIB, floor=0,
                                snapshot=lambda *a, **k: pytest.fail("a candidate no runner loads was downloaded"))
        assert not got["ok"] and "needs its own runner" in got["why"]
        state = conn.execute("SELECT v.tier, v.outcome, v.reason, v.detail FROM verdicts v JOIN proposals p "
                             "ON p.id = v.proposal_id WHERE p.name = ? ORDER BY v.id DESC LIMIT 1", (OCR,)).fetchone()
        assert tuple(state)[:3] == ("fetch", "queued", "harness") and "needs its own runner" in state["detail"]
    finally:
        conn.close()


def test_a_candidate_no_lane_takes_is_never_fetched():
    conn = ms.connect()
    try:
        _queued(conn, "lolzinventor/Qwen3.5-4B-Base-ZitGen-V1", "")
        row = fetching.row(conn, "lolzinventor/Qwen3.5-4B-Base-ZitGen-V1")
        got = fetching.for_test(conn, row, free=900 * GIB, floor=0,
                                snapshot=lambda *a, **k: pytest.fail("a laneless candidate was downloaded"))
        assert not got["ok"] and fetching.why_not(row)[0] == fetching.NO_LANE
    finally:
        conn.close()


def test_weights_already_held_for_a_candidate_no_runner_loads_go_stamped(world):
    d = make_repo(world.hub, OCR, size=4096)
    _queued(world.conn, OCR, "ocr", tags=("mlx",))
    world.conn.execute("UPDATE downloads SET finished_at = ? WHERE repo = ?", (NOW - 38 * DAY, OCR))
    world.conn.commit()
    got = disk.clean(inv(world), NOW, world.conn)
    assert [r["repo"] for r in got["evicted"]] == [OCR] and not d.exists()
    row = world.conn.execute("SELECT state, removed_by FROM downloads WHERE repo = ?", (OCR,)).fetchone()
    assert (row["state"], row["removed_by"]) == ("removed", disk.TESTED)
