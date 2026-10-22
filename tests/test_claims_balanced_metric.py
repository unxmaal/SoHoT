"""#791: the claims lane ranks, screens and adopts on recall and specificity balanced, not pass rate."""
import json
from pathlib import Path

import pytest

from evals import core
from harness import adopt, screen, winners
from harness.checks import claims as claims_check

pytestmark = pytest.mark.usefixtures("sat_exam")

STRATA = Path(__file__).parent / "fixtures" / "claims" / "strata-791.json"


def _real() -> dict[str, list]:
    rows = json.loads(STRATA.read_text(encoding="utf-8"))["rows"]
    # The negative control: abstains on every case, so it passes exactly the expect-empty ones.
    rows["always-empty"] = [[empty, empty, 0] for empty, _, _ in rows["7b"]]
    return rows


def _results(name: str, rows: list, ids=None) -> list[core.Result]:
    return [core.Result(ids[i] if ids else f"case-{i}", name, bool(passed), 1.0, 0,
                        "" if passed else "content",
                        metrics={"claims_expect_empty": empty, "claims_emitted": emitted,
                                 "claims_schema_valid": 1},
                        failure_class="" if passed else "content_failed")
            for i, (empty, passed, emitted) in enumerate(rows)]


def _summary(names=("7b", "14b", "always-empty")) -> dict:
    real = _real()
    return core.summarize([r for n in names for r in _results(n, real[n])])


def _ranked(monkeypatch, summary: dict) -> str:
    from harness import runs
    run = {"lane": "claims", "path": "p", "id": 1}
    monkeypatch.setattr(runs, "summaries", lambda conn, tier=None: [(run, dict(summary), [])])
    return winners.from_receipts(None, plain_only=False)["claims"]["candidate"]


def _row_dicts(names) -> list[dict]:
    real = _real()
    return [{"candidate": r.candidate, "case_id": r.case_id, "passed": r.passed,
             "failure_class": r.failure_class, "metrics": r.metrics}
            for n in names for r in _results(n, real[n])]


# ---- the strata are reported apart, and balanced over the lane's own weight ----------

def test_the_summary_reports_recall_and_specificity_per_stratum():
    got = {n: row["metrics"] for n, row in _summary().items()}
    assert (got["7b"]["claims_case_recall"], got["7b"]["claims_case_specificity"]) == (0.5556, 0.6686)
    assert (got["14b"]["claims_case_recall"], got["14b"]["claims_case_specificity"]) == (0.25, 0.9709)
    assert (got["always-empty"]["claims_case_recall"], got["always-empty"]["claims_case_specificity"]) == (0.0, 1.0)


def test_the_balanced_score_is_the_weighted_macro_average_of_the_strata():
    got = {n: row["metrics"]["claims_balanced"] for n, row in _summary().items()}
    assert got == {"7b": 0.6121, "14b": 0.6105, "always-empty": 0.5}


def test_pass_rate_alone_would_rank_the_control_above_the_7b():
    rows = _summary()
    assert rows["always-empty"]["pass_rate"] > rows["7b"]["pass_rate"]


def test_the_strata_weight_is_a_registered_knob_at_half():
    from harness import knobs
    assert claims_check.RECALL_WEIGHT == 0.5
    assert knobs.KNOBS["claims_recall_weight"].sites == ("harness/checks/claims.py:RECALL_WEIGHT",)


def test_a_summary_with_one_stratum_reports_no_balanced_score():
    real = _real()
    negatives = [row for row in real["7b"] if row[0]]
    got = core.summarize(_results("7b", negatives))["7b"]["metrics"]
    assert "claims_case_specificity" in got and "claims_balanced" not in got


# ---- the balance is the lane's, not the corpus's ------------------------------------

@pytest.mark.parametrize("model", ["14b", "always-empty"])
def test_resampling_the_negatives_leaves_balanced_unchanged_while_pass_rate_moves(model):
    rows = _real()[model]
    negatives = [row for row in rows if row[0]]
    doubled = rows + negatives
    kept = [row for row in negatives if row[1]]
    dropped = [row for row in negatives if not row[1]]
    halved = [row for row in rows if not row[0]] + kept[::2] + dropped[::2]
    base = core.summarize(_results(model, rows))[model]
    for resampled in (doubled, halved):
        got = core.summarize(_results(model, resampled))[model]
        assert got["metrics"]["claims_balanced"] == pytest.approx(base["metrics"]["claims_balanced"], abs=0.005)
        assert abs(got["pass_rate"] - base["pass_rate"]) > 0.01


