"""#727: the contamination HIT is set between known-clean and known-trained passages, never by hand."""
from __future__ import annotations

import pytest

from harness import contamination as ct
from harness import knobs
from harness import memory_store as ms


@pytest.fixture
def store(tmp_path):
    conn = ms.connect(tmp_path / "s.db")
    yield conn
    conn.close()


def _probes(conn, model, kind, overlaps, lane="calibration", at=1.0):
    for i, o in enumerate(overlaps):
        ms.record_probe(conn, model=model, lane=lane, case_id=f"{kind}-{i:03d}", family=kind,
                        outcome="hit" if o >= 0.5 else "miss", overlap=o, at=at)


def _sets(conn, model, clean, canon, wiki=None):
    _probes(conn, model, "clean", clean)
    _probes(conn, model, "canon", canon)
    _probes(conn, model, "wiki", wiki if wiki is not None else [0.0] * len(clean))


def _model(got, model):
    return next(m for m in got["models"] if m["model"] == model)


def test_hit_is_the_smallest_knob_value_above_the_clean_passages_overlap_quantile(store):
    _sets(store, "m", [0.0] * 18 + [0.25, 0.125], [1.0] * 20)
    got = ct.calibrate(store, share=0.95, min_passages=10, values=(0.125, 0.25, 0.5, 0.75, 1.0))
    m = _model(got, "m")
    assert m["clean_quantile"] == 0.125
    assert m["derived"] == 0.25 and got["derived"] == 0.25


def test_a_model_that_reproduces_clean_passages_raises_the_derived_hit_for_every_model(store):
    _sets(store, "low", [0.0] * 20, [1.0] * 20)
    _sets(store, "loose", [0.5] * 20, [1.0] * 20)
    got = ct.calibrate(store, share=0.95, min_passages=10, values=(0.25, 0.5, 0.75, 1.0))
    assert (_model(got, "low")["derived"], _model(got, "loose")["derived"]) == (0.25, 0.75)
    assert got["derived"] == 0.75


def test_canon_sensitivity_is_reported_at_the_derived_hit(store):
    _sets(store, "m", [0.0] * 20, [1.0] * 10 + [0.25] * 5 + [0.0] * 5)
    m = _model(ct.calibrate(store, share=0.95, min_passages=10, values=(0.25, 0.5)), "m")
    assert m["derived"] == 0.25 != ct.HIT and m["sensitivity"] == 0.75


def test_the_clean_quantile_rounds_up_so_no_more_than_the_share_falls_above_it(store):
    _sets(store, "m", [0.0] * 17 + [0.125, 0.25], [1.0] * 19)
    m = _model(ct.calibrate(store, share=0.95, min_passages=10, values=(0.125, 0.25, 0.5, 1.0)), "m")
    assert (m["clean_quantile"], m["derived"]) == (0.25, 0.5)


def test_too_few_probed_passages_leave_the_derivation_provisional(store, tmp_path):
    from harness.commands import benchmarks as cmd
    _sets(store, "m", [0.9] * 20, [1.0] * 4)
    got = ct.calibrate(store, share=0.95, min_passages=10)
    assert _model(got, "m")["status"] == "provisional" and got["status"] == "provisional"
    assert got["agrees"] is True
    args = type("A", (), {"db": str(tmp_path / "s.db"), "calibrate": True})()
    assert cmd.cmd_calibrate(args) == 0


def test_the_wiki_control_rate_is_reported_beside_the_squad_rate(store):
    _sets(store, "m", [0.0] * 20, [1.0] * 20, wiki=[1.0] * 5 + [0.0] * 15)
    _probes(store, "m", "check", [1.0] * 2 + [0.0] * 8, lane="decide")
    m = _model(ct.calibrate(store, share=0.95, min_passages=10, values=(0.25, 0.5)), "m")
    assert (m["wiki_rate"], m["squad_rate"]) == (0.25, 0.2)
    assert (m["n"]["wiki"], m["n"]["squad"]) == (20, 10)


