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