# ---- the pinned negative control ranks, adopts and screens below a model that extracts ----

def test_the_always_empty_control_ranks_below_the_7b(monkeypatch):
    summary = _summary(("7b", "always-empty"))
    assert _ranked(monkeypatch, summary) == "7b"


def test_the_14b_against_the_7b_comes_out_as_the_strata_say(monkeypatch):
    summary = _summary()
    assert _ranked(monkeypatch, summary) == "7b"
    rows = {n: summary[n] for n in ("14b", "always-empty")}
    assert _ranked(monkeypatch, rows) == "14b"


def test_adopt_never_prefers_the_control_to_a_model_that_extracts():
    summary = _summary()
    for model in ("7b", "14b"):
        assert not adopt.better(summary[model], summary["always-empty"], lane="claims")
        assert adopt.better(summary["always-empty"], summary[model], lane="claims")


def test_adopt_decide_refuses_the_control_as_a_challenger_to_the_7b():
    summary = _summary(("7b", "always-empty"))
    rows = _row_dicts(("7b", "always-empty"))
    got = adopt.decide("claims", {"candidate": "7b", **summary["7b"]},
                       {"candidate": "always-empty", **summary["always-empty"]}, rows=rows)
    assert not got.adopt


def test_the_paired_gate_weighs_each_stratum_by_the_lane_not_by_its_case_count():
    rows = _row_dicts(("7b", "always-empty"))
    cell, _, _ = adopt.paired_p(rows, "always-empty", "7b", lane="claims")
    # Each negative counts as positives/negatives of a case, so the larger stratum cannot outvote the smaller.
    assert (cell.gained, cell.lost) == (20, 12)
    doubled = rows + [{**r, "case_id": f"{r['case_id']}-again"} for r in rows
                      if r["metrics"]["claims_expect_empty"]]
    again, _, _ = adopt.paired_p(doubled, "always-empty", "7b", lane="claims")
    assert (again.gained, again.lost) == (20, 12)


def test_a_claims_screen_that_only_abstained_is_not_screened():
    summary = _summary(("always-empty",))
    assert screen.outcome(0, summary).outcome != "screened"


def test_a_claims_screen_that_extracted_is_screened():
    summary = _summary(("7b",))
    assert screen.outcome(0, summary).outcome == "screened"


# ---- every claims row carries its case's stratum, a failed one too --------------------

def test_a_row_stored_before_the_stratum_mark_is_read_from_its_checker_metrics():
    assert core.claims_stratum({"claims_empty_cases": 1, "claims_schema_valid": 1}) == 1
    assert core.claims_stratum({"claims_schema_valid": 1, "claims_emitted": 2}) == 0
    assert core.claims_stratum({"claims_schema_valid": 0}) is None
    assert core.claims_stratum({core.claims_check.STRATUM: 0, "claims_schema_valid": 0}) == 0


@pytest.mark.gauntlet("a-closed-table-fronting-an-open-set", site="harness/winners.py:PRIMARY")
def test_every_lane_with_an_abstain_stratum_ranks_on_a_declared_primary_metric():
    for lane, name in winners.PRIMARY.items():
        assert lane in core.MODALITIES and core.direction_of(name) != "neutral", lane
    with_abstain = {lane for lane, keys in core.ASSERTION_KEYS.items() if "expect_empty" in keys}
    assert with_abstain and with_abstain <= set(winners.PRIMARY)
    assert winners.primary({"pass_rate": 0.4}, "svg") == (True, 1.0, 0.4)


class _Crash:
    candidate = "fake"

    def warm(self):
        pass

    def run(self, case):
        return core.Result(case.id, self.candidate, False, 0.1, 0, "server error",
                           failure_class="crashed")

    def artifact(self, case, suffix):
        return f"{case.id}{suffix}"


@pytest.mark.parametrize("empty", [True, False])
def test_a_row_the_checker_never_saw_still_counts_in_its_stratum(tmp_path, empty):
    from evals import run
    case = core.Case(id="claims-x", modality="claims", prompt="p",
                     assertions={"expect_empty": empty}, source=tmp_path / "x.yaml")
    rows = []
    run._run_candidate(run.parse_args([]), "fake", _Crash(), [case], rows, tmp_path)
    assert rows[0].metrics["claims_expect_empty"] == int(empty)
