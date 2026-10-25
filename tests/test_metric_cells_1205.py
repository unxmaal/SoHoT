"""The benchmarks page and the lane report show every metric a row carries, never a silent cut. #1205."""
import copy
from pathlib import Path

from harness import publish, site

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "site"
NOW = 1.7598e9
CLAIMS = {"claims_bad_matched": 1.0, "claims_good_found": 6.0, "claims_good_total": 8.0,
          "claims_precision": 0.857, "claims_recall": 0.75, "claims_reviewed_matched": 5.0,
          "claims_unreviewed": 2.0}


def _machines():
    docs = publish.load(FIXTURES)
    doc = copy.deepcopy(docs[0])
    lane = next(l for l in doc["lanes"] if l["comparison"])
    lane["metrics"] = dict(CLAIMS)
    for row in lane["comparison"]:
        row["metrics"] = dict(CLAIMS)
    lane["exams"] = [{"cases": 3, "runs": 1, "run_at": lane["last_run_at"],
                      "rows": copy.deepcopy(lane["comparison"])}]
    return [doc]


def test_a_row_with_the_seven_claims_metrics_shows_all_seven_on_the_benchmarks_page():
    bench = site.render(_machines(), now=NOW)["benchmarks/index.html"]
    for name, value in CLAIMS.items():
        assert f"{name} {value:.3f}" in bench, name


def test_the_lane_report_shows_all_seven_in_the_lane_row_and_the_comparison():
    report = publish.render_site(_machines(), now=NOW)
    for name, value in CLAIMS.items():
        assert report.count(f"{name} {value:.3f}") >= 2, name


def test_each_metric_sits_on_its_own_line_and_is_escaped():
    cell = publish.metric_html({"b<x>": 2.0, "a": 1.0})
    assert cell == "a 1.000<br>b&lt;x&gt; 2.000"
    assert publish.metric_html({}) == "" and publish.metric_html(None) == ""
