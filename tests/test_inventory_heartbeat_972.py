"""A live_audit check whose backlog a loop step repairs warns until that step marks its own heartbeat key. #972."""
import pytest

from harness import heartbeat, live_audit, reasons
from harness import memory_store as ms
from harness.commands import loop as loop_cmd
from tests.test_runner_gap_until_950 import _gateway, _vlm
from tests.test_runner_gap_until_950 import _seed as _seed_gap

SUMMED = "too-big: smallest weight it names is 223.2 GiB, over the 66 GiB ceiling"


def _hf(conn, name):
    ms.record(conn, ms.Seen(name=name, source="t", resolved=name, kind="weights", registry=ms.HUGGINGFACE))


def _summed(conn):
    _hf(conn, "org/summed")
    ms.decide(conn, "org/summed", "declined", tier=ms.INSPECT, reason="machine", until="ceiling_gb:>223.2",
              detail=SUMMED, ceiling_gb=66.0)
    return "org/summed"


def _unranked(conn):
    _hf(conn, "sesame/csm-1b")
    ms.decide(conn, "sesame/csm-1b", "ignored", tier=ms.INSPECT, reason=reasons.CANDIDATE, detail=ms.UNRANKED)
    return "sesame/csm-1b"


def _attached(conn):
    _hf(conn, "inclusionAI/VISTA-9B")
    conn.execute("UPDATE proposals SET attaches_to = 'gui', card_read = 'description', card_tags = '[]' "
                 "WHERE name = 'inclusionAI/VISTA-9B'")
    ms.decide(conn, "inclusionAI/VISTA-9B", "queued", tier=ms.INSPECT, reason=reasons.CANDIDATE, detail="fits")
    return "inclusionAI/VISTA-9B"


def _gap(conn):
    _seed_gap(conn, "LiquidAI/LFM2.5-VL-3B", "code", _vlm("lfm2_vl"), "declined", ms.SCREEN,
              "the installed runtime could not load it: " + _gateway("Model type lfm2_vl not supported."),
              until="version:mlx-lm>0.32.0", reason=reasons.RUNTIME)
    return "LiquidAI/LFM2.5-VL-3B"


BACKLOGS = {"too_big_names_variant": _summed, "no_ranking_verdict": _unranked,
            "attachment_by_tag": _attached, "runner_gap_until_current": _gap}


def _decided(conn, name):
    return conn.execute("SELECT v.decided_at FROM proposals p JOIN verdicts v ON v.id = p.state_verdict_id "
                        "WHERE p.name = ?", (name,)).fetchone()[0]


def _audit(check, seed, marks=None):
    conn = ms.connect()
    try:
        name = seed(conn)
        conn.commit()
        at = _decided(conn, name)
    finally:
        conn.close()
    heartbeat.start()
    for key, offset in (marks or {}).items():
        heartbeat.mark(key, at + offset)
    heartbeat.finish(0)
    return name, {c["name"]: c for c in live_audit.audit(ms.db_path())["checks"]}[check]


@pytest.mark.parametrize("check", sorted(BACKLOGS))
def test_a_backlog_with_no_repair_mark_warns_and_does_not_fail(check):
    name, got = _audit(check, BACKLOGS[check])
    assert got["ok"] and got["warn"] and name in got["detail"]
    assert live_audit.REPAIRED_BY[check] in got["detail"]


@pytest.mark.parametrize("check", sorted(BACKLOGS))
def test_a_row_decided_before_its_repairs_mark_fails(check):
    name, got = _audit(check, BACKLOGS[check], {live_audit.REPAIRED_BY[check]: 60})
    assert not got["ok"] and not got["warn"] and name in got["detail"]


@pytest.mark.parametrize("check", sorted(BACKLOGS))
def test_a_row_decided_after_its_repairs_mark_still_only_warns(check):
    _, got = _audit(check, BACKLOGS[check], {live_audit.REPAIRED_BY[check]: -60})
    assert got["ok"] and got["warn"]


def test_a_requeue_from_code_that_predates_variant_sizing_does_not_fail_the_variant_check():
    _, got = _audit("too_big_names_variant", _summed, {heartbeat.REOPENED_TOO_BIG: 60})
    assert got["ok"] and got["warn"]


def test_every_repaired_check_waits_on_a_key_the_next_loop_keeps():
    assert set(live_audit.REPAIRED_BY) <= set(live_audit.VERDICTS)
    assert set(live_audit.REPAIRED_BY.values()) <= set(heartbeat.KEPT)
    heartbeat.start()
    for key in heartbeat.KEPT:
        heartbeat.mark(key, 1234.0)
    heartbeat.finish(0)
    heartbeat.start()
    assert all(heartbeat.marked(key) == 1234.0 for key in heartbeat.KEPT)


def _noop(*_a, **_k):
    return []


STEPS = {
    "too_big_names_variant": (lambda: loop_cmd._reopen_stale_too_big(),
                              {"requeue_stale_too_big": _noop, "requeue_old_sizing": _noop}),
    "no_ranking_verdict": (lambda: loop_cmd._reopen_unranked(), {"requeue_unranked": _noop}),
    "attachment_by_tag": (lambda: loop_cmd._rederive_attachments(),
                          {"rederive_attachments": lambda *a, **k: {"read": 0, "changed": [], "requeued": [],
                                                                    "unread": [], "gone": []}}),
    "revisitable": (lambda: loop_cmd._reopen_revisitable(), {"revisitable": _noop, "requeue_revisitable": _noop}),
    "runner_gap_until_current": (lambda: loop_cmd._reread_runtime_declines(None),
                                 {"cards_to_reread": _noop, "rewrite_runner_gap_untils": _noop}),
}


@pytest.mark.parametrize("check", sorted(STEPS))
def test_each_repair_step_marks_its_own_key_from_when_it_began(check, monkeypatch):
    run, fakes = STEPS[check]
    for attr, fake in fakes.items():
        monkeypatch.setattr(ms, attr, fake)
    key = live_audit.REPAIRED_BY[check]
    heartbeat.start()
    began = heartbeat.clock()
    run()
    got = heartbeat.marked(key)
    assert got is not None and began <= got <= heartbeat.clock()
    assert all(heartbeat.marked(other) is None for other in set(live_audit.REPAIRED_BY.values()) - {key}
               if other != heartbeat.REOPENED_TOO_BIG)


def test_a_re_read_that_left_cards_unread_marks_nothing(monkeypatch):
    monkeypatch.setattr(ms, "rederive_attachments", lambda *a, **k: {
        "read": 0, "changed": [], "requeued": [], "unread": ["org/x: 429"], "gone": []})
    heartbeat.start()
    loop_cmd._rederive_attachments()
    assert heartbeat.marked(heartbeat.REDERIVED_ATTACHMENTS) is None
