"""Decide lane headline: the lane metric leads, exact passes say what they count, the holdout is not one family. #671."""
import re
from collections import Counter
from pathlib import Path

from evals import decide_corpus as dc
from evals.core import Case, load_cases
from harness import holdout, publish, report, site

ROOT = Path(__file__).resolve().parents[1]
NOW = 1.79e9


def _row(name, passed, accuracy, reference=False):
    return {"candidate": name, "model": name, "served_as": "", "reference": reference, "not_run": "",
            "passed": passed, "total": 10, "pass_rate": passed / 10, "median_s": 0.5, "first_s": 1.0,
            "peak_gb": 9.0, "run_at": "2026-10-23T00:00:00Z",
            "metrics": {"decide_ece": 0.03, "decide_brier": 0.24, "decide_accuracy": accuracy, "calibrated": 1.0}}


def _doc(rows, lane="decide"):
    return {"generated_at": "2026-10-23T00:00:00Z", "schema": 1, "export_version": 1,
            "machine": {"label": "box", "slug": "box"},
            "lanes": [{"lane": lane, "serves": rows[0]["candidate"], "adopted": False, "pass_rate": rows[0]["pass_rate"],
                       "passed": rows[0]["passed"], "total": rows[0]["total"],
                       "median_s": 0.5, "metrics": rows[0]["metrics"], "measured_at": "2026-10-23T00:00:00Z",
                       "last_run_at": "2026-10-23T00:00:00Z", "comparison": rows,
                       "exams": [{"cases": 10, "runs": 1, "run_at": "2026-10-23T00:00:00Z", "rows": rows}]}]}


def _table(page):
    return page[page.index("<table>"):page.index("</table>")]


def test_decide_bench_row_leads_with_field_accuracy():
    page = site.benchmarks([_doc([_row("imajev", 4, 0.842)])], now=NOW)
    head = re.findall(r"<th>(.*?)</th>", _table(page))
    assert head.index("decide_accuracy") < head.index("all fields right"), head
    cells = re.findall(r'<td class="num">(.*?)</td>', _table(page))
    assert cells[0] == "0.842" and cells[1] == "4/10 0.40", cells


def test_exact_passes_labelled_all_fields_right():
    doc = _doc([_row("imajev", 4, 0.842)])
    report_page = publish.render_site([doc], now=NOW)
    assert "all fields right 4/10 0.40" in report_page
    assert "decide_accuracy 0.842" in report_page
    # A lane with no pooled metric keeps its plain pass column.
    code = site.benchmarks([_doc([{**_row("q", 4, 0.0), "metrics": {}}], lane="code")], now=NOW)
    assert "all fields right" not in code and "<th>pass</th>" in code


def test_comparison_rows_sort_on_the_lane_metric():
    rows = [_row("more-exact", 5, 0.70), _row("more-fields", 3, 0.85)]
    assert [r["candidate"] for r in sorted(rows, key=lambda r: publish._rank(r, "decide"))] == \
        ["more-fields", "more-exact"]


def test_metrics_follow_the_lane_order():
    m = {"decide_ece": 0.03, "decide_brier": 0.24, "decide_accuracy": 0.84, "calibrated": 1.0}
    assert publish.metric_html(m, "decide").split("<br>") == [
        "decide_accuracy 0.840", "decide_brier 0.240", "decide_ece 0.030", "calibrated 1.000"]
    assert publish.metric_html(m).startswith("calibrated 1.000")


def test_local_report_keeps_every_metric():
    lane = {"lane": "claims", "wanted": True, "serves": "x", "adopted": False, "unverified": False,
            "stale": False, "pass_rate": 0.5, "median_s": 1.0, "metrics": {f"claims_metric_{i}": 0.5 for i in range(7)}}
    html = report._lane_rows([lane], {})
    for i in range(7):
        assert f"claims_metric_{i} 0.500" in html


def test_exam_with_no_reference_says_so():
    lone = site.benchmarks([_doc([_row("imajev", 4, 0.842)])], now=NOW)
    assert "no reference" in lone.lower()
    ref = site.benchmarks([_doc([_row("imajev", 4, 0.842), _row("opus", 5, 0.86, reference=True)])], now=NOW)
    assert "no reference" not in ref.lower()


# --- the holdout -----------------------------------------------------------

def _case(cid):
    return Case(id=cid, modality="decide", prompt=cid, context="", params={}, assertions={})


def _fam(ids):
    return Counter(holdout.family(i) for i in ids)


def test_holdout_family_share_is_bounded():
    split = holdout.for_lane("decide", ROOT / "evals" / "cases")
    mix = _fam(split.holdout)
    assert max(mix.values()) <= holdout.FAMILY_SHARE * len(split.holdout), mix
    assert len(split.holdout) >= 100, mix


def test_every_decide_family_reaches_the_holdout():
    cases = load_cases(ROOT / "evals" / "cases" / "decide")
    split = holdout.for_lane("decide", ROOT / "evals" / "cases")
    assert set(_fam(split.holdout)) == {holdout.family(c.id) for c in cases}
    assert min(_fam(split.holdout).values()) >= 10, _fam(split.holdout)


def test_family_cap_moves_holdout_cases_to_dev_only():
    cases = [_case(f"big-{i}") for i in range(300)] + [_case(f"small-{i}") for i in range(30)]
    free = holdout.assign("code", cases)
    capped = holdout.assign("decide", cases)
    assert set(capped.holdout) <= set(free.holdout)
    assert set(free.dev) <= set(capped.dev)
    assert set(capped.holdout) | set(capped.dev) == {c.id for c in cases}
    mix = _fam(capped.holdout)
    assert mix["big"] <= holdout.FAMILY_SHARE * len(capped.holdout) and mix["small"] == _fam(free.holdout)["small"]
    assert capped.version != free.version == holdout.VERSION
    assert holdout.version("decide") == capped.version
    # One family alone has nothing to balance against.
    assert holdout.assign("decide", cases[:300]).holdout == holdout.assign("code", cases[:300]).holdout


def test_route_picks_reuse_domains_once_all_are_taken_and_keep_the_first_picks():
    rows = {f"massive-{i}": {"id": i, "scenario": f"d{i % 3}", "utt": "u", "annot_utt": "u"} for i in range(30)}
    ids = list(rows)
    small = dc.pick_route(ids, rows, n=3)
    big = dc.pick_route(ids, rows, n=9)
    assert big[:3] == small and len(big) == 9
    assert Counter(rows[i]["scenario"] for i in big) == {"d0": 3, "d1": 3, "d2": 3}
