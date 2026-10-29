"""Which of a lane's metrics breaks a tie after its first key is declared in winners.ORDER, never the alphabet (#717)."""
from pathlib import Path

import pytest

from evals import core
from harness import adopt, lanes, winners
from tests.test_metric_directions import emitted_metrics

REPO = Path(__file__).resolve().parent.parent
#: Checker modules named for something other than the lane they score.
CHECKER_LANES = {"speech": ("tts", "stt")}


def row(**metrics):
    return {"pass_rate": 1.0, "passed": 4, "total": 4, "median_s": 1.0, "metrics": metrics}


def best(lane, **rows):
    names = winners.shared_metrics(rows.values(), lane)
    return max(rows, key=lambda k: winners.order_key(rows[k], names, lane))


def test_a_music_candidate_with_the_better_wer_outranks_one_with_the_better_duration():
    assert best("music", lyrics=row(wer=0.10, duration_error_s=0.5), length=row(wer=0.40, duration_error_s=0.0)) == "lyrics"
    assert adopt.better(row(wer=0.40, duration_error_s=0.0), row(wer=0.10, duration_error_s=0.5), "music")


def test_a_repo_candidate_that_applied_its_patch_outranks_one_with_a_higher_tool_call_rate():
    applied = row(resolved=0.0, patch_applied=0.5, agent_valid_call_rate=0.5)
    chatty = row(resolved=0.0, patch_applied=0.25, agent_valid_call_rate=1.0)
    assert best("repo", applied=applied, chatty=chatty) == "applied"


def test_a_tts_speaker_similarity_score_never_outranks_wer():
    assert best("tts", clear=row(wer=0.0, speaker_similarity=0.70), alike=row(wer=0.2, speaker_similarity=0.95)) == "clear"


@pytest.mark.gauntlet("a-closed-table-fronting-an-open-set", site="harness/winners.py:ORDER")
def test_a_shared_metric_no_order_names_follows_the_declared_ones_alphabetically():
    names = winners.shared_metrics([row(wer=0.1, duration_error_s=0.0, zeta=1.0, adherence=1.0)], "music")
    assert names == ("wer", "duration_error_s", "adherence", "zeta")
    assert winners.shared_metrics([row(b_score=1.0, a_score=1.0)], "image") == ("a_score", "b_score")


def _ranked(path: Path) -> set[str]:
    names = emitted_metrics(path.read_text(encoding="utf-8"), path.relative_to(REPO).as_posix())
    return {n for n in names if core.direction_of(n) != "neutral" and n not in core._COMPANIONS}


def test_every_lane_whose_checker_emits_several_ranked_metrics_declares_their_order():
    missing = {}
    for path in sorted((REPO / "harness" / "checks").glob("*.py")):
        for lane in CHECKER_LANES.get(path.stem, (path.stem,)):
            if lane not in lanes.ALL:
                continue
            ranked = _ranked(path) | ({"speaker_similarity"} if lane == "tts" else set())
            undeclared = ranked - set(winners.ORDER.get(lane, ())) - {winners.PRIMARY.get(lane)}
            if len(ranked) > 1 and undeclared:
                missing[lane] = sorted(undeclared)
    assert not missing, f"declare these in winners.ORDER, or the alphabet ranks them: {missing}"


def test_every_declared_order_names_metrics_with_a_direction():
    for lane, names in winners.ORDER.items():
        assert lane in lanes.ALL + lanes.BY_HAND, lane
        assert len(set(names)) == len(names), lane
        assert all(core.direction_of(n) != "neutral" for n in names), lane
