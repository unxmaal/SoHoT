"""`soh gauntlet audit|review`: the gauntlet's two questions from the CLI (#492)."""

import json

from harness import cli


def test_soh_gauntlet_review_prints_the_questions(capsys):
    assert cli.main(["gauntlet", "review", "HEAD...HEAD"]) == 0
    assert capsys.readouterr().out.startswith("no review questions")


def test_soh_gauntlet_review_is_one_object_under_json(capsys):
    assert cli.main(["gauntlet", "review", "HEAD...HEAD", "--json"]) == 0
    got = json.loads(capsys.readouterr().out)
    assert got["ok"] and got["verb"] == "gauntlet" and got["action"] == "review"
    assert got["report"].startswith("no review questions")


def test_soh_gauntlet_audit_offline_reads_the_snapshot(capsys):
    rc = cli.main(["gauntlet", "audit", "--offline"])
    out = capsys.readouterr().out
    assert "closed defects with no class: 0" in out
    assert rc == 0


def test_a_failing_audit_is_not_ok_under_json(capsys, monkeypatch):
    from tests.gauntlet import classes
    monkeypatch.setattr(classes, "UNCLASSIFIED", {})
    rc = cli.main(["gauntlet", "audit", "--offline", "--json"])
    got = json.loads(capsys.readouterr().out)
    assert rc == 1 and got["ok"] is False and "no class" in got["report"]


def test_an_option_review_cannot_use_is_refused_not_ignored(capsys):
    assert cli.main(["gauntlet", "review", "--offline"]) == 1
    assert "are for audit" in capsys.readouterr().err


def test_an_audit_where_the_history_ref_is_missing_says_so_and_does_not_crash(capsys):
    # A CI checkout is one commit with no origin/main; the closing-reference half is skipped there.
    rc = cli.main(["gauntlet", "audit", "--offline", "--ref", "refs/remotes/origin/no-such-branch"])
    out = capsys.readouterr().out
    assert rc == 0 and "not in this clone" in out


def test_a_range_given_to_audit_is_refused_not_ignored(capsys):
    assert cli.main(["gauntlet", "audit", "HEAD"]) == 1
    assert "--ref" in capsys.readouterr().err
