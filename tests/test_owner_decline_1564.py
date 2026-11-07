"""`soh decline` writes the owner's terminal decline: fetch, screen and retests never touch the candidate or its runner base again. #1564."""
from __future__ import annotations

import json

import pytest

from harness import cli, fetching, hold, reasons
from harness import memory_store as ms
from harness.commands import decline as decline_cmd
from tests.test_runner_base_weights import BASE, FREE, GIB, OMNI, Snapshot, db, on_disk, queued_omnisvg  # noqa: F401

SAID = "owner: not wanted"


def state(db, name=OMNI):
    return db.execute("SELECT p.state, p.next_retest_at, v.tier, v.reason, v.judge, v.detail FROM proposals p "
                      "JOIN verdicts v ON v.id = p.state_verdict_id WHERE p.name = ?", (name,)).fetchone()


def test_a_declined_candidate_and_its_runner_base_are_never_fetched(db):
    queued_omnisvg(db, tier="screen")
    on_disk(db, OMNI)
    decline_cmd.decline(db, OMNI, SAID)
    snap = Snapshot()
    done = fetching.run(db, {OMNI: 9 * GIB, BASE: 7 * GIB}, snapshot=snap, free=FREE)
    assert snap.asked == [] and done == []
    assert fetching.queued(db, needs_lane=False) == []


def test_the_decline_is_terminal_owner_and_no_retest_reopens_it(db):
    queued_omnisvg(db)
    decline_cmd.decline(db, OMNI, SAID)
    got = state(db)
    assert (got["state"], got["tier"], got["reason"], got["judge"]) == ("declined", ms.ADOPT, reasons.OWNER, "owner")
    assert SAID in got["detail"] and got["next_retest_at"] is None
    assert ms.due_retests(db, now=4e10) == []
    with pytest.raises(ms.IllegalTransition):
        ms.decide(db, OMNI, "queued", tier="screen")


def test_a_decline_names_who_and_why_and_a_known_candidate(db):
    queued_omnisvg(db)
    with pytest.raises(ValueError):
        decline_cmd.decline(db, OMNI, "  ")
    with pytest.raises(ValueError):
        decline_cmd.decline(db, "org/never-sighted", SAID)
    assert state(db)["state"] == "queued"


def test_the_cli_declines(db, capsys):
    queued_omnisvg(db)
    assert cli.main(["decline", OMNI, SAID, "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["name"] == OMNI
    assert state(db)["state"] == "declined"
    assert cli.main(["decline", OMNI]) != 0


def test_the_fetch_unit_downloads_nothing_while_benchmarks_are_held(db, monkeypatch, capsys):
    from harness import day_fetch
    started = []
    monkeypatch.setattr(day_fetch, "run", lambda a: started.append(a) or {"started": False, "why": "-"})
    monkeypatch.setattr(fetching, "queued", lambda *a, **k: started.append("queued") or [])
    hold.hold(db, "owner: evals paused")
    assert cli.main(["fetch", "--day"]) == 0
    assert cli.main(["fetch", "--run"]) == 0
    out = capsys.readouterr().out
    assert started == [] and out.count("no fetch: benchmarks held since") == 2
    hold.release(db)
    assert cli.main(["fetch", "--day"]) == 0 and len(started) == 1
