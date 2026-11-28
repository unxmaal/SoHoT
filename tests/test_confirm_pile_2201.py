"""#2201: held wins whose confirm jobs piled up paused show a Needs-you item with a button that runs the cleanup, and it goes with the pile."""
from __future__ import annotations

from harness import workqueue as wq
from tests.test_owner_buttons_2138 import band, client, in_process, page, tap  # noqa: F401
from tests.test_status_buttons_2135 import add_job, set_state, with_conn


def _paused(tmp_path, vid, n):
    for i in range(n):
        job = add_job(tmp_path, ("/rel/python", "-m", "harness.cli", "adopt", "--confirm", str(vid)), title=f"confirm {vid} #{i}")
        set_state(job, "paused", rc=75)


def test_a_pile_of_paused_confirms_is_a_needs_you_item_and_its_button_clears_it(tmp_path, client, in_process):
    _paused(tmp_path, 27443, 3)
    _paused(tmp_path, 27444, 1)
    shown = page(client)
    assert "paused confirm jobs piled up" in shown and "3 paused confirm jobs across 1 verdict(s): 27443 (3)" in shown
    assert band(shown) == ["confirm_cleanup"]
    tap(client, "confirm_cleanup")
    left = with_conn(lambda c: wq.confirm_counts(c, (wq.PAUSED,)))
    assert left == {}
    assert "paused confirm jobs piled up" not in page(client) and "confirm_cleanup" not in band(page(client))


def test_no_item_without_duplicates(tmp_path, client):
    _paused(tmp_path, 27443, 1)
    assert "paused confirm jobs piled up" not in page(client)
