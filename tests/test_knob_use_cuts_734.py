"""The limits the use-based knob inventory found record a limit_cuts row when they bind (#734, #1087)."""
from __future__ import annotations

import json
from pathlib import Path

from harness import cuts


def _spooled() -> list[tuple]:
    path = cuts._spool_path()
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    return [(r["knob"], r["kept"], r["dropped"]) for r in map(json.loads, lines)]


def test_a_lineage_past_the_hops_is_a_cut_and_a_short_one_is_not(monkeypatch):
    from harness import family
    monkeypatch.setattr(family, "HOPS", 2)
    chain = {f"m{i}": [f"m{i + 1}"] for i in range(5)}
    assert family.root("m3", chain) == "m5"
    assert _spooled() == []
    assert family.root("m0", chain) == "m2"
    assert [k for k, _, _ in _spooled()] == ["family_hops"]


def test_junit_failure_text_past_the_tail_is_one_cut_per_report(tmp_path):
    from evals import repo
    xml = tmp_path / "junit.xml"
    long = "x" * (repo.FAILURE_CHARS + 10)
    xml.write_text("<testsuite>"
                   f"<testcase classname='t' name='a'><failure message='m'>{long}</failure></testcase>"
                   f"<testcase classname='t' name='b'><failure message='m'>{long}</failure></testcase>"
                   "<testcase classname='t' name='c'><failure message='m'>short</failure></testcase>"
                   "</testsuite>", encoding="utf-8")
    got = repo.failure_text(xml, ["t::a", "t::c"])
    assert len(got["t::a"]) == repo.FAILURE_CHARS and got["t::c"] == "m\nshort"
    assert _spooled() == [("repo_failure_chars", None, 2)]


def test_decide_check_paragraphs_record_their_trimmed_questions():
    from evals import decide_corpus as dc
    questions = {f"p{p}q{i}": {"context": f"p{p}", "answerable": i % 2 == 0}
                 for p in range(3) for i in range(dc.QUESTIONS + (2 if p == 0 else 0))}
    got = dc.pick_check(list(questions), questions, n=5)
    assert len(got) == 3
    assert _spooled() == [("decide_check_questions", None, 1)]


def test_a_long_budget_cut_reply_is_measured_on_its_tail_and_says_so():
    from harness import degenerate as dg
    dg.measure("ab " * (dg.MIN_CHARS // 3 + 1))
    assert _spooled() == []
    dg.measure("ab " * dg.TAIL_CHARS)
    assert _spooled() == [("degenerate_tail_chars", dg.TAIL_CHARS, 3 * dg.TAIL_CHARS - dg.TAIL_CHARS)]


def test_a_source_item_too_short_to_probe_is_a_cut():
    from harness import contamination as c
    assert c.split_prefix("word " * (c.PREFIX_WORDS + c.TARGET_WORDS)) is not None
    assert _spooled() == []
    assert c.split_prefix("too short") is None
    assert _spooled() == [("contamination_probe_words", 0, 1)]


def test_a_number_whose_qualifier_sits_just_past_the_window_is_a_cut():
    from harness import assertions as a
    near = "Measured 2026-09-12.\n\nIt takes 41 s a run.\n"
    far = "Measured 2026-09-12.\n\n\n\nIt takes 41 s a run.\n"
    def number(text):
        return next(c for c in a.scan(text, Path("x.md"), "x.md") if "NUM" in c.kinds)
    assert number(near).qualified
    assert _spooled() == []
    assert not number(far).qualified
    assert [k for k, _, d in _spooled()] == ["assertions_qualifier_window"]


def test_more_quantized_descendants_than_the_tries_is_a_cut(monkeypatch):
    from harness import quants
    monkeypatch.setattr(quants, "descendants", lambda base, get, machine: [f"q{i}" for i in range(quants.TRIES + 3)])

    def gone(rid, **kw):
        raise quants.ins.Gone(rid)
    monkeypatch.setattr(quants.ins, "inspect_model", gone)
    assert quants.best("base") is None
    assert _spooled() == [("quants_tries", quants.TRIES, 3)]
