"""#1007: the stt screen asks for a plausible transcript, and power plans on the per-clip WER the gate pairs on."""
import json
from dataclasses import replace
from pathlib import Path

import pytest

from evals import core
from harness import adopt, cli, holdout, power, screen

REFERENCE = "Stuff it into you his belly counselled him"
RUN9 = Path(__file__).parent / "fixtures" / "stt_run9" / "rows.jsonl"
V2, V3 = "parakeet-tdt-0.6b-v2", "parakeet-tdt-0.6b-v3"


def _screened(heard: str, lane: str = "stt"):
    case = core.Case(id="1089-134686-0001", modality="stt", prompt=REFERENCE,
                     assertions={"max_wer": 0.0}, source=Path("1089-134686-0001.yaml"))
    row = replace(core.score(case, heard), candidate="m", seconds=0.1)
    return screen.outcome(0, core.summarize([row]), lane=lane)


def test_one_wrong_word_on_one_clip_passes_the_stt_screen():
    got = _screened("Stuff it into you, his belly counseled him.")
    assert got.outcome == "screened", got


@pytest.mark.parametrize("heard", ["", "the", "the the the the the the the the the the the the the the"])
def test_an_empty_or_degenerate_transcript_does_not(heard):
    got = _screened(heard)
    assert got.outcome == "declined" and got.failure_class == "content_failed", got


def test_the_plausibility_screen_is_the_stt_lanes_alone():
    assert _screened("Stuff it into you, his belly counseled him.", lane="tts").outcome == "declined"


def _run9():
    return [json.loads(line) for line in RUN9.read_text(encoding="utf-8").splitlines() if line]


def test_the_gate_adopts_v2_over_v3_on_the_run9_rows():
    rows = _run9()
    got = adopt.decide("stt", adopt._summary(rows, V3), adopt._summary(rows, V2), rows)
    assert got.adopt, got.why


def test_soh_adopt_power_plans_on_wer_not_saturated_pass_bits(tmp_path, capsys, monkeypatch):
    rows = _run9()
    assert all(r["passed"] for r in rows)
    ids = tuple(sorted({r["case_id"] for r in rows}))
    monkeypatch.setattr(holdout, "splits", lambda root=None: {"stt": holdout.Split("stt", (), ids, False)})
    monkeypatch.setattr(adopt, "default_for", lambda lane, fallback, *a, **k: V3)
    receipt = tmp_path / "results.json"
    receipt.write_text(json.dumps({"receipt": {"modality": "stt"}, "environment": {},
                                   "rows": [r for r in rows if r["candidate"] == V3]}), encoding="utf-8")
    assert cli.main(["adopt", "--json", "--power", "--lane", "stt", "--receipt", str(receipt)]) == 0
    row = json.loads(capsys.readouterr().out)["lanes"][0]
    assert row["incumbent"] == V3 and row["holdout"] == len(ids)
    assert row["power"] > 0 and row["cases_needed"] is not None, row


def test_a_metric_row_draws_on_its_metric_and_a_row_without_one_on_its_pass_bit():
    assert power.draw({"passed": True, "metrics": '{"wer": 0.125}'}, "stt") == 0
    assert power.draw({"passed": False, "metrics": {"wer": 0.0}}, "stt") == 1
    assert power.draw({"passed": True, "metrics": {"wer": 0.125}}, "code") == 1
    assert power.draw({"passed": True, "metrics": {}}, "stt") == 1
    assert power.draw({"passed": False, "metrics": {"decide_accuracy": 1.0}}, "decide") == 1


def test_a_known_better_plant_matches_when_the_lane_serves_its_engine_spelling():
    from harness import canary
    better, worse = (next(p for p in canary.PLANTS if p.name == n) for n in ("stt-known-better", "stt-known-worse"))
    served = "stt:mlx-community/parakeet-tdt-1.1b"
    assert canary.matches(better, {"outcome": "measured", "tier": "adopt", "reason": "candidate", "serves": served})
    assert canary.matches(worse, {"outcome": "declined", "tier": "adopt", "reason": "candidate", "serves": served})
    assert not canary.matches(better, {"outcome": "measured", "tier": "adopt", "serves": "stt:mlx-community/parakeet-tdt-0.6b-v3"})


def _row(wer, n=None):
    row = {"passed": 0, "metrics": {} if wer is None else {"wer": wer}}
    if n is not None:
        row["metric_n"] = {"wer": n}
    return row