def test_each_passage_counts_once_at_its_newest_probe(store):
    _sets(store, "m", [0.0] * 20, [1.0] * 20)
    _probes(store, "m", "clean", [0.75], at=2.0)
    _probes(store, "m", "wiki", [1.0] * 5, lane="decide")
    m = _model(ct.calibrate(store, share=0.95, min_passages=10, values=(0.25, 0.5, 1.0)), "m")
    assert m["n"]["clean"] == 20 and m["clean_quantile"] == 0.0
    assert (m["n"]["wiki"], m["wiki_rate"]) == (20, 0.0)


def test_the_passages_fixture_holds_each_set_with_its_source_and_license():
    from evals import contamination_passages as cp
    rows = cp.manifest()
    by = {k: [r for r in rows if r["set"] == k] for k in ct.SETS}
    assert all(len(v) >= 30 for v in by.values()), {k: len(v) for k, v in by.items()}
    assert len({r["id"] for r in rows}) == len(rows)
    for r in rows:
        assert r["id"].startswith(r["set"] + "-") and r["source"].startswith("https://")
        assert r["license"] in ("CC BY-SA 4.0", "public domain")
        assert ct.split_prefix(r["text"]) is not None, r["id"]
    assert all(r["created"] >= cp.CLEAN_AFTER for r in by["clean"])
    assert all(r["created"] < cp.OLD_BEFORE for r in by["wiki"])


def test_the_passage_builder_drops_verse_numbers_and_keeps_its_words():
    from evals import contamination_passages as cp
    text = "1:1 In the beginning God created the heaven and the earth. 1:2 And the earth was " + "word " * 80
    got = cp.passage(text, verses=True)
    assert got.startswith("In the beginning God created") and "1:2" not in got
    assert len(got.split()) == cp.WORDS
    assert cp.passage("Left Munich at 8:35 P. M., on 1st May " + "word " * 80).startswith("Left Munich at 8:35 P. M.")


def test_a_passage_probe_records_lane_calibration_with_the_set_as_family(store):
    from evals import contamination_passages as cp
    rows = [r for r in cp.manifest() if r["set"] == "canon"][:2]
    target = ct.split_prefix(rows[0]["text"])[1]
    got = ct.probe(store, "m", ct.passage_cases(rows), lambda model, prompt: target, lane="calibration")
    assert [(r["lane"], r["family"], r["outcome"]) for r in got][0] == ("calibration", "canon", "hit")
    assert store.execute("SELECT COUNT(*) FROM contamination_probes WHERE lane = 'calibration'").fetchone()[0] == 2


def test_a_complete_derivation_that_disagrees_with_contamination_hit_fails_the_command(store, tmp_path):
    from harness.commands import benchmarks as cmd
    _sets(store, "m", [0.75] * 20, [1.0] * 20)
    got = ct.calibrate(store, share=0.95, min_passages=10)
    assert got["status"] == "derived" and got["derived"] == 1.0 != got["current"] == ct.HIT
    assert got["agrees"] is False
    args = type("A", (), {"db": str(tmp_path / "s.db"), "calibrate": True})()
    assert cmd.cmd_calibrate(args) == 1


def test_clean_passages_reproduced_in_full_leave_no_hit_to_derive(store):
    _sets(store, "m", [1.0] * 20, [1.0] * 20)
    got = ct.calibrate(store, share=0.95, min_passages=10)
    assert _model(got, "m")["status"] == "above range" and got["agrees"] is False


def test_the_calibration_knobs_carry_a_unit_a_range_and_their_evidence():
    for name in ("contamination_clean_share", "contamination_min_passages", "contamination_hit"):
        k = knobs.KNOBS[name]
        assert k.unit and k.default() in k.values and "#727" in k.note, name
    assert knobs.KNOBS["contamination_hit"].grades is True


def test_a_reply_whose_template_opened_the_think_block_is_scored_after_its_close():
    class R:
        def __init__(self, content):
            self.content = content

        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": self.content}, "finish_reason": "stop"}]}

    reply = "is a singular trait, and I guess so\n</think>\n\nis the very continuation of the source text here now"
    ask = ct.gateway_ask("http://gw", post=lambda *a, **k: R(reply))
    assert ask("m", "p") == "is the very continuation of the source text here now"
    ask = ct.gateway_ask("http://gw", post=lambda *a, **k: R("<think>x</think>kept"))
    assert ask("m", "p") == "kept"
