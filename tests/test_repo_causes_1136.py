"""A crashed repo row is classed: provider_refused when the provider's usage screen refused the prompt. #1136."""
from evals.analysis import repo_failures as F
from tests.test_repo_causes_1128 import _run

REFUSED = ("claude -p: API Error: Opus 5.5's safeguards flagged this message "
           "(https://www.anthropic.com/legal/aup). Try rephrasing the request in a new session.")
ROWS = {
    "t-refused": ("crashed", REFUSED, None, None, None, None),
    "t-crashed": ("crashed", "claude -p exited 1: connection reset", None, None, None, None),
    "t-other": ("server_dead", "the server went away", None, None, None, None),
}


def test_a_crashed_row_is_provider_refused_or_crashed_never_unclassed(tmp_path):
    run = F.load_run(_run(tmp_path, "r", ROWS))
    got = {r["case"]: r["cause"] for r in F.causes(run, {})}
    assert got == {"t-refused": "provider_refused", "t-crashed": "crashed", "t-other": "server_dead"}


def test_the_table_lists_the_new_classes_in_codebook_order(tmp_path):
    run = F.load_run(_run(tmp_path, "r", ROWS))
    lines = F.cause_table(F.causes(run, {})).splitlines()
    names = [line.split(" | ")[0].lstrip("| ") for line in lines[2:5]]
    assert names == ["provider_refused", "crashed", "server_dead"]
