"""The code and extract lanes grown to their holdout target by generated cases with known-answer controls. #603."""
import copy
import json
import re

import pytest
import yaml

from evals import importers
from evals.core import case_digest, load_cases
from evals.importers import code_synth, extract_synth
from harness import adopt, cli, holdout

CODE_DIR = importers.CASES / "code" / "code_synth"
EXTRACT_DIR = importers.CASES / "extract" / "extract_synth"
#: Live `soh adopt --power --table`, 2026-11-27: holdout cases each lane was short of its target.
SHORT = {"code": 241, "extract": 500}
#: Holdout and cases in each lane before this import (the hand-written and imported sets already shipped).
BEFORE = {"code": {"holdout": 135, "cases": 451}, "extract": {"holdout": 152, "cases": 450}}


def _table_row(capsys, monkeypatch, lane):
    monkeypatch.setattr(adopt, "default_for", lambda lane, fallback, *a, **k: "inc")
    assert cli.main(["adopt", "--json", "--power", "--lane", lane]) == 0
    return {r["lane"]: r for r in json.loads(capsys.readouterr().out)["lanes"]}[lane]


def _check_in_process(source, checks):
    """(passed, failed) check expressions of `source`, run in this process: the generator's own code only."""
    ns: dict = {}
    exec(source, ns)  # noqa: S102
    failed = []
    for c in checks:
        try:
            ok = bool(eval(c, ns))  # noqa: S307
        except Exception:
            ok = False
        if not ok:
            failed.append(c)
    return len(checks) - len(failed), failed


SHIPPED_CODE = load_cases(CODE_DIR)
SHIPPED_EXTRACT = load_cases(EXTRACT_DIR)


# --- the count and holdout size of each lane after the import, from the power table ---

@pytest.mark.parametrize("lane", ["code", "extract"])
def test_the_power_table_shows_each_lane_past_its_holdout_target(capsys, monkeypatch, lane):
    row = _table_row(capsys, monkeypatch, lane)
    target = BEFORE[lane]["holdout"] + SHORT[lane]
    assert row["holdout"] >= target, (lane, row["holdout"], target)
    assert row["cases"] >= BEFORE[lane]["cases"] + round(SHORT[lane] / holdout.FRACTION)


def test_the_generators_hold_each_new_set_to_the_target_size():
    assert len(SHIPPED_CODE) == code_synth.COUNT and len(SHIPPED_EXTRACT) == extract_synth.COUNT
    for cases, lane in ((SHIPPED_CODE, "code"), (SHIPPED_EXTRACT, "extract")):
        side = holdout.for_lane(lane)
        added = sum(1 for c in cases if side.side(c.id) == "holdout")
        assert added >= SHORT[lane], (lane, added)


# --- known-answer controls ---

def test_every_code_reference_passes_all_its_checks_and_every_wrong_variant_fails_one():
    rows = code_synth.fetch()
    assert len(rows) == code_synth.COUNT
    for row in rows:
        passed, failed = _check_in_process(row["ref"], row["checks"])
        assert not failed, (row["item"], failed)
        assert _check_in_process(row["wrong"], row["checks"])[1], row["item"]


def test_a_shipped_code_slice_passes_its_reference_and_fails_wrong_and_constants():
    cases = SHIPPED_CODE[::40]
    got = importers.negative_control(cases, code_synth.RESPONDERS, code_synth.passes)
    n = len(cases)
    assert n >= 20
    assert got["reference"] == (n, n)
    assert got["wrong"][0] == 0 and got["none"][0] == 0 and got["zero"][0] == 0


def test_every_extract_answer_is_in_its_text_and_the_controls_separate_it_from_wrong_answers():
    got = importers.negative_control(SHIPPED_EXTRACT, extract_synth.RESPONDERS, extract_synth.passes)
    n = len(SHIPPED_EXTRACT)
    assert got["reference"] == (n, n)
    assert got["unknown"][0] == 0 and got["echo"][0] == 0 and got["empty"][0] == 0


def test_an_extract_answer_that_is_a_different_cases_answer_passes_only_when_the_values_coincide():
    by_family: dict = {}
    for c in SHIPPED_EXTRACT:
        by_family.setdefault(c.source.stem[-4:], []).append(c)
    cases = SHIPPED_EXTRACT
    shifted = [extract_synth.passes(c, cases[(i + 1) % len(cases)].assertions["equals"][0]) for i, c in enumerate(cases)]
    assert sum(shifted) < len(cases) * 0.1


