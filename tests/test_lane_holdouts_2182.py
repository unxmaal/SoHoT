"""The claims and pii lanes grown to their holdout target by generated cases with planted-wrong controls. #2182."""
import json
import re

import pytest

from evals import importers
from evals.core import case_digest, load_cases
from evals.importers import claims_synth, pii_synth
from harness import adopt, cli, holdout

SOURCES = {"claims": claims_synth, "pii": pii_synth}
#: Live `soh lane-gate status` at release 163: holdout cases each lane was short of its target.
SHORT = {"claims": 57, "pii": 183}
#: The shipped holdout before this import (claims are local-only, so none are shipped).
BEFORE = {"claims": 0, "pii": 166}
SHIPPED = {lane: load_cases(importers.CASES / lane / f"{lane}_synth") for lane in SOURCES}


def _row(capsys, monkeypatch, lane):
    monkeypatch.setattr(adopt, "FAMILY", 1)  # these holdouts were sized to the first comparison's level
    monkeypatch.setattr(adopt, "default_for", lambda lane, fallback, *a, **k: "inc")
    assert cli.main(["adopt", "--json", "--power", "--lane", lane]) == 0
    return {r["lane"]: r for r in json.loads(capsys.readouterr().out)["lanes"]}[lane]


@pytest.mark.parametrize("lane", sorted(SOURCES))
def test_the_power_table_reads_each_lane_at_or_above_0_8(capsys, monkeypatch, lane):
    row = _row(capsys, monkeypatch, lane)
    assert row["power"] >= 0.8, (lane, row["power"], row["holdout"], row["cases_needed"])
    assert row["holdout"] >= BEFORE[lane] + SHORT[lane]
    assert row["more_holdout"] == 0


@pytest.mark.parametrize("lane", sorted(SOURCES))
def test_each_generator_ships_every_case_it_draws_and_nothing_else(lane, tmp_path):
    mod = SOURCES[lane]
    assert len(SHIPPED[lane]) == mod.COUNT
    importers.run(f"{lane}_synth", root=tmp_path)
    fresh = load_cases(tmp_path / lane / f"{lane}_synth")
    assert [case_digest(c) for c in fresh] == [case_digest(c) for c in SHIPPED[lane]]


@pytest.mark.parametrize("lane", sorted(SOURCES))
def test_the_draws_repeat_and_every_case_is_generated_not_copied(lane):
    mod = SOURCES[lane]
    assert mod.fetch(count=40) == mod.fetch(count=40)
    assert mod.fetch(seed=mod.SEED + 1, count=10) != mod.fetch(count=10)
    assert mod.LICENSE == "generated" and mod.SOURCE.startswith("generated:")
    ids = [c.id for c in SHIPPED[lane]]
    assert len(set(ids)) == len(ids)
    assert len({c.prompt + json.dumps(c.params, sort_keys=True) for c in SHIPPED[lane]}) == len(ids)


@pytest.mark.parametrize("lane", sorted(SOURCES))
def test_the_planted_wrong_answer_fails_every_new_case_and_the_reference_passes_every_one(lane):
    mod = SOURCES[lane]
    got = importers.negative_control(SHIPPED[lane], mod.RESPONDERS, mod.passes)
    n = len(SHIPPED[lane])
    assert got["reference"] == (n, n)
    assert got["planted"] == (0, n)


def test_a_do_nothing_reply_is_neither_all_right_nor_all_wrong_on_claims_and_pii():
    for lane, mod, nothing in (("claims", claims_synth, "nothing"), ("pii", pii_synth, "nothing")):
        got = importers.negative_control(SHIPPED[lane], {nothing: mod.RESPONDERS[nothing]}, mod.passes)[nothing]
        assert 0 < got[0] < got[1], lane


# --- pii: the extension leaves the first cases alone and adds kinds ---

def test_the_cases_shipped_before_the_extension_are_unchanged_and_the_new_ones_add_kinds():
    first = pii_synth.fetch(count=pii_synth.EXTENDED_FROM)
    assert first == pii_synth.fetch()[: pii_synth.EXTENDED_FROM]
    old = {k for r in first for k in r["kinds"]}
    new = {k for r in pii_synth.fetch()[pii_synth.EXTENDED_FROM:] for k in r["kinds"]}
    assert {"dob", "ssn", "passport", "handle"} <= new - old
    assert re.fullmatch(r"9\d\d-\d\d-\d{4}", next(l for r in pii_synth.fetch() for l in r["labels"]
                                                  if "ssn" in r["kinds"]))


def test_pii_planted_reply_marks_nothing_where_data_is_and_everything_where_none_is():
    for c in SHIPPED["pii"][:200]:
        spans = json.loads(pii_synth.RESPONDERS["planted"](c))["spans"]
        assert (spans == []) == bool(c.assertions["pii"])


# --- claims: reviews point at real lines, and each reviewed case carries a rejected claim ---

def test_every_reviewed_claims_case_has_a_good_review_a_rejected_one_and_refs_into_the_chat():
    from harness.checks import claims as check
    reviewed = [c for c in SHIPPED["claims"] if not c.assertions.get("expect_empty")]
    assert 0.3 * len(SHIPPED["claims"]) < len(reviewed) < 0.8 * len(SHIPPED["claims"])
    for c in reviewed:
        lines = {int(m.group(1)): (m.group(2), m.group(3)) for m in
                 (re.match(r"\[(\d+)\] (\S+): (.*)", x) for x in c.prompt.splitlines())}
        verdicts = [r["verdict"] for r in c.assertions["reviews"]]
        assert "good" in verdicts and ({"wrong", "made_up"} & set(verdicts)), c.id
        for r in c.assertions["reviews"]:
            check.validate_case(c.params["system"], c.params["schema"], [r], False)
            assert all(lines[ref][0] == r["user"] for ref in r["refs"]), c.id
            assert all(r["claim"] != lines[ref][1] for ref in r["refs"])


def test_a_rejected_claim_is_never_also_a_good_one():
    for c in SHIPPED["claims"]:
        reviews = c.assertions.get("reviews") or []
        good = {r["claim"] for r in reviews if r["verdict"] == "good"}
        assert not good & {r["claim"] for r in reviews if r["verdict"] in ("wrong", "made_up")}, c.id


def test_the_claims_planted_reply_fails_each_case_for_a_reason_that_is_not_only_missing_recall():
    from harness.checks import claims as check
    reviewed = [c for c in SHIPPED["claims"] if not c.assertions.get("expect_empty")]
    for c in reviewed[:200]:
        got = check.check(claims_synth.RESPONDERS["planted"](c), c.params["schema"], c.assertions["reviews"])
        assert not got.ok and "rejected" in got.reason, c.id


def test_each_lane_holds_more_holdout_than_its_target_from_these_cases_alone():
    for lane in SOURCES:
        side = holdout.assign(lane, SHIPPED[lane])
        assert len(side.holdout) >= SHORT[lane], lane
