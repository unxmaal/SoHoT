"""#1047: our llama-server plan refusing a stem before any load is never the candidate broken."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

from evals import run
from harness import coherence, context, downloads, ds4, reasons, screen, serving
from harness import memory_store as ms
from harness.commands import screen as screen_cmd
from harness.memory_store import revisit, transitions
from tests.test_context import GIB, QWEN3_4B, write_gguf

ROOT = Path(__file__).resolve().parent.parent
STEM = "Qwen3.8-27B-DFlash2-Q2_K_S-MIX"
#: A drafter's header: an architecture, and no context_length or attention keys under it.
NO_SHAPE = {"general.architecture": "dflash", "general.name": STEM}
# Verdict 12930's detail, as the 2026-10-19 day loop wrote it.
DETAIL_12930 = (f"the screen exited 1 || llamacpp:{STEM} is not served: refused: the GGUF header gives no "
                "trained context or KV shape to size a cache from")


@pytest.fixture
def models(tmp_path, monkeypatch):
    d = tmp_path / "gguf"
    d.mkdir()
    monkeypatch.setenv("LLAMACPP_MODELS_DIR", str(d))
    return d


@pytest.fixture
def conn():
    c = ms.connect()
    yield c
    c.close()


def _planned(conn, models, stem, meta, budget=60 * GIB):
    p = models / f"{stem}.gguf"
    write_gguf(p, meta)
    downloads.record(conn, "HermiHg/Qwen3.8-27B-DFlash2-Q2_K_S-MIX-GGUF", downloads.GGUF, p, file=p.name)
    return context.plan(conn, budget=budget)


def _refusal(stem, why, monkeypatch) -> str:
    """The text serving.route raises for a stem whose recorded plan says `why`."""
    monkeypatch.setattr(context, "refusal", lambda s, conn=None: why if s == stem else "")
    with pytest.raises(ValueError) as exc:
        serving.route(f"llamacpp:{stem}")
    return str(exc.value)


@pytest.mark.parametrize("candidate", [f"llamacpp:{STEM}", "HermiHg/Qwen3.8-27B-DFlash2-Q2_K_S-MIX-GGUF"])
def test_a_header_with_no_context_or_kv_shape_screens_as_our_gap(conn, models, candidate):
    plan = _planned(conn, models, STEM, NO_SHAPE)
    assert plan[0]["ctx"] == 0 and "no trained context or KV shape" in plan[0]["why"]
    proc = subprocess.run([sys.executable, "-m", "evals.run", "--modality", "code", "--screen", "--repeat", "1",
                           "--candidates", f"llamacpp:{STEM}"],
                          capture_output=True, text=True, cwd=ROOT, env=dict(os.environ), timeout=120)
    assert proc.returncode != 0 and "is not served: refused:" in proc.stderr, proc.stderr[-800:]
    v = screen_cmd.verdict_of_run(proc.returncode, proc.stderr, None, candidate)
    assert (v.outcome, v.reason, v.failure_class) == ("declined", reasons.RUNTIME, reasons.LOAD_FAILED_LAYOUT)
    assert v.until == f"plan:{STEM}"
    detail = screen_cmd.screen_detail(v.detail, proc.stderr, None)
    assert "the GGUF header gives no trained context or KV shape" in detail
    assert not transitions.incoherent(v.outcome, v.reason, v.until)


def _whys(models, conn):
    """Every refusal text the plan writes, from the plan's own functions."""
    meta = {**QWEN3_4B}
    short = models / "Short.gguf"
    write_gguf(short, meta)
    short.write_bytes(short.read_bytes()[:40])
    downloads.record(conn, "org/short", downloads.GGUF, short, file=short.name)
    unread = context.plan(conn, budget=60 * GIB)[0]["why"]
    return {
        "no-shape": context.choose(NO_SHAPE, GIB, 60 * GIB).why,
        "weights-over-budget": context.choose(meta, 61 * GIB, 60 * GIB).why,
        "kv-room-under-floor": context.choose(meta, 60 * GIB - 1024, 60 * GIB).why,
        "trained-under-floor": context.choose({**meta, "qwen3.context_length": 4096}, GIB, 60 * GIB).why,
        "slots-over-room": context.choose_slots(meta, GIB, 2 * GIB, 8, 262144).why,
        "slot-over-cap": context.choose_slots(meta, GIB, 60 * GIB, 1, 32768, kv_cap=GIB).why,
        "truncated-header": unread,
    }


EXPECTED = {
    "no-shape": reasons.LOAD_FAILED_LAYOUT,
    "weights-over-budget": reasons.PLAN_REFUSED,
    "kv-room-under-floor": reasons.PLAN_REFUSED,
    "trained-under-floor": reasons.PLAN_REFUSED,
    "slots-over-room": reasons.PLAN_REFUSED,
    "slot-over-cap": reasons.PLAN_REFUSED,
    "truncated-header": reasons.SHORT_COPY,
}


@pytest.mark.parametrize("kind", sorted(EXPECTED))
def test_every_plan_refusal_is_outside_the_candidate(kind, conn, models, monkeypatch):
    why = _whys(models, conn)[kind]
    assert why.startswith("refused: "), why
    text = _refusal("S", why, monkeypatch)
    assert reasons.classify(text, reasons.STDERR, "llamacpp:S") == EXPECTED[kind]
    assert reasons.classify(f"the screen exited 1 || {text}", reasons.RUNNER, "org/s-GGUF") == EXPECTED[kind]
    v = screen_cmd.verdict_of_run(1, text, None, "llamacpp:S")
    assert v.reason != reasons.CANDIDATE and v.failure_class == EXPECTED[kind]
    if v.outcome == "declined":
        assert v.until == "plan:S" and why in v.detail
    assert not transitions.incoherent(v.outcome, v.reason, v.until)