def test_the_extract_asks_have_one_answer_each_and_do_not_leak_it_in_the_question():
    for row in extract_synth.fetch():
        assert row["answers"][0] in row["context"]
        assert not re.search(rf"(?<!\w){re.escape(row['answers'][0])}(?!\w)", row["question"]), row["item"]


# --- determinism and provenance ---

def test_importing_twice_gives_identical_case_digests(tmp_path):
    digests = []
    for name in ("a", "b"):
        for source in ("code_synth", "extract_synth"):
            importers.run(source, root=tmp_path / name, rows=importers.module(source).fetch()[:50])
        digests.append(sorted(case_digest(c) for lane in ("code", "extract") for c in load_cases(tmp_path / name / lane)))
    assert digests[0] == digests[1] and len(digests[0]) == 100


def test_the_shipped_cases_are_what_the_generators_write_now(tmp_path):
    for source, shipped in (("code_synth", SHIPPED_CODE), ("extract_synth", SHIPPED_EXTRACT)):
        importers.run(source, root=tmp_path)
        fresh = load_cases(tmp_path / importers.module(source).LANE / source)
        assert [case_digest(c) for c in fresh] == [case_digest(c) for c in shipped]


def test_every_generated_case_carries_its_source_license_date_and_a_unique_id():
    for cases, mod in ((SHIPPED_CODE, code_synth), (SHIPPED_EXTRACT, extract_synth)):
        assert len({c.id for c in cases}) == len(cases)
        assert mod.LICENSE in importers.ALLOWED_LICENSES
        for c in cases:
            att = yaml.safe_load(c.source.read_text(encoding="utf-8"))["attribution"]
            assert att["license"] == "generated" and att["date"] == "2026-11-27"
            assert att["revision"] == mod.REVISION and re.fullmatch(r"[0-9a-f]{40}", att["revision"])


def test_a_different_seed_draws_different_cases_and_the_same_seed_the_same():
    assert code_synth.fetch(seed=1, count=20) == code_synth.fetch(seed=1, count=20)
    assert code_synth.fetch(seed=1, count=20) != code_synth.fetch(seed=2, count=20)
    assert extract_synth.fetch(seed=1, count=24) == extract_synth.fetch(seed=1, count=24)
    assert extract_synth.fetch(seed=1, count=24) != extract_synth.fetch(seed=2, count=24)


def test_a_code_draw_whose_wrong_variant_passes_every_check_is_refused():
    row = copy.deepcopy(code_synth.fetch(count=1)[0])
    problem = {"fn": row["fn"], "ref": row["ref"], "wrong": row["ref"], "inputs": [([1, 2, 3],)] * 7}
    assert code_synth._finish(problem) is None


def test_no_two_code_prompts_are_the_same():
    prompts = [c.prompt for c in SHIPPED_CODE]
    assert len(set(prompts)) == len(prompts)


#: Live `soh lane-gate status` 2026-11-27 with the first 880 cases: the code lane needed 417 holdout in all.
LANE_GATE_NEEDS = 417


def test_the_margin_cases_come_only_from_families_the_incumbent_can_lose_in():
    margin = [r for r in code_synth.fetch() if code_synth.MARGIN_FROM <= r["item"] < code_synth.LONG_FROM]
    assert len(margin) == code_synth.LONG_FROM - code_synth.MARGIN_FROM >= 150
    assert {r["stratum"].split("-")[0] for r in margin} <= {"strs", "algo", "hard"}
    assert [r for r in code_synth.fetch(count=code_synth.MARGIN_FROM)] == code_synth.fetch()[:code_synth.MARGIN_FROM]


def test_the_margin_clears_the_lane_gate_need_with_room_to_spare(capsys, monkeypatch):
    side = holdout.for_lane("code")
    added = sum(1 for c in SHIPPED_CODE[code_synth.MARGIN_FROM:] if side.side(c.id) == "holdout")
    assert added >= 40, added
    assert _table_row(capsys, monkeypatch, "code")["holdout"] >= LANE_GATE_NEEDS + 30
