"""The code and decide holdouts grown past the lane gate's power bar with room to spare. #2195."""
import re

from evals import importers
from evals.core import load_cases
from evals.importers import code_synth
from harness import holdout

#: Live `soh lane-gate status`, 2026-11-28: the holdout each lane held and the gate's projected power at it.
LIVE = {"code": (463, 0.74), "decide": (132, 0.79)}
#: Holdout at which the gate projected power 0.85 from that day's incumbent draws.
AT_085 = {"code": 663, "decide": 152}


def _holdout(lane):
    return len(holdout.for_lane(lane).holdout)


def test_each_lane_holds_out_enough_for_power_point_eight_five():
    for lane, need in AT_085.items():
        assert _holdout(lane) >= need, (lane, _holdout(lane), need)


def test_the_long_pipelines_come_after_every_older_code_case_and_leave_them_alone():
    rows = code_synth.fetch()
    assert len(rows) == code_synth.COUNT > code_synth.LONG_FROM
    assert rows[:code_synth.LONG_FROM] == code_synth.fetch(count=code_synth.LONG_FROM)
    for row in rows[code_synth.LONG_FROM:]:
        steps = int(re.match(r"(?:strs|ints)-(\d+)-steps", row["stratum"]).group(1))
        assert steps in code_synth.LONG_STEPS, row["item"]
    assert not any(int(re.match(r"\w+-(\d+)-steps", r["stratum"]).group(1)) in code_synth.LONG_STEPS
                   for r in rows[:code_synth.LONG_FROM] if re.match(r"\w+-\d+-steps", r["stratum"]))


def test_the_long_pipelines_add_holdout_cases():
    side = holdout.for_lane("code")
    cases = load_cases(importers.CASES / "code")
    added = sum(1 for c in cases if c.id.startswith("code-synth-") and int(c.id[-4:]) >= code_synth.LONG_FROM
                and side.side(c.id) == "holdout")
    assert added >= 200, added


def test_the_decide_holdout_grows_with_its_route_and_policy_cases_and_keeps_one_family_to_half():
    side = holdout.for_lane("decide")
    families = {}
    for cid in side.holdout:
        families[holdout.family(cid)] = families.get(holdout.family(cid), 0) + 1
    assert families["route-massive"] >= 36
    assert max(families.values()) <= holdout.FAMILY_SHARE * len(side.holdout)