def test_a_plan_until_is_met_once_a_recorded_plan_serves_the_stem(conn, models):
    _planned(conn, models, STEM, NO_SHAPE)
    assert not context.planned(STEM)
    assert not revisit.until_met(f"plan:{STEM}", {})
    write_gguf(models / f"{STEM}.gguf", {**QWEN3_4B})
    context.plan(conn, budget=60 * GIB)
    assert context.planned(STEM)
    assert revisit.until_met(f"plan:{STEM}", {})
    assert revisit.until_met("plan:S", {"planned": {"S"}})
    assert not revisit.until_met("plan:S", {"planned": set()})
    assert not revisit.until_met("plan:", {"planned": {""}})


def test_a_ds4_serving_refusal_before_load_is_the_harness(monkeypatch):
    def refuse(spec):
        raise ds4.Unservable("no ds4-server at /x/ds4-server; build it with scripts/ds4-build.sh")
    monkeypatch.setattr(ds4, "preflight", refuse)
    with pytest.raises(SystemExit) as exc:
        run._servable("ds4:DeepSeek-V4-Flash-Q2")
    v = screen_cmd.verdict_of_run(1, str(exc.value), None, "ds4:DeepSeek-V4-Flash-Q2")
    assert (v.outcome, v.reason, v.failure_class) == ("queued", reasons.HARNESS, reasons.HARNESS_ERROR)


def test_a_spec_no_text_server_routes_is_the_harness():
    with pytest.raises(ValueError) as exc:
        serving.route("weird:thing")
    assert reasons.classify(str(exc.value), reasons.STDERR, "weird:thing") == reasons.HARNESS_ERROR


def test_a_candidate_failure_stays_the_candidates():
    text = "the screen exited 1 || RuntimeError: shape mismatch in layer 3"
    assert reasons.classify(text, reasons.RUNNER, f"llamacpp:{STEM}") == reasons.CRASHED
    assert reasons.plan_refusal(text) == ("", "")
    assert screen.decide_class(reasons.CRASHED, text, f"llamacpp:{STEM}").until == ""


def _broken(conn, name, detail):
    ms.record(conn, ms.Seen(name=name, source="t", registry=ms.HUGGINGFACE, lane="code", resolved=name))
    pid = conn.execute("SELECT id FROM proposals WHERE name = ?", (name,)).fetchone()[0]
    transitions._write(conn, pid, name, {"outcome": "broken", "tier": "screen", "detail": detail,
                                         "decided_at": 1792406712.0, "until": "", "reason": "candidate",
                                         "failure_class": reasons.CRASHED})
    conn.commit()


def test_coherence_re_decides_the_broken_screen_12930_wrote(tmp_path):
    store = ms.connect(tmp_path / "s.db")
    try:
        _broken(store, "HermiHg/Qwen3.8-27B-DFlash2-Q2_K_S-MIX-GGUF", DETAIL_12930)
        found = coherence.changes(store)
        assert [c["name"] for c in found] == ["HermiHg/Qwen3.8-27B-DFlash2-Q2_K_S-MIX-GGUF"]
        assert found[0]["now"] == ["declined", "screen", reasons.RUNTIME, f"plan:{STEM}"]
        coherence.apply(store, found)
        held = store.execute("SELECT p.state, v.reason, v.until, v.failure_class FROM proposals p "
                             "JOIN verdicts v ON v.id = p.state_verdict_id").fetchone()
        assert tuple(held) == ("declined", reasons.RUNTIME, f"plan:{STEM}", reasons.LOAD_FAILED_LAYOUT)
        assert coherence.changes(store) == []
    finally:
        store.close()


def test_coherence_holds_a_drafter_as_an_attachment_whatever_its_plan_refusal_says(tmp_path):
    import json
    store = ms.connect(tmp_path / "s.db")
    try:
        name = "HermiHg/Qwen3.8-27B-DFlash2-Q2_K_S-MIX-GGUF"
        _broken(store, name, DETAIL_12930)
        store.execute("UPDATE proposals SET card_tags = ?, card_read = 'card' WHERE name = ?",
                      (json.dumps(["gguf", "draft-model"]), name))
        found = coherence.changes(store)
        assert [(c["name"], c["now"], c.get("attach")) for c in found] == [
            (name, ["declined", "fetch", reasons.CANDIDATE, ""], screen.DRAFTER)]
    finally:
        store.close()


def test_the_audit_warns_on_a_pinned_misread_broken_screen_and_fails_a_new_one(tmp_path):
    from harness import live_audit
    store = ms.connect(tmp_path / "s.db")
    try:
        _broken(store, "HermiHg/Qwen3.8-27B-DFlash2-Q2_K_S-MIX-GGUF", DETAIL_12930)
        vid = store.execute("SELECT state_verdict_id FROM proposals").fetchone()[0]
        bad, known = live_audit._broken_runner_layout(store, pinned=frozenset({vid}))
        assert bad == [] and len(known) == 1
        bad, known = live_audit._broken_runner_layout(store, pinned=frozenset())
        assert len(bad) == 1 and known == []
        coherence.apply(store, coherence.changes(store))
        assert live_audit._broken_runner_layout(store, pinned=frozenset()) == ([], [])
    finally:
        store.close()