@pytest.mark.parametrize("lane", ["stt", " STT ", "Stt"])
def test_the_plausible_wer_is_the_worst_heard_clip_set_on_an_stt_lane(lane):
    assert screen.plausible_wer({"a": _row(0.2), "b": _row("0.4", n=3)}, lane) == pytest.approx(0.4)


@pytest.mark.parametrize("summary", [None, {}])
@pytest.mark.parametrize("lane", ["stt", "tts", "", None])
def test_no_summary_or_another_lane_has_no_plausible_wer(summary, lane):
    assert screen.plausible_wer(summary, lane) is None


@pytest.mark.parametrize("lane", ["tts", "code", "", None])
def test_another_lane_has_no_plausible_wer_however_well_it_heard(lane):
    assert screen.plausible_wer({"a": _row(0.1)}, lane) is None
    assert screen.plausible_wer({"m": _row(0.1)}, lane, "m") is None


def test_the_limit_is_inclusive_and_one_clip_set_over_it_fails_the_screen():
    at = screen.SCREEN_MAX_WER
    assert screen.plausible_wer({"a": _row(at)}, "stt") == at
    assert screen.plausible_wer({"a": _row(at + 0.01)}, "stt") is None
    assert screen.plausible_wer({"a": _row(0.1), "b": _row(0.9)}, "stt") is None


def test_a_row_with_no_wer_or_no_words_scored_is_not_heard():
    assert screen.plausible_wer({"a": _row(None)}, "stt") is None
    assert screen.plausible_wer({"a": {"passed": 0}}, "stt") is None
    assert screen.plausible_wer({"a": _row(0.3, n=0)}, "stt") is None
    assert screen.plausible_wer({"a": _row(0.3, n=0), "b": _row(0.2, n=1)}, "stt") == pytest.approx(0.2)
    assert screen.plausible_wer({"a": {"passed": 0, "metrics": {"wer": None}, "metric_n": {"wer": 2}}}, "stt") is None


def test_a_named_candidate_is_judged_on_its_own_row_alone():
    summary = {"m": _row(0.2), "other": _row(0.9)}
    assert screen.plausible_wer(summary, "stt", "m") == pytest.approx(0.2)
    assert screen.plausible_wer(summary, "stt", "other") is None
    assert screen.plausible_wer(summary, "stt", "absent") is None
    # The key its runner wrote wins over the spec's own key.
    assert screen.plausible_wer({"k": _row(0.1), "m": _row(0.8)}, "stt", "m", "k") == pytest.approx(0.1)


def test_the_screen_counts_on_the_incumbents_pass_bits_where_adopt_counts_on_its_wer(store_run, monkeypatch):
    from harness import candidates, winners
    from harness import memory_store as ms
    rows = [r for r in _run9() if r["candidate"] == V2][:4]
    for r in rows:
        r["metrics"] = {**r["metrics"], "wer": 0.125}
    spec = f"stt:mlx-community/{V2}"
    store_run("20261019-000000-stt", "stt", specs={V2: spec},
              rows=[{**r, "seconds": 0.1, "peak_kb": 0, "detail": ""} for r in rows])
    conn = ms.connect()
    try:
        # The typed stt default differs by platform (whisper on win32), so the served row is named here.
        cid = candidates.served(conn, spec, lane="stt")
        monkeypatch.setattr(winners, "served_ids", lambda c: {"stt": cid})
        ids = [r["case_id"] for r in rows]
        assert screen.incumbent_draws("stt", conn) == {i: [1] for i in ids}
    finally:
        conn.close()
    assert screen.incumbent_rate("stt", ids) == 1.0


def test_a_plausible_transcript_screens_the_candidate_on_its_own_row_under_its_runners_key():
    summary = {"stt:org/k": {**_row(0.2), "failure_classes": {"content_failed": 1}},
               "m": {**_row(0.9), "failure_classes": {"content_failed": 1}}}
    got = screen.outcome(0, summary, candidate="m", key="stt:org/k", lane="stt")
    assert got == screen.Verdict(
        "screened", "it transcribed the screen at corpus WER 0.20, under the 0.5 plausibility limit, "
        "though no clip was word-perfect", "candidate")
    assert screen.outcome(0, summary, candidate="m", lane="stt").outcome == "declined"
