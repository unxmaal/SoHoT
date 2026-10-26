"""`soh votes`: each human A/B verdict beside the order the lane's checker gives the same artifacts (#92)."""
import json

import pytest

from harness import cli, human, paths, runs
from harness import memory_store as ms
from harness.live_audit import open_readonly


def row(cand, case, passed, **metrics):
    return {"case_id": case, "candidate": cand, "passed": passed, "seconds": 1.0,
            "metrics": metrics, "output": "<svg/>"}


def stored(conn, name, lane, rows):
    run = paths.runs() / name
    run.mkdir(parents=True, exist_ok=True)
    runs.record(conn, run, {"receipt": {"modality": lane}, "environment": ms.this_machine(), "rows": rows})
    return name


def vote(conn, lane, run, case, a, b, answers):
    for answer in answers:
        human.record(lane, case, a, b, answer, run=run, voter="tester", conn=conn)


@pytest.fixture
def conn():
    c = ms.connect()
    yield c
    c.close()


def outcome(got, case):
    return next(p["outcome"] for p in got["pairs"] if p["case"] == case)


def test_a_checker_that_orders_the_pair_the_persons_way_agrees(conn):
    run = stored(conn, "r-agree", "svg", [row("alpha", "frog#1", True), row("alpha", "frog#2", True),
                                          row("beta", "frog#1", True), row("beta", "frog#2", False)])
    vote(conn, "svg", run, "frog", "alpha", "beta", ["a", "a", "a"])
    assert outcome(human.metric_agreement(conn), "frog") == human.AGREE


def test_a_checker_that_orders_it_the_other_way_disagrees(conn):
    run = stored(conn, "r-disagree", "svg", [row("alpha", "frog#1", True), row("alpha", "frog#2", False),
                                             row("beta", "frog#1", True), row("beta", "frog#2", True)])
    vote(conn, "svg", run, "frog", "alpha", "beta", ["a", "a", "b"])
    got = human.metric_agreement(conn)
    assert outcome(got, "frog") == human.DISAGREE
    assert got["lanes"]["svg"] == {human.DISAGREE: 1}


def test_a_checker_that_passes_both_alike_cannot_tell(conn):
    run = stored(conn, "r-tie", "web", [row("alpha", "page#1", True, ink=0.9), row("beta", "page#1", True, ink=0.1)])
    vote(conn, "web", run, "page", "alpha", "beta", ["a", "a", "a"])
    assert outcome(human.metric_agreement(conn), "page") == human.CANNOT_TELL


def test_speed_is_not_the_checker_seeing_quality(conn):
    run = stored(conn, "r-speed", "web", [row("alpha", "page#1", True, tokens_per_s=10.0),
                                          row("beta", "page#1", True, tokens_per_s=90.0)])
    vote(conn, "web", run, "page", "alpha", "beta", ["a", "a", "a"])
    assert outcome(human.metric_agreement(conn), "page") == human.CANNOT_TELL


def test_a_ranked_quality_metric_separates_a_pass_tie(conn):
    run = stored(conn, "r-metric", "image", [row("alpha", "fox#1", True, adherence=0.2),
                                             row("beta", "fox#1", True, adherence=0.8)])
    vote(conn, "image", run, "fox", "alpha", "beta", ["b", "b", "b"])
    assert outcome(human.metric_agreement(conn), "fox") == human.AGREE


def test_no_preference_and_too_few_answers_are_not_scored_against_the_checker(conn):
    run = stored(conn, "r-open", "svg", [row("alpha", "frog#1", True), row("beta", "frog#1", False),
                                         row("alpha", "gear#1", True), row("beta", "gear#1", False)])
    vote(conn, "svg", run, "frog", "alpha", "beta", ["a", "b", "tie"])
    vote(conn, "svg", run, "gear", "alpha", "beta", ["a", "a"])
    got = human.metric_agreement(conn)
    assert outcome(got, "frog") == human.NO_PREFERENCE
    assert outcome(got, "gear") == human.UNDECIDED


def test_a_vote_whose_run_is_not_stored_is_unscored(conn):
    vote(conn, "svg", "gone-run", "frog", "alpha", "beta", ["a", "a", "a"])
    assert outcome(human.metric_agreement(conn), "frog") == human.UNSCORED


def test_the_command_reads_a_store_without_writing_it(conn, capsys):
    run = stored(conn, "r-cli", "svg", [row("alpha", "frog#1", True), row("beta", "frog#1", False)])
    vote(conn, "svg", run, "frog", "alpha", "beta", ["a", "a", "a"])
    conn.commit()
    path = ms.db_path()
    before = path.read_bytes()
    assert cli.main(["votes", "--json", "--store", str(path)]) == 0
    got = json.loads(capsys.readouterr().out)
    assert got["lanes"] == {"svg": {human.AGREE: 1}}
    assert path.read_bytes() == before
    ro = open_readonly(path)
    try:
        assert human.metric_agreement(ro, "web") == {"pairs": [], "lanes": {}}
    finally:
        ro.close()
